"""Capture with auction orders (LOC buy at the close, MOO sell at the open => no half-spread):
US commission 0.07%/side + SEC fee; KR commission 0.015%/side + 0.20% sell tax. 2015-2026, % per event."""
import numpy as np
import pandas as pd

from study import cluster_t, week_key

ev = pd.read_csv("results/events_long.csv.gz", parse_dates=["ex_date"])
ev = ev[(ev.ex_date >= "2015-01-01") & ev.strategy.isin(["C_open", "C_close"])]
rows = []
for (g, st), x in ev.groupby(["group", "strategy"]):
    us = g.startswith("US")
    tax = 0.0 if (us or g == "KR_ETF") else 0.0020
    cost = (2 * 0.0007 + 0.000028) if us else (2 * 0.00015 + tax)
    net = x["DIVTAX"] - cost  # approximation: per-side cost on ~equal buy/sell prices
    rows.append({"group": g, "strategy": st, "n": len(x), "round_trip_cost%": 100 * cost, "mean%": 100 * net.mean(),
                 "win%": 100 * (net > 0).mean(), "t_clu": cluster_t(net.to_numpy(), week_key(x["ex_date"]))})
print(pd.DataFrame(rows).to_string(index=False, float_format=lambda v: f"{v:.3f}"))
