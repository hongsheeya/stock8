"""10-23: US direction-trend rule (PAPER-only so far) on 2 years of data.

Data: yfinance regular-session bars, 1h (730 days) and 5m (60 days; used to
check that the hourly replay agrees with a finer one on the same days).
Rule (same shape as the validated KS rule): signal on a CLOSED bar, fill at
the next bar's open; index moved >= 1% from its day open in the side's
direction and is on that side of its session VWAP, the ETF above its own
VWAP; entries from `start` ET until 15:00 ET; one entry per ETF per day;
exit when the index is back through its open ("open") or across VWAP
("vwap"), the ETF -stop%, or flat at the last bar starting before 15:50 ET.
Cost per side: 0.10% (event commission + spread) or 0.25% (KIS list price).
Seed level: trade % x 0.33.
"""
import os
import pickle
import statistics
import sys
from collections import defaultdict

import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "us_cache")
os.makedirs(CACHE, exist_ok=True)
PAIRS = {"SQQQ": ("BEAR", "QQQ"), "PSQ": ("BEAR", "QQQ"), "SH": ("BEAR", "SPY"), "SPXU": ("BEAR", "SPY"),
         "SOXS": ("BEAR", "SOXX"), "QLD": ("BULL", "QQQ"), "SSO": ("BULL", "SPY"), "USD": ("BULL", "SOXX")}
SYMBOLS = sorted(set(PAIRS) | {p for _s, p in PAIRS.values()})


def load(interval, period):
    path = os.path.join(CACHE, f"{interval}.pkl")
    if os.path.exists(path):
        return pickle.load(open(path, "rb"))
    out = {}
    for sym in SYMBOLS:
        df = yf.Ticker(sym).history(period=period, interval=interval, prepost=False, auto_adjust=False)
        df = df.tz_convert("America/New_York")
        days = defaultdict(list)
        for ts, row in df.iterrows():
            hm = ts.strftime("%H:%M")
            if hm < "09:30" or hm >= "16:00" or row["Open"] != row["Open"]:
                continue
            days[ts.date().isoformat()].append({"hm": hm, "o": float(row["Open"]), "h": float(row["High"]), "l": float(row["Low"]),
                                                "c": float(row["Close"]), "v": float(row["Volume"] or 0)})
        for d, bars in days.items():
            pv = vv = 0.0
            for b in bars:
                tp = (b["h"] + b["l"] + b["c"]) / 3
                pv += tp * b["v"]; vv += b["v"]
                b["vwap"] = pv / vv if vv else tp
        out[sym] = dict(days)
        print(interval, sym, len(days), flush=True)
    pickle.dump(out, open(path, "wb"))
    return out


def trade(data, etf, day, start, exit_mode, stop, cost, bar_minutes):
    side, proxy = PAIRS[etf]
    e, ix = data[etf].get(day), data[proxy].get(day)
    if not e or not ix:
        return None
    pm = {b["hm"]: b for b in ix}
    o = ix[0]["o"]; sgn = 1 if side == "BULL" else -1
    for i in range(len(e) - 1):
        b, n = e[i], e[i + 1]
        p = pm.get(b["hm"])
        # the bar starting at hm closes at hm + bar_minutes
        close_hm = _add(b["hm"], bar_minutes)
        if p is None or close_hm < start or close_hm > "15:00":
            continue
        move = (p["c"] / o - 1) * 100 * sgn
        if not (move >= 1.0 and (p["c"] - p["vwap"]) * sgn > 0 and b["c"] > b["vwap"]):
            continue
        entry = n["o"]
        for j in range(i + 1, len(e)):
            bj = e[j]
            pj = pm.get(bj["hm"])
            last = j == len(e) - 1 or _add(e[j + 1]["hm"], 0) >= "15:50"
            if bj["l"] <= entry * (1 - stop / 100):
                px = min(bj["o"], entry * (1 - stop / 100))
                return (px / entry - 1) * 100 - 2 * cost
            if pj is not None:
                mv = (pj["c"] / o - 1) * 100 * sgn
                rev = mv < 0 if exit_mode == "open" else (pj["c"] - pj["vwap"]) * sgn < 0
            else:
                rev = False
            if rev or last:
                px = e[j + 1]["o"] if (rev and j + 1 < len(e)) else bj["c"]
                return (px / entry - 1) * 100 - 2 * cost
        return (e[-1]["c"] / entry - 1) * 100 - 2 * cost
    return None


def _add(hm, minutes):
    h, m = int(hm[:2]), int(hm[3:5]) + minutes
    h += m // 60; m %= 60
    return f"{h:02d}:{m:02d}"


def run(data, days, bar_minutes, start="10:00", exit_mode="open", stop=2.5, cost=0.10, sides=("BULL", "BEAR")):
    per_day, trades, by_side = defaultdict(float), [], defaultdict(list)
    for d in days:
        for etf, (side, _p) in PAIRS.items():
            if side not in sides:
                continue
            r = trade(data, etf, d, start, exit_mode, stop, cost, bar_minutes)
            if r is not None:
                trades.append(r); per_day[d] += r * 0.33; by_side[side].append(r)
    eq = pk = dd = 0.0
    for d in days:
        eq += per_day.get(d, 0); pk = max(pk, eq); dd = min(dd, eq - pk)
    q = max(1, len(days) // 4)
    quarters = [sum(per_day.get(d, 0) for d in days[k * q:(k + 1) * q if k < 3 else len(days)]) for k in range(4)]
    return {"n": len(trades), "win": sum(r > 0 for r in trades) / max(1, len(trades)) * 100,
            "avg": statistics.mean(trades) if trades else 0, "total": sum(per_day.values()), "dd": dd, "q": quarters,
            "bull": sum(by_side["BULL"]) * 0.33, "bear": sum(by_side["BEAR"]) * 0.33}


def fmt(label, r):
    return (f"{label:42s} 거래 {r['n']:4d} 승률 {r['win']:3.0f}% 평균 {r['avg']:+.3f}% 합계 {r['total']:+6.1f}% 낙폭 {r['dd']:+6.1f}% "
            f"| 롱 {r['bull']:+6.1f} 인버스 {r['bear']:+6.1f} | 분기 " + " ".join(f"{x:+5.1f}" for x in r["q"]))


if __name__ == "__main__":
    h1 = load("1h", "730d")
    m5 = load("5m", "60d")
    days_h = sorted(set.intersection(*[set(h1[s]) for s in SYMBOLS]))
    days_m = sorted(set.intersection(*[set(m5[s]) for s in SYMBOLS]))
    overlap = [d for d in days_m if d in set(days_h)]
    print(f"1h days {len(days_h)} ({days_h[0]}..{days_h[-1]}), 5m days {len(days_m)}, overlap {len(overlap)}")
    variants = [("10:00 시작 · 시가 복귀 청산 · 손절 2.5%", dict(start="10:00", exit_mode="open", stop=2.5)),
                ("10:00 · VWAP 청산 · 손절 1.5% (현재 모의 설정)", dict(start="10:00", exit_mode="vwap", stop=1.5)),
                ("10:30 · 시가 복귀 · 2.5%", dict(start="10:30", exit_mode="open", stop=2.5)),
                ("11:00 · 시가 복귀 · 2.5%", dict(start="11:00", exit_mode="open", stop=2.5))]
    print("\n== 같은 60일, 5분봉 vs 1시간봉 (1시간봉이 믿을 만한지) ==")
    for label, kw in variants:
        print(fmt("5m  " + label, run(m5, overlap, 5, **kw)))
        print(fmt("1h  " + label, run(h1, overlap, 60, **kw)))
    print("\n== 2년 (1시간봉) ==")
    half = len(days_h) // 2
    for label, kw in variants:
        for cost in (0.10, 0.25):
            r = run(h1, days_h, 60, cost=cost, **kw)
            a = run(h1, days_h[:half], 60, cost=cost, **kw)["total"]; b = run(h1, days_h[half:], 60, cost=cost, **kw)["total"]
            print(fmt(f"{label} 편도{cost}%", r) + f" | 앞 {a:+.1f} 뒤 {b:+.1f}")
    print("\n== 롱만 (2년, 1시간봉, 편도 0.10%) ==")
    for label, kw in variants[:1] + variants[2:]:
        print(fmt("롱만 " + label, run(h1, days_h, 60, sides=("BULL",), **kw)))
