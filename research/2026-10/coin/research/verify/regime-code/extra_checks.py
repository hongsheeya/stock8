"""Extra checks on top of verify_regime.py (same independent helpers):
1) equal-weight buy & hold per window, 2) B100 FULL quarterly returns,
3) execution-latency sensitivity (fill one bar later: open of the 2nd 5m bar of the day),
4) selection without the API warm-up (indicators from 5m-derived closes only),
5) dependence of TEST on warm-up data (SMA100 window at TEST start).
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_regime as V

MK = V.MKTS
bars = {m: V.load(m) for m in MK}
seqs = {m: V.daily_close_map(m, bars[m])[0] for m in MK}
end = max(bars[m][-1]["t"] for m in MK) + "Z"
W = {"TRAIN": (V.START, V.SPLIT), "TEST": (V.SPLIT, end), "FULL": (V.START, end)}


def b_sig(seqmap, m, n):
    a = V.sma_signal(seqmap[m], n)
    b = V.sma_signal(seqmap["KRW-BTC"], n)
    return {d: a[d] and b.get(d, False) for d in a}


# 1) buy & hold
alltrue = {d: True for d, _ in seqs["KRW-BTC"]}
for wn, (lo, hi) in W.items():
    rs = [V.sim(bars[m], alltrue, lo, hi) for m in MK]
    print(f"B&H {wn}: {sum(r[0] for r in rs) / 5 * 100:+.2f}%  mdd {V.port_mdd([r[2] for r in rs]) * 100:+.2f}%  per coin",
          " ".join(f"{m[4:]} {r[0] * 100:+.2f}" for m, r in zip(MK, rs)))

# 2) B100 FULL quarters
sig = {m: b_sig(seqs, m, 100) for m in MK}
curves = [V.sim(bars[m], sig[m], *W["FULL"])[2] for m in MK]


def port_at(t_excl):
    vals = []
    for cv in curves:
        v = 1.0
        for t, e in cv:
            if t < t_excl:
                v = e
            else:
                break
        vals.append(v)
    return sum(vals) / len(vals)


edges = [1.0] + [port_at(b) for b in ("2026-01-21", "2026-04-22", "2026-07-22")] + [port_at("9999")]
print("B100 FULL quarters:", " ".join(f"{(edges[k + 1] / edges[k] - 1) * 100:+.2f}%" for k in range(4)))


# 3) latency: fill at open of the second bar of each day
def sim_late(bs, sg, lo, hi, skip=1):
    w = [r for r in bs if lo <= r["t"] < hi]
    cash, units = 1.0, 0.0
    seen_day, k = None, 0
    for r in w:
        d = r["t"][:10]
        if d != seen_day:
            seen_day, k = d, 0
        else:
            k += 1
        if k != skip:
            continue
        want = sg.get(V.prev_day(d), False)
        if want and units == 0.0:
            units, cash = cash * (1 - V.SIDE) / r["o"], 0.0
        elif not want and units > 0.0:
            cash, units = units * r["o"] * (1 - V.SIDE), 0.0
    if units > 0.0:
        cash = units * w[-1]["c"] * (1 - V.SIDE)
    return cash - 1


for skip in (1, 2, 12):
    print(f"B100 TEST, fill at open of bar #{skip} of the day (+{5 * skip} min):",
          f"{sum(sim_late(bars[m], sig[m], *W['TEST'], skip) for m in MK) / 5 * 100:+.2f}%")

# 4) no warm-up: drop the API closes
seqs5 = {m: [(d, c) for d, c in seqs[m] if d >= "2025-10-22"] for m in MK}


def mom(seq, L):
    return {d: (i >= L and c > seq[i - L][1]) for i, (d, c) in enumerate(seq)}


def dual(seq, f, s):
    vals = [c for _, c in seq]
    return {d: (i + 1 >= s and sum(vals[i + 1 - f:i + 1]) / f > sum(vals[i + 1 - s:i + 1]) / s)
            for i, (d, _) in enumerate(seq)}


combos = {}
for n in (20, 50, 100):
    combos[f"S{n}"] = lambda m, n=n: V.sma_signal(seqs5[m], n)
    combos[f"B{n}"] = lambda m, n=n: b_sig(seqs5, m, n)
for L in (7, 14, 30):
    combos[f"M{L}"] = lambda m, L=L: mom(seqs5[m], L)
for f, s in ((5, 20), (10, 50), (20, 100)):
    combos[f"X{f}_{s}"] = lambda m, f=f, s=s: dual(seqs5[m], f, s)
tr = {}
for name, fn in combos.items():
    tr[name] = sum(V.sim(bars[m], fn(m), *W["TRAIN"])[0] for m in MK) / 5
    te = sum(V.sim(bars[m], fn(m), *W["TEST"])[0] for m in MK) / 5
    print(f"  no-warmup {name:8s} TRAIN {tr[name] * 100:+7.2f}%  TEST {te * 100:+7.2f}%")
print("no-warmup TRAIN selection:", max(tr, key=tr.get))

# 5) first day whose SMA100 uses only 5m-derived closes
days = [d for d, _ in seqs["KRW-BTC"]]
i0 = days.index("2025-10-22")
print("first day with SMA100 fully from 5m data:", days[i0 + 99], "(TEST signals start from 2026-06-20 close)")
