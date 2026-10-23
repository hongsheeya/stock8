"""Supplementary robustness checks for breakout 4h_N55_atr2 (run after robust_verify.py).

 (g) correlated null: shift the whole trade schedule by ONE random circular time
     offset common to all 5 coins (keeps cross-coin synchronisation, trade count,
     holding lengths). Compares with the observed portfolio return.
 (h) context: best-5-days removal applied to buy & hold and to all 12 grid combos on TEST
 (i) chosen rule on non-overlapping blocks and rolling 3-month windows (start flat)
 (j) best-5-days / Aug-19..22 removal combined with 0.40% RT cost
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import robust_verify as R  # noqa: E402
W = R.W


def window():
    coins = [W.Coin(m) for m in W.MARKETS]
    first = max(cn.t[0] for cn in coins)
    hour = np.timedelta64(1, "h").astype("timedelta64[ns]")
    ps = (first + hour - np.timedelta64(1, "ns")).astype("datetime64[h]").astype("datetime64[ns]")
    pe = min(cn.t[-1] for cn in coins) + W.FIVE_MIN
    return coins, ps, pe


def shifted_return(coins, sched, ps, pe, shift_ns, C):
    """sched[m] = list of (entry_time, exit_time). Shift circularly within [ps, pe)."""
    span = pe - ps
    rets = []
    for cn in coins:
        cash = 1.0
        for et, xt in sched[cn.m]:
            dur = xt - et
            e = ps + ((et - ps + shift_ns) % span)
            pieces = []
            if e + dur <= pe:
                pieces.append((e, e + dur))
            else:
                pieces.append((e, pe))
                pieces.append((ps, ps + (e + dur - pe)))
            for s, x in pieces:
                ks = int(np.searchsorted(cn.t, s, "left"))
                kx = int(np.searchsorted(cn.t, x, "left"))  # sell at open of bar at x (or last close)
                if ks >= len(cn.t) or cn.t[ks] >= pe:
                    continue
                if kx < len(cn.t) and cn.t[kx] < pe and kx > ks:
                    px = cn.o[kx]
                else:
                    kx2 = int(np.searchsorted(cn.t, pe, "left")) - 1
                    px = cn.c[max(kx2, ks)]
                cash *= (px * (1 - C)) / (cn.o[ks] * (1 + C))
        rets.append(cash)
    return (np.mean(rets) - 1) * 100


def main():
    coins, ps, pe = window()
    P = {"TRAIN": (ps, R.CUT_B), "TEST": (R.CUT_B, pe), "FULL": (ps, pe)}
    chosen = R.Spec("4h", 55, "atr2")

    print("(g) CORRELATED NULL: one common random circular time-shift of the whole trade schedule (0.20% RT)")
    rng = np.random.default_rng(7)
    for p in ("TEST", "TRAIN", "FULL"):
        a, b = P[p]
        r = R.run(coins, chosen, a, b)
        sched = {}
        # rebuild schedule with exit times from simulate (exit at the 5m bar where the stop hit)
        for cn in coins:
            T = R.build(cn, "4h", 0, (55,), 14, 50, (20,))
            tr, k_ps, k_pe = R.simulate(cn, T, 55, 2.0, 20, a, b)
            sched[cn.m] = [(cn.t[ek], cn.t[xk]) for ek, _, xk, _, _ in tr]
        # sanity: zero shift approximates observed (exit at next open instead of stop price)
        z = shifted_return(coins, sched, a, b, np.timedelta64(0, "ns"), W.C)
        span_ns = int((b - a) / np.timedelta64(1, "ns"))
        sims = np.array([shifted_return(coins, sched, a, b,
                                        np.timedelta64(int(rng.integers(0, span_ns // 300_000_000_000)) * 300_000_000_000, "ns"),
                                        W.C) for _ in range(1000)])
        print(f"  {p:5s} observed {r['ret']:+6.2f}% (zero-shift approx {z:+6.2f}%); shifted: mean {sims.mean():+6.2f}, "
              f"median {np.median(sims):+6.2f}, 5th {np.percentile(sims, 5):+6.2f}, 95th {np.percentile(sims, 95):+6.2f}; "
              f"P(shift >= observed) = {np.mean(sims >= r['ret']):.3f}; P(shift >= zero-shift approx, like-for-like) = {np.mean(sims >= z):.3f}")

    print("\n(h) CONTEXT: 5 best portfolio days set to 0% on TEST")
    a, b = P["TEST"]
    bh_grid = np.arange(a, b, W.FIVE_MIN)
    eqs = []
    for cn in coins:
        k_ps = int(np.searchsorted(cn.t, a, "left"))
        k_pe = int(np.searchsorted(cn.t, b, "left"))
        eq = cn.c[k_ps:k_pe] / (cn.o[k_ps] * (1 + W.C))
        eq[-1] *= (1 - W.C)
        eqs.append(W.to_grid(cn, eq, k_ps, bh_grid))
    port = np.mean(eqs, axis=0)
    dr = R.daily_returns(bh_grid, port)
    rem = dr.copy()
    rem[dr.sort_values(ascending=False).head(5).index] = 0
    print(f"  buy&hold TEST {(port[-1] - 1) * 100:+.2f}% -> best 5 days removed {(np.prod(1 + rem.values) - 1) * 100:+.2f}%")
    for s in R.grid12():
        r = R.run(coins, s, a, b)
        dr = R.daily_returns(r["grid"], r["port"])
        rem = dr.copy()
        rem[dr.sort_values(ascending=False).head(5).index] = 0
        lo, hi = np.datetime64("2026-08-19", "ns"), np.datetime64("2026-08-23", "ns")
        drop = {(x["m"], x["ek"]) for x in r["tlist"] if lo <= x["et"] < hi}
        r4 = R.run(coins, s, a, b, drop=drop)
        tag = "  <== chosen" if s.name == chosen.name else ""
        print(f"  {s.name:34s} TEST {r['ret']:+7.2f} -> best5days removed {(np.prod(1 + rem.values) - 1) * 100:+7.2f}; "
              f"Aug19-22 entries removed {r4['ret']:+7.2f}{tag}")

    print("\n(i) CHOSEN RULE ON NON-OVERLAPPING BLOCKS / ROLLING 3-MONTH WINDOWS (each starts flat, 0.20% RT)")
    cuts = [ps, np.datetime64("2026-01-21", "ns"), np.datetime64("2026-04-21", "ns"), R.CUT_B,
            np.datetime64("2026-07-21", "ns"), pe]
    for i in range(len(cuts) - 1):
        r = R.run(coins, chosen, cuts[i], cuts[i + 1])
        bh = W.buy_hold(coins, cuts[i], cuts[i + 1])["ret"]
        print(f"  {str(cuts[i])[:10]} .. {str(cuts[i + 1])[:10]}  strat {r['ret']:+6.2f}% (n {r['trades']:2d})  b&h {bh:+7.2f}%")
    starts = pd.date_range("2025-11-01", "2026-07-01", freq="MS") + pd.Timedelta(days=20)
    wins, beats = 0, 0
    lines = []
    for st in starts:
        s0 = np.datetime64(st, "ns")
        e0 = np.datetime64(st + pd.DateOffset(months=3), "ns")
        e0 = min(e0, pe)
        r = R.run(coins, chosen, s0, e0)
        bh = W.buy_hold(coins, s0, e0)["ret"]
        wins += r["ret"] > 0
        beats += r["ret"] > bh
        lines.append(f"{str(s0)[:10]}+3m {r['ret']:+5.2f} (bh {bh:+6.2f})")
    print("  rolling: " + "; ".join(lines))
    print(f"  rolling 3m windows: strat>0 in {wins}/{len(starts)}, strat>b&h in {beats}/{len(starts)}")

    print("\n(j) COMBINED STRESS on TEST (0.40% RT)")
    a, b = P["TEST"]
    r = R.run(coins, chosen, a, b, C=0.002)
    dr = R.daily_returns(r["grid"], r["port"])
    rem = dr.copy()
    rem[dr.sort_values(ascending=False).head(5).index] = 0
    lo, hi = np.datetime64("2026-08-19", "ns"), np.datetime64("2026-08-23", "ns")
    drop = {(x["m"], x["ek"]) for x in r["tlist"] if lo <= x["et"] < hi}
    r4 = R.run(coins, chosen, a, b, C=0.002, drop=drop)
    tl = sorted(r["tlist"], key=lambda x: -x["pnl"])[:5]
    r5 = R.run(coins, chosen, a, b, C=0.002, drop={(x["m"], x["ek"]) for x in tl})
    print(f"  TEST @0.40%: {r['ret']:+.2f}%; best 5 days removed {(np.prod(1 + rem.values) - 1) * 100:+.2f}%; "
          f"Aug19-22 entries removed {r4['ret']:+.2f}%; best 5 trades removed {r5['ret']:+.2f}%")


if __name__ == "__main__":
    main()
