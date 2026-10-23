"""Final-decision check: breakout 4h_N55_atr2 with an extra half-tick spread per side.
Imports the researcher's breakout_wf.py unchanged; only the fill prices are adjusted:
buy fill = fill + tick/2, sell fill = fill - tick/2 (on top of the 0.10%/side cost).
Ticks inferred from the 5m data: BTC 1000, ETH 1000, XRP 1, SOL 100, DOGE 1 KRW.
Also reports the 4-coin portfolio without DOGE (25% each)."""
import os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "breakout"))
import breakout_wf as B

TICK = {"KRW-BTC": 1000.0, "KRW-ETH": 1000.0, "KRW-XRP": 1.0, "KRW-SOL": 100.0, "KRW-DOGE": 1.0}
COMBO = ("4h", 55, "atr2")

def run(coins, ps, pe, half_tick):
    grid = np.arange(ps, pe, B.FIVE_MIN)
    eqs, rets, per = [], [], {}
    for cn in coins:
        tr, k_ps, k_pe = B.simulate(cn, COMBO, ps, pe)
        ht = TICK[cn.m] / 2 if half_tick else 0.0
        tr2 = [(ek, epx + ht, xk, xpx - ht, why) for ek, epx, xk, xpx, why in tr]
        eq = B.coin_equity(cn, tr2, k_ps, k_pe)
        rets += [(x * (1 - B.C)) / (e * (1 + B.C)) - 1 for _, e, _, x, _ in tr2]
        per[cn.m.split("-")[1]] = round(float((eq[-1] - 1) * 100), 2)
        eqs.append(B.to_grid(cn, eq, k_ps, grid))
    port = np.mean(eqs, axis=0)
    return float((port[-1] - 1) * 100), B.mdd(port), len(rets), float(np.mean(rets) * 100), per

coins = [B.Coin(m) for m in B.MARKETS]
first = max(cn.t[0] for cn in coins)
hour = np.timedelta64(1, "h").astype("timedelta64[ns]")
ps0 = (first + hour - 1).astype("datetime64[h]").astype("datetime64[ns]")
pe0 = min(cn.t[-1] for cn in coins)
print("window", ps0, pe0)
periods = {"TRAIN": (ps0, B.SPLIT), "TEST": (B.SPLIT, pe0), "FULL": (ps0, pe0)}
for label, cset in (("5 coins", coins), ("4 coins (no DOGE)", [c for c in coins if c.m != "KRW-DOGE"])):
    for ht in (False, True):
        for p, (a, b) in periods.items():
            r, m, n, avg, per = run(cset, a, b, ht)
            print(f"{label:18s} halftick={ht!s:5s} {p:5s} ret {r:+7.2f}%  mdd {m:+6.2f}%  n {n:3d}  avg {avg:+5.2f}%  {per}")
