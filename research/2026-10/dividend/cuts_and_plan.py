"""(1) Dividend-cut frequency: each payment vs the payment closest to one year earlier (+-45 days), 2016-2026.
(2) Small arithmetic used in the feature plan (capital that produces 20M KRW gross dividends)."""
import os

import numpy as np
import pandas as pd

from study import GROUP, RES, load

pd.set_option("display.width", 220)
rows = []
for sym in GROUP:
    st = load(sym)
    s = pd.Series(st["D"], index=st["dates"])
    s = s[s > 0]
    for d, a in s[s.index >= "2016-01-01"].items():
        prev = s[(s.index >= d - pd.Timedelta(days=410)) & (s.index <= d - pd.Timedelta(days=320))]
        if prev.empty:
            continue
        j = np.argmin(np.abs((prev.index - (d - pd.Timedelta(days=365))).days))
        rows.append({"sym": sym, "group": GROUP[sym], "date": d.date(), "amt": a, "amt_1y_ago": prev.iloc[j],
                     "chg%": 100 * (a / prev.iloc[j] - 1)})
C = pd.DataFrame(rows)
C.to_csv(os.path.join(RES, "dividend_yoy.csv"), index=False)
C["cut10"] = C["chg%"] <= -10
print("=== payments >=10% below the payment one year earlier (2016-2026)")
print(C.groupby("group").agg(payments=("cut10", "size"), cut_share=("cut10", "mean")).to_string(float_format=lambda v: f"{v:.3f}"))
g = C[C.cut10].groupby(["group", "sym"]).agg(n=("cut10", "size"), first=("date", "min"), last=("date", "max"),
                                                worst=("chg%", "min"))
print(g.to_string(float_format=lambda v: f"{v:.1f}"))

print("\n=== 20,000,000 KRW comprehensive-taxation threshold: invested capital whose GROSS dividends reach it")
for y in (0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12):
    print(f"  yield {100 * y:.0f}% -> {20_000_000 / y:,.0f} KRW")
