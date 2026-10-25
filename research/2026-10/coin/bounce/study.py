"""Bear-market daily bounce rules (PREREG.md). Spot long only, entries only
while the coin's daily close is below its SMA50; next-day-open fills; -8%
stop inside the hourly candles; 5-day time exit. Four 25% sleeves; costs
0.10% (0.20%) per side plus half a tick. Placebo: random regime days with the
same exits. Combination: the live rule (coin_strategy.replay, ATR x4) has the
sleeve first; a bounce trade overlapping it is dropped."""
import importlib.util
import os
import random
import statistics
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("sstudy", os.path.join(HERE, "..", "short", "study.py"))
SH = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SH)
V, S, U = SH.V, SH.S, SH.U
H, DAY = 3600, 86400
MARKETS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"]
FULL = ("2018-01-15", "2026-10-24")
SUBS = {"A 2018-01~2019-10": ("2018-01-15", "2019-10-21"), "B 2019-10~2025-10": ("2019-10-21", "2025-10-21"),
        "C 2025-10~2026-10": ("2025-10-21", "2026-10-24")}
STOP = 0.08
HOLD_DAYS = 5
RULES = ("B1", "B2", "B3")
LABEL = {"B1": "RSI(2)<10 → 5일선 위 청산", "B2": "3일 연속 하락 -10% → 첫 상승 청산", "B3": "볼린저 하단 → 5일선 위 청산"}


def indicators(days):
    closes = [d["c"] for d in days]
    n = len(closes)
    sma = lambda k, i: sum(closes[i + 1 - k:i + 1]) / k if i + 1 >= k else None
    rsi = [None] * n
    ag = al = None
    for i in range(1, n):
        ch = closes[i] - closes[i - 1]
        g, l = max(ch, 0.0), max(-ch, 0.0)
        if i < 2:
            ag, al = g, l
            continue
        if i == 2:
            ag, al = (ag + g) / 2, (al + l) / 2
        else:
            ag, al = ag + (g - ag) / 2, al + (l - al) / 2
        rsi[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    out = []
    for i in range(n):
        s20 = sma(20, i)
        sd = statistics.pstdev(closes[i - 19:i + 1]) if i >= 19 else None
        out.append({"sma50": sma(50, i), "sma5": sma(5, i), "rsi2": rsi[i],
                    "bb_low": (s20 - 2 * sd) if s20 is not None and sd is not None else None})
    return closes, out


def entry_signal(rule, i, closes, ind):
    x = ind[i]
    if x["sma50"] is None or closes[i] >= x["sma50"]:
        return False  # bear regime only
    if rule == "B1":
        return x["rsi2"] is not None and x["rsi2"] < 10
    if rule == "B2":
        return i >= 3 and closes[i] < closes[i - 1] < closes[i - 2] < closes[i - 3] and closes[i] / closes[i - 3] - 1 <= -0.10
    return x["bb_low"] is not None and closes[i] < x["bb_low"]


def profit_exit(rule, i, closes, ind):
    if rule == "B2":
        return closes[i] > closes[i - 1]
    return ind[i]["sma5"] is not None and closes[i] > ind[i]["sma5"]


def simulate_from(rule, entry_day, days, closes, ind, by_day, end):
    """Entry at the open of days[entry_day]; returns (et, epx, xt, xpx, why) or None."""
    first = by_day.get(days[entry_day]["start"])
    if not first or first[0]["t"] >= end:
        return None
    et, epx = first[0]["t"], first[0]["o"]
    stop = epx * (1 - STOP)
    for j in range(entry_day, len(days)):
        for row in by_day.get(days[j]["start"], []):
            if row["t"] >= end:
                return (et, epx, row["t"], row["o"], "end")
            if row["l"] <= stop:
                return (et, epx, row["t"], min(row["o"], stop), "stop")
        timed = j - entry_day + 1 >= HOLD_DAYS
        if timed or profit_exit(rule, j, closes, ind):
            nxt = by_day.get(days[j]["end"]) if j + 1 < len(days) else None
            if not nxt:
                last = by_day[days[j]["start"]][-1]
                return (et, epx, last["t"], last["c"], "end")
            return (et, epx, nxt[0]["t"], nxt[0]["o"], "time" if timed else "profit")
    return None


def prepared(market):
    c = V.candles(market)
    days = S.build_bars(c, S.DAY_SEC)
    closes, ind = indicators(days)
    by_day = defaultdict(list)
    for row in c:
        by_day[row["t"] // DAY * DAY].append(row)
    return c, days, closes, ind, by_day


def bounce_trades(rule, prep, start, end):
    c, days, closes, ind, by_day = prep
    trades, i = [], 0
    while i < len(days) - 1:
        d = days[i]
        if d["end"] < start + DAY or d["start"] >= end or not entry_signal(rule, i, closes, ind):
            i += 1
            continue
        tr = simulate_from(rule, i + 1, days, closes, ind, by_day, end)
        if not tr or tr[0] < start:
            i += 1
            continue
        trades.append(("L",) + tr)
        i = max(i + 1, next((k for k, x in enumerate(days) if x["start"] <= tr[2] < x["end"]), i + 1))
    return trades


def regime_days(prep, start, end):
    c, days, closes, ind, by_day = prep
    return [i for i in range(len(days) - 1) if start + DAY <= days[i]["end"] and days[i]["start"] < end
            and ind[i]["sma50"] is not None and closes[i] < ind[i]["sma50"]]


def merge(main, extra):
    taken = sorted((t[1], t[3]) for t in main)
    out = list(main)
    for t in sorted(extra, key=lambda x: x[1]):
        if any(not (t[3] < a or t[1] > b) for a, b in taken):
            continue
        out.append(t)
        taken.append((t[1], t[3]))
    return sorted(out, key=lambda x: x[1])


def portfolio(trades_by_market, preps, period, fee):
    start, end = U.epoch(period[0]), U.epoch(period[1])
    curves, rets = [], []
    for m, trades in trades_by_market.items():
        eq, r = SH.sleeve(preps[m][0], trades, start, end, fee=fee)
        curves.append(eq)
        rets += r["L"]
    hours = sorted(curves[0])
    port = [sum(cv[t] for cv in curves) / len(curves) for t in hours]
    years = (end - start) / (365.25 * DAY)
    peak, mdd = 0.0, 0.0
    for v in port:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    cagr = (port[-1] ** (1 / years) - 1) * 100 if port[-1] > 0 else -100.0
    return {"cagr": cagr, "mdd": mdd * 100, "mar": cagr / abs(mdd * 100) if mdd < 0 else 0.0, "n": len(rets),
            "avg": statistics.mean(rets) * 100 if rets else 0.0, "win": sum(x > 0 for x in rets) / len(rets) * 100 if rets else 0.0}


def fmt(label, r):
    return (f"{label:34s} 연{r['cagr']:+6.1f}% 낙폭{r['mdd']:+6.1f}% MAR{r['mar']:5.2f} 거래{r['n']:4d} "
            f"승률{r['win']:3.0f}% 평균{r['avg']:+.2f}%")


def trade_ret(t, fee=0.001):
    return (t[4] * (1 - fee)) / (t[2] * (1 + fee)) - 1


def placebo(rule, preps, real, start, end, reps=1000, seed=7):
    rng = random.Random(seed)
    pools = {m: regime_days(p, start, end) for m, p in preps.items()}
    counts = {m: len(real[m]) for m in preps}
    real_mean = statistics.mean([trade_ret(t) for m in real for t in real[m]])
    beats = 0
    means = []
    for _ in range(reps):
        rs = []
        for m, p in preps.items():
            pool = pools[m]
            if not pool or not counts[m]:
                continue
            for i in rng.sample(pool, min(counts[m], len(pool))):
                tr = simulate_from(rule, i + 1, p[1], p[2], p[3], p[4], end)
                if tr:
                    rs.append(trade_ret(("L",) + tr))
        mu = statistics.mean(rs) if rs else 0.0
        means.append(mu)
        beats += mu >= real_mean
    return real_mean * 100, statistics.mean(means) * 100, beats / reps


def main():
    preps = {m: prepared(m) for m in MARKETS}
    fs, fe = U.epoch(FULL[0]), U.epoch(FULL[1])
    main_tr = {m: [("L",) + t for t in S.replay(preps[m][0], fs, fe)] for m in MARKETS}
    base = portfolio(main_tr, preps, FULL, 0.001)
    print(fmt("지금 롱 규칙 단독 (ATR×4)", base))
    verdicts = {}
    for rule in RULES:
        print(f"\n== {rule} {LABEL[rule]} ==")
        real = {m: bounce_trades(rule, preps[m], fs, fe) for m in MARKETS}
        r1 = portfolio(real, preps, FULL, 0.001)
        r2 = portfolio(real, preps, FULL, 0.002)
        print(fmt("전체 (0.10%)", r1))
        print(fmt("전체 (0.20%)", r2))
        subs = {}
        for lab, per in SUBS.items():
            a, b = U.epoch(per[0]), U.epoch(per[1])
            sub_tr = {m: bounce_trades(rule, preps[m], a, b) for m in MARKETS}
            subs[lab] = portfolio(sub_tr, preps, per, 0.001)
            print(fmt(f"  {lab}", subs[lab]))
        rm, pm, p = placebo(rule, preps, real, fs, fe)
        print(f"  무작위 비교: 실제 평균 {rm:+.2f}% / 무작위 평균 {pm:+.2f}% / 무작위가 같거나 좋을 확률 {p:.3f}")
        combo = portfolio({m: merge(main_tr[m], real[m]) for m in MARKETS}, preps, FULL, 0.001)
        print(fmt("  지금 규칙 + 반등 매매", combo))
        checks = [
            ("1 전체 연수익 플러스 (0.10%·0.20%)", r1["cagr"] > 0 and r2["cagr"] > 0),
            ("2 하위 구간 2개 이상 플러스", sum(s["cagr"] > 0 for s in subs.values()) >= 2),
            ("3 낙폭 -25% 이내", r1["mdd"] >= -25),
            ("4 거래당 평균 +0.3% 이상", r1["avg"] >= 0.3),
            ("5 무작위보다 확실히 좋음 (p<0.0167)", p < 0.0167),
            ("6 합쳐도 나빠지지 않음", combo["mar"] >= base["mar"] and combo["mdd"] >= -25),
        ]
        for name, ok in checks:
            print(f"    {'통과' if ok else '탈락'} {name}")
        verdicts[rule] = (all(ok for _n, ok in checks), combo["mar"])
    passed = [r for r, (ok, _m) in verdicts.items() if ok]
    print("\n결론:", f"후보 {max(passed, key=lambda r: verdicts[r][1])} (모의 운용 검증 후 사용)" if passed else "통과한 규칙 없음 — 하락장에는 지금처럼 현금 대기")


if __name__ == "__main__":
    main()
