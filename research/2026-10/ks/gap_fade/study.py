"""KS gap fade (PREREG.md). Reuses ../daily/study.py data and helpers
(KS_CACHE must point at its cache)."""
import os
import random
import statistics
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "daily"))
import study as d  # noqa: E402

START, SPLIT, END = pd.Timestamp("2016-09-22"), pd.Timestamp("2021-10-01"), d.END
OOS_START, OOS_END = pd.Timestamp("2010-02-22"), pd.Timestamp("2016-09-22")
FEE, FEE_HI = 0.0005, 0.0015
O, C, DAYS = d.O, d.C, d.DAYS


def gap(k):
    return O["069500"].iat[k] / C["069500"].iat[k - 1] - 1


def ok(sym, k):
    return not (np.isnan(O[sym].iat[k]) or np.isnan(C[sym].iat[k]))


def trades(th, start, end, long_only=False):
    lo, hi = int(np.searchsorted(DAYS, start)), int(np.searchsorted(DAYS, end))
    out = []
    for k in range(max(lo, 1), hi):
        g = gap(k)
        if np.isnan(g):
            continue
        if g >= th and not long_only and ok("252670", k):
            out.append((k, "O", k, "C", "252670"))
        elif g <= -th and ok("122630", k):
            out.append((k, "O", k, "C", "122630"))
    return out


def curve(tr, fee, start, end):
    return d.daily_curve(tr, fee, start, end)


def placebo(tr, start, end, reps=1000, seed=5):
    rng = random.Random(seed)
    lo, hi = int(np.searchsorted(DAYS, start)), int(np.searchsorted(DAYS, end))
    real = statistics.mean(d.trade_ret(t, FEE) for t in tr)
    pools = {s: [k for k in range(lo, hi) if ok(s, k)] for s in ("122630", "252670")}
    beats, means = 0, []
    for _ in range(reps):
        sim = []
        for s in ("122630", "252670"):
            n = sum(1 for t in tr if t[4] == s)
            sim += [(k, "O", k, "C", s) for k in rng.sample(pools[s], n)]
        mu = statistics.mean(d.trade_ret(t, FEE) for t in sim)
        means.append(mu)
        beats += mu >= real
    return round(real * 100, 3), round(statistics.mean(means) * 100, 3), beats / reps


def main():
    tr = trades(0.005, START, END)
    full = curve(tr, FEE, START, END)
    st = d.stats(full)
    first, second = d.stats(curve(tr, FEE, START, SPLIT)), d.stats(curve(tr, FEE, SPLIT, END))
    hi = d.stats(curve(tr, FEE_HI, START, END))
    years = (END - START).days / 365.25
    print(f"G1 gap 0.5%: trades {len(tr)} ({len(tr) / years:.1f}/yr)  full {st}  first {first}  second {second}  @0.15% {hi}")
    for s, label in (("252670", "gap up -> inverse"), ("122630", "gap down -> leverage")):
        side = [t for t in tr if t[4] == s]
        print(f"   {label}: n {len(side)} mean/trade {statistics.mean(d.trade_ret(t, FEE) for t in side) * 100:+.3f}% (after cost) "
              f"gross {statistics.mean(d.trade_ret(t, 0) for t in side) * 100:+.3f}%  full {d.stats(curve(side, FEE, START, END))}")
    print("   by year:", {y: d.year_ret(full, y) for y in range(2017, 2027)})
    real, rand, p = placebo(tr, START, END)
    print(f"   placebo: mean/trade {real}% vs random {rand}%  p={p}")
    nb = {th: d.stats(curve(trades(th, START, END), FEE, START, END)) for th in (0.003, 0.008)}
    print("   neighbors:", nb)
    oos = trades(0.005, OOS_START, OOS_END, long_only=True)
    oos_st = d.stats(curve(oos, FEE, OOS_START, OOS_END))
    print(f"   unseen 2010-02~2016-09 long side: n {len(oos)} {oos_st} mean/trade {statistics.mean(d.trade_ret(t, FEE) for t in oos) * 100:+.3f}%")
    gates = {
        "1 halves>0": first[0] > 0 and second[0] > 0,
        "2 @0.15%>0": hi[0] > 0,
        "3 placebo p<0.01": p < 0.01,
        "4 MAR>=0.3": st[2] >= 0.3,
        "5 neighbors>0": all(v[0] > 0 for v in nb.values()),
        "6 unseen long>0": oos_st[0] > 0,
    }
    print("gates", gates, "->", "PASS" if all(gates.values()) else "FAIL")


if __name__ == "__main__":
    main()
