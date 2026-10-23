"""One-account recycling with RANDOM choice among same-day candidates (50 seeds), to check that the
highest-yield-first rule in study.slot_sim does not drive the annualised numbers. Also per-year
returns for the headline cases."""
import os

import numpy as np
import pandas as pd

from study import RES, group_sets

pd.set_option("display.width", 250)
pd.set_option("display.float_format", lambda v: f"{v:.2f}")
ev = pd.read_csv(os.path.join(RES, "events_long.csv.gz"), parse_dates=["ex_date", "entry_date", "exit_date"])
START, END = pd.Timestamp("2015-01-01"), pd.Timestamp("2026-10-21")
span = (END - START).days / 365.25
ev = ev[ev.entry_date >= START]
sets = group_sets(ev)


def run(sub, rng, scen_cols):
    order = rng.permutation(len(sub))
    s = sub.iloc[order].sort_values("entry_date", kind="stable")
    taken, last_exit, last_kind = [], None, None
    for i, ed, xd, xk in zip(s.index, s.entry_date, s.exit_date, s.exit_kind):
        if last_exit is None or ed > last_exit or (ed == last_exit and last_kind == "open"):
            taken.append(i)
            last_exit, last_kind = xd, xk
    tk = s.loc[taken]
    return {c: 100 * (np.prod(1 + tk[c].to_numpy()) ** (1 / span) - 1) for c in scen_cols}, len(tk) / span, tk


rows = []
cases = [(g, st) for g in ["US_STOCK", "US_DIV_ETF", "US_CC_ETF", "US_ALL", "KR_STOCK", "KR_ETF"]
         for st in ["C_open", "C_close", "C_+20", "C_rec20", "R_5", "R_20", "P_5", "P_20", "X20_open"]]
for g, st in cases:
    sub = ev[sets[g] & (ev.strategy == st)]
    cols = ["RAW", "DIVTAX", "OPT", "BASE"] + (["BASE_FX"] if g.startswith("US") else [])
    res = [run(sub, np.random.default_rng(seed), cols) for seed in range(50)]
    d = {"group": g, "strategy": st, "trades_per_year": np.median([r[1] for r in res])}
    for c in cols:
        v = np.array([r[0][c] for r in res])
        d[f"{c}_med"] = np.median(v)
        if c == "OPT":
            d["OPT_p10"], d["OPT_p90"] = np.percentile(v, [10, 90])
    rows.append(d)
out = pd.DataFrame(rows)
out.to_csv(os.path.join(RES, "slot_random.csv"), index=False)
print("=== one-account recycling, random same-day choice, median CAGR% over 50 seeds (2015-01..2026-10)")
print(out.to_string(index=False))

print("\n=== per-year compounded return % (OPT), seed 0, headline cases")
for g, st in [("US_ALL", "C_open"), ("US_STOCK", "C_open"), ("US_CC_ETF", "C_open"), ("KR_STOCK", "C_open"), ("KR_STOCK", "R_20")]:
    sub = ev[sets[g] & (ev.strategy == st)]
    _, tpy, tk = run(sub, np.random.default_rng(0), ["OPT"])
    yr = (1 + tk["OPT"]).groupby(tk.entry_date.dt.year).prod() - 1
    n = tk.groupby(tk.entry_date.dt.year).size()
    print(f"\n{g} {st}: trades/yr {tpy:.1f}")
    print(pd.DataFrame({"OPT%": 100 * yr, "trades": n}).T.to_string())
