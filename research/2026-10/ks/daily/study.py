"""KS daily strategies (PREREG.md). yfinance adjusted daily OHLC of KS ETFs;
069500 is the KOSPI200 signal. `python study.py fetch` caches d_<SYM>.pkl in
KS_CACHE (default ./ks_cache, not committed).

Placebo (gate 3, K2-K4): random entries with the same count, side and holding
structure. K2 holds every night, so - as for the US overnight test (D1) - its
placebo is the same count of random intraday (open->close) holds."""
import os
import pickle
import random
import statistics
import sys

import numpy as np
import pandas as pd

CACHE = os.environ.get("KS_CACHE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "ks_cache")
SYMBOLS = {"069500": "069500.KS", "122630": "122630.KS", "252670": "252670.KS", "SOX": "^SOX"}
START, END = pd.Timestamp("2010-02-22"), pd.Timestamp("2026-10-31")
SPLIT = pd.Timestamp("2018-07-01")
K4_START, K4_SPLIT = pd.Timestamp("2016-09-22"), pd.Timestamp("2021-10-01")
FEE, FEE_HI = 0.0005, 0.0015
REPS = 1000


def fetch():
    import yfinance as yf
    os.makedirs(CACHE, exist_ok=True)
    for key, sym in SYMBOLS.items():
        df = yf.Ticker(sym).history(period="max", auto_adjust=True)
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        df = df[df["Close"] > 0][["Open", "Close"]]
        pickle.dump(df, open(os.path.join(CACHE, f"d_{key}.pkl"), "wb"))
        print(key, df.index[0].date(), df.index[-1].date(), len(df))


def load(key):
    return pickle.load(open(os.path.join(CACHE, f"d_{key}.pkl"), "rb"))


def setup():
    base = load("069500")
    days = base.index[(base.index >= pd.Timestamp("2009-01-01")) & (base.index < END)]
    O = pd.DataFrame({k: load(k)["Open"] for k in ("069500", "122630", "252670")}).reindex(days)
    C = pd.DataFrame({k: load(k)["Close"] for k in ("069500", "122630", "252670")}).reindex(days)
    sox = load("SOX")["Close"]
    sox_ret = sox.pct_change()
    # US session d feeds the first KS session after d
    us_signal = pd.Series(np.nan, index=days)
    j = 0
    us_days = sox_ret.index
    for i, day in enumerate(days):
        while j + 1 < len(us_days) and us_days[j + 1] < day:
            j += 1
        if us_days[j] < day:
            us_signal.iloc[i] = sox_ret.iloc[j]
    return days, O, C, us_signal


DAYS, O, C, US = setup() if sys.argv[1:] != ["fetch"] else (None, None, None, None)


def rsi2(close):
    out = np.full(len(close), np.nan)
    ag = al = None
    for k in range(1, len(close)):
        ch = close[k] - close[k - 1]
        g, l = max(ch, 0.0), max(-ch, 0.0)
        if k == 1:
            ag, al = g, l
            continue
        if k == 2:
            ag, al = (ag + g) / 2, (al + l) / 2
        else:
            ag, al = ag + (g - ag) / 2, al + (l - al) / 2
        out[k] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


if DAYS is not None:
    SIG = C["069500"].values
    SMA200 = pd.Series(SIG).rolling(200).mean().values
    SMA5 = pd.Series(SIG).rolling(5).mean().values
    RSI = rsi2(SIG)
    FIRST = int(np.searchsorted(DAYS, START))


# trades: (entry_day, "O"/"C", exit_day, "O"/"C", symbol)
def trades_k1():
    out, holding, e = [], False, None
    for k in range(FIRST - 1, len(DAYS) - 1):
        on = k >= 126 and SIG[k] / SIG[k - 126] - 1 > 0
        if on and not holding:
            holding, e = True, k + 1
        elif not on and holding:
            out.append((e, "O", k + 1, "O", "122630"))
            holding = False
    if holding:
        out.append((e, "O", len(DAYS) - 1, "C", "122630"))
    return out


def trades_k2():
    return [(d, "C", d + 1, "O", "122630") for d in range(FIRST, len(DAYS) - 1)]


def k3_exit(e):
    for k in range(e, min(len(DAYS) - 1, e + 10)):
        if SIG[k] > SMA5[k] or k - e + 1 >= 10:
            return k + 1
    return None


def trades_k3(entry_days=None):
    out, d = [], FIRST
    sig = set(entry_days) if entry_days is not None else {k for k in range(FIRST, len(DAYS) - 1) if SIG[k] > SMA200[k] and RSI[k] < 10}
    while d < len(DAYS) - 1:
        if d in sig:
            x = k3_exit(d + 1)
            if x is None:
                break
            out.append((d + 1, "O", x, "O", "122630"))
            d = x
            continue
        d += 1
    return out


def k3_regime_days():
    return [k for k in range(FIRST, len(DAYS) - 1) if SIG[k] > SMA200[k]]


def trades_k4(long_only=False, start=K4_START):
    lo = int(np.searchsorted(DAYS, start))
    out = []
    for d in range(lo, len(DAYS)):
        s = US.iloc[d]
        if np.isnan(s):
            continue
        if s >= 0.01:
            out.append((d, "O", d, "C", "122630"))
        elif s <= -0.01 and not long_only:
            out.append((d, "O", d, "C", "252670"))
    return out


def trade_ret(t, fee):
    e, ek, x, xk, sym = t
    pe = O[sym].iat[e] if ek == "O" else C[sym].iat[e]
    px = O[sym].iat[x] if xk == "O" else C[sym].iat[x]
    return px * (1 - fee) / (pe * (1 + fee)) - 1


def daily_curve(trades, fee, start, end):
    r = pd.Series(0.0, index=DAYS)
    for e, ek, x, xk, sym in trades:
        o, c = O[sym].values, C[sym].values
        ref = o[e] if ek == "O" else c[e]
        day = e if ek == "O" else e + 1
        r.iat[min(day, len(DAYS) - 1)] -= fee
        while day <= x:
            end_px = o[x] if (day == x and xk == "O") else c[day]
            r.iat[day] += end_px / ref - 1
            ref = c[day]
            if day == x:
                break
            day += 1
        r.iat[x] -= fee
    r = r[(r.index >= start) & (r.index < end)]
    return (1 + r).cumprod()


def hold_curve(sym, start, end):
    s = C[sym][(C.index >= start) & (C.index < end)].dropna()
    return s / s.iloc[0]


def stats(eq):
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] ** (1 / years) - 1) * 100 if eq.iloc[-1] > 0 else -100.0
    mdd = (eq / eq.cummax() - 1).min() * 100
    return round(cagr, 1), round(mdd, 1), round(cagr / abs(mdd), 2) if mdd < 0 else 0.0


def year_ret(eq, year):
    s = eq[eq.index.year == year]
    prev = eq[eq.index.year < year]
    if not len(s):
        return None
    return round((s.iloc[-1] / (prev.iloc[-1] if len(prev) else 1.0) - 1) * 100, 1)


def placebo(name, trades, seed=7):
    rng = random.Random(seed)
    real = statistics.mean(trade_ret(t, FEE) for t in trades)
    beats, means = 0, []
    for _ in range(REPS):
        if name == "K2":
            days = rng.sample(range(FIRST, len(DAYS)), len(trades))
            sim = [(d, "O", d, "C", "122630") for d in days]
        elif name == "K3":
            pool = k3_regime_days()
            sim = []
            for p in sorted(rng.sample(pool, len(trades))):
                sim += trades_k3(entry_days=[p])[:1]
        else:  # K4: same count per side, random days in the window
            lo = int(np.searchsorted(DAYS, K4_START))
            sim = []
            for sym in ("122630", "252670"):
                n = sum(1 for t in trades if t[4] == sym)
                pool = [d for d in range(lo, len(DAYS)) if not (np.isnan(O[sym].iat[d]) or np.isnan(C[sym].iat[d]))]
                sim += [(d, "O", d, "C", sym) for d in rng.sample(pool, n)]
        mu = statistics.mean(trade_ret(t, FEE) for t in sim)
        means.append(mu)
        beats += mu >= real
    return round(real * 100, 3), round(statistics.mean(means) * 100, 3), beats / REPS


def main():
    print(f"data {DAYS[0].date()} ~ {DAYS[-1].date()}; K1-K3 {START.date()} split {SPLIT.date()}; K4 {K4_START.date()} split {K4_SPLIT.date()}")
    rows = {}
    for name, trades, s0, sp in (("K1", trades_k1(), START, SPLIT), ("K2", trades_k2(), START, SPLIT),
                                 ("K3", trades_k3(), START, SPLIT), ("K4", trades_k4(), K4_START, K4_SPLIT)):
        full = daily_curve(trades, FEE, s0, END)
        rows[name] = {
            "trades": len(trades), "per_year": round(len(trades) / ((END - s0).days / 365.25), 1),
            "full": stats(full), "first": stats(daily_curve(trades, FEE, s0, sp)), "second": stats(daily_curve(trades, FEE, sp, END)),
            "full_hi": stats(daily_curve(trades, FEE_HI, s0, END)), "y2020": year_ret(full, 2020), "y2022": year_ret(full, 2022),
            "trades_list": trades,
        }
    holds = {sym: {"full": stats(hold_curve(sym, START, END)), "first": stats(hold_curve(sym, START, SPLIT)),
                   "second": stats(hold_curve(sym, SPLIT, END))} for sym in ("069500", "122630")}
    print("\nhold 069500:", holds["069500"], "\nhold 122630:", holds["122630"])
    print(f"\n{'':3s} {'n':>5s} {'/yr':>5s} | {'CAGR':>6s} {'MDD':>6s} {'MAR':>5s} | {'1st':>6s} {'2nd':>6s} (CAGR) | {'@0.15%':>6s} | 2020 2022")
    for n, r in rows.items():
        print(f"{n:3s} {r['trades']:5d} {r['per_year']:5.1f} | {r['full'][0]:+6.1f} {r['full'][1]:+6.1f} {r['full'][2]:5.2f} | "
              f"{r['first'][0]:+6.1f} {r['second'][0]:+6.1f}        | {r['full_hi'][0]:+6.1f} | {r['y2020']} {r['y2022']}")
    lo = trades_k4(long_only=True, start=START)
    print("\nK4 long side only 2010~: n", len(lo), "full", stats(daily_curve(lo, FEE, START, END)),
          "halves", stats(daily_curve(lo, FEE, START, SPLIT))[0], stats(daily_curve(lo, FEE, SPLIT, END))[0])
    verdict = {}
    for n, r in rows.items():
        gates = {"1 halves>0": r["first"][0] > 0 and r["second"][0] > 0, "2 @0.15%>0": r["full_hi"][0] > 0}
        if n == "K1":
            gates["3 MAR>holds all periods"] = all(r[p][2] > max(holds["069500"][p][2], holds["122630"][p][2]) for p in ("full", "first", "second"))
        else:
            real, rand, p = placebo(n, r["trades_list"])
            print(f"{n} placebo: mean/trade {real}% vs random {rand}%  p={p}")
            gates["3 placebo p<0.0042"] = p < 0.0042
            gates["4 MAR>=0.3"] = r["full"][2] >= 0.3
        verdict[n] = all(gates.values())
        print(f"{n} gates {gates} -> {'PASS' if verdict[n] else 'FAIL'}")
    print("\nverdict:", verdict)


if __name__ == "__main__":
    if sys.argv[1:] == ["fetch"]:
        fetch()
    else:
        main()
