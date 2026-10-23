"""Does capture work for any yield bucket? C_open / C_close by per-event gross yield, 2015-2026."""
import numpy as np
import pandas as pd

from study import cluster_t, week_key

pd.set_option("display.width", 220)
ev = pd.read_csv("results/events_long.csv.gz", parse_dates=["ex_date", "entry_date", "exit_date"])
ev = ev[(ev.ex_date >= "2015-01-01") & ev.strategy.isin(["C_open", "C_close"])]
ev["mkt"] = np.where(ev.group.str.startswith("US"), "US", "KR")
bins = [0, 0.005, 0.01, 0.015, 0.02, 1]
labels = ["<0.5%", "0.5-1%", "1-1.5%", "1.5-2%", ">=2%"]
ev["ybin"] = pd.cut(ev["yield"], bins, labels=labels, right=False)
rows = []
for (m, st, yb), g in ev.groupby(["mkt", "strategy", "ybin"], observed=True):
    k = week_key(g.ex_date)
    d = {"mkt": m, "strategy": st, "yield": yb, "n": len(g)}
    for sc in ["RAW", "DIVTAX", "OPT", "BASE"]:
        d[sc] = 100 * g[sc].mean()
    d["OPT_t_clu"] = cluster_t(g["OPT"].to_numpy(), k)
    d["OPT_win%"] = 100 * (g["OPT"] > 0).mean()
    rows.append(d)
out = pd.DataFrame(rows)
print("mean net return per event (%) by gross yield of the event, 2015-2026")
print(out.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
out.to_csv("results/yield_buckets.csv", index=False)
