"""10-23: three low-turnover / reversal ideas for the US market.

Pre-registered (before running):
A. Daily trend filter: hold the 2x ETF (QLD for QQQ, SSO for SPY) while the
   index signal is on, cash otherwise. Signal at the close, trade at the next
   open. Grid (6): SMA200, SMA150, SMA100, 12m momentum>0, 6m momentum>0,
   SMA200 AND 6m momentum>0. Two sleeves 50/50.
B. Daily breakout swing (the coin rule on daily bars): index close > highest
   high of the previous N days and > SMA50 -> buy the 2x ETF (QLD/SSO/USD for
   QQQ/SPY/SOXX) at the next open; exit when the index closes below its stop
   (chandelier: highest high since entry - k x ATR14, or the M-day low), sell
   at the next open. Grid (6): N in {20, 55} x exit in {2ATR, 3ATR, M-day low
   (M = N/2)}. Three sleeves 1/3 each.
C. Intraday reversal (1h bars, 3 years): from the 10:30 bar close ET, when the
   index has moved >= T% from its open and is beyond its VWAP in that
   direction, buy the opposite-side 2x ETF (QQQ up -> QID, down -> QLD; SPY ->
   SDS/SSO); exit when the index is back at VWAP (or its open), ETF -2.5%, or
   flat before 15:50. Grid (4): T in {1.0, 1.5} x target in {vwap, open}.
Selection: A/B on 2007-2016 (TRAIN) by MAR = CAGR/|MDD|; TEST 2017-2026
untouched. C on the first half of the 3 years, test on the second half.
Costs per side: 0.10% and 0.25%. Equity compounds per sleeve.
"""
import math
import os
import pickle
import statistics
from collections import defaultdict

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "us_cache")
os.makedirs(CACHE, exist_ok=True)
SPLIT = pd.Timestamp("2017-01-01")


def daily(sym):
    path = os.path.join(CACHE, f"d_{sym}.pkl")
    if os.path.exists(path):
        return pickle.load(open(path, "rb"))
    df = yf.Ticker(sym).history(period="max", interval="1d", auto_adjust=True)
    df.index = df.index.tz_localize(None).normalize()
    df = df[["Open", "High", "Low", "Close"]].dropna()
    pickle.dump(df, open(path, "wb"))
    return df


def stats(eq):
    eq = eq.dropna()
    if len(eq) < 2:
        return 0.0, 0.0
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 and eq.iloc[-1] > 0 else -1
    mdd = (eq / eq.cummax() - 1).min()
    return cagr * 100, mdd * 100


def sleeve_equity(signal, etf, cost):
    """signal: bool Series on index dates (decided at close). Position from the
    next open: daily return open->open of the ETF while in."""
    df = etf.copy()
    sig = signal.reindex(df.index).ffill().fillna(False).astype(bool)
    pos = sig.shift(1).fillna(False)              # decided at t-1 close, in from t open
    oo = df["Open"].shift(-1) / df["Open"] - 1    # open t -> open t+1
    ret = np.where(pos, oo, 0.0)
    trades = (pos != pos.shift(1)).fillna(False) & (df.index > df.index[0])
    ret = ret - np.where(trades, cost / 100, 0.0)
    eq = pd.Series(np.cumprod(1 + np.nan_to_num(ret)), index=df.index)
    return eq, int(trades.sum())


def study_a(cost):
    qqq, spy, qld, sso = daily("QQQ"), daily("SPY"), daily("QLD"), daily("SSO")
    start = max(qld.index[0], sso.index[0]) + pd.Timedelta(days=400)
    rules = {
        "SMA200": lambda c: c > c.rolling(200).mean(),
        "SMA150": lambda c: c > c.rolling(150).mean(),
        "SMA100": lambda c: c > c.rolling(100).mean(),
        "MOM12m": lambda c: c / c.shift(252) - 1 > 0,
        "MOM6m": lambda c: c / c.shift(126) - 1 > 0,
        "SMA200&MOM6m": lambda c: (c > c.rolling(200).mean()) & (c / c.shift(126) - 1 > 0),
    }
    out = {}
    for name, fn in rules.items():
        eqs, n = [], 0
        for idx, etf in ((qqq, qld), (spy, sso)):
            e, t = sleeve_equity(fn(idx["Close"]), etf, cost)
            eqs.append(e[e.index >= start] / e[e.index >= start].iloc[0]); n += t
        port = (eqs[0] + eqs[1]) / 2
        out[name] = (port, n)
    bh = {}
    for sym in ("QQQ", "SPY", "QLD", "SSO"):
        d = daily(sym)["Close"]; d = d[d.index >= start]; bh[sym] = d / d.iloc[0]
    return out, bh


def study_b(cost):
    pairs = (("QQQ", "QLD"), ("SPY", "SSO"), ("SOXX", "USD"))
    data = {i: daily(i) for i, _ in pairs}
    etfs = {e: daily(e) for _, e in pairs}
    start = max(e.index[0] for e in etfs.values()) + pd.Timedelta(days=120)
    out = {}
    for n in (20, 55):
        for ex in ("2ATR", "3ATR", "LOW"):
            eqs, trades = [], 0
            for idx_sym, etf_sym in pairs:
                d = data[idx_sym]; e = etfs[etf_sym]
                h, l, c = d["High"], d["Low"], d["Close"]
                tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
                atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
                hh = h.rolling(n).max().shift(1)
                sma = c.rolling(50).mean()
                low_m = l.rolling(n // 2).min().shift(1)
                in_pos, top, stop = False, 0.0, 0.0
                sig = pd.Series(False, index=d.index)
                for i, t in enumerate(d.index):
                    if in_pos:
                        top = max(top, h.iloc[i])
                        if ex == "LOW":
                            stop = low_m.iloc[i]
                        else:
                            k = 2.0 if ex == "2ATR" else 3.0
                            stop = max(stop, top - k * atr.iloc[i])
                        if c.iloc[i] < stop:
                            in_pos = False
                    elif not math.isnan(hh.iloc[i]) and not math.isnan(sma.iloc[i]) and c.iloc[i] > hh.iloc[i] and c.iloc[i] > sma.iloc[i]:
                        in_pos, top = True, h.iloc[i]
                        stop = (h.iloc[i] - (2.0 if ex == "2ATR" else 3.0) * atr.iloc[i]) if ex != "LOW" else low_m.iloc[i]
                    sig.iloc[i] = in_pos
                eq, t = sleeve_equity(sig, e, cost)
                eq = eq[eq.index >= start]; eqs.append(eq / eq.iloc[0]); trades += t
            port = sum(eqs) / len(eqs)
            out[f"N{n}_{ex}"] = (port, trades)
    return out


def split_stats(port):
    tr = port[port.index < SPLIT]; te = port[port.index >= SPLIT]
    a = stats(tr); b = stats(te / te.iloc[0]); f = stats(port)
    return a, b, f


def report_ab(label, res, years_total):
    rows = []
    for name, (port, n) in res.items():
        (tc, tm), (sc, sm), (fc, fm) = split_stats(port)
        rows.append((name, tc, tm, sc, sm, fc, fm, n))
    chosen = max(rows, key=lambda r: r[1] / abs(r[2]) if r[2] < 0 else r[1])[0]
    print(f"\n== {label} (선택 = 학습 구간 MAR 최고) ==")
    for name, tc, tm, sc, sm, fc, fm, n in rows:
        tag = "  <== 선택" if name == chosen else ""
        print(f"  {name:14s} 학습 연{tc:+6.1f}% 낙폭{tm:+6.1f}% | 시험 연{sc:+6.1f}% 낙폭{sm:+6.1f}% | 전체 연{fc:+6.1f}% 낙폭{fm:+6.1f}% | 거래/년 {n / years_total:4.1f}{tag}")
    return chosen


if __name__ == "__main__":
    for cost in (0.10, 0.25):
        res, bh = study_a(cost)
        yrs = (list(res.values())[0][0].index[-1] - list(res.values())[0][0].index[0]).days / 365.25
        report_ab(f"A. 일봉 추세 필터 (편도 {cost}%)", res, yrs)
        if cost == 0.10:
            print("  -- 단순 보유 비교 --")
            for sym, s in bh.items():
                (tc, tm), (sc, sm), (fc, fm) = split_stats(s)
                print(f"  {sym:14s} 학습 연{tc:+6.1f}% 낙폭{tm:+6.1f}% | 시험 연{sc:+6.1f}% 낙폭{sm:+6.1f}% | 전체 연{fc:+6.1f}% 낙폭{fm:+6.1f}%")
        resb = study_b(cost)
        yrs = (list(resb.values())[0][0].index[-1] - list(resb.values())[0][0].index[0]).days / 365.25
        report_ab(f"B. 일봉 돌파 스윙 (편도 {cost}%)", resb, yrs)
