"""Placebo test for run-up windows: for each event, compare its market-adjusted N-day pre-ex return with
random N-day windows of the SAME stock within +-250 trading days that do not touch any ex-date (+-2 days).
p = share of 2000 placebo portfolios (one random window per event) whose mean AR >= the actual mean AR."""
import numpy as np
import pandas as pd

from study import GROUP, MKT, PROXY, align_proxy, beta_of, load

rng = np.random.default_rng(11)
proxies = {k: load(v) for k, v in PROXY.items()}


def test(groups, N, start="2015-01-01", end="2026-12-31", n_perm=2000):
    actual, pools = [], []
    for sym in [s for s in GROUP if GROUP[s] in groups]:
        st = load(sym)
        pC, pO, pCD = align_proxy(st, proxies[MKT[sym]])
        b = beta_of(st, pC, pCD)
        C, D, CD, valid, dates = st["C"], st["D"], st["CD"], st["valid"], st["dates"]
        n = len(C)
        ex = np.flatnonzero(D > 0)
        touch = np.zeros(n, bool)
        for e in ex:
            touch[max(0, e - 2):e + 3] = True
        ctouch = np.cumsum(touch)

        def ar(t0, t1):
            r = (C[t1] + CD[t1] - CD[t0]) / C[t0] - 1
            rm = (pC[t1] + pCD[t1] - pCD[t0]) / pC[t0] - 1
            return r - b * rm

        for e in ex:
            if not (pd.Timestamp(start) <= dates[e] <= pd.Timestamp(end)):
                continue
            t1, t0 = e - 1, e - 1 - N
            if t0 < 0 or not (valid[t0] and valid[t1]) or not np.isfinite(pC[t0]) or not np.isfinite(pC[t1]):
                continue
            a = ar(t0, t1)
            lo, hi = max(N, e - 250), min(n - 1, e + 250)
            cand = np.arange(lo, hi)
            s0 = cand - N
            ok = valid[cand] & valid[s0] & ((ctouch[cand] - ctouch[s0]) == 0) & np.isfinite(pC[cand]) & np.isfinite(pC[s0])
            cand = cand[ok]
            if len(cand) < 20 or not np.isfinite(a):
                continue
            pool = np.array([ar(c - N, c) for c in cand])
            pool = pool[np.isfinite(pool)]
            actual.append(a)
            pools.append(pool)
    actual = np.array(actual)
    perm = np.array([np.mean([p[rng.integers(len(p))] for p in pools]) for _ in range(n_perm)])
    return len(actual), 100 * actual.mean(), 100 * perm.mean(), 100 * np.percentile(perm, 97.5), (perm >= actual.mean()).mean()


rows = []
for groups, N, label, start, end in [
    ({"US_STOCK"}, 5, "US_STOCK R_5", "2015-01-01", "2026-12-31"),
    ({"US_STOCK"}, 5, "US_STOCK R_5", "2023-01-01", "2026-12-31"),
    ({"US_STOCK"}, 20, "US_STOCK R_20", "2015-01-01", "2026-12-31"),
    ({"KR_STOCK"}, 20, "KR_STOCK R_20", "2015-01-01", "2026-12-31"),
    ({"KR_STOCK"}, 20, "KR_STOCK R_20", "2023-01-01", "2026-12-31"),
    ({"KR_STOCK"}, 10, "KR_STOCK R_10", "2015-01-01", "2026-12-31"),
    ({"KR_ETF"}, 20, "KR_ETF R_20", "2015-01-01", "2026-12-31")]:
    n, a, pm, p975, p = test(groups, N, start, end)
    rows.append({"case": label, "period": f"{start[:4]}-{end[:4]}", "events": n, "actual_AR%": a, "placebo_mean_AR%": pm,
                 "placebo_97.5pct%": p975, "p_value": p})
out = pd.DataFrame(rows)
out.to_csv("results/placebo_windows.csv", index=False)
print(out.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
