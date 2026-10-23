"""Robustness checks on the few variants that look positive.

1. Own-drift control: event return minus the same stock's average return for an equally long window
   (mean daily total return over ex-date +-126 trading days, x holding days). Separates "dividend-window
   effect" from "this stock was rising anyway" (e.g. KR financials during the 2023-2026 value-up rally).
2. Per-year and per-ticker breakdown of the candidate variants.
3. KR ex-open capture sensitivity to execution (auction, no spread) and transaction-tax rate.
"""
import math
import os

import numpy as np
import pandas as pd

from study import GROUP, KR_SELL_TAX, PERIODS, RES, cluster_t, load, week_key

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 300)
pd.set_option("display.float_format", lambda v: f"{v:.3f}")

ev = pd.read_csv(os.path.join(RES, "events_long.csv.gz"), parse_dates=["ex_date", "entry_date", "exit_date"])

# --- own-drift control ------------------------------------------------------------------------
drift = {}
for sym in GROUP:
    st = load(sym)
    r = pd.Series(st["ret"], index=st["dates"])
    ok = pd.Series(st["valid"], index=st["dates"]) & pd.Series(np.r_[False, st["valid"][:-1]], index=st["dates"])
    r = r.where(ok)
    # centred 253-day mean daily total return (gross dividends), min 120 obs
    drift[sym] = r.rolling(253, center=True, min_periods=120).mean()
ev["own_drift"] = [drift[s].get(d, np.nan) for s, d in zip(ev["sym"], ev["ex_date"])]
ev["EX_OWN"] = ev["RAW"] - ev["own_drift"] * ev["hd"]
ev["AR_RAW"] = ev["RAW"] - ev["beta"] * ev["Rm"]


def stat(sub, col):
    x = sub[col].to_numpy(float)
    ok = np.isfinite(x)
    x = x[ok]
    if len(x) < 5:
        return pd.Series({"n": len(x)})
    k = week_key(sub["ex_date"])[ok]
    return pd.Series({"n": len(x), "mean%": 100 * x.mean(), "t_clu": cluster_t(x, k), "clusters": len(set(k))})


cands = ["C_open", "C_close", "R_5", "R_10", "R_20", "P_5", "X5_open", "X20_open", "C_+20", "P_20"]
rows = []
for pname, (a, b) in PERIODS.items():
    pm = (ev.ex_date >= a) & (ev.ex_date <= b)
    for g in ["US_STOCK", "US_DIV_ETF", "US_CC_ETF", "KR_STOCK", "KR_ETF"]:
        if pname == "2005-2014" and g.startswith("KR"):
            continue
        for s in cands:
            sub = ev[pm & (ev.group == g) & (ev.strategy == s)]
            if len(sub) < 5:
                continue
            a1 = stat(sub, "RAW")
            a2 = stat(sub, "AR_RAW")
            a3 = stat(sub, "EX_OWN")
            rows.append({"period": pname, "group": g, "strategy": s, "n": a1["n"], "clusters": a1.get("clusters"),
                         "RAW%": a1.get("mean%"), "AR_mkt%": a2.get("mean%"), "AR_mkt_t": a2.get("t_clu"),
                         "EX_own%": a3.get("mean%"), "EX_own_t": a3.get("t_clu")})
R = pd.DataFrame(rows)
R.to_csv(os.path.join(RES, "robust_owndrift.csv"), index=False)
print("=== RAW (pre-tax, pre-cost) mean, market-adjusted AR and own-drift excess, by period")
for s in cands:
    print(f"\n--- {s}")
    print(R[R.strategy == s].pivot_table(index="group", columns="period", values=["AR_mkt%", "AR_mkt_t", "EX_own%", "EX_own_t"]).round(3).to_string())

# --- per-year breakdown of candidates ---------------------------------------------------------
print("\n=== per-year RAW market-adjusted AR% (mean) for candidate variants")
for g, s in [("KR_STOCK", "R_20"), ("KR_STOCK", "C_open"), ("US_STOCK", "R_5"), ("KR_ETF", "R_20"), ("US_CC_ETF", "C_open")]:
    sub = ev[(ev.group == g) & (ev.strategy == s) & (ev.ex_date >= "2015-01-01")]
    y = sub.groupby(sub.ex_date.dt.year).agg(n=("RAW", "size"), RAW=("RAW", "mean"), AR=("AR_RAW", "mean"), EXOWN=("EX_OWN", "mean"))
    print(f"\n{g} {s}")
    print((y.assign(RAW=100 * y.RAW, AR=100 * y.AR, EXOWN=100 * y.EXOWN)).T.round(2).to_string())

print("\n=== per-ticker KR_STOCK R_20 2015-2026 (RAW, AR, own-drift excess; %)")
sub = ev[(ev.group == "KR_STOCK") & (ev.strategy == "R_20") & (ev.ex_date >= "2015-01-01")]
print(sub.groupby("sym").agg(n=("RAW", "size"), RAW=("RAW", "mean"), AR=("AR_RAW", "mean"), EXOWN=("EX_OWN", "mean")).mul(
    [1, 100, 100, 100]).round(2).to_string())

# --- KR ex-open capture sensitivity -------------------------------------------------------------
print("\n=== KR_STOCK C_open: net mean% under execution / tax variants (dividend tax 15.4% always on)")
sub = ev[(ev.group == "KR_STOCK") & (ev.strategy == "C_open") & (ev.ex_date >= "2015-01-01")].copy()
# DIVTAX = (P1-P0 + 0.846*D)/P0 ; costs approx = c*(1 + P1/P0) + tax*P1/P0 ; P1/P0 ~ 1 - drop (tiny), use 1
out = []
for label, comm, spread, tax in [("auction fills, 2026 tax 0.20%", 0.00015, 0.0, 0.0020),
                                 ("spread 0.05%/side, 2026 tax 0.20%", 0.00015, 0.0005, 0.0020),
                                 ("auction fills, 2025 tax 0.15%", 0.00015, 0.0, 0.0015),
                                 ("auction fills, 2024 tax 0.18%", 0.00015, 0.0, 0.0018)]:
    net = sub["DIVTAX"] - (2 * (comm + spread) + tax)
    for pname, (a, b) in PERIODS.items():
        if pname == "2005-2014":
            continue
        m = (sub.ex_date >= a) & (sub.ex_date <= b)
        x = net[m].to_numpy()
        k = week_key(sub.loc[m, "ex_date"])
        out.append({"variant": label, "period": pname, "n": len(x), "mean%": 100 * x.mean(), "win%": 100 * (x > 0).mean(),
                    "t_clu": cluster_t(x, k), "clusters": len(set(k))})
print(pd.DataFrame(out).to_string(index=False))
