"""Independent re-implementation of ONE combo (default 4h_N55_atr2) with plain
pandas resample + python loops, to cross-check breakout_wf.simulate trade by
trade, and to list the trades (dates, prices, %) per period.

usage: python audit_chosen.py [TF] [N] [EXIT]
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breakout_wf as W  # noqa: E402


def independent(coin_df, tf, N, ex, ps, pe):
    df = coin_df.set_index("t")
    bars = df.resample(tf, label="left", closed="left").agg({"o": "first", "h": "max", "l": "min", "c": "last"}).dropna()
    daily = df["c"].resample("1D").last().dropna()
    sma = daily.rolling(50).mean()
    # ATR14 Wilder
    pc = bars["c"].shift(1)
    tr = pd.concat([bars["h"] - bars["l"], (bars["h"] - pc).abs(), (bars["l"] - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    td = pd.Timedelta(tf)
    M = W.CHAN_EXIT[N]
    k = W.KATR.get(ex)
    idx = list(bars.index)
    five = df.loc[(df.index >= ps) & (df.index < pe)]
    trades, pos = [], None
    for j in range(len(idx)):
        st = idx[j]
        if st >= pe:
            break
        if pos is not None:
            seg = five.loc[(five.index >= st) & (five.index < st + td)]
            hit = seg[seg["l"] <= pos["stop"]]
            if len(hit):
                r = hit.iloc[0]
                trades.append((pos["t"], pos["px"], hit.index[0], min(r["o"], pos["stop"])))
                pos = None
            else:
                if k:
                    pos["hh"] = max(pos["hh"], bars["h"].iloc[j])
                    pos["stop"] = max(pos["stop"], pos["hh"] - k * atr.iloc[j])
                else:
                    pos["stop"] = bars["l"].iloc[j - M + 1:j + 1].min()
        if pos is None and j + 1 < len(idx) and idx[j + 1] < pe and j >= N and j >= M - 1:
            nxt = idx[j + 1]
            first5 = five.loc[(five.index >= nxt) & (five.index < nxt + td)]
            if not len(first5) or first5.index[0] < ps:
                continue
            if np.isnan(atr.iloc[j]):
                continue
            c = bars["c"].iloc[j]
            if c <= bars["h"].iloc[j - N:j].max():
                continue
            done_days = sma[sma.index + pd.Timedelta("1D") <= st + td]
            if not len(done_days) or np.isnan(done_days.iloc[-1]) or c <= done_days.iloc[-1]:
                continue
            pos = {"t": first5.index[0], "px": first5["o"].iloc[0]}
            if k:
                pos["hh"] = bars["h"].iloc[j]
                pos["stop"] = pos["hh"] - k * atr.iloc[j]
            else:
                pos["stop"] = bars["l"].iloc[j - M + 1:j + 1].min()
    if pos is not None:
        trades.append((pos["t"], pos["px"], five.index[-1], five["c"].iloc[-1]))
    return trades


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "4h"
    N = int(sys.argv[2]) if len(sys.argv) > 2 else 55
    ex = sys.argv[3] if len(sys.argv) > 3 else "atr2"
    combo = (tf, N, ex)
    coins = [W.Coin(m) for m in W.MARKETS]
    first = max(cn.t[0] for cn in coins)
    hour = np.timedelta64(1, "h").astype("timedelta64[ns]")
    ps = (first + hour - np.timedelta64(1, "ns")).astype("datetime64[h]").astype("datetime64[ns]")
    pe = min(cn.t[-1] for cn in coins) + W.FIVE_MIN
    periods = {"TRAIN": (ps, W.SPLIT), "TEST": (W.SPLIT, pe)}
    mism = 0
    for cn in coins:
        df = pd.DataFrame({"t": pd.to_datetime(cn.t), "o": cn.o, "h": cn.h, "l": cn.l, "c": cn.c})
        for p, (a, b) in periods.items():
            tr, _, _ = W.simulate(cn, combo, a, b)
            mine = [(pd.Timestamp(cn.t[e]), ep, pd.Timestamp(cn.t[x]), xp) for e, ep, x, xp, _ in tr]
            ind = independent(df, tf, N, ex, pd.Timestamp(a), pd.Timestamp(b))
            same = len(mine) == len(ind) and all(
                m[0] == i[0] and m[2] == i[2] and abs(m[1] - i[1]) < 1e-9 and abs(m[3] - i[3]) < 1e-6 for m, i in zip(mine, ind))
            mism += (not same)
            print(f"{cn.m:9s} {p:5s} trades main {len(mine):3d} independent {len(ind):3d} match {same}")
            if p == "TEST" or not same:
                for e, ep, x, xp in mine:
                    r = (xp * (1 - W.C)) / (ep * (1 + W.C)) - 1
                    print(f"      {e}  buy {ep:>14,.1f} -> {x}  sell {xp:>14,.1f}  {r * 100:+6.2f}%")
                if not same:
                    print("    independent:")
                    for e, ep, x, xp in ind:
                        print(f"      {e}  buy {ep:>14,.1f} -> {x}  sell {xp:>14,.1f}")
    print(f"\nmismatching coin-periods: {mism}")


if __name__ == "__main__":
    main()
