"""10-23: C. intraday reversal (fade) on QQQ / SPY, plus extra A checks.

C rule (pre-registered): signal on a CLOSED bar between 10:00 and 15:00 ET;
the index has moved >= T% from its day open and is beyond its session VWAP
in that direction -> take the opposite side at the next bar's open (2x
exposure, modelled as 2 x index return: QLD/SSO after a drop, QID/SDS after
a rise). Exit: target touched (index back to VWAP or to its open; filled at
the target), index stop 1.25% further against (= ETF -2.5%, checked first if
both touch in one bar), else the session close. One trade per index per day.
Grid: T in {1.0, 1.5} x target in {vwap, open}. Pick on the first half of the
3 years, report the second half. Costs 0.10% / 0.25% per side on the ETF.
Seed-level = trade % x 0.33 (as in the other US studies).
"""
import importlib.util
import os
import statistics
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("u", os.path.join(HERE, "us_trend_study.py"))
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)


def fade(bars, start, T, target, cost, bar_minutes, lev=2.0, stop_idx=1.25):
    o = bars[0]["o"]
    for i in range(len(bars) - 1):
        b = bars[i]
        close_hm = u._add(b["hm"], bar_minutes)
        if close_hm < start or close_hm > "15:00":
            continue
        move = (b["c"] / o - 1) * 100
        if abs(move) < T or (b["c"] - b["vwap"]) * move <= 0:
            continue
        sgn = -1 if move > 0 else 1          # our direction on the index
        entry = bars[i + 1]["o"]
        tgt = b["vwap"] if target == "vwap" else o
        # target must still be on the far side of the entry
        if (tgt - entry) * sgn <= 0:
            return None
        stop = entry * (1 - sgn * stop_idx / 100)
        for j in range(i + 1, len(bars)):
            bj = bars[j]
            if target == "vwap" and j > i + 1:
                tgt = bars[j - 1]["vwap"]
            hit_stop = bj["l"] <= stop if sgn > 0 else bj["h"] >= stop
            hit_tgt = bj["h"] >= tgt if sgn > 0 else bj["l"] <= tgt
            if hit_stop:
                px = min(bj["o"], stop) if sgn > 0 else max(bj["o"], stop)
                break
            if hit_tgt:
                px = max(bj["o"], tgt) if sgn > 0 else min(bj["o"], tgt)
                break
        else:
            px = bars[-1]["c"]
        return {"ret": (px / entry - 1) * 100 * sgn * lev - 2 * cost, "dir": "up_fade" if sgn < 0 else "down_fade"}
    return None


def run(data, days, bar_minutes, T, target, cost, start="10:00"):
    per_day, trades, by_dir = defaultdict(float), [], defaultdict(list)
    for d in days:
        for idx in ("QQQ", "SPY"):
            bars = data[idx].get(d)
            if not bars:
                continue
            t = fade(bars, start, T, target, cost, bar_minutes)
            if t:
                trades.append(t["ret"]); per_day[d] += t["ret"] * 0.33; by_dir[t["dir"]].append(t["ret"])
    eq = pk = dd = 0.0
    for d in days:
        eq += per_day.get(d, 0); pk = max(pk, eq); dd = min(dd, eq - pk)
    q = max(1, len(days) // 4)
    quarters = [sum(per_day.get(d, 0) for d in days[k * q:(k + 1) * q if k < 3 else len(days)]) for k in range(4)]
    return {"n": len(trades), "win": sum(r > 0 for r in trades) / max(1, len(trades)) * 100,
            "avg": statistics.mean(trades) if trades else 0, "total": sum(per_day.values()), "dd": dd, "q": quarters,
            "up": sum(by_dir["up_fade"]) * 0.33, "down": sum(by_dir["down_fade"]) * 0.33,
            "nup": len(by_dir["up_fade"]), "ndown": len(by_dir["down_fade"])}


def fmt(label, r):
    return (f"{label:30s} 거래 {r['n']:4d} 승률 {r['win']:3.0f}% 평균 {r['avg']:+.3f}% 합계 {r['total']:+6.1f}% 낙폭 {r['dd']:+6.1f}% "
            f"| 상승되돌림 {r['nup']}건 {r['up']:+6.1f} 하락되돌림 {r['ndown']}건 {r['down']:+6.1f} | 분기 " + " ".join(f"{x:+5.1f}" for x in r["q"]))


if __name__ == "__main__":
    h1 = u.load("1h", "730d"); m5 = u.load("5m", "60d")
    days_h = sorted(set(h1["QQQ"]) & set(h1["SPY"]))
    days_m = sorted(set(m5["QQQ"]) & set(m5["SPY"]))
    half = len(days_h) // 2
    print(f"1h {len(days_h)}일 ({days_h[0]}..{days_h[-1]}), 앞 절반 ~{days_h[half - 1]}, 5m {len(days_m)}일")
    grid = [(T, tg) for T in (1.0, 1.5) for tg in ("vwap", "open")]
    for cost in (0.10, 0.25):
        print(f"\n== C. 장중 되돌림 (편도 {cost}%) ==")
        rows = []
        for T, tg in grid:
            a = run(h1, days_h[:half], 60, T, tg, cost); b = run(h1, days_h[half:], 60, T, tg, cost)
            rows.append(((T, tg), a, b))
        best = max(rows, key=lambda r: r[1]["total"])[0]
        for key, a, b in rows:
            tag = "  <== 선택" if key == best else ""
            print(fmt(f"학습 T{key[0]} {key[1]}", a))
            print(fmt(f"시험 T{key[0]} {key[1]}", b) + tag)
        print("-- 같은 규칙, 최근 60일 5분봉 vs 1시간봉 --")
        overlap = [d for d in days_m if d in set(days_h)]
        for T, tg in grid:
            print(fmt(f"5m T{T} {tg}", run(m5, overlap, 5, T, tg, cost)))
            print(fmt(f"1h T{T} {tg}", run(h1, overlap, 60, T, tg, cost)))
