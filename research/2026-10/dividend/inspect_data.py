"""Data-quality diagnostics: ex-date alignment, outliers, gaps, splits, dividend sanity."""
import json
import os

import numpy as np
import pandas as pd

from fetch import ALL, CACHE, MARKET, path_for

START = pd.Timestamp("2015-01-01")


def load(sym):
    df = pd.read_csv(path_for(sym), index_col=0, parse_dates=True)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


rows = []
for s in ALL:
    if s in MARKET:
        continue
    df = load(s)
    meta = json.load(open(path_for(s).replace(".csv", ".meta.json"), encoding="utf-8"))
    d = df[df.index >= START - pd.Timedelta(days=60)]
    c = d["Close"]
    o = d["Open"]
    ret = c.pct_change()
    big = ret[ret.abs() > 0.15]
    gaps = d.index.to_series().diff().dt.days
    biggap = gaps[gaps > 6]
    splits = d["Stock Splits"][d["Stock Splits"] > 0]
    zero_open = int(((o <= 0) | o.isna()).sum())
    open_eq_close = int((o == c).sum())
    divi = np.flatnonzero(d["Dividends"].values > 0)
    divi = [i for i in divi if d.index[i] >= START and 3 <= i < len(d) - 3]
    # alignment: pooled close-to-close drop / dividend at offsets -2..+2 (k=0 is the listed ex-date)
    align = {}
    for k in range(-2, 3):
        num = den = 0.0
        for i in divi:
            j = i + k
            if j - 1 < 0 or j >= len(d):
                continue
            num += c.iloc[j - 1] - c.iloc[j]
            den += d["Dividends"].iloc[i]
        align[k] = num / den if den else np.nan
    yields = [d["Dividends"].iloc[i] / c.iloc[i - 1] for i in divi]
    rows.append({
        "sym": s, "ccy": meta.get("currency"), "first": df.index[0].date(), "n_div_2015+": len(divi),
        "yield_med%": round(100 * np.median(yields), 3) if yields else None,
        "yield_max%": round(100 * max(yields), 3) if yields else None,
        "align-2": round(align[-2], 2), "align-1": round(align[-1], 2), "align0": round(align[0], 2),
        "align+1": round(align[1], 2), "align+2": round(align[2], 2),
        "n|ret|>15%": len(big), "gaps>6d": len(biggap), "splits": len(splits), "zero_open": zero_open,
        "open==close": open_eq_close,
    })
    if len(big) or len(splits) or len(biggap):
        print(f"--- {s}: big moves {[(str(k.date()), round(v, 3)) for k, v in big.items()]}")
        if len(splits):
            print(f"    splits {[(str(k.date()), v) for k, v in splits.items()]}")
        if len(biggap):
            print(f"    gaps {[(str(k.date()), int(v)) for k, v in biggap.items()]}")

out = pd.DataFrame(rows)
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
print(out.to_string(index=False))
out.to_csv(os.path.join(os.path.dirname(CACHE), "data_quality.csv"), index=False)
