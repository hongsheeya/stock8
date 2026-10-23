"""Independent re-computation of every per-coin window return in results.json.

Plain day-level loop (no numpy bar simulation): the position for day D is the
signal at the close of day D-1; trades fill at the first 5m open of the day;
an open position is liquidated at the window's last 5m close. Cost 0.1%/side.
"""
import json
import os

import pandas as pd

import regime as R

res = json.load(open(os.path.join(R.HERE, "results.json")))
data = {m: R.load5m(m) for m in R.MARKETS}
closes = {m: R.daily_closes(m, data[m])[0] for m in R.MARKETS}
end = max(data[m]["t"].iloc[-1] for m in R.MARKETS) + pd.Timedelta("5min")
windows = {"TRAIN": (R.START, R.SPLIT), "TEST": (R.SPLIT, end), "FULL": (R.START, end)}
worst = 0.0
for name, kind, p in R.GRID:
    for m in R.MARKETS:
        sig = R.signal(kind, p, closes[m], closes["KRW-BTC"])
        df = data[m]
        for w, (lo, hi) in windows.items():
            d = df[(df["t"] >= lo) & (df["t"] < hi)]
            days = d.groupby("day").agg(o=("o", "first"))
            last_close = d["c"].iloc[-1]
            eq, entry, n = 1.0, None, 0
            for day, row in days.iterrows():
                want = bool(sig.get(day - pd.Timedelta("1D"), False))
                if want and entry is None:
                    entry, n = row["o"], n + 1
                elif not want and entry is not None:
                    eq *= row["o"] / entry * (1 - R.SIDE) ** 2
                    entry = None
            if entry is not None:
                eq *= last_close / entry * (1 - R.SIDE) ** 2
            got = res["grid"][name][w]["coin"][m]
            diff = abs((eq - 1) - got["ret"])
            worst = max(worst, diff)
            if diff > 1e-9 or n != got["n"]:
                print("MISMATCH", name, m, w, eq - 1, got["ret"], n, got["n"])
print("checked 12 combos x 5 coins x 3 windows; max abs return diff", worst)
