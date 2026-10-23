"""G1 (pre-registered promotion gate): the FROZEN breakout rule 4h_N55_atr2 on
Upbit 5m data 2019-10-21 .. 2025-10-21 (never used in the research), using the
researcher's engine (breakout_wf.py) unchanged; only the data folder differs.
Cost 0.10% per side plus half a tick per side (tick inferred per coin per month
from the observed price grid). Sleeves are 20% each and sit in cash before a
market's KRW listing. Pass: CAGR > 0, >= 4 of 6 years >= 0%, portfolio MDD >= -15%.
"""
import os, sys
import numpy as np
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "breakout"))
import breakout_wf as B
B.CANDLES = os.path.join(os.path.dirname(os.path.dirname(HERE)), "candles_hist")
COMBO = ("4h", 55, "atr2")
START, END = np.datetime64("2019-10-21T00:00:00", "ns"), np.datetime64("2025-10-21T00:00:00", "ns")
CUTS = [np.datetime64(f"{y}-10-21T00:00:00", "ns") for y in range(2019, 2026)]


def tick_table(coin):
    """month -> smallest positive step between distinct close prices that month."""
    df = pd.DataFrame({"m": np.asarray(coin.t).astype("datetime64[M]"), "c": coin.c})
    out = {}
    for m, g in df.groupby("m"):
        u = np.unique(np.round(g["c"].values, 6))
        d = np.diff(u)
        d = d[d > 1e-9]
        out[m] = float(d.min()) if d.size else 0.0
    return out


def tick_at(table, t):
    m = np.datetime64(t, "M")
    return table.get(m, 0.0)


def run(coins, half_tick=True, cost=B.C):
    B.C = cost
    grid = np.arange(START, END, B.FIVE_MIN)
    eqs, rets, per = [], [], {}
    for cn in coins:
        tr, k_ps, k_pe = B.simulate(cn, COMBO, START, END)
        if half_tick:
            tb = tick_table(cn)
            tr = [(ek, epx + tick_at(tb, cn.t[ek]) / 2, xk, xpx - tick_at(tb, cn.t[xk]) / 2, why) for ek, epx, xk, xpx, why in tr]
        eq = B.coin_equity(cn, tr, k_ps, k_pe)
        r = [(x * (1 - B.C)) / (e * (1 + B.C)) - 1 for _, e, _, x, _ in tr]
        rets += r
        per[cn.m.split("-")[1]] = (round(float((eq[-1] - 1) * 100), 1), len(tr))
        eqs.append(B.to_grid(cn, eq, k_ps, grid))
    port = np.mean(eqs, axis=0)
    years = []
    for a, b in zip(CUTS[:-1], CUTS[1:]):
        ia = int(np.searchsorted(grid, a, "left")) - 1
        ib = int(np.searchsorted(grid, b, "left")) - 1
        va = 1.0 if ia < 0 else float(port[ia])
        years.append((float(port[ib]) / va - 1) * 100)
    total = float(port[-1] - 1) * 100
    cagr = (float(port[-1]) ** (1 / 6) - 1) * 100
    return total, cagr, B.mdd(port), years, len(rets), float(np.mean(rets) * 100) if rets else 0.0, per


coins = [B.Coin(m) for m in B.MARKETS]
for cn in coins:
    print(f"{cn.m:9s} first {cn.t[0]} last {cn.t[-1]} bars {len(cn.t)}")
for label, cset in (("5 coins", coins), ("4 coins (no DOGE)", [c for c in coins if c.m != "KRW-DOGE"])):
    for ht, cost, tag in ((False, 0.001, "base 0.10%/side"), (True, 0.001, "G1: 0.10%/side + half tick"), (True, 0.002, "2x cost + half tick")):
        total, cagr, mdd, years, n, avg, per = run(cset, ht, cost)
        ok = cagr > 0 and sum(y >= 0 for y in years) >= 4 and mdd >= -15
        print(f"{label:18s} {tag:28s} total {total:+7.1f}%  CAGR {cagr:+5.2f}%  MDD {mdd:+6.1f}%  trades {n:4d} avg {avg:+5.2f}% | years " +
              " ".join(f"{y:+6.1f}" for y in years) + f" | {'PASS' if ok else 'FAIL'}")
        print(f"{'':18s} per coin (ret %, trades): {per}")
    # buy and hold reference per year
grid = np.arange(START, END, B.FIVE_MIN)
eqs = []
for cn in coins:
    k_ps = int(np.searchsorted(cn.t, START, "left")); k_pe = int(np.searchsorted(cn.t, END, "left"))
    eq = cn.c[k_ps:k_pe] / cn.o[k_ps]
    eqs.append(B.to_grid(cn, eq, k_ps, grid))
port = np.mean(eqs, axis=0)
yr = []
for a, b in zip(CUTS[:-1], CUTS[1:]):
    ia = int(np.searchsorted(grid, a, "left")) - 1; ib = int(np.searchsorted(grid, b, "left")) - 1
    yr.append((float(port[ib]) / (1.0 if ia < 0 else float(port[ia])) - 1) * 100)
print("buy&hold (cash before listing) years " + " ".join(f"{y:+6.1f}" for y in yr) + f" | MDD {B.mdd(port):+.1f}%")
