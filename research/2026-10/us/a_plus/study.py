"""US A-plus study (PREREG.md). Daily weights per sleeve, signals at the
close, trades at the next open, cost on the weight change only.

Data: yfinance adjusted daily OHLC, cached as d_<SYM>.pkl in US_CACHE
(default: ./us_cache, not committed). `python study.py fetch` downloads."""
import os
import pickle
import sys

import numpy as np
import pandas as pd

CACHE = os.environ.get("US_CACHE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "us_cache")
START = pd.Timestamp("2007-07-26")
END = pd.Timestamp("2026-10-31")
SPLIT = pd.Timestamp("2017-01-01")
PAIRS = (("QQQ", "QLD"), ("SPY", "SSO"))
SECTORS = ("XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB")
SYMBOLS = ("QQQ", "SPY", "QLD", "SSO", "IEF", "TLT", "SHY", "GLD") + SECTORS
MOM = 126
REBOUND_YEARS = (2010, 2011, 2015, 2019, 2020, 2023)


def fetch():
    import yfinance as yf
    os.makedirs(CACHE, exist_ok=True)
    for sym in SYMBOLS:
        df = yf.Ticker(sym).history(period="max", auto_adjust=True)
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        pickle.dump(df[["Open", "Close"]], open(os.path.join(CACHE, f"d_{sym}.pkl"), "wb"))
        print(sym, df.index[0].date(), df.index[-1].date(), len(df))


def panel():
    o, c = {}, {}
    for sym in SYMBOLS:
        df = pickle.load(open(os.path.join(CACHE, f"d_{sym}.pkl"), "rb"))
        o[sym], c[sym] = df["Open"], df["Close"]
    O, C = pd.DataFrame(o), pd.DataFrame(c)
    keep = C[list(SYMBOLS)].notna().all(axis=1) & O[list(SYMBOLS)].notna().all(axis=1)
    O, C = O[keep], C[keep]
    return O[O.index < END], C[C.index < END]


if sys.argv[1:] != ["fetch"]:
    O, C = panel()
    DAYS = C.index
    MONTH_END = np.array([i == len(DAYS) - 1 or DAYS[i].month != DAYS[i + 1].month for i in range(len(DAYS))])


def mom(sym, n=MOM):
    s = C[sym]
    return (s / s.shift(n) - 1).values


def run(target, fee):
    """target: DataFrame of weights decided at close k (applied from open k+1).
    Returns the daily equity curve."""
    cols = list(target.columns)
    W = target.fillna(0.0).values
    o, c = O[cols].values, C[cols].values
    eq = np.ones(len(DAYS))
    w_prev = np.zeros(len(cols))
    for k in range(1, len(DAYS)):
        w_new = W[k - 1]
        gap = o[k] / c[k - 1] - 1   # overnight on the old weights
        intraday = c[k] / o[k] - 1  # after the open on the new weights
        cost = np.abs(w_new - w_prev).sum() * fee
        eq[k] = eq[k - 1] * (1 + (w_prev * gap).sum()) * (1 - cost) * (1 + (w_new * intraday).sum())
        w_prev = w_new
    return pd.Series(eq, index=DAYS)


def sleeve_a(idx, etf, off=None, vol=None):
    """A on one sleeve. off(k) -> {sym: w} while A is in cash. vol: (target, band)."""
    m = mom(idx)
    cols = sorted({etf, "IEF", "TLT", "SHY", "GLD"})
    W = pd.DataFrame(0.0, index=DAYS, columns=cols)
    ret = C[etf].pct_change().values
    w_risk = 0.0
    off_pick = {}
    for k in range(len(DAYS)):
        if k >= MOM and m[k] > 0:
            if vol is None:
                w_risk = 1.0
            else:
                target, band = vol
                rv = np.std(ret[max(1, k - 19):k + 1], ddof=1) * np.sqrt(252) if k >= 21 else np.inf
                want = min(1.0, target / rv) if rv > 0 else 1.0
                if w_risk == 0.0 or abs(want - w_risk) >= band:
                    w_risk = want
            W.iat[k, cols.index(etf)] = w_risk
            off_pick = {}
        else:
            w_risk = 0.0
            if off is not None:
                if not off_pick or off.get("monthly") and MONTH_END[k]:
                    off_pick = off["pick"](k)
                for sym, w in off_pick.items():
                    W.iat[k, cols.index(sym)] = w
    return W


def strategy(name, fee, **kw):
    if name == "E4":
        top, n = kw.get("top", 3), kw.get("lookback", MOM)
        spy = mom("SPY", MOM)
        moms = {s: mom(s, n) for s in SECTORS}
        W = pd.DataFrame(0.0, index=DAYS, columns=list(SECTORS))
        cur = {}
        for k in range(len(DAYS)):
            if MONTH_END[k] and k >= max(MOM, n):
                cur = {}
                if spy[k] > 0:
                    best = sorted(SECTORS, key=lambda s: moms[s][k], reverse=True)[:top]
                    cur = {s: 1.0 / top for s in best}
            for s, w in cur.items():
                W.at[DAYS[k], s] = w
        return run(W, fee)
    curves = []
    for idx, etf in PAIRS:
        if name == "A":
            W = sleeve_a(idx, etf)
        elif name == "E1":
            bond = kw.get("bond", "IEF")
            W = sleeve_a(idx, etf, off={"pick": lambda k, b=bond: {b: 1.0}})
        elif name == "E2":
            n = kw.get("lookback", MOM)
            mi, mg = mom("IEF", n), mom("GLD", n)

            def pick(k, mi=mi, mg=mg):
                best, val = ("IEF", mi[k]) if mi[k] >= mg[k] else ("GLD", mg[k])
                return {best: 1.0} if val > 0 else {}
            W = sleeve_a(idx, etf, off={"pick": pick, "monthly": True})
        elif name == "E3":
            W = sleeve_a(idx, etf, vol=(kw.get("target", 0.35), kw.get("band", 0.20)))
        curves.append(run(W, fee))
    return (curves[0] + curves[1]) / 2


def stats(eq, start=START, end=END):
    s = eq[(eq.index >= start) & (eq.index < end)]
    s = s / s.iloc[0]
    years = (s.index[-1] - s.index[0]).days / 365.25
    cagr = (s.iloc[-1] ** (1 / years) - 1) * 100
    mdd = (s / s.cummax() - 1).min() * 100
    return cagr, mdd, cagr / abs(mdd)


def year_ret(eq, year):
    s = eq[eq.index.year == year]
    prev = eq[eq.index.year < year]
    base = prev.iloc[-1] if len(prev) else s.iloc[0]
    return (s.iloc[-1] / base - 1) * 100


def turnover(name, **kw):
    """Average one-way weight changes per year (approx. trades)."""
    eq0 = strategy(name, 0.0, **kw)
    eq1 = strategy(name, 0.01, **kw)
    years = (DAYS[-1] - START).days / 365.25
    s0, s1 = eq0[eq0.index >= START], eq1[eq1.index >= START]
    drag = np.log((s0.iloc[-1] / s0.iloc[0]) / (s1.iloc[-1] / s1.iloc[0]))
    return drag / 0.01 / years


MAIN = {"A": {}, "E1": {"bond": "IEF"}, "E2": {"lookback": 126}, "E3": {"target": 0.35, "band": 0.20}, "E4": {"top": 3, "lookback": 126}}
NEIGHBORS = {
    "E1": [{"bond": "TLT"}, {"bond": "SHY"}],
    "E2": [{"lookback": 63}, {"lookback": 252}],
    "E3": [{"target": 0.25, "band": 0.20}, {"target": 0.45, "band": 0.20}, {"target": 0.35, "band": 0.10}, {"target": 0.35, "band": 0.30}],
    "E4": [{"top": 2, "lookback": 126}, {"top": 4, "lookback": 126}, {"top": 3, "lookback": 63}, {"top": 3, "lookback": 252}],
}


def main():
    print(f"data {DAYS[0].date()} ~ {DAYS[-1].date()} ({len(DAYS)} days)")
    res = {}
    for name, kw in MAIN.items():
        e10, e25 = strategy(name, 0.001, **kw), strategy(name, 0.0025, **kw)
        res[name] = {"full": stats(e10), "first": stats(e10, START, SPLIT), "second": stats(e10, SPLIT, END),
                     "full25": stats(e25), "y2022": year_ret(e10, 2022),
                     "rebound": {y: round(year_ret(e10, y), 1) for y in REBOUND_YEARS}, "turn": turnover(name, **kw)}
    a = res["A"]
    print(f"\n{'':4s} {'CAGR':>7s} {'MDD':>7s} {'MAR':>5s} | {'1st MAR':>7s} {'2nd MAR':>7s} | {'MAR@.25':>7s} | {'2022':>6s} | turn/yr")
    for name, r in res.items():
        print(f"{name:4s} {r['full'][0]:+7.1f} {r['full'][1]:+7.1f} {r['full'][2]:5.2f} | {r['first'][2]:7.2f} {r['second'][2]:7.2f} | "
              f"{r['full25'][2]:7.2f} | {r['y2022']:+6.1f} | {r['turn']:.1f}")
    print("\nrebound years:", {n: r["rebound"] for n, r in res.items()})
    print("\nneighbors (full MAR @0.10%, A =", round(a["full"][2], 3), ")")
    verdict = {}
    for name in ("E1", "E2", "E3", "E4"):
        r = res[name]
        nb = [(kw, stats(strategy(name, 0.001, **kw))[2]) for kw in NEIGHBORS[name]]
        beats = sum(1 for _kw, mar in nb if mar > a["full"][2])
        need = len(nb) if len(nb) == 2 else 3
        gates = {
            "1 MAR>=A+0.05": r["full"][2] >= a["full"][2] + 0.05,
            "2 halves>=A": r["first"][2] >= a["first"][2] and r["second"][2] >= a["second"][2],
            "3 MAR@0.25>=A": r["full25"][2] >= a["full25"][2],
            f"4 neighbors {beats}/{len(nb)} (need {need})": beats >= need,
        }
        verdict[name] = all(gates.values())
        print(f"  {name}: " + ", ".join(f"{kw} {mar:.3f}" for kw, mar in nb))
        print(f"     gates: {gates} -> {'PASS' if verdict[name] else 'FAIL'}")
    print("\nverdict:", verdict)


if __name__ == "__main__":
    if sys.argv[1:] == ["fetch"]:
        fetch()
    else:
        main()
