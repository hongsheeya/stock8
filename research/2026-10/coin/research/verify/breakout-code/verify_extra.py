"""Extra adversarial checks for breakout 4h_N55_atr2 (verifier, not researcher).
1) equal-weight buy-and-hold TEST return (with 0.1%/side)
2) count of fully-missing 4h buckets in the window per coin
3) execution-latency stress: enter at the open of the 2nd 5m bar of the next 4h bar
4) SMA filter lagged one extra day (stress the daily-close boundary)
"""
import sys
import numpy as np
import verify_breakout as V


def sim_variant(T, O, H, L, C, ps, pe, delay=0, sma_lag=0):
    bkt, h4, l4, c4, atr, don = V.build4h(T, O, H, L, C)
    days, sma = V.daily_sma(T, C)
    bidx = {int(b): j for j, b in enumerate(bkt)}
    k0 = int(np.searchsorted(T, ps, "left"))
    k1 = int(np.searchsorted(T, pe, "left"))
    tr, long, pend = [], False, None
    stop = hh = ek = ep = None
    for k in range(k0, k1):
        b = T[k] // V.B4
        prevb = T[k - 1] // V.B4 if k > 0 else None
        if prevb is not None and prevb != b:
            J = bidx[int(prevb)]
            if long:
                hh = max(hh, h4[J]); stop = max(stop, hh - V.K_ATR * atr[J])
            if not long and pend is None:
                s = V.sma_at(days, sma, (int(prevb) + 1) * V.B4 - sma_lag * V.DAY)
                if not np.isnan(don[J]) and not np.isnan(atr[J]) and not np.isnan(s) and c4[J] > don[J] and c4[J] > s:
                    pend = [delay, h4[J], h4[J] - V.K_ATR * atr[J]]
        if pend is not None:
            if pend[0] == 0:
                long, ek, ep, hh, stop = True, k, O[k], pend[1], pend[2]
                pend = None
            else:
                pend[0] -= 1
        if long and L[k] <= stop:
            tr.append((ek, ep, k, min(O[k], stop))); long = False
    if long:
        tr.append((ek, ep, k1 - 1, C[k1 - 1]))
    return tr, k0, k1


def main():
    data = {m: V.load(m) for m in V.MARKETS}
    pe = min(d[0][-1] for d in data.values()) + 300
    first = max(d[0][0] for d in data.values())
    ps_full = -(-first // 3600) * 3600
    split = V.ts("2026-06-21T00:00:00")
    # 1) buy and hold TEST
    bh = []
    for m, (T, O, H, L, C) in data.items():
        k0 = int(np.searchsorted(T, split)); k1 = int(np.searchsorted(T, pe))
        bh.append((C[k1 - 1] * (1 - V.FEE)) / (O[k0] * (1 + V.FEE)) - 1)
    print("buy&hold TEST mean %+.2f%%  " % (np.mean(bh) * 100) + " ".join(f"{x*100:+.1f}" for x in bh))
    # 2) missing 4h buckets
    for m, (T, O, H, L, C) in data.items():
        k0 = int(np.searchsorted(T, ps_full))
        b = np.unique(T[k0:] // V.B4)
        print(f"{m} missing 4h buckets in window: {int(b[-1] - b[0] + 1 - len(b))}")
    # 3,4) stress variants on TEST / TRAIN / FULL
    for label, kw in [("base", {}), ("entry delayed +5m", {"delay": 1}), ("entry delayed +15m", {"delay": 3}),
                      ("SMA lagged 1 extra day", {"sma_lag": 1})]:
        line = []
        for p, (a, b_) in {"TRAIN": (ps_full, split), "TEST": (split, pe), "FULL": (ps_full, pe)}.items():
            fin = []
            for m, (T, O, H, L, C) in data.items():
                tr, k0, k1 = sim_variant(T, O, H, L, C, a, b_, **kw)
                eq = V.equity(T, C, tr, k0, k1)
                fin.append(eq[-1] - 1)
            line.append(f"{p} {np.mean(fin)*100:+6.2f}%")
        print(f"{label:24s} " + "  ".join(line))
    return 0


if __name__ == "__main__":
    sys.exit(main())
