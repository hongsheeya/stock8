"""Special / unusually large distributions (> 1.8x median of the previous 4 payments): how do they behave?"""
import numpy as np
import pandas as pd

from study import GROUP, load

ev = pd.read_csv("results/events_long.csv.gz", parse_dates=["ex_date", "entry_date", "exit_date"])
ev = ev[(ev.ex_date >= "2015-01-01") & (ev.strategy == "C_open")]
flags = {}
for sym in GROUP:
    st = load(sym)
    s = pd.Series(st["D"], index=st["dates"])
    s = s[s > 0]
    med = s.shift(1).rolling(4, min_periods=4).median()
    for d, a in s.items():
        if np.isfinite(med.get(d, np.nan)):
            flags[(sym, d)] = a > 1.8 * med[d]
ev["special"] = [flags.get((s, d), False) for s, d in zip(ev.sym, ev.ex_date)]
ev["mkt"] = np.where(ev.group.str.startswith("US"), "US", "KR")
g = ev.groupby(["mkt", "special"]).agg(n=("RAW", "size"), yld=("yield", "median"), RAW=("RAW", "mean"),
                                         DIVTAX=("DIVTAX", "mean"), OPT=("OPT", "mean"))
g[["yld", "RAW", "DIVTAX", "OPT"]] *= 100
print("C_open by special flag (KR 'special' = mostly year-end vs quarterly size difference), 2015-2026, % per event")
print(g.round(3).to_string())
print(ev[ev.special & (ev.mkt == "US")].groupby("sym").size().to_string())
