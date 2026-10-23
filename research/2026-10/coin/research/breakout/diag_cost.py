"""Diagnostic only (not used for selection): chosen combo 4h_N55_atr2 with the
round-trip cost doubled to 0.40% (0.20% per side)."""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_wf as W

W.C = 0.002
coins = [W.Coin(m) for m in W.MARKETS]
first = max(cn.t[0] for cn in coins)
hour = np.timedelta64(1, "h").astype("timedelta64[ns]")
ps = (first + hour - np.timedelta64(1, "ns")).astype("datetime64[h]").astype("datetime64[ns]")
pe = min(cn.t[-1] for cn in coins) + W.FIVE_MIN
for p, (a, b) in {"TRAIN": (ps, W.SPLIT), "TEST": (W.SPLIT, pe), "FULL": (ps, pe)}.items():
    r = W.run(coins, ("4h", 55, "atr2"), a, b)
    print(f"cost 0.40% RT  {p:5s} {W.fmt(r)}   {W.coins_line(r)}")
