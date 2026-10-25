"""Coin short side (PREREG.md). One state machine per coin: flat -> long
(the live rule, ATR x4) or short (the exact mirror); one position at a time.
Long-only with this machine must reproduce the variants study's V1 (asserted).

C1: 0.10%/side + half a tick, fills any time, no borrow cost.
C2: inverse-ETF reality (BTC/ETH): 0.30%/side, 10%/yr carry while short,
fills only in the US regular session (14-20 UTC weekdays; a stop touched
outside it fills at the next session open)."""
import datetime
import importlib.util
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("vstudy", os.path.join(HERE, "..", "variants", "study.py"))
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)
S, U = V.S, V.U
H, DAY = 3600, 86400
MARKETS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"]
FULL = ("2018-01-15", "2026-10-24")
SUBS = {"A 2018-01~2019-10": ("2018-01-15", "2019-10-21"), "B 2019-10~2025-10": ("2019-10-21", "2025-10-21"),
        "C 2025-10~2026-10": ("2025-10-21", "2026-10-24")}


def machine(c, start, end, k=4.0, long=True, short=True):
    """Trades [(side, entry_t, entry_px, exit_t, exit_px, why)]."""
    bars = S.build_bars(c)
    daily = [(b["start"], b["c"]) for b in S.build_bars(c, S.DAY_SEC)]
    atr = S.atr_series(bars)
    by_bar = defaultdict(list)
    for row in c:
        by_bar[row["t"] // S.BAR_SEC * S.BAR_SEC].append(row)
    trades, pos, entry, di = [], {}, None, 0
    for j, bar in enumerate(bars):
        if bar["end"] < start or bar["start"] >= end:
            continue
        while di < len(daily) and daily[di][0] + S.DAY_SEC <= bar["end"]:
            di += 1
        done = daily[:di]
        sma = sum(x for _t, x in done[-50:]) / 50 if len(done) >= 50 else None
        if pos:
            for row in by_bar.get(bar["start"], []):
                if row["t"] >= end:
                    break
                if pos["side"] == "L" and row["l"] <= pos["stop"]:
                    trades.append(("L", entry[0], entry[1], row["t"], min(row["o"], pos["stop"]), "stop"))
                    pos = {}
                    break
                if pos["side"] == "S" and row["h"] >= pos["stop"]:
                    trades.append(("S", entry[0], entry[1], row["t"], max(row["o"], pos["stop"]), "stop"))
                    pos = {}
                    break
            if pos and atr[j] is not None:
                if pos["side"] == "L":
                    pos["x"] = max(pos["x"], bar["h"])
                    pos["stop"] = max(pos["stop"], pos["x"] - k * atr[j])
                else:
                    pos["x"] = min(pos["x"], bar["l"])
                    pos["stop"] = min(pos["stop"], pos["x"] + k * atr[j])
        if not pos and j + 1 < len(bars) and bars[j + 1]["start"] < end:
            if j < S.DONCHIAN_N or atr[j] is None or sma is None:
                continue
            window = bars[j - S.DONCHIAN_N:j]
            side = None
            if long and bar["c"] > max(b["h"] for b in window) and bar["c"] > sma:
                side = "L"
            elif short and bar["c"] < min(b["l"] for b in window) and bar["c"] < sma:
                side = "S"
            if not side:
                continue
            first = by_bar.get(bars[j + 1]["start"], [])
            if not first or first[0]["t"] < start:
                continue
            entry = (first[0]["t"], first[0]["o"])
            pos = {"side": side, "x": bar["h"] if side == "L" else bar["l"],
                   "stop": bar["h"] - k * atr[j] if side == "L" else bar["l"] + k * atr[j]}
    if pos and entry:
        last = [r for r in c if r["t"] < end][-1]
        trades.append((pos["side"], entry[0], entry[1], last["t"], last["c"], "end"))
    return trades


def in_session(t):
    d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
    return d.weekday() < 5 and 14 <= d.hour <= 19


def next_session(t, candles_by_t, end):
    while t < end:
        if in_session(t) and t in candles_by_t:
            return t
        t += H
    return None


def to_etf(trades, c, end):
    """C2: move every short fill into the US session (entries and exits)."""
    by_t = {r["t"]: r for r in c}
    out = []
    for side, et, epx, xt, xpx, why in trades:
        if side != "S":
            out.append((side, et, epx, xt, xpx, why))
            continue
        e2 = next_session(et, by_t, end)
        if e2 is None:
            continue
        epx2 = by_t[e2]["o"] if e2 != et else epx
        if in_session(xt) and xt >= e2:
            x2, xpx2 = xt, xpx
        else:
            x2 = next_session(max(xt, e2), by_t, end)
            if x2 is None:
                x2, xpx2 = xt, xpx
            else:
                xpx2 = by_t[x2]["o"]
                if why == "stop":
                    xpx2 = max(xpx2, xpx)  # the gap can only make a short stop worse
        out.append((side, e2, epx2, x2, xpx2, why))
    return out


def sleeve(c, trades, start, end, fee, half_tick=True, carry=0.0):
    tk = U.ticks(c) if half_tick else {}
    month = lambda sec: datetime.datetime.fromtimestamp(sec, datetime.timezone.utc).strftime("%Y-%m")
    close = {r["t"]: r["c"] for r in c}
    ev = sorted(trades, key=lambda x: x[1])
    eq, cash, pos, ti, last = {}, 1.0, None, 0, None
    rets = {"L": [], "S": []}
    t = start
    while t < end:
        last = close.get(t, last)
        if pos and pos["exit_t"] == t:
            side, epx, xpx = pos["side"], pos["epx"], pos["xpx"]
            if side == "L":
                r = (xpx * (1 - fee)) / (epx * (1 + fee)) - 1
            else:
                r = (epx * (1 - fee) - xpx * (1 + fee)) / epx - carry * (t - pos["t"]) / (365.25 * DAY)
            cash *= (1 + r)
            rets[side].append(r)
            pos = None
        while ti < len(ev) and ev[ti][1] <= t and pos is None:
            side, et, epx, xt, xpx, _w = ev[ti]
            ti += 1
            if et != t:
                continue
            ht = tk.get(month(et), 0) / 2
            hx = tk.get(month(xt), 0) / 2
            pos = {"side": side, "t": et, "exit_t": xt, "epx": epx + ht if side == "L" else epx - ht,
                   "xpx": xpx - hx if side == "L" else xpx + hx}
            if xt == t:  # stopped in the entry candle
                side, epx, xpx = pos["side"], pos["epx"], pos["xpx"]
                r = (xpx * (1 - fee)) / (epx * (1 + fee)) - 1 if side == "L" else (epx * (1 - fee) - xpx * (1 + fee)) / epx
                cash *= (1 + r)
                rets[side].append(r)
                pos = None
        if pos and last:
            mark = (last / pos["epx"] - 1) if pos["side"] == "L" else (1 - last / pos["epx"])
            eq[t] = cash * (1 + mark)
        else:
            eq[t] = cash
        t += H
    return eq, rets


def run(markets, period, k=4.0, long=True, short=True, cost="C1"):
    start, end = U.epoch(period[0]), U.epoch(period[1])
    curves, rets = [], {"L": [], "S": []}
    for m in markets:
        c = V.candles(m)
        tr = machine(c, start, end, k=k, long=long, short=short)
        if cost == "C2":
            tr = to_etf(tr, c, end)
            eq, r = sleeve(c, tr, start, end, fee=0.003, half_tick=False, carry=0.10)
        else:
            eq, r = sleeve(c, tr, start, end, fee=0.001)
        curves.append(eq)
        for s in r:
            rets[s] += r[s]
    hours = sorted(curves[0])
    port = [sum(cv[t] for cv in curves) / len(curves) for t in hours]
    years = (end - start) / (365.25 * DAY)
    peak, mdd = 0.0, 0.0
    for v in port:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    cagr = (port[-1] ** (1 / years) - 1) * 100 if port[-1] > 0 else -100.0
    return {"cagr": cagr, "mdd": mdd * 100, "mar": cagr / abs(mdd * 100) if mdd < 0 else 0.0,
            "nL": len(rets["L"]), "nS": len(rets["S"]),
            "winS": sum(x > 0 for x in rets["S"]) / len(rets["S"]) * 100 if rets["S"] else 0.0,
            "avgS": sum(rets["S"]) / len(rets["S"]) * 100 if rets["S"] else 0.0}


def fmt(label, r):
    return (f"{label:30s} 연{r['cagr']:+6.1f}% 낙폭{r['mdd']:+6.1f}% MAR{r['mar']:5.2f} | 롱 {r['nL']:3d}회 숏 {r['nS']:3d}회 "
            f"(숏 승률 {r['winS']:3.0f}%, 평균 {r['avgS']:+.2f}%)")


def main():
    c0 = V.candles("KRW-BTC")
    a, b = U.epoch(V.SELECT[0]), U.epoch(V.SELECT[1])
    lo = machine(c0, a, b, k=4.0, short=False)
    ref = V.replay_4h(c0, a, b, k=4.0)
    assert [t[1:] for t in lo] == ref, "long-only machine must equal V1"
    print("parity: long-only machine == V1 (ATR x4): OK")

    res = {}
    for label, per in [("전체 2018-01~2026-10", FULL)] + list(SUBS.items()):
        print(f"\n== {label} (C1: 0.10%+반 칸) ==")
        for name, kw in (("롱 단독 (현재)", dict(short=False)), ("숏 단독", dict(long=False)), ("롱+숏", {}),
                         ("[참고] 숏 단독 ×2", dict(long=False, k=2.0))):
            r = run(MARKETS, per, **kw)
            res[(label, name)] = r
            print(fmt(name, r), flush=True)

    print("\n== C2 인버스 ETF 현실 (BTC·ETH, 전체 구간) ==")
    lo2 = run(MARKETS[:2], FULL, short=False)
    sh2 = run(MARKETS[:2], FULL, long=False, cost="C2")
    ls2 = run(MARKETS[:2], FULL, cost="C2")
    print(fmt("롱 단독 BTC·ETH (C1)", lo2))
    print(fmt("숏 단독 BTC·ETH (C2)", sh2))
    print(fmt("롱(C1)+숏(C2) BTC·ETH", ls2))
    for label, per in SUBS.items():
        print(fmt(f"  숏 C2 {label}", run(MARKETS[:2], per, long=False, cost="C2")))

    full = "전체 2018-01~2026-10"
    sh, lo_, ls = res[(full, "숏 단독")], res[(full, "롱 단독 (현재)")], res[(full, "롱+숏")]
    subs_pos = sum(res[(lab, "숏 단독")]["cagr"] > 0 for lab in SUBS)
    checks = [
        ("1 숏 단독이 원리상 돈이 됨 (C1)", sh["cagr"] > 0 and subs_pos >= 2, f"전체 연{sh['cagr']:+.1f}%, 구간 플러스 {subs_pos}/3"),
        ("2 롱+숏이 롱 단독보다 나음 (C1)", ls["mar"] > lo_["mar"] and ls["mdd"] >= -35,
         f"MAR {ls['mar']:.2f} vs {lo_['mar']:.2f}, 낙폭 {ls['mdd']:.1f}%"),
        ("3 인버스 ETF로 실현 가능 (C2)", sh2["cagr"] > 0 and ls2["mar"] >= lo2["mar"],
         f"숏 연{sh2['cagr']:+.1f}%, MAR {ls2['mar']:.2f} vs {lo2['mar']:.2f}"),
    ]
    print("\n== 판정 ==")
    for name, ok, detail in checks:
        print(f"  {'통과' if ok else '탈락'}  {name}: {detail}")
    ok1, ok2, ok3 = (c[1] for c in checks)
    verdict = "숏 추가 안 함" if not (ok1 and ok2) else ("인버스 ETF로 실현 가능" if ok3 else "원리상 되지만 인버스 ETF로는 안 됨")
    print("결론:", verdict)


if __name__ == "__main__":
    main()
