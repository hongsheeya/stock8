"""Coin strategy variants (PREREG.md). Same construction as the live engine:
four 25% sleeves compounding independently, cash before a listing; cost per
side 0.10% (or 0.20%) plus half a tick; Upbit 60m candles (UTC days).

V0 is the app's own coin_strategy.replay; V1 the same code with k=4 (parity
of the k-parameterised copy with V0 is asserted at start)."""
import datetime
import importlib.util
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ustudy", os.path.join(HERE, "..", "universe", "study.py"))
U = importlib.util.module_from_spec(spec)
spec.loader.exec_module(U)
S = U.S
DATA = U.DATA
H, DAY = 3600, 86400
MARKETS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"]
SELECT = ("2019-10-21", "2026-10-24")
HOLDOUT = ("2018-01-15", "2019-10-21")
SELECT_CUTS = ["2019-10-21", "2020-10-21", "2021-10-21", "2022-10-21", "2023-10-21", "2024-10-21", "2025-10-21", "2026-10-24"]
HOLDOUT_CUTS = ["2018-01-15", "2018-10-21", "2019-10-21"]


def candles(market):
    rows = {}
    for folder in ("hourly_early", "hourly"):
        path = os.path.join(DATA, folder, f"{market}.json")
        if os.path.exists(path):
            for r in json.load(open(path)):
                rows[r["t"]] = r
    return [{"t": U.epoch(r["t"]), "o": float(r["o"]), "h": float(r["h"]), "l": float(r["l"]), "c": float(r["c"])}
            for r in sorted(rows.values(), key=lambda r: r["t"])]


# ------------------------------------------------------------------ 4h family
def replay_4h(c, start, end, k=2.0, exit_mode="atr"):
    """coin_strategy.replay generalised: k = ATR multiple; exit_mode "atr" or
    "sma50d" (exit at the next day's first candle after a daily close < SMA50)."""
    bars = S.build_bars(c)
    daily = [(b["start"], b["c"]) for b in S.build_bars(c, S.DAY_SEC)]
    atr = S.atr_series(bars)
    by_bar = defaultdict(list)
    for row in c:
        by_bar[row["t"] // S.BAR_SEC * S.BAR_SEC].append(row)
    trades, pos, entry, di = [], {}, None, 0
    exit_next = False
    for j, bar in enumerate(bars):
        if bar["end"] < start or bar["start"] >= end:
            continue
        while di < len(daily) and daily[di][0] + S.DAY_SEC <= bar["end"]:
            di += 1
        done = daily[:di]
        sma = sum(x for _t, x in done[-50:]) / 50 if len(done) >= 50 else None
        if pos.get("long"):
            rows = by_bar.get(bar["start"], [])
            if exit_mode == "atr":
                for row in rows:
                    if row["t"] >= end:
                        break
                    if row["l"] <= pos["stop"]:
                        trades.append((entry[0], entry[1], row["t"], min(row["o"], pos["stop"]), "stop"))
                        pos = {}
                        break
                if pos.get("long") and atr[j] is not None:
                    pos["hh"] = max(pos["hh"], bar["h"])
                    pos["stop"] = max(pos["stop"], pos["hh"] - k * atr[j])
            else:
                if exit_next and rows and rows[0]["t"] < end:
                    trades.append((entry[0], entry[1], rows[0]["t"], rows[0]["o"], "trend"))
                    pos, exit_next = {}, False
                if pos.get("long") and bar["end"] % S.DAY_SEC == 0 and sma is not None and done and done[-1][1] < sma:
                    exit_next = True
        if not pos.get("long") and j + 1 < len(bars) and bars[j + 1]["start"] < end:
            if j < S.DONCHIAN_N or atr[j] is None or sma is None:
                continue
            hh = max(b["h"] for b in bars[j - S.DONCHIAN_N:j])
            if not (bar["c"] > hh and bar["c"] > sma):
                continue
            first = by_bar.get(bars[j + 1]["start"], [])
            if not first or first[0]["t"] < start:
                continue
            entry = (first[0]["t"], first[0]["o"])
            pos = {"long": True, "hh": bar["h"], "stop": bar["h"] - k * atr[j]}
            exit_next = False
    if pos.get("long") and entry:
        last = [r for r in c if r["t"] < end][-1]
        trades.append((entry[0], entry[1], last["t"], last["c"], "end"))
    return trades


# ------------------------------------------------------------------ daily family
def daily_bars(c):
    out = []
    for b in S.build_bars(c, S.DAY_SEC):
        out.append(b)
    return out


def replay_daily(c, start, end, rule):
    days = daily_bars(c)
    first_of_day = {}
    for row in c:
        first_of_day.setdefault(row["t"] // DAY * DAY, row)
    trades, holding, entry = [], False, None
    closes = [d["c"] for d in days]
    for i, d in enumerate(days):
        if d["end"] < start or d["start"] >= end:
            continue
        nxt = first_of_day.get(d["end"])
        if rule == "turtle":
            if i < 20:
                continue
            want_in = closes[i] > max(x["h"] for x in days[i - 20:i])
            want_out = closes[i] < min(x["l"] for x in days[i - 10:i])
        else:
            n = 50 if rule == "sma50" else 100
            if i + 1 < n:
                continue
            sma = sum(closes[i + 1 - n:i + 1]) / n
            want_in, want_out = closes[i] > sma, closes[i] < sma
        if nxt is None or nxt["t"] >= end:
            continue
        if not holding and want_in and nxt["t"] >= start:
            holding, entry = True, (nxt["t"], nxt["o"])
        elif holding and want_out:
            trades.append((entry[0], entry[1], nxt["t"], nxt["o"], "trend"))
            holding = False
    if holding and entry:
        last = [r for r in c if r["t"] < end][-1]
        trades.append((entry[0], entry[1], last["t"], last["c"], "end"))
    return trades


VARIANTS = {
    "V0": lambda c, a, b: S.replay(c, a, b),
    "V1": lambda c, a, b: replay_4h(c, a, b, k=4.0),
    "V2": lambda c, a, b: replay_4h(c, a, b, exit_mode="sma50d"),
    "V3": lambda c, a, b: replay_daily(c, a, b, "turtle"),
    "V4": lambda c, a, b: replay_daily(c, a, b, "sma50"),
    "V5": lambda c, a, b: replay_daily(c, a, b, "sma100"),
}
LABEL = {"V0": "현재 규칙", "V1": "손절 ATR×4", "V2": "일봉 50일선 이탈 청산", "V3": "터틀(20일 돌파/10일 이탈)",
         "V4": "50일선 위 보유", "V5": "100일선 위 보유"}


# ------------------------------------------------------------------ sleeves
def sleeve_curve(c, trades, start, end, fee):
    tk = U.ticks(c)
    month = lambda sec: datetime.datetime.fromtimestamp(sec, datetime.timezone.utc).strftime("%Y-%m")
    adj = [(et, epx + tk.get(month(et), 0) / 2, xt, xpx - tk.get(month(xt), 0) / 2) for et, epx, xt, xpx, _w in trades]
    close = {r["t"]: r["c"] for r in c}
    eq, cash, qty, ti, last = {}, 1.0, 0.0, 0, None
    rets, holds = [], []
    t = start
    while t < end:
        while ti < len(adj) and adj[ti][2] == t and qty > 0:
            proceeds = qty * adj[ti][3] * (1 - fee)
            rets.append(proceeds / cost_basis - 1)
            holds.append((adj[ti][2] - adj[ti][0]) / DAY)
            cash, qty = proceeds, 0.0
            ti += 1
        if ti < len(adj) and adj[ti][0] == t and qty == 0:
            cost_basis = cash
            qty, cash = cash / (adj[ti][1] * (1 + fee)), 0.0
            if adj[ti][2] == t:
                proceeds = qty * adj[ti][3] * (1 - fee)
                rets.append(proceeds / cost_basis - 1)
                holds.append(0.0)
                cash, qty = proceeds, 0.0
                ti += 1
        last = close.get(t, last)
        eq[t] = cash + qty * (last or 0)
        t += H
    return eq, rets, holds


def run(variant, markets, period, fee=0.001, exclude=()):
    start, end = U.epoch(period[0]), U.epoch(period[1])
    curves, rets, holds, pnl = [], [], [], {}
    for m in markets:
        c = candles(m)
        trades = VARIANTS[variant](c, start, end) if c else []
        eq, r, h = sleeve_curve(c, trades, start, end, fee) if c else ({}, [], [])
        if not eq:
            eq = {t: 1.0 for t in range(start, end, H)}
        pnl[m] = eq[max(eq)] - 1
        if m in exclude:
            continue
        curves.append(eq)
        rets += r
        holds += h
    hours = sorted(curves[0])
    port = [sum(cv[t] for cv in curves) / len(curves) for t in hours]
    years = (end - start) / (365.25 * DAY)
    peak, mdd = 0.0, 0.0
    for v in port:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    cagr = (port[-1] ** (1 / years) - 1) * 100 if port[-1] > 0 else -100.0
    idx = dict(zip(hours, port))
    return {"cagr": cagr, "mdd": mdd * 100, "mar": cagr / abs(mdd * 100) if mdd < 0 else float("inf"), "total": (port[-1] - 1) * 100,
            "trades": len(rets), "win": sum(x > 0 for x in rets) / len(rets) * 100 if rets else 0.0,
            "hold": sum(holds) / len(holds) if holds else 0.0, "pnl": pnl, "idx": idx, "port_end": port[-1]}


def periods(res, cuts):
    out, prev = [], 1.0
    idx = res["idx"]
    keys = sorted(idx)
    for cut in cuts[1:]:
        t = U.epoch(cut)
        k = max((x for x in keys if x <= t - H), default=keys[-1])
        out.append((idx[k] / prev - 1) * 100)
        prev = idx[k]
    return out


def line(name, r, years=None):
    ys = (" | " + " ".join(f"{y:+6.1f}" for y in years)) if years else ""
    return (f"{name:3s} {LABEL[name]:22s} 연{r['cagr']:+6.1f}% 낙폭{r['mdd']:+6.1f}% MAR{r['mar']:5.2f} 누적{r['total']:+8.1f}% "
            f"거래{r['trades']:4d} 승률{r['win']:3.0f}% 평균보유{r['hold']:5.1f}일{ys}")


def main():
    c0 = candles("KRW-BTC")
    a, b = U.epoch(SELECT[0]), U.epoch(SELECT[1])
    assert replay_4h(c0, a, b, k=2.0) == S.replay(c0, a, b), "k-parameterised copy must equal the live replay"
    print("parity V0 copy == coin_strategy.replay: OK")

    print("\n== 선정 구간 2019-10-21 ~ 2026-10-24 (BTC·ETH·XRP·SOL), 비용 0.10%+반 칸 ==")
    sel = {}
    for v in VARIANTS:
        sel[v] = run(v, MARKETS, SELECT)
        sel[v]["years"] = periods(sel[v], SELECT_CUTS)
        print(line(v, sel[v], sel[v]["years"]), flush=True)
    base = sel["V0"]
    eligible = [v for v in VARIANTS if v != "V0" and sel[v]["cagr"] >= base["cagr"] and sel[v]["mdd"] >= -35]
    pick = max(eligible, key=lambda v: sel[v]["mar"]) if eligible else None
    print(f"\n선정: {pick or '없음 (V0 유지)'}  (조건 통과: {eligible})")

    print("\n== 참고: 비용 2배 (선정 구간) ==")
    dbl = {v: run(v, MARKETS, SELECT, fee=0.002) for v in VARIANTS}
    for v in VARIANTS:
        print(line(v, dbl[v]))

    print("\n== 시험 구간 2018-01-15 ~ 2019-10-21 (BTC·ETH·XRP) ==")
    hold = {}
    for v in VARIANTS:
        hold[v] = run(v, MARKETS[:3], HOLDOUT)
        hold[v]["years"] = periods(hold[v], HOLDOUT_CUTS)
        print(line(v, hold[v], hold[v]["years"]), flush=True)
    bh = {}
    for per, mk in ((SELECT, MARKETS), (HOLDOUT, MARKETS[:3])):
        start, end = U.epoch(per[0]), U.epoch(per[1])
        curves = []
        for m in mk:
            c = candles(m)
            first = next((r for r in c if r["t"] >= start), None)
            eq, cl, last = {}, {r["t"]: r["c"] for r in c}, None
            q = 1.0 / first["o"] if first else 0
            t = start
            while t < end:
                last = cl.get(t, last)
                eq[t] = q * last if (first and last and t >= first["t"]) else 1.0
                t += H
            curves.append(eq)
        hours = sorted(curves[0])
        port = [sum(cv[t] for cv in curves) / len(curves) for t in hours]
        peak, mdd = 0.0, 0.0
        for v in port:
            peak = max(peak, v); mdd = min(mdd, v / peak - 1)
        yrs = (end - start) / (365.25 * DAY)
        bh[per] = ((port[-1] ** (1 / yrs) - 1) * 100, mdd * 100)
        print(f"단순 보유 {per[0]}~{per[1]}: 연{bh[per][0]:+.1f}% 낙폭{bh[per][1]:+.1f}%")

    if pick:
        print(f"\n== 채택 기준 판정: {pick} vs V0 ==")
        best = max(base["pnl"], key=base["pnl"].get)
        ex_pick = run(pick, MARKETS, SELECT, exclude=(max(sel[pick]["pnl"], key=sel[pick]["pnl"].get),))
        ex_base = run("V0", MARKETS, SELECT, exclude=(best,))
        checks = [
            ("1 시험 구간 MAR ≥ V0", hold[pick]["mar"] >= hold["V0"]["mar"], f"{hold[pick]['mar']:.2f} vs {hold['V0']['mar']:.2f}"),
            ("2 시험 구간 낙폭 -35% 이내", hold[pick]["mdd"] >= -35, f"{hold[pick]['mdd']:.1f}%"),
            ("3 비용 2배 연수익 > V0", dbl[pick]["cagr"] > dbl["V0"]["cagr"], f"{dbl[pick]['cagr']:+.1f}% vs {dbl['V0']['cagr']:+.1f}%"),
            ("4 플러스인 해 ≥ V0", sum(y >= 0 for y in sel[pick]["years"]) >= sum(y >= 0 for y in base["years"]),
             f"{sum(y >= 0 for y in sel[pick]['years'])} vs {sum(y >= 0 for y in base['years'])} (7개 구간)"),
            ("5 최고 코인 제외 연수익 > V0", ex_pick["cagr"] > ex_base["cagr"], f"{ex_pick['cagr']:+.1f}% vs {ex_base['cagr']:+.1f}%"),
        ]
        for name, ok, detail in checks:
            print(f"  {'통과' if ok else '탈락'}  {name}: {detail}")
        print("판정:", "채택 (V0 교체)" if all(ok for _n, ok, _d in checks) else "V0 유지")


if __name__ == "__main__":
    main()
