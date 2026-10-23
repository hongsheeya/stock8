"""Diagnostics for the chosen VBO combo (k=0.7, N=10): trade list sanity checks. Not used for selection."""
import numpy as np, pandas as pd
import vbo_research as V

coins = {m: V.Coin(m, V.load(m)) for m in V.MARKETS}
for m in V.MARKETS:
    c = coins[m]
    tr = V.simulate(c, 0.7, 10)
    rets = np.array([x["ret"] for x in tr])
    print(m, "n", len(tr), "worst", np.round(np.sort(rets)[:3] * 100, 2), "best", np.round(np.sort(rets)[-3:] * 100, 2))
    # verify a couple of trades against raw bars
    for x in tr[:2] + [x for x in tr if x["entry_day"] >= V.SPLIT][:1]:
        j = c.day_index[x["entry_day"]]
        a, b = c.first[j], c.last[j]
        # bars before entry must all have high < target
        assert (c.h[a:x["i_in"]] < x["target"]).all()
        assert c.h[x["i_in"]] >= x["target"]
        assert str(c.t[x["i_out"]])[:10] == str((x["entry_day"] + pd.Timedelta(days=1)).date())
        print("   ", str(x["entry_day"].date()), "target %.6g fill %.6g in %s out %s @ %.6g ret %+.2f%%" % (
            x["target"], x["fill"], str(c.t[x["i_in"]])[:16], str(c.t[x["i_out"]])[:16], x["exit"], x["ret"] * 100))
    if m == "KRW-XRP":
        for x in tr:
            if x["entry_day"] >= V.SPLIT:
                print("     XRP TEST", str(x["entry_day"].date()), "%+.2f%%" % (x["ret"] * 100))

# t-stat of per-trade net returns (chosen combo), pooled across coins
allt = [x for m in V.MARKETS for x in V.simulate(coins[m], 0.7, 10)]
for name, sel in [("TRAIN", lambda x: x["entry_day"] < V.SPLIT), ("TEST", lambda x: x["entry_day"] >= V.SPLIT), ("FULL", lambda x: True)]:
    r = np.array([x["ret"] for x in allt if sel(x)])
    print(f"{name}: n={len(r)} mean {r.mean()*100:+.3f}% sd {r.std(ddof=1)*100:.2f}% t={r.mean()/(r.std(ddof=1)/np.sqrt(len(r))):.2f}")
