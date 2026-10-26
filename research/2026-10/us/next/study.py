"""US next strategies (PREREG.md). Signals on the index (QQQ, SPY), trades in
the 2x ETF (QLD, SSO), two 50/50 sleeves, cash otherwise.

Daily data: yfinance adjusted OHLC (cached .pkl from the 10-23 study);
hourly: the 730-day regular-session 1h cache (bars carry hm, o, h, l, c).
Set US_CACHE to the folder holding d_*.pkl and 1h.pkl."""
import os
import pickle
import random
import statistics

import numpy as np
import pandas as pd

CACHE = os.environ.get("US_CACHE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "us_cache")
PAIRS = (("QQQ", "QLD"), ("SPY", "SSO"))
SPLIT = pd.Timestamp("2017-01-01")
START = pd.Timestamp("2007-07-26")
RULES = ("D1", "D2", "D3", "D4")
LABEL = {"D1": "밤사이 보유", "D2": "월말·월초", "D3": "상승장 눌림목 RSI(2)", "D4": "장 초반 1시간 돌파"}


def daily(sym):
    return pickle.load(open(os.path.join(CACHE, f"d_{sym}.pkl"), "rb"))


def aligned(idx, etf):
    i, e = daily(idx), daily(etf)
    df = pd.DataFrame({"iC": i["Close"], "O": e["Open"], "C": e["Close"]}).dropna()
    return df[df.index >= START - pd.Timedelta(days=400)]


def rsi2(close):
    out = [np.nan] * len(close)
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
    return np.array(out)


# ------------------------------------------------------------ trades (day indices)
def trades_d1(df):
    return [(d, "C", d + 1, "O") for d in range(len(df) - 1)]


def trades_d2(df):
    out, idx = [], df.index
    for d in range(len(df) - 4):
        if idx[d].month != idx[d + 1].month:
            out.append((d, "C", d + 3, "C"))
    return out


_IND = {}


def d3_ind(df):
    key = (len(df), df.index[0], float(df["iC"].iloc[0]), float(df["iC"].iloc[-1]))
    if key not in _IND:
        c = df["iC"].values
        _IND[key] = (c, pd.Series(c).rolling(200).mean().values, pd.Series(c).rolling(5).mean().values, rsi2(c))
    return _IND[key]


def trades_d3(df, entry_days=None):
    c, sma200, sma5, r = d3_ind(df)
    out, d = [], 200
    signals = entry_days if entry_days is not None else [k for k in range(200, len(df) - 1) if c[k] > sma200[k] and r[k] < 10]
    sig = set(signals)
    if entry_days is not None and len(entry_days) == 1:
        d = entry_days[0]
    while d < len(df) - 1:
        if d not in sig:
            d += 1
            continue
        e = d + 1
        x = None
        for k in range(e, min(len(df) - 1, e + 10)):
            if c[k] > sma5[k] or k - e + 1 >= 10:
                x = k + 1
                break
        if x is None:
            break
        out.append((e, "O", x, "O"))
        d = x
    return out


def regime_days_d3(df):
    c, sma200, _s5, _r = d3_ind(df)
    return [k for k in range(200, len(df) - 1) if c[k] > sma200[k]]


def daily_returns(df, trades, fee):
    O, C = df["O"].values, df["C"].values
    r = np.zeros(len(df))
    for e, ek, x, xk in trades:
        if ek == "O":
            ref, day = O[e], e
        else:
            ref, day = C[e], e + 1
        r[e if ek == "O" else min(e + 1, len(df) - 1)] -= fee
        while day <= x and day < len(df):
            end = O[x] if (day == x and xk == "O") else C[day]
            r[day] += end / ref - 1
            ref = C[day]
            if day == x:
                break
            day += 1
        r[min(x, len(df) - 1)] -= fee
    return r


def trade_returns(df, trades, fee):
    O, C = df["O"].values, df["C"].values
    px = lambda d, k: O[d] if k == "O" else C[d]
    return [(px(x, xk) * (1 - fee)) / (px(e, ek) * (1 + fee)) - 1 for e, ek, x, xk in trades]


def trades_a(df):
    """The running rule A (6-month momentum of the index), next-open fills."""
    c = df["iC"].values
    on = [k >= 126 and c[k] / c[k - 126] - 1 > 0 for k in range(len(df))]
    out, holding, e = [], False, None
    for k in range(len(df) - 1):
        if on[k] and not holding:
            holding, e = True, k + 1
        elif not on[k] and holding:
            out.append((e, "O", k + 1, "O"))
            holding = False
    if holding:
        out.append((e, "O", len(df) - 1, "C"))
    return out


# ------------------------------------------------------------ metrics
def curve(rule, fee, start=START, end=None):
    eqs = []
    for idx, etf in PAIRS:
        df = aligned(idx, etf)
        tr = {"D1": trades_d1, "D2": trades_d2, "D3": trades_d3, "A": trades_a}[rule](df)
        r = daily_returns(df, tr, fee)
        s = pd.Series(np.cumprod(1 + r), index=df.index)
        s = s[(s.index >= start) & ((s.index < end) if end is not None else True)]
        eqs.append(s / s.iloc[0])
    return (eqs[0] + eqs[1]) / 2


def stats(eq):
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] ** (1 / years) - 1) * 100 if eq.iloc[-1] > 0 else -100.0
    mdd = (eq / eq.cummax() - 1).min() * 100
    return cagr, mdd, (cagr / abs(mdd) if mdd < 0 else 0.0)


def placebo_daily(rule, reps=1000, seed=11):
    rng = random.Random(seed)
    real, pools = [], []
    for idx, etf in PAIRS:
        df = aligned(idx, etf)
        df = df[df.index >= START - pd.Timedelta(days=300)]
        tr = {"D1": trades_d1, "D2": trades_d2, "D3": trades_d3}[rule](df)
        tr = [t for t in tr if df.index[t[0]] >= START]
        real += trade_returns(df, tr, 0.001)
        pools.append((df, tr))
    real_mean = statistics.mean(real)
    beats = 0
    means = []
    for _ in range(reps):
        rs = []
        for df, tr in pools:
            n = len(tr)
            lo = next(k for k in range(len(df)) if df.index[k] >= START)
            if rule == "D1":  # same count of intraday (open->close) holds
                days = rng.sample(range(lo, len(df)), min(n, len(df) - lo))
                rs += trade_returns(df, [(d, "O", d, "C") for d in days], 0.001)
            elif rule == "D2":  # random 3-day close->close windows
                days = rng.sample(range(lo, len(df) - 4), n)
                rs += trade_returns(df, [(d, "C", d + 3, "C") for d in days], 0.001)
            else:  # random uptrend days, same exits
                pool = [k for k in regime_days_d3(df) if k >= lo]
                picks = sorted(rng.sample(pool, min(n, len(pool))))
                sim = []
                for p in picks:
                    t = trades_d3(df, entry_days=[p])
                    sim += t[:1]
                rs += trade_returns(df, sim, 0.001)
        mu = statistics.mean(rs)
        means.append(mu)
        beats += mu >= real_mean
    return real_mean * 100, statistics.mean(means) * 100, beats / reps


# ------------------------------------------------------------ D4 intraday
def d4_trades(h1, day, idx, etf, entry_bar=None):
    ix, e = h1[idx].get(day), h1[etf].get(day)
    if not ix or not e or len(ix) < 3 or len(e) != len(ix):
        return None
    first = ix[0]
    for i in range(1, len(ix) - 1):
        if ix[i]["hm"] > "14:00":
            break
        hit = (i == entry_bar) if entry_bar is not None else (ix[i]["c"] > first["h"])
        if not hit:
            continue
        entry = e[i + 1]["o"]
        for j in range(i + 1, len(ix)):
            if ix[j]["c"] < first["l"] and j + 1 < len(e):
                return e[j + 1]["o"] / entry - 1
        return e[-1]["c"] / entry - 1
    return None


def d4_run(h1, days, fee, random_bars=None):
    per_day, rets = [], []
    for d in days:
        tot = 0.0
        for idx, etf in PAIRS:
            eb = random_bars.get((d, idx)) if random_bars is not None else None
            if random_bars is not None and eb is None:
                continue
            r = d4_trades(h1, d, idx, etf, entry_bar=eb)
            if r is None:
                continue
            r -= 2 * fee
            rets.append(r)
            tot += 0.5 * r
        per_day.append(tot)
    eq = np.cumprod(1 + np.array(per_day))
    years = len(days) / 252
    cagr = (eq[-1] ** (1 / years) - 1) * 100 if eq[-1] > 0 else -100.0
    mdd = (eq / np.maximum.accumulate(eq) - 1).min() * 100
    return cagr, mdd, rets


def main():
    print(f"데이터: 일봉 {daily('QQQ').index[0].date()}~{daily('QQQ').index[-1].date()}")
    a_full = curve("A", 0.001)
    a_cagr, a_mdd, a_mar = stats(a_full)
    print(f"A (지금 운용) 2007-07~: 연{a_cagr:+.1f}% 낙폭{a_mdd:.1f}% MAR{a_mar:.2f}")
    verdict = {}
    for rule in ("D1", "D2", "D3"):
        print(f"\n== {rule} {LABEL[rule]} ==")
        f1 = curve(rule, 0.001)
        c, m, mar = stats(f1)
        ca, ma, _ = stats(curve(rule, 0.001, end=SPLIT))
        cb, mb, _ = stats(curve(rule, 0.001, start=SPLIT))
        c25, m25, _ = stats(curve(rule, 0.0025))
        rm, pm, p = placebo_daily(rule)
        blend = 0.5 * a_full + 0.5 * f1.reindex(a_full.index).ffill()
        bc, bm, bmar = stats(blend)
        print(f"  전체(0.10%) 연{c:+6.1f}% 낙폭{m:+6.1f}% MAR{mar:5.2f} | 앞 연{ca:+6.1f}% 뒤 연{cb:+6.1f}% | 0.25% 연{c25:+6.1f}%")
        print(f"  무작위 비교: 실제 평균 {rm:+.3f}% / 무작위 평균 {pm:+.3f}% / 무작위가 같거나 좋을 확률 {p:.3f}")
        print(f"  A와 반반: 연{bc:+.1f}% 낙폭{bm:.1f}% MAR{bmar:.2f} (A 단독 {a_mar:.2f})")
        checks = [("1 앞·뒤 모두 플러스 (0.10%)", ca > 0 and cb > 0), ("2 0.25%에서 플러스", c25 > 0),
                  ("3 MAR ≥ 0.5", mar >= 0.5), ("4 무작위보다 확실히 좋음 (p<0.0125)", p < 0.0125),
                  ("5 A와 섞으면 MAR 상승", bmar > a_mar)]
        for name, ok in checks:
            print(f"    {'통과' if ok else '탈락'} {name}")
        verdict[rule] = all(ok for _n, ok in checks)

    print(f"\n== D4 {LABEL['D4']} (1시간봉) ==")
    h1 = pickle.load(open(os.path.join(CACHE, "1h.pkl"), "rb"))
    days = sorted(set(h1["QQQ"]) & set(h1["SPY"]) & set(h1["QLD"]) & set(h1["SSO"]))
    half = len(days) // 2
    c, m, rets = d4_run(h1, days, 0.001)
    ca, _ma, _ = d4_run(h1, days[:half], 0.001)
    cb, _mb, _ = d4_run(h1, days[half:], 0.001)
    c25, _m25, _ = d4_run(h1, days, 0.0025)
    mar = c / abs(m) if m < 0 else 0.0
    real_mean = statistics.mean(rets) * 100
    rng = random.Random(5)
    eligible = {}
    for d in days:
        for idx, _etf in PAIRS:
            bars = h1[idx].get(d) or []
            eligible[(d, idx)] = [i for i in range(1, len(bars) - 1) if bars[i]["hm"] <= "14:00"]
    n_by_idx = {}
    for d in days:
        for idx, etf in PAIRS:
            if d4_trades(h1, d, idx, etf) is not None:
                n_by_idx[idx] = n_by_idx.get(idx, 0) + 1
    beats, means = 0, []
    for _ in range(1000):
        rb = {}
        for idx, _etf in PAIRS:
            pool = [d for d in days if eligible[(d, idx)]]
            for d in rng.sample(pool, min(n_by_idx.get(idx, 0), len(pool))):
                rb[(d, idx)] = rng.choice(eligible[(d, idx)])
        _c, _m, rr = d4_run(h1, days, 0.001, random_bars=rb)
        mu = statistics.mean(rr) * 100 if rr else 0.0
        means.append(mu)
        beats += mu >= real_mean
    p = beats / 1000
    print(f"  {days[0]}~{days[-1]} {len(days)}일 | 전체(0.10%) 연{c:+6.1f}% 낙폭{m:+6.1f}% MAR{mar:5.2f} 거래{len(rets)} | 앞 연{ca:+6.1f}% 뒤 연{cb:+6.1f}% | 0.25% 연{c25:+6.1f}%")
    print(f"  무작위 비교: 실제 평균 {real_mean:+.3f}% / 무작위 평균 {statistics.mean(means):+.3f}% / 확률 {p:.3f}")
    checks = [("1 앞·뒤 모두 플러스 (0.10%)", ca > 0 and cb > 0), ("2 0.25%에서 플러스", c25 > 0),
              ("3 MAR ≥ 0.5", mar >= 0.5), ("4 무작위보다 확실히 좋음 (p<0.0125)", p < 0.0125)]
    for name, ok in checks:
        print(f"    {'통과' if ok else '탈락'} {name}")
    verdict["D4"] = all(ok for _n, ok in checks)
    passed = [r for r, ok in verdict.items() if ok]
    print("\n결론:", ("통과: " + ", ".join(f"{r} {LABEL[r]}" for r in passed)) if passed else "통과한 후보 없음 — A(추세 보유)만 유지")


if __name__ == "__main__":
    main()
