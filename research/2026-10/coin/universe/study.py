"""Universe expansion study (PREREG.md). The frozen rule is the app's own
coin_strategy.py (imported, not copied); entries are gated by point-in-time
universe membership at the signal bar's close. Portfolio of N slots: an entry
buys equity/N (or the cash left). Cost per side 0.10% (or 0.20%) plus half a
tick (tick inferred per coin per month from the observed price grid)."""
import calendar
import datetime
import importlib.util
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("COIN_UNIVERSE_DATA") or os.path.join(HERE, "data")
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
spec = importlib.util.spec_from_file_location("coin_strategy", os.path.join(ROOT, "src", "portal", "trading", "model", "coin_strategy.py"))
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)

U4 = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"]
MAIN = ("2019-10-21", "2025-10-21")
RECENT = ("2025-10-21", "2026-10-24")
H = 3600


def epoch(iso):
    return calendar.timegm(datetime.datetime.fromisoformat(iso[:19]).timetuple())


_CACHE = {}


def hourly(market):
    if market not in _CACHE:
        path = os.path.join(DATA, "hourly", f"{market}.json")
        rows = json.load(open(path)) if os.path.exists(path) else []
        _CACHE[market] = [{"t": epoch(r["t"]), "o": float(r["o"]), "h": float(r["h"]), "l": float(r["l"]), "c": float(r["c"])} for r in rows]
    return _CACHE[market]


def ticks(candles):
    by_month = defaultdict(set)
    for r in candles:
        by_month[datetime.datetime.utcfromtimestamp(r["t"]).strftime("%Y-%m")].add(round(r["c"], 8))
    out = {}
    for month, values in by_month.items():
        v = sorted(values)
        diffs = [b - a for a, b in zip(v, v[1:]) if b - a > 1e-12]
        out[month] = min(diffs) if diffs else 0.0
    return out


def gated_replay(candles, start, end, allowed):
    """coin_strategy.replay with one change: an entry needs allowed(bar_end)."""
    bars = S.build_bars(candles)
    daily = [(b["start"], b["c"]) for b in S.build_bars(candles, S.DAY_SEC)]
    atr = S.atr_series(bars)
    by_bar = defaultdict(list)
    for row in candles:
        by_bar[int(row["t"]) // S.BAR_SEC * S.BAR_SEC].append(row)
    trades, pos, entry = [], {}, None
    di = 0
    for j, bar in enumerate(bars):
        if bar["end"] < start or bar["start"] >= end:
            continue
        if pos.get("long"):
            for row in by_bar.get(bar["start"], []):
                if row["t"] >= end:
                    break
                if row["l"] <= pos["stop"]:
                    trades.append((entry[0], entry[1], row["t"], min(row["o"], pos["stop"]), "stop"))
                    pos = {}
                    break
            if pos.get("long") and atr[j] is not None:
                pos["hh"] = max(pos["hh"], bar["h"])
                pos["stop"] = max(pos["stop"], pos["hh"] - S.ATR_K * atr[j])
        if not pos.get("long") and j + 1 < len(bars) and bars[j + 1]["start"] < end and allowed(bar["end"]):
            if j < S.DONCHIAN_N or atr[j] is None:
                continue
            hh = max(b["h"] for b in bars[j - S.DONCHIAN_N:j])
            while di < len(daily) and daily[di][0] + S.DAY_SEC <= bar["end"]:
                di += 1
            done = daily[:di]
            sma = sum(c for _t, c in done[-S.DAILY_MA:]) / S.DAILY_MA if len(done) >= S.DAILY_MA else None
            if sma is None or not (bar["c"] > hh and bar["c"] > sma):
                continue
            first = by_bar.get(bars[j + 1]["start"], [])
            if not first or first[0]["t"] < start:
                continue
            entry = (first[0]["t"], first[0]["o"])
            pos = {"long": True, "hh": bar["h"], "stop": bar["h"] - S.ATR_K * atr[j]}
    if pos.get("long") and entry:
        last = [r for r in candles if r["t"] < end][-1]
        trades.append((entry[0], entry[1], last["t"], last["c"], "end"))
    return trades


def membership(universe):
    """universe: {"YYYY-MM-DD": [markets]} -> allowed(market)(sec)."""
    keys = sorted((epoch(d), set(m)) for d, m in universe.items())

    def for_market(market):
        def allowed(sec):
            cur = None
            for t, members in keys:
                if t <= sec:
                    cur = members
                else:
                    break
            return bool(cur) and market in cur
        return allowed
    return for_market


def simulate(markets, n_slots, start_iso, end_iso, gate=None, fee=0.001, half_tick=True, exclude=()):
    start, end = epoch(start_iso), epoch(end_iso)
    events = []
    for m in markets:
        if m in exclude:
            continue
        candles = hourly(m)
        if not candles:
            continue
        allowed = gate(m) if gate else (lambda sec: True)
        tk = ticks(candles) if half_tick else {}
        for et, epx, xt, xpx, why in gated_replay(candles, start, end, allowed):
            em = datetime.datetime.utcfromtimestamp(et).strftime("%Y-%m")
            xm = datetime.datetime.utcfromtimestamp(xt).strftime("%Y-%m")
            events.append((et, m, epx + tk.get(em, 0) / 2, xt, xpx - tk.get(xm, 0) / 2, why))
    events.sort()
    price = {m: {r["t"]: r["c"] for r in hourly(m)} for m in {e[1] for e in events}}
    exits = defaultdict(list)
    entries = defaultdict(list)
    for ev in events:
        entries[ev[0]].append(ev)
        exits[ev[3]].append(ev)
    cash, held, last_px = 1.0, {}, {}
    eq_curve, trades, pnl_by = [], [], defaultdict(float)
    t = start

    def close_due(t):
        nonlocal cash
        for ev in exits.get(t, []):
            key = (ev[1], ev[0])
            if key in held:
                qty, cost = held.pop(key)
                proceeds = qty * ev[4] * (1 - fee)
                cash += proceeds
                trades.append(proceeds / cost - 1)
                pnl_by[ev[1]] += proceeds - cost

    while t <= end:
        close_due(t)
        if entries.get(t):
            equity = cash + sum(q * last_px.get(k[0], 0) for k, (q, _c) in held.items())
            for ev in entries[t]:
                spend = min(cash, equity / n_slots)
                if spend <= 1e-9:
                    continue
                qty = spend / (ev[2] * (1 + fee))
                cash -= spend
                held[(ev[1], ev[0])] = (qty, spend)
            close_due(t)  # stopped out inside the entry candle
        for k in held:
            p = price[k[0]].get(t)
            if p:
                last_px[k[0]] = p
        eq_curve.append((t, cash + sum(q * last_px.get(k[0], 0) for k, (q, _c) in held.items())))
        t += H
    return eq_curve, trades, pnl_by


def summarize(eq_curve, trades, start_iso, end_iso, cuts=None):
    v = [e for _t, e in eq_curve]
    peak, mdd = 0.0, 0.0
    for x in v:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1)
    years = (epoch(end_iso) - epoch(start_iso)) / (365.25 * 86400)
    cagr = (v[-1] ** (1 / years) - 1) * 100 if v[-1] > 0 else -100
    out = {"total": (v[-1] - 1) * 100, "cagr": cagr, "mdd": mdd * 100, "trades": len(trades),
           "per_year": len(trades) / years, "avg": sum(trades) / len(trades) * 100 if trades else 0.0,
           "win": sum(r > 0 for r in trades) / len(trades) * 100 if trades else 0.0}
    if cuts:
        idx = {t: e for t, e in eq_curve}
        ys = []
        for a, b in zip(cuts[:-1], cuts[1:]):
            ea = idx.get(epoch(a), 1.0) if epoch(a) > eq_curve[0][0] else 1.0
            eb = idx.get(epoch(b), v[-1])
            ys.append((eb / ea - 1) * 100)
        out["years"] = ys
    return out


def fmt(label, r):
    years = " ".join(f"{y:+6.1f}" for y in r.get("years", []))
    return (f"{label:34s} 연{r['cagr']:+6.1f}% 누적{r['total']:+7.1f}% 낙폭{r['mdd']:+6.1f}% 거래{r['trades']:4d} ({r['per_year']:4.1f}/년) "
            f"평균{r['avg']:+5.2f}% 승률{r['win']:3.0f}%" + (f" | {years}" if years else ""))


def main():
    universes = json.load(open(os.path.join(DATA, "universes.json")))
    cuts = [f"{y}-10-21" for y in range(2019, 2026)]
    sets = {
        "U4": (U4, 4, None),
        "U10": (sorted({m for ms in universes["U10"].values() for m in ms}), 10, membership(universes["U10"])),
        "U20": (sorted({m for ms in universes["U20"].values() for m in ms}), 20, membership(universes["U20"])),
    }
    results = {}
    for name, (markets, n, gate) in sets.items():
        for fee, tag in ((0.001, "기본"), (0.002, "비용2배")):
            for (a, b), period in ((MAIN, "주"), (RECENT, "최근")):
                eq, tr, by = simulate(markets, n, a, b, gate=gate, fee=fee)
                r = summarize(eq, tr, a, b, cuts if period == "주" else None)
                r["pnl_by"] = dict(by)
                results[(name, tag, period)] = r
                print(fmt(f"{name} {tag} {period}구간", r), flush=True)
        # remove the single best coin (main period, base cost)
        by = results[(name, "기본", "주")]["pnl_by"]
        best = max(by, key=by.get) if by else None
        if best:
            eq, tr, _ = simulate(markets, n, *MAIN, gate=gate, exclude=(best,))
            r = summarize(eq, tr, *MAIN, cuts)
            results[(name, "최고코인제외", "주")] = r
            print(fmt(f"{name} {best.split('-')[1]} 제외 주구간", r), flush=True)
        top = sorted(by.items(), key=lambda kv: -kv[1])
        print(f"   {name} 코인별 손익(시드=1): " + ", ".join(f"{m.split('-')[1]} {v:+.3f}" for m, v in top[:8]) +
              (" ... " + ", ".join(f"{m.split('-')[1]} {v:+.3f}" for m, v in top[-4:]) if len(top) > 8 else ""), flush=True)
    json.dump({" | ".join(k): v for k, v in results.items()}, open(os.path.join(DATA, "results.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
