"""Week-block bootstrap 95% CIs (resampling whole ex-date weeks) for the headline per-event means, 2015-2026."""
import numpy as np
import pandas as pd

from study import week_key

rng = np.random.default_rng(7)
ev = pd.read_csv("results/events_long.csv.gz", parse_dates=["ex_date"])
ev = ev[ev.ex_date >= "2015-01-01"]
cases = [("US_STOCK", "C_open", "OPT"), ("US_STOCK", "C_open", "DIVTAX"), ("US_DIV_ETF", "C_open", "OPT"),
         ("US_CC_ETF", "C_open", "OPT"), ("KR_STOCK", "C_open", "OPT"), ("KR_STOCK", "C_open", "DIVTAX"),
         ("KR_ETF", "C_open", "OPT"), ("US_STOCK", "R_5", "OPT"), ("KR_STOCK", "R_20", "OPT"), ("KR_STOCK", "X20_open", "OPT"),
         ("US_STOCK", "C_close", "DIVTAX")]
rows = []
for g, st, sc in cases:
    x = ev[(ev.group == g) & (ev.strategy == st)]
    r = x[sc].to_numpy(float)
    ar = r - (x["beta"] * x["Rm"]).to_numpy(float)
    k = week_key(x["ex_date"])
    uk, inv = np.unique(k, return_inverse=True)
    sums = np.bincount(inv, weights=r); sums_ar = np.bincount(inv, weights=np.nan_to_num(ar)); cnt = np.bincount(inv)
    B = 4000
    idx = rng.integers(0, len(uk), size=(B, len(uk)))
    m = sums[idx].sum(1) / cnt[idx].sum(1)
    ma = sums_ar[idx].sum(1) / cnt[idx].sum(1)
    rows.append({"group": g, "strategy": st, "scenario": sc, "n": len(r), "weeks": len(uk), "mean%": 100 * r.mean(),
                 "ci95_lo%": 100 * np.percentile(m, 2.5), "ci95_hi%": 100 * np.percentile(m, 97.5),
                 "AR%": 100 * np.nanmean(ar), "AR_ci_lo%": 100 * np.percentile(ma, 2.5), "AR_ci_hi%": 100 * np.percentile(ma, 97.5)})
out = pd.DataFrame(rows)
out.to_csv("results/bootstrap_ci.csv", index=False)
print(out.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
