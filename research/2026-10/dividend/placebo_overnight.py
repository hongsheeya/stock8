"""Placebo: average close->next-open and close->next-close returns on NON-ex-dates (same tickers, 2015-2026),
to compare with the ex-date capture legs (C_open/C_close RAW minus the dividend yield)."""
import numpy as np
import pandas as pd

from study import GROUP, load

rows = []
for sym in GROUP:
    st = load(sym)
    d, C, O, D, v = st["dates"], st["C"], st["O"], st["D"], st["valid"]
    m = (d >= pd.Timestamp("2015-01-01"))
    i = np.arange(1, len(C))
    ok = m[1:] & v[1:] & v[:-1] & (D[1:] == 0)
    exd = np.r_[False, D[1:] > 0]
    near = np.zeros(len(C), bool)
    for e in np.flatnonzero(exd):
        near[max(0, e - 2):e + 3] = True
    ok &= ~near[1:]
    on = (O[1:] / C[:-1] - 1)[ok]
    cc = (C[1:] / C[:-1] - 1)[ok]
    rows.append({"sym": sym, "group": GROUP[sym], "days": int(ok.sum()), "overnight%": 100 * on.mean(), "close2close%": 100 * cc.mean()})
P = pd.DataFrame(rows)
print("placebo (non-ex days, +-2 days around ex-dates excluded), mean % per day, 2015-2026")
print(P.groupby("group")[["overnight%", "close2close%"]].mean().round(4).to_string())
P.to_csv("results/placebo_overnight.csv", index=False)
