"""Print the key tables from ./results for the write-up (all numbers come from study.py outputs)."""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 400)
pd.set_option("display.float_format", lambda v: f"{v:.3f}")

S = pd.read_csv(os.path.join(RES, "summary.csv"))
GROUPS = ["US_STOCK", "US_DIV_ETF", "US_CC_ETF", "US_ALL", "KR_STOCK", "KR_ETF"]
CORE = ["C_open", "C_close", "C_+3", "C_+5", "C_+10", "C_+20", "C_rec10", "C_rec20",
        "R_5", "R_10", "R_20", "P_3", "P_5", "P_10", "P_20"]


def tab(period, scen, strategies, groups=GROUPS, cols=("n", "mean%", "median%", "win%", "t", "t_clu", "hd", "per_day%", "mean_ex_top5%", "AR%", "AR_t_clu", "fragile")):
    sub = S[(S.period == period) & (S.scenario == scen) & S.strategy.isin(strategies) & S.group.isin(groups)].copy()
    sub["strategy"] = pd.Categorical(sub["strategy"], strategies, ordered=True)
    sub["group"] = pd.Categorical(sub["group"], groups, ordered=True)
    return sub.sort_values(["group", "strategy"])[["group", "strategy", *cols]]


def pivot_mean(period, strategies, groups, scens=("RAW", "DIVTAX", "OPT", "BASE", "BASE_FX", "OPT_CGT"), col="mean%"):
    sub = S[(S.period == period) & S.strategy.isin(strategies) & S.group.isin(groups) & S.scenario.isin(scens)]
    p = sub.pivot_table(index=["group", "strategy"], columns="scenario", values=col)
    p = p.reindex(columns=[c for c in scens if c in p.columns])
    idx = [(g, s) for g in groups for s in strategies if (g, s) in p.index]
    return p.loc[idx]


which = sys.argv[1] if len(sys.argv) > 1 else "all"

if which in ("all", "decomp"):
    print("=== Mean net return per event (%), 2015-2026, by scenario (decomposition RAW -> after dividend tax -> after costs)")
    print(pivot_mean("2015-2026", CORE, GROUPS))

if which in ("all", "capture"):
    for sc in ("DIVTAX", "OPT", "BASE"):
        print(f"\n=== {sc} 2015-2026 detail")
        print(tab("2015-2026", sc, CORE).to_string(index=False))

if which in ("all", "periods"):
    for st in ["C_open", "C_close", "C_+5", "C_+20", "R_5", "R_10", "R_20", "P_5", "P_20"]:
        print(f"\n=== {st}: mean% by period (OPT / RAW-AR%)")
        sub = S[(S.strategy == st) & S.group.isin(GROUPS)]
        a = sub[sub.scenario == "OPT"].pivot_table(index="group", columns="period", values="mean%")
        b = sub[sub.scenario == "RAW"].pivot_table(index="group", columns="period", values="AR%")
        n = sub[sub.scenario == "OPT"].pivot_table(index="group", columns="period", values="n")
        tc = sub[sub.scenario == "RAW"].pivot_table(index="group", columns="period", values="AR_t_clu")
        cols = ["2005-2014", "2015-2019", "2020-2022", "2023-2026", "2015-2026"]
        out = pd.concat({"OPT_mean%": a.reindex(columns=cols), "RAW_AR%": b.reindex(columns=cols),
                         "RAW_AR_t": tc.reindex(columns=cols), "n": n.reindex(columns=cols)}, axis=1)
        print(out.reindex(GROUPS))

if which in ("all", "combo"):
    combos = [f"X{n}_{k}" for n in (5, 10, 20) for k in ("open", "close", "+5", "+10", "+20")]
    print("\n=== Combined (run-up entry, hold through ex) vs run-up exit before ex, 2015-2026, mean% per scenario")
    print(pivot_mean("2015-2026", ["R_5", "R_10", "R_20"] + combos, GROUPS, scens=("RAW", "DIVTAX", "OPT", "BASE")))
    print("\n=== Combined: RAW AR% and cluster t")
    print(pivot_mean("2015-2026", ["R_5", "R_10", "R_20"] + combos, GROUPS, scens=("RAW",), col="AR%").join(
        pivot_mean("2015-2026", ["R_5", "R_10", "R_20"] + combos, GROUPS, scens=("RAW",), col="AR_t_clu"), rsuffix="_t"))

if which in ("all", "drop"):
    D = pd.read_csv(os.path.join(RES, "drop_ratio.csv"))
    cols = ["period", "group", "n", "yield_med%", "drop_open_pooled", "drop_open_adj_pooled", "drop_open_adj_se",
            "drop_close_pooled", "drop_close_adj_pooled", "drop_close_adj_se", "drop_open_adj_median", "drop_close_adj_median",
            "drop_open_adj_wmean", "drop_close_adj_wmean"]
    print("\n=== Ex-date drop / gross dividend (pooled = yield-weighted; adj = beta x proxy move removed; se clustered by week)")
    print(D[cols].to_string(index=False))
    T = pd.read_csv(os.path.join(RES, "drop_ratio_ticker.csv"))
    print("\n=== per ticker 2015-2026 (beta-adjusted pooled drop ratios)")
    print(T.sort_values(["group", "drop_open_adj_pooled"]).to_string(index=False))

if which in ("all", "bh"):
    B = pd.read_csv(os.path.join(RES, "buyhold.csv"))
    print("\n=== Buy & hold, net dividends reinvested (CAGR%, MDD%), per ticker")
    p = B.pivot_table(index=["group", "sym"], columns="period", values=["CAGR_netdiv%", "MDD%"])
    print(p)
    print("\n=== group means (tickers with full-period data only)")
    full = B[B.full_period]
    g = full.groupby(["group", "period"]).agg(n=("sym", "count"), CAGR_mean=("CAGR_netdiv%", "mean"),
                                              CAGR_median=("CAGR_netdiv%", "median"), MDD_mean=("MDD%", "mean"),
                                              priceCAGR_mean=("price_CAGR%", "mean"))
    print(g)

if which in ("all", "slot"):
    SS = pd.read_csv(os.path.join(RES, "slot_sim.csv"))
    keep = ["C_open", "C_close", "C_+5", "C_+20", "C_rec20", "R_5", "R_10", "R_20", "P_5", "P_20", "X10_close", "X20_+20"]
    sub = SS[SS.strategy.isin(keep) & SS.scenario.isin(["RAW", "DIVTAX", "OPT", "BASE", "BASE_FX", "OPT_CGT"])]
    print("\n=== One-account capital recycling 2015-01 .. 2026-10 (one position at a time; highest yield first)")
    print(sub.to_string(index=False))
