"""
VBO family (Larry Williams volatility breakout, Korean-crypto variants) -- walk-forward research.

PRE-REGISTRATION (fixed before any result was looked at)
-------------------------------------------------------
Universe: KRW-BTC, KRW-ETH, KRW-XRP, KRW-SOL, KRW-DOGE (Upbit spot, long-only, no leverage).
Day d = 00:00..24:00 UTC (Upbit daily candle, 09:00 KST). Daily OHLC is built from the 5m bars of
that UTC day (missing 5m bars are simply absent; open = first available bar's open, etc.).

Rule, evaluated at 00:00 UTC of day d using only CLOSED days d-1, d-2, ... and today's open:
    range_{d-1} = high_{d-1} - low_{d-1}
    k_d         = fixed k, or "noise20" = mean over the 20 closed days d-20..d-1 of 1 - |C-O|/(H-L)
    target_d    = open_d + k_d * range_{d-1}
    filter      = open_d > SMA_N(daily close) over closed days d-N..d-1
If the filter passes, a resting BUY-STOP order is placed at target_d for day d.
    Entry fill  = on the FIRST 5m bar of day d whose high >= target_d, at max(target_d, that bar's open)
                  (a gap through the stop fills at the bar open, i.e. worse).
    Exit        = market sell at the OPEN of the first 5m bar at/after 00:00 UTC of day d+1.
                  (A position still open at the end of the data is liquidated at the last close.)
    Sizing      = 100% of the coin's sleeve (headline).
    Cost        = 0.05% fee + 0.05% slippage per side, i.e. fill*(1+0.001) on buy, exit*(1-0.001) on sell
                  (~0.20% per round trip), applied to every trade.
At most one trade per coin per day.

Grid (12 combos): k in {0.3, 0.5, 0.7, noise20} x N in {3, 5, 10}.
Warm-up: all combos start trading on the same day (data day index 21, so noise20 has 20 full closed days;
the first data day 2025-10-21 is partial and is never used as "yesterday" for a trade).
Selection: the single combo with the highest TRAIN portfolio return (mean of the 5 coins' compounded
returns), same combo for all 5 coins. TEST is then reported untouched.
TRAIN = trades whose entry day < 2026-06-21 (their exits are <= 2026-06-21 00:00 UTC), TEST = entry day >= 2026-06-21.

Informational variants of the chosen combo (fixed parameters, NOT used for selection, reported for
TRAIN and TEST so they can be judged on TRAIN):
    V1 vol-target sizing: fraction = min(1, 0.02 / (range_{d-1} / close_{d-1}))   (target 2% daily move)
    V2 BTC regime filter: additionally require KRW-BTC open_d > KRW-BTC SMA_N(close) (same N)
    V3 intraday stop at today's open: after entry, exit if price trades back to open_d
       (entry bar: stop only if the bar CLOSES <= stop, fill at stop; later bars: if bar open <= stop
        fill at bar open, elif low <= stop fill at stop).

Portfolio: 20% of the seed per coin, cash when flat, compounded per coin, no rebalancing.
Portfolio equity = mean of the 5 sleeve equities, marked to market at every 5m close on a common
5-minute grid (forward-filled closes; marking includes the exit-side cost).
"""
import json
import os
import sys

import numpy as np
import pandas as pd

BASE = r"C:\Users\변기국~1\AppData\Local\Temp\claude\C--dev\93ae6530-93fd-4894-8774-b698a96bffc9\scratchpad\coin"
MARKETS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]
SPLIT = pd.Timestamp("2026-06-21T00:00:00")
CS = 0.001  # cost per side (fee 0.05% + slippage 0.05%)
WARMUP_DAY_IDX = 21
K_GRID = [0.3, 0.5, 0.7, "noise20"]
N_GRID = [3, 5, 10]
QUARTER_BOUNDS = [pd.Timestamp(x) for x in
                  ["2025-10-21", "2026-01-21", "2026-04-21", "2026-07-21", "2026-10-22"]]


# ----------------------------------------------------------------------------------------- data
def load(market):
    with open(os.path.join(BASE, "candles", f"{market}_5m.json"), encoding="utf-8") as f:
        rows = json.load(f)
    df = pd.DataFrame(rows)
    df["t"] = pd.to_datetime(df["t"])
    df = df.sort_values("t").drop_duplicates("t").reset_index(drop=True)
    return df


class Coin:
    def __init__(self, market, df):
        self.market = market
        self.t = df["t"].values.astype("datetime64[ns]")
        self.o = df["o"].values.astype(float)
        self.h = df["h"].values.astype(float)
        self.l = df["l"].values.astype(float)
        self.c = df["c"].values.astype(float)
        day = df["t"].dt.floor("D")
        g = pd.DataFrame({"day": day, "i": np.arange(len(df))}).groupby("day")["i"]
        first = g.min()
        last = g.max()
        self.days = first.index.values.astype("datetime64[ns]")
        self.first = first.values
        self.last = last.values
        self.D_o = self.o[self.first]
        self.D_c = self.c[self.last]
        self.D_h = np.array([self.h[a:b + 1].max() for a, b in zip(self.first, self.last)])
        self.D_l = np.array([self.l[a:b + 1].min() for a, b in zip(self.first, self.last)])
        rng = self.D_h - self.D_l
        with np.errstate(divide="ignore", invalid="ignore"):
            noise = np.where(rng > 0, 1.0 - np.abs(self.D_c - self.D_o) / rng, 1.0)
        self.noise = noise
        self.day_index = {pd.Timestamp(d): j for j, d in enumerate(self.days)}

    def sma_prev(self, j, n):
        """SMA of closes of closed days j-n..j-1."""
        return self.D_c[j - n:j].mean()


# ----------------------------------------------------------------------------------- simulation
def simulate(coin, k_mode, n, sizing="full", btc=None, stop_mode=None):
    """Return list of trades: dict(entry_day, i_in, i_out, fill, exit, frac, ret)."""
    trades = []
    nd = len(coin.days)
    for j in range(WARMUP_DAY_IDX, nd):
        rng_prev = coin.D_h[j - 1] - coin.D_l[j - 1]
        if k_mode == "noise20":
            k = coin.noise[j - 20:j].mean()
        else:
            k = float(k_mode)
        o_d = coin.D_o[j]
        target = o_d + k * rng_prev
        if not (o_d > coin.sma_prev(j, n)):
            continue
        if btc is not None:
            jb = btc.day_index.get(pd.Timestamp(coin.days[j]))
            if jb is None or jb < n or not (btc.D_o[jb] > btc.sma_prev(jb, n)):
                continue
        a, b = coin.first[j], coin.last[j]
        hit = np.nonzero(coin.h[a:b + 1] >= target)[0]
        if len(hit) == 0:
            continue
        i_in = a + hit[0]
        fill = max(target, coin.o[i_in])
        if sizing == "voltarget":
            rel = rng_prev / coin.D_c[j - 1]
            frac = 1.0 if rel <= 0 else min(1.0, 0.02 / rel)
        else:
            frac = 1.0
        i_out, px_out, how = None, None, None
        if stop_mode == "dayopen":
            stop = o_d
            if coin.c[i_in] <= stop:
                i_out, px_out, how = i_in, stop, "stop"
            else:
                for i in range(i_in + 1, b + 1):
                    if coin.o[i] <= stop:
                        i_out, px_out, how = i, coin.o[i], "stop"
                        break
                    if coin.l[i] <= stop:
                        i_out, px_out, how = i, stop, "stop"
                        break
        if i_out is None:
            if j + 1 < nd:
                i_out = coin.first[j + 1]
                px_out, how = coin.o[i_out], "nextopen"
            else:  # end of data: liquidate at last close
                i_out = len(coin.c) - 1
                px_out, how = coin.c[i_out], "eod"
        ret = px_out * (1 - CS) / (fill * (1 + CS)) - 1.0
        trades.append(dict(entry_day=pd.Timestamp(coin.days[j]), i_in=i_in, i_out=i_out, fill=fill, target=target,
                           exit=px_out, frac=frac, ret=ret, how=how,
                           t_in=coin.t[i_in], t_out=coin.t[i_out]))
    return trades


# ------------------------------------------------------------------------------- equity on grid
class Grid:
    def __init__(self, coins):
        t0 = min(c.t[0] for c in coins.values())
        t1 = max(c.t[-1] for c in coins.values())
        self.t = np.arange(t0, t1 + np.timedelta64(5, "m"), np.timedelta64(5, "m"))
        self.close = {}
        for m, c in coins.items():
            s = pd.Series(c.c, index=c.t).reindex(self.t).ffill()
            s = s.fillna(c.o[0])
            self.close[m] = s.values
        self.pos = {m: np.searchsorted(self.t, c.t) for m, c in coins.items()}  # coin bar idx -> grid idx

    def span(self, T0, T1):
        g0 = int(np.searchsorted(self.t, np.datetime64(T0)))
        g1 = int(np.searchsorted(self.t, np.datetime64(T1)))
        return g0, g1


def sleeve_equity(grid, market, trades, g0, g1):
    """Mark-to-market equity of one sleeve over grid[g0:g1], start 1.0."""
    G = g1 - g0
    eq = np.empty(G)
    cl = grid.close[market][g0:g1]
    gp = grid.pos[market]
    cur, p = 1.0, 0
    for tr in trades:
        gi0 = gp[tr["i_in"]] - g0
        gi1 = gp[tr["i_out"]] - g0
        if tr["how"] == "eod":
            gi1 = G - 1
        gi0 = max(gi0, 0)
        gi1 = min(gi1, G - 1)
        eq[p:gi0] = cur
        f = tr["frac"]
        eq[gi0:gi1] = cur * (1 - f) + cur * f * cl[gi0:gi1] * (1 - CS) / (tr["fill"] * (1 + CS))
        cur = cur * (1 + f * tr["ret"])
        p = gi1
    eq[p:] = cur
    return eq


def mdd(eq):
    peak = np.maximum.accumulate(eq)
    return float((eq / peak - 1).min())


def period_report(grid, coins, all_trades, T0, T1):
    g0, g1 = grid.span(T0, T1)
    span_ns = (grid.t[g1 - 1] - grid.t[g0]).astype("timedelta64[ns]").astype(float) + 5 * 60e9
    eqs, per_coin, trades_all, tim = {}, {}, [], []
    for m in coins:
        tr = [x for x in all_trades[m] if T0 <= x["entry_day"] < T1]
        eq = sleeve_equity(grid, m, tr, g0, g1)
        eqs[m] = eq
        per_coin[m] = dict(ret=eq[-1] - 1, mdd=mdd(eq), n=len(tr))
        trades_all += tr
        inmk = sum((x["t_out"] - x["t_in"]).astype("timedelta64[ns]").astype(float) for x in tr)
        tim.append(inmk / span_ns)
    port = np.mean([eqs[m] for m in coins], axis=0)
    rets = np.array([x["ret"] for x in trades_all]) if trades_all else np.array([])
    return dict(
        ret=float(np.mean([per_coin[m]["ret"] for m in coins])),
        port_end=float(port[-1] - 1),
        mdd=mdd(port),
        n=len(trades_all),
        win=float((rets > 0).mean()) if len(rets) else float("nan"),
        avg=float(rets.mean()) if len(rets) else float("nan"),
        tim=float(np.mean(tim)),
        per_coin=per_coin,
        port_eq=port,
        g0=g0,
    )


def buyhold(grid, coins, T0, T1):
    g0, g1 = grid.span(T0, T1)
    eqs, per = [], {}
    for m, c in coins.items():
        # start price: first open at/after T0; end: last close before T1
        i0 = int(np.searchsorted(c.t, np.datetime64(T0)))
        i1 = int(np.searchsorted(c.t, np.datetime64(T1))) - 1
        p0 = c.o[i0]
        cl = grid.close[m][g0:g1]
        eq = cl / p0
        eqs.append(eq)
        per[m] = c.c[i1] / p0 - 1
    port = np.mean(eqs, axis=0)
    return dict(ret=float(np.mean(list(per.values()))), mdd=mdd(port), per_coin=per)


def quarters(rep, grid):
    port = rep["port_eq"]
    g0 = rep["g0"]
    out = []
    for qa, qb in zip(QUARTER_BOUNDS[:-1], QUARTER_BOUNDS[1:]):
        a = max(int(np.searchsorted(grid.t, np.datetime64(qa))) - g0, 0)
        b = min(int(np.searchsorted(grid.t, np.datetime64(qb))) - g0, len(port))
        start_val = 1.0 if a == 0 else port[a - 1]
        out.append(port[b - 1] / start_val - 1)
    return out


def bh_quarters(grid, coins):
    T0, T1 = QUARTER_BOUNDS[0], QUARTER_BOUNDS[-1]
    g0, g1 = grid.span(T0, T1)
    eqs = []
    for m, c in coins.items():
        eqs.append(grid.close[m][g0:g1] / c.o[0])
    port = np.mean(eqs, axis=0)
    out = []
    for qa, qb in zip(QUARTER_BOUNDS[:-1], QUARTER_BOUNDS[1:]):
        a = max(int(np.searchsorted(grid.t, np.datetime64(qa))) - g0, 0)
        b = min(int(np.searchsorted(grid.t, np.datetime64(qb))) - g0, len(port))
        start_val = 1.0 if a == 0 else port[a - 1]
        out.append(port[b - 1] / start_val - 1)
    return out


def pct(x):
    return f"{100 * x:+.2f}%"


def main():
    coins = {m: Coin(m, load(m)) for m in MARKETS}
    grid = Grid(coins)
    T_START = pd.Timestamp(str(grid.t[0])).floor("D")
    T_END = pd.Timestamp(str(grid.t[-1])) + pd.Timedelta(minutes=5)
    periods = {"TRAIN": (T_START, SPLIT), "TEST": (SPLIT, T_END), "FULL": (T_START, T_END)}

    print("data:", str(grid.t[0]), "->", str(grid.t[-1]), "grid bars", len(grid.t))
    for m, c in coins.items():
        exp = int((c.t[-1] - c.t[0]) / np.timedelta64(5, "m")) + 1
        print(f"  {m}: bars {len(c.t)} (missing {exp - len(c.t)}), days {len(c.days)}, "
              f"first trade day {str(c.days[WARMUP_DAY_IDX])[:10]}")

    bh = {k: buyhold(grid, coins, *v) for k, v in periods.items()}
    print("\nBUY & HOLD (equal weight, no rebalance)")
    for k in periods:
        print(f"  {k:5s} ret {pct(bh[k]['ret'])}  mdd {pct(bh[k]['mdd'])}  per-coin " +
              ", ".join(f"{m[4:]} {pct(v)}" for m, v in bh[k]["per_coin"].items()))
    print("  FULL quarters:", [pct(x) for x in bh_quarters(grid, coins)])

    # ---------------------------------------------------------------- grid
    results = {}
    for k_mode in K_GRID:
        for n in N_GRID:
            tr = {m: simulate(coins[m], k_mode, n) for m in MARKETS}
            results[(k_mode, n)] = {p: period_report(grid, coins, tr, *periods[p]) for p in periods}
            results[(k_mode, n)]["trades"] = tr

    print("\nGRID (all 12 pre-registered combos; selection uses TRAIN column only)")
    print(f"  {'k':>8s} {'N':>3s} | {'TRAIN ret':>10s} {'mdd':>8s} {'n':>4s} | {'TEST ret':>10s} {'mdd':>8s} {'n':>4s} | {'FULL ret':>10s}")
    for (k_mode, n), r in results.items():
        print(f"  {str(k_mode):>8s} {n:3d} | {pct(r['TRAIN']['ret']):>10s} {pct(r['TRAIN']['mdd']):>8s} {r['TRAIN']['n']:4d} | "
              f"{pct(r['TEST']['ret']):>10s} {pct(r['TEST']['mdd']):>8s} {r['TEST']['n']:4d} | {pct(r['FULL']['ret']):>10s}")

    best = max(results, key=lambda key: results[key]["TRAIN"]["ret"])
    print(f"\nCHOSEN ON TRAIN: k={best[0]}, N={best[1]}  (TRAIN ret {pct(results[best]['TRAIN']['ret'])})")

    def show(label, r):
        print(f"\n== {label}")
        for p in periods:
            x = r[p]
            print(f"  {p:5s} ret {pct(x['ret'])} (port-end {pct(x['port_end'])})  mdd {pct(x['mdd'])}  trades {x['n']}  "
                  f"win {100 * x['win']:.1f}%  avg/trade {pct(x['avg'])}  time-in-mkt {100 * x['tim']:.1f}%")
            print("        per-coin: " + ", ".join(
                f"{m[4:]} {pct(v['ret'])} (mdd {pct(v['mdd'])}, n={v['n']})" for m, v in x["per_coin"].items()))
        print("  FULL quarters:", [pct(q) for q in quarters(r["FULL"], grid)])

    show(f"CHOSEN k={best[0]} N={best[1]}", results[best])

    # neighbours in the grid
    ki = K_GRID.index(best[0])
    ni = N_GRID.index(best[1])
    print("\nNEIGHBOURS (TEST return / TRAIN return)")
    for dk, dn in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]:
        a, b = ki + dk, ni + dn
        if 0 <= a < len(K_GRID) and 0 <= b < len(N_GRID):
            key = (K_GRID[a], N_GRID[b])
            print(f"  k={key[0]} N={key[1]}: TEST {pct(results[key]['TEST']['ret'])}  TRAIN {pct(results[key]['TRAIN']['ret'])}")
    tests = np.array([r["TEST"]["ret"] for r in results.values()])
    print(f"  all 12 combos TEST: median {pct(np.median(tests))}, min {pct(tests.min())}, max {pct(tests.max())}, "
          f"#>0: {(tests > 0).sum()}/12")

    # exits breakdown, trades in TEST per coin
    trs = results[best]["trades"]
    print("\nTEST trades per coin (chosen):",
          {m[4:]: sum(1 for x in trs[m] if x["entry_day"] >= SPLIT) for m in MARKETS})
    gaps = sum(1 for m in MARKETS for x in trs[m] if coins[m].o[x["i_in"]] > x["target"])
    print("entries filled at bar open (gap through stop) over full year:", gaps,
          "of", sum(len(trs[m]) for m in MARKETS))

    # ---------------------------------------------------------- informational variants (not selected on)
    k_b, n_b = best
    variants = {
        "V1 voltarget 2%": dict(sizing="voltarget"),
        "V2 +BTC>SMA_N filter": dict(btc=coins["KRW-BTC"]),
        "V3 stop at day open": dict(stop_mode="dayopen"),
    }
    for name, kw in variants.items():
        tr = {m: simulate(coins[m], k_b, n_b, **kw) for m in MARKETS}
        r = {p: period_report(grid, coins, tr, *periods[p]) for p in periods}
        show(f"{name} (k={k_b}, N={n_b}) -- informational, not used for selection", r)


if __name__ == "__main__":
    main()
