"""Breakout family - walk-forward study (long-only spot, Upbit KRW, 5 coins).

PRE-REGISTRATION (written before any run of this script; not changed afterwards)
-------------------------------------------------------------------------------
Bars      : 5m Upbit candles resampled to 1h / 4h bars, UTC-aligned
            (4h bars start 00/04/08/12/16/20 UTC). Missing 5m bars are simply
            absent; a TF bar is built from whatever 5m bars exist in it.
Entry     : at the CLOSE of TF bar j, if
              close[j] > highest high of the previous N TF bars (j-N .. j-1)
              AND close[j] > SMA50 of COMPLETED UTC-day closes
                  (Upbit day = 00:00 UTC; only days that ended at or before
                   the bar's close are used)
            -> buy at the OPEN of TF bar j+1 (first existing 5m bar in it).
Exit      : a protective sell-stop that is fixed for the whole TF bar and is
            recomputed only from CLOSED TF bars:
              chan : stop = lowest low of the last M TF bars (incl. bar j),
                     M = 10 for N=20, M = 20 for N=55 (Turtle 20/10, 55/20)
              atr2 : chandelier, stop = highest high since the signal bar
                     - 2.0 x ATR14(Wilder, TF bars); ratchets up only
              atr3 : same with 3.0 x ATR14
            The stop is checked on the 5m bars inside the holding TF bar in
            time order: first 5m bar with low <= stop exits at
            min(that 5m bar's open, stop)  (= stop, or worse on a gap).
            Re-entry is allowed on any later closed-bar signal (including the
            close of the bar in which the stop was hit).
Costs     : 0.10% per side (0.05% fee + 0.05% slippage) = 0.20% round trip,
            entry price x 1.001, exit price x 0.999, every trade.
Sizing    : 20% of seed per coin, all-in when long, cash when flat,
            compounded per coin. Portfolio = mean of the 5 coin equities.
Grid (12) : TF in {1h, 4h} x N in {20, 55} x exit in {chan, atr2, atr3}.
            SMA50-daily filter, ATR14 and the channel-exit lengths are fixed.
Selection : on TRAIN only. Highest TRAIN portfolio return among combos with
            >= 15 TRAIN trades (all coins together); tie -> smaller TRAIN MDD.
            The same combo is used for all 5 coins. TEST is then reported
            untouched for the chosen combo, plus all 12 combos for sensitivity.
Periods   : common window [ps, pe) where ps = latest first-bar time of the 5
            coins rounded up to the hour, pe = earliest last-bar time + 5m.
            TRAIN = [ps, 2026-06-21 00:00 UTC), TEST = [2026-06-21, pe),
            FULL = [ps, pe). Each period is simulated on its own: it starts
            flat, entries must fill inside the period, an open position is
            closed at the last 5m close of the period (with cost). Indicators
            use all history before each bar (past data only).
Quarters  : FULL split at 2026-01-21, 2026-04-21, 2026-07-21 (00:00 UTC).
Diagnostic (NOT used for selection): chosen combo without the SMA50 filter.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
COIN_DIR = os.path.dirname(os.path.dirname(HERE))
CANDLES = os.path.join(COIN_DIR, "candles")
MARKETS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]
SPLIT = np.datetime64("2026-06-21T00:00:00", "ns")
QUARTER_CUTS = [np.datetime64(x, "ns") for x in ("2026-01-21T00:00:00", "2026-04-21T00:00:00", "2026-07-21T00:00:00")]
C = 0.001  # per side
TFS = {"1h": "1h", "4h": "4h"}
NS = [20, 55]
EXITS = ["chan", "atr2", "atr3"]
CHAN_EXIT = {20: 10, 55: 20}
KATR = {"atr2": 2.0, "atr3": 3.0}
DAILY_MA = 50
ATR_N = 14
MIN_TRAIN_TRADES = 15
FIVE_MIN = np.timedelta64(5, "m").astype("timedelta64[ns]")


def combos():
    return [(tf, n, ex) for tf in TFS for n in NS for ex in EXITS]


def cname(c):
    tf, n, ex = c
    return f"{tf}_N{n}_{ex}"


class Coin:
    def __init__(self, market):
        rows = json.load(open(os.path.join(CANDLES, f"{market}_5m.json"), encoding="utf-8"))
        df = pd.DataFrame(rows)
        df["t"] = pd.to_datetime(df["t"])
        n0 = len(df)
        df = df.drop_duplicates("t").sort_values("t").reset_index(drop=True)
        self.dups = n0 - len(df)
        self.m = market
        self.t = df["t"].values.astype("datetime64[ns]")
        self.o = df["o"].values.astype(float)
        self.h = df["h"].values.astype(float)
        self.l = df["l"].values.astype(float)
        self.c = df["c"].values.astype(float)
        # daily (UTC day == Upbit 09:00 KST day)
        day = df["t"].dt.floor("1D")
        dclose = df.groupby(day)["c"].last()
        self.day_start = dclose.index.values.astype("datetime64[ns]")
        self.dsma = dclose.rolling(DAILY_MA).mean().values
        self.tf = {}
        pos = np.arange(len(df))
        for name, freq in TFS.items():
            key = df["t"].dt.floor(freq)
            g = pd.DataFrame({"key": key, "o": df["o"], "h": df["h"], "l": df["l"], "c": df["c"], "pos": pos}).groupby("key", sort=True)
            agg = g.agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"), a=("pos", "first"), b=("pos", "last"))
            start = agg.index.values.astype("datetime64[ns]")
            end = start + pd.Timedelta(freq).to_timedelta64().astype("timedelta64[ns]")
            h, l, c = agg["h"], agg["l"], agg["c"]
            pc = c.shift(1)
            tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
            atr = tr.ewm(alpha=1.0 / ATR_N, adjust=False, min_periods=ATR_N).mean()
            didx = np.searchsorted(self.day_start, end - np.timedelta64(1, "D").astype("timedelta64[ns]"), side="right") - 1
            sma = np.where(didx >= 0, self.dsma[np.clip(didx, 0, None)], np.nan)
            T = {
                "start": start, "end": end,
                "h": h.values, "l": l.values, "c": c.values,
                "a": agg["a"].values, "b": agg["b"].values,
                "atr": atr.values, "sma": sma,
                "hh": {n: h.rolling(n).max().shift(1).values for n in NS},
                "ll": {m: l.rolling(m).min().values for m in set(CHAN_EXIT.values())},
            }
            self.tf[name] = T


def simulate(coin, combo, ps, pe, use_filter=True):
    tfname, N, ex = combo
    T = coin.tf[tfname]
    k_ps = int(np.searchsorted(coin.t, ps, "left"))
    k_pe = int(np.searchsorted(coin.t, pe, "left"))
    a, b = T["a"], T["b"]
    hhp, h, c, atr, sma = T["hh"][N], T["h"], T["c"], T["atr"], T["sma"]
    llw = T["ll"][CHAN_EXIT[N]]
    katr = KATR.get(ex)
    j0 = max(int(np.searchsorted(a, k_ps, "left")) - 1, 0)
    j1 = int(np.searchsorted(a, k_pe, "left"))  # bars j < j1 start before pe
    L, O = coin.l, coin.o
    trades = []
    in_pos = False
    ek = epx = stop = hh = None
    for j in range(j0, j1):
        if in_pos:
            lo, hi = a[j], min(b[j], k_pe - 1)
            hit = np.flatnonzero(L[lo:hi + 1] <= stop)
            if hit.size:
                k = lo + int(hit[0])
                trades.append((ek, epx, k, min(O[k], stop), "stop"))
                in_pos = False
            elif katr is not None:
                hh = max(hh, h[j])
                stop = max(stop, hh - katr * atr[j])
            else:
                stop = llw[j]
        if not in_pos and j + 1 < j1:
            nk = a[j + 1]
            if nk < k_ps or np.isnan(hhp[j]) or np.isnan(atr[j]) or np.isnan(llw[j]):
                continue
            if c[j] <= hhp[j]:
                continue
            if use_filter and (np.isnan(sma[j]) or c[j] <= sma[j]):
                continue
            in_pos = True
            ek, epx = int(nk), O[nk]
            if katr is not None:
                hh = h[j]
                stop = hh - katr * atr[j]
            else:
                stop = llw[j]
    if in_pos:
        k = k_pe - 1
        trades.append((ek, epx, k, coin.c[k], "end"))
    return trades, k_ps, k_pe


def coin_equity(coin, trades, k_ps, k_pe):
    """Mark-to-market equity on the coin's own 5m bars in [k_ps, k_pe), start 1.0."""
    n = k_pe - k_ps
    eq = np.empty(n)
    cash, p = 1.0, 0
    for ek, epx, xk, xpx, _ in trades:
        e, x = ek - k_ps, xk - k_ps
        eq[p:e] = cash
        units = cash / (epx * (1 + C))
        eq[e:x] = units * coin.c[ek:xk]
        cash = units * xpx * (1 - C)
        p = x
    eq[p:] = cash
    return eq


def to_grid(coin, eq, k_ps, grid):
    pos = np.searchsorted(coin.t[k_ps:k_ps + len(eq)], grid, "right") - 1
    return np.where(pos >= 0, eq[np.clip(pos, 0, None)], 1.0)


def mdd(eq):
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    return float((eq / peak - 1).min() * 100)


def run(coins, combo, ps, pe, use_filter=True, quarters=False):
    grid = np.arange(ps, pe, FIVE_MIN)
    span = (pe - ps) / np.timedelta64(1, "ns")
    per, eqs, all_tr, tim = {}, [], [], []
    for cn in coins:
        tr, k_ps, k_pe = simulate(cn, combo, ps, pe, use_filter)
        eq = coin_equity(cn, tr, k_ps, k_pe)
        rets = [(x * (1 - C)) / (e * (1 + C)) - 1 for _, e, _, x, _ in tr]
        all_tr += rets
        per[cn.m] = {"ret": float((eq[-1] - 1) * 100), "trades": len(tr), "mdd": mdd(eq)}
        tim.append(sum((cn.t[xk] - cn.t[ek]) / np.timedelta64(1, "ns") for ek, _, xk, _, _ in tr) / span)
        eqs.append(to_grid(cn, eq, k_ps, grid))
    port = np.mean(eqs, axis=0)
    out = {
        "ret": float((port[-1] - 1) * 100),
        "mdd": mdd(port),
        "trades": len(all_tr),
        "win": float(np.mean([r > 0 for r in all_tr]) * 100) if all_tr else None,
        "avg": float(np.mean(all_tr) * 100) if all_tr else None,
        "tim": float(np.mean(tim) * 100),
        "coins": per,
    }
    if quarters:
        out["q"] = quarter_returns(grid, port, ps, pe)
    return out


def quarter_returns(grid, port, ps, pe):
    cuts = [ps] + QUARTER_CUTS + [pe]
    vals = []
    for cut in cuts:
        i = int(np.searchsorted(grid, cut, "left")) - 1  # last 5m bar that closes at or before cut
        vals.append(1.0 if i < 0 else float(port[i]))
    return [(vals[i + 1] / vals[i] - 1) * 100 for i in range(4)]


def buy_hold(coins, ps, pe, quarters=False):
    grid = np.arange(ps, pe, FIVE_MIN)
    per, eqs = {}, []
    for cn in coins:
        k_ps = int(np.searchsorted(cn.t, ps, "left"))
        k_pe = int(np.searchsorted(cn.t, pe, "left"))
        eq = cn.c[k_ps:k_pe] / (cn.o[k_ps] * (1 + C))
        eq[-1] *= (1 - C)
        per[cn.m] = {"ret": float((eq[-1] - 1) * 100), "trades": 1, "mdd": mdd(eq)}
        eqs.append(to_grid(cn, eq, k_ps, grid))
    port = np.mean(eqs, axis=0)
    out = {"ret": float((port[-1] - 1) * 100), "mdd": mdd(port), "trades": 5, "tim": 100.0, "coins": per}
    if quarters:
        out["q"] = quarter_returns(grid, port, ps, pe)
    return out


def fmt(r):
    w = "  n/a" if r.get("win") is None else f"{r['win']:5.1f}"
    a = "   n/a" if r.get("avg") is None else f"{r['avg']:+6.2f}"
    return f"ret {r['ret']:+7.2f}%  mdd {r['mdd']:+7.2f}%  trades {r['trades']:4d}  win {w}%  avg {a}%  tim {r['tim']:5.1f}%"


def coins_line(r):
    return "  ".join(f"{m.split('-')[1]} {v['ret']:+6.1f}" for m, v in r["coins"].items())


def main():
    coins = [Coin(m) for m in MARKETS]
    first = max(cn.t[0] for cn in coins)
    hour = np.timedelta64(1, "h").astype("timedelta64[ns]")
    ps = (first + hour - np.timedelta64(1, "ns")).astype("datetime64[h]").astype("datetime64[ns]")
    pe = min(cn.t[-1] for cn in coins) + FIVE_MIN
    print(f"window {ps} .. {pe} (exclusive); split {SPLIT}")
    for cn in coins:
        exp = int((cn.t[-1] - cn.t[0]) / FIVE_MIN) + 1
        print(f"  {cn.m:9s} bars {len(cn.t)} missing {exp - len(cn.t)} dups {cn.dups} first {cn.t[0]} last {cn.t[-1]}")
    periods = {"TRAIN": (ps, SPLIT), "TEST": (SPLIT, pe), "FULL": (ps, pe)}

    res = {}
    for combo in combos():
        res[cname(combo)] = {p: run(coins, combo, a, b, quarters=(p == "FULL")) for p, (a, b) in periods.items()}
    bh = {p: buy_hold(coins, a, b, quarters=(p == "FULL")) for p, (a, b) in periods.items()}

    print("\n== TRAIN (selection) ==")
    for k, v in res.items():
        print(f"  {k:14s} {fmt(v['TRAIN'])}")
    ok = [k for k, v in res.items() if v["TRAIN"]["trades"] >= MIN_TRAIN_TRADES]
    chosen = sorted(ok, key=lambda k: (-res[k]["TRAIN"]["ret"], -res[k]["TRAIN"]["mdd"]))[0]
    print(f"\nCHOSEN on TRAIN: {chosen}")

    print("\n== TEST (all combos; sensitivity, not used for selection) ==")
    for k, v in res.items():
        tag = " <== chosen" if k == chosen else ""
        print(f"  {k:14s} {fmt(v['TEST'])}{tag}")

    ctf, cn_, cex = next(c for c in combos() if cname(c) == chosen)
    neigh = [cname(c) for c in combos() if sum(x != y for x, y in zip(c, (ctf, cn_, cex))) == 1]
    print("\nneighbours of chosen (differ in one dimension), TEST return:")
    for k in neigh:
        print(f"  {k:14s} TEST {res[k]['TEST']['ret']:+7.2f}%  TRAIN {res[k]['TRAIN']['ret']:+7.2f}%")

    print("\n== CHOSEN combo detail ==")
    for p in periods:
        r = res[chosen][p]
        print(f"  {p:5s} {fmt(r)}")
        print(f"        per coin: {coins_line(r)}")
    print(f"  FULL quarters: " + " ".join(f"{q:+6.2f}%" for q in res[chosen]["FULL"]["q"]))

    print("\n== Equal-weight buy and hold ==")
    for p in periods:
        r = bh[p]
        print(f"  {p:5s} ret {r['ret']:+7.2f}%  mdd {r['mdd']:+7.2f}%   per coin: {coins_line(r)}")
    print(f"  FULL quarters: " + " ".join(f"{q:+6.2f}%" for q in bh["FULL"]["q"]))
    print("  cash: 0.00% every period")

    combo = (ctf, cn_, cex)
    abl = {p: run(coins, combo, a, b, use_filter=False, quarters=(p == "FULL")) for p, (a, b) in periods.items()}
    print("\n== DIAGNOSTIC (not used for selection): chosen combo WITHOUT SMA50-daily filter ==")
    for p in periods:
        print(f"  {p:5s} {fmt(abl[p])}   per coin: {coins_line(abl[p])}")

    out = {"window": [str(ps), str(pe)], "split": str(SPLIT), "chosen": chosen, "neighbours": neigh,
           "results": res, "buy_hold": bh, "diag_no_filter": abl}
    with open(os.path.join(HERE, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(f"\nsaved {os.path.join(HERE, 'results.json')}")


if __name__ == "__main__":
    sys.exit(main())
