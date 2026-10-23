"""Compact tables of the numbers quoted in the write-up (reads ./results produced by study.py / robustness.py)."""
import os

import numpy as np
import pandas as pd

from study import KR_SELL_TAX, RES, cost_params

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 300)
pd.set_option("display.float_format", lambda v: f"{v:.3f}")
S = pd.read_csv(os.path.join(RES, "summary.csv"))
G = ["US_STOCK", "US_DIV_ETF", "US_CC_ETF", "US_ALL", "KR_STOCK", "KR_ETF"]

print("=== round-trip friction (% of trade value, excluding dividend tax)")
for sc in ["OPT", "BASE", "BASE_FX"]:
    c, s, sec, fx = cost_params(sc, "US")
    print(f"US {sc}: {100 * (2 * (c + s + fx) + sec):.4f}%")
c, s, sec, fx = cost_params("OPT", "KR")
print(f"KR stock (any scenario): {100 * (2 * (c + s) + 0.0020):.4f}%   KR ETF: {100 * (2 * (c + s)):.4f}%")


def row(period, group, strat, scen):
    r = S[(S.period == period) & (S.group == group) & (S.strategy == strat) & (S.scenario == scen)]
    return r.iloc[0] if len(r) else None


print("\n=== Table A (2015-2026): mean % per event by scenario + OPT win%/t + RAW AR")
out = []
for g in G:
    for st in ["C_open", "C_close", "C_+3", "C_+5", "C_+10", "C_+20", "C_rec20"]:
        d = {"group": g, "strategy": st}
        for sc in ["RAW", "DIVTAX", "OPT", "BASE", "BASE_FX", "OPT_CGT"]:
            r = row("2015-2026", g, st, sc)
            d[sc] = r["mean%"] if r is not None else np.nan
        r = row("2015-2026", g, st, "OPT")
        d.update({"n": r["n"], "OPT_med%": r["median%"], "OPT_win%": r["win%"], "OPT_t_clu": r["t_clu"],
                  "OPT_ex_top5%": r["mean_ex_top5%"], "hd": r["hd"], "OPT_per_day%": r["per_day%"]})
        r = row("2015-2026", g, st, "RAW")
        d.update({"RAW_AR%": r["AR%"], "RAW_AR_t": r["AR_t_clu"]})
        out.append(d)
print(pd.DataFrame(out).to_string(index=False))

print("\n=== Table B: run-up / post-ex / combined (2015-2026)")
out = []
for g in G:
    for st in ["R_5", "R_10", "R_20", "P_3", "P_5", "P_10", "P_20", "X5_open", "X10_open", "X20_open", "X20_+20"]:
        d = {"group": g, "strategy": st}
        for sc in ["RAW", "DIVTAX", "OPT", "BASE"]:
            r = row("2015-2026", g, st, sc)
            d[sc] = r["mean%"] if r is not None else np.nan
        r = row("2015-2026", g, st, "OPT")
        d.update({"n": r["n"], "OPT_win%": r["win%"], "OPT_t_clu": r["t_clu"], "hd": r["hd"], "OPT_AR%": r["AR%"],
                  "OPT_AR_t": r["AR_t_clu"]})
        r = row("2015-2026", g, st, "RAW")
        d.update({"RAW_AR%": r["AR%"], "RAW_AR_t": r["AR_t_clu"], "fragile": r["fragile"]})
        out.append(d)
print(pd.DataFrame(out).to_string(index=False))

print("\n=== Table C: sub-period stability, OPT mean% and RAW AR% (cluster t)")
for st in ["C_open", "C_close", "R_5", "R_20", "P_5", "C_+20"]:
    sub = S[(S.strategy == st) & S.group.isin(G)]
    a = sub[sub.scenario == "OPT"].pivot_table(index="group", columns="period", values="mean%")
    b = sub[sub.scenario == "RAW"].pivot_table(index="group", columns="period", values="AR%")
    t = sub[sub.scenario == "RAW"].pivot_table(index="group", columns="period", values="AR_t_clu")
    cols = ["2005-2014", "2015-2019", "2020-2022", "2023-2026"]
    print(f"\n-- {st}")
    print(pd.concat({"OPT%": a.reindex(columns=cols), "AR%": b.reindex(columns=cols), "AR_t": t.reindex(columns=cols)},
                    axis=1).reindex(G).to_string())

print("\n=== Table D: break-even drop ratio vs observed (2015-2026, ex-open, beta-adjusted pooled)")
D = pd.read_csv(os.path.join(RES, "drop_ratio.csv"))
for g, net, rt in [("US_STOCK", 0.85, None), ("US_DIV_ETF", 0.85, None), ("US_CC_ETF", 0.85, None), ("KR_STOCK", 0.846, 0.0033),
                   ("KR_ETF", 0.846, 0.0013)]:
    r = D[(D.period == "2015-2026") & (D.group == g)].iloc[0]
    y = r["yield_med%"] / 100
    if g.startswith("US"):
        be_opt = net - 0.002428 / y
        be_base = net - 0.006028 / y
        txt = f"break-even OPT {be_opt:.3f}, BASE {be_base:.3f}"
    else:
        txt = f"break-even {net - rt / y:.3f}"
    print(f"{g}: median yield/event {100 * y:.3f}%, tax-only break-even {net:.3f}, {txt}; observed open {r['drop_open_adj_pooled']:.3f} "
          f"(se {r['drop_open_adj_se']:.3f}), close {r['drop_close_adj_pooled']:.3f} (se {r['drop_close_adj_se']:.3f})")

print("\n=== Table E: one-account recycling 2015-01..2026-10 (CAGR %)")
SS = pd.read_csv(os.path.join(RES, "slot_sim.csv"))
keep = ["C_open", "C_close", "C_+20", "C_rec20", "R_5", "R_20", "P_5", "P_20", "X5_open", "X20_open"]
sub = SS[SS.strategy.isin(keep)]
p = sub.pivot_table(index=["group", "strategy"], columns="scenario", values="CAGR%").reindex(
    columns=["RAW", "DIVTAX", "OPT", "BASE", "BASE_FX", "OPT_CGT"])
tp = sub[sub.scenario == "OPT"].set_index(["group", "strategy"])[["trades_per_year", "days_invested_share%", "worst_year%", "pos_years", "years"]]
print(p.join(tp).to_string())

print("\n=== Table F: buy & hold, net dividends reinvested (group means over tickers with full-period data)")
B = pd.read_csv(os.path.join(RES, "buyhold.csv"))
full = B[B.full_period]
print(full.groupby(["group", "period"]).agg(n=("sym", "count"), CAGR_mean=("CAGR_netdiv%", "mean"), CAGR_median=("CAGR_netdiv%", "median"),
                                            MDD_mean=("MDD%", "mean")).to_string())
print(B[(B.period == "2015-2026")][["sym", "group", "start", "end", "CAGR_netdiv%", "price_CAGR%", "MDD%"]].sort_values(["group", "CAGR_netdiv%"]).to_string(index=False))
