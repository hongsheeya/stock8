"""Family "meanrev": long-only spot mean reversion on Upbit KRW markets.

PRE-REGISTRATION (written before any backtest was run; do not edit after):

Bars      : 5m Upbit candles aggregated into UTC-clock TF buckets (15m or 1h).
            A TF bar is closed at bucket end; signals use only closed TF bars.
            Any order fills at the OPEN of the first 5m bar at/after the
            signal bar's close time (missing 5m bars -> next available bar).
Indicators: on TF closes: SMA20, population std20, lower band = SMA20 - k*std20,
            ATR14 (Wilder) on TF bars.
            Daily regime (higher TF): UTC-day closes (Upbit day = 09:00 KST);
            "up" if the last COMPLETED day's close > SMA of the last 20
            completed daily closes.
Entry     : flat, and the TF bar closes below the lower band after the previous
            TF bar closed at/above its lower band (fresh cross), and
            (regime == "none" or regime "d20" is up). Buy at next open.
Exits     : (1) mean reversion: a TF bar closes >= SMA20 -> sell next open
            (2) hard stop: stop = fill price - 4 * ATR14(TF, signal bar),
                watched on 5m bars after the fill; a 5m bar opening at/below
                the stop fills at that open, otherwise a 5m low <= stop fills
                at the stop price
            (3) time stop: still open at the close of the 48th TF bar after
                the signal bar -> sell next open
            (4) end of evaluation window: sell at the window's last 5m close.
Costs     : 0.10% per side (0.05% fee + 0.05% slippage) -> ~0.20% round trip.
Sizing    : 20% of the seed per coin, all-in on that sleeve when long, cash
            when flat; each sleeve compounds on its own. Portfolio equity =
            mean of the 5 sleeve equities (marked at 5m close net of exit cost).
GRID (12) : TF in {15m, 1h} x k in {1.5, 2.0, 2.5} x regime in {none, d20}.
Selection : on TRAIN only (bars before 2026-06-21T00:00Z): among combos whose
            mean trades per coin on TRAIN >= 20 (~30/yr pace), take the highest
            TRAIN portfolio return (tie -> smaller TRAIN MDD). If none
            qualifies, take the highest TRAIN return and flag it. Same combo
            for all 5 coins. TEST (from 2026-06-21T00:00Z) reported untouched.
Windows   : indicators are causal and computed on the whole series, so TEST
            uses earlier bars only as warm-up; each window is simulated
            separately (entries only from signals whose close time is inside
            the window, forced exit at window end). Full year = one run.

POST-HOC ROBUSTNESS (added AFTER the first run, NOT part of the pre-registration):
  `--spread` additionally charges half an Upbit price tick per side (buy at
  open + tick/2, sell at fill - tick/2) on top of the 0.20%. Reason found in
  the first run: KRW-DOGE trades on a 1 KRW tick at ~100-300 KRW (0.3-1.0% per
  tick), so trade-price candles bounce between bid and ask and a short-bar
  mean-reversion rule books a fake edge. Tick table inferred from the data:
  >=2,000,000: 1000 | >=100,000: 100 | >=10,000: 50 | >=100: 1 | <100: 0.01.
  Under --spread the same TRAIN-only selection rule is re-applied and flagged.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CANDLES = os.path.normpath(os.path.join(HERE, "..", "..", "candles"))
COINS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]
SPLIT = pd.Timestamp("2026-06-21T00:00:00")
SIDE = 0.001          # 0.05% fee + 0.05% slippage per side
STOP_ATR = 4.0
TIME_STOP = 48
BB_N = 20
ATR_N = 14
D_SMA = 20
MIN_TRAIN_TRADES_PER_COIN = 20
GRID = [(tf, k, rg) for tf in ("15min", "1h") for k in (1.5, 2.0, 2.5) for rg in ("none", "d20")]
QUARTER_CUTS = [pd.Timestamp("2026-01-21"), pd.Timestamp("2026-04-21"), pd.Timestamp("2026-07-21")]
FIVE = pd.Timedelta(minutes=5)
SPREAD = "--spread" in sys.argv


def half_tick(p):
    if not SPREAD:
        return 0.0
    if p >= 2_000_000: t = 1000.0
    elif p >= 100_000: t = 100.0
    elif p >= 10_000: t = 50.0
    elif p >= 100: t = 1.0
    else: t = 0.01
    return t / 2


def load(m):
    df = pd.DataFrame(json.load(open(os.path.join(CANDLES, f"{m}_5m.json"))))
    df["t"] = pd.to_datetime(df["t"])
    return df.sort_values("t").reset_index(drop=True)


class Coin:
    def __init__(self, m):
        self.m = m
        df = load(m)
        self.t = df["t"].values.astype("datetime64[ns]")
        self.o = df["o"].values; self.h = df["h"].values
        self.l = df["l"].values; self.c = df["c"].values
        self.end = self.t[-1] + np.timedelta64(5, "m")
        # daily regime (completed UTC days only)
        d = df.groupby(df["t"].dt.floor("D"))["c"].last()
        sma = d.rolling(D_SMA).mean()
        self.day_end = (d.index + pd.Timedelta(days=1)).values.astype("datetime64[ns]")
        self.day_up = ((d > sma) & sma.notna()).values
        self.day_valid = sma.notna().values
        self.df = df
        self.tf = {}

    def tf_bars(self, tf):
        if tf in self.tf:
            return self.tf[tf]
        df = self.df
        g = df.groupby(df["t"].dt.floor(tf))
        b = pd.DataFrame({"o": g["o"].first(), "h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last()})
        start = b.index.values.astype("datetime64[ns]")
        close_t = (b.index + pd.Timedelta(tf)).values.astype("datetime64[ns]")
        keep = close_t <= self.end            # drop an unfinished last bucket
        b = b[keep]; start = start[keep]; close_t = close_t[keep]
        c = b["c"]
        sma = c.rolling(BB_N).mean()
        sd = c.rolling(BB_N).std(ddof=0)
        prev_c = c.shift(1)
        tr = pd.concat([b["h"] - b["l"], (b["h"] - prev_c).abs(), (b["l"] - prev_c).abs()], axis=1).max(axis=1)
        tr.iloc[0] = b["h"].iloc[0] - b["l"].iloc[0]
        atr = tr.ewm(alpha=1.0 / ATR_N, adjust=False).mean()
        atr.iloc[:ATR_N] = np.nan
        # regime state at each TF close: last day with day_end <= close_t
        di = np.searchsorted(self.day_end, close_t, side="right") - 1
        up = np.where(di >= 0, self.day_up[np.clip(di, 0, None)], False)
        res = dict(start=start, close_t=close_t, c=c.values, sma=sma.values, sd=sd.values, atr=atr.values,
                   s5=np.searchsorted(self.t, start, "left"), e5=np.searchsorted(self.t, close_t, "left"), up=up)
        self.tf[tf] = res
        return res


def simulate(coin, tf, k, rg, ws, we):
    """Simulate one coin sleeve in window [ws, we). Returns trades, times, equity, time-in-market fraction."""
    B = coin.tf_bars(tf)
    t5, o5, l5, c5 = coin.t, coin.o, coin.l, coin.c
    ws64, we64 = np.datetime64(ws), np.datetime64(we)
    w0 = np.searchsorted(t5, ws64, "left"); w1 = np.searchsorted(t5, we64, "left")  # coin 5m bars [w0, w1)
    cB, smaB, atrB, closeT, e5 = B["c"], B["sma"], B["atr"], B["close_t"], B["e5"]
    lower = smaB - k * B["sd"]
    nB = len(cB)
    # entry signal on closed TF bar i (NaN comparisons are False -> warm-up excluded)
    sig = np.zeros(nB, dtype=bool)
    sig[1:] = (cB[1:] < lower[1:]) & (cB[:-1] >= lower[:-1]) & ~np.isnan(atrB[1:])
    if rg == "d20":
        sig &= B["up"]
    sig_idx = np.flatnonzero(sig)
    trades = []
    i_min = np.searchsorted(closeT, ws64, "left")    # signal close time must be >= ws
    while True:
        p = np.searchsorted(sig_idx, i_min, "left")
        if p >= len(sig_idx):
            break
        i = sig_idx[p]
        if closeT[i] > we64:
            break
        j = e5[i]                                     # fill: open of first 5m bar at/after signal close
        if j >= w1:
            break
        p_in = o5[j]
        stop = p_in - STOP_ATR * atrB[i]
        q0 = j                                         # next 5m bar to watch for the stop
        exit_px = xbar = reason = None
        m = i + 1
        while exit_px is None:
            in_win = m < nB and closeT[m] <= we64
            q_end = e5[m] if in_win else w1
            for q in range(q0, q_end):                 # hard stop on 5m bars
                if q > j and o5[q] <= stop:
                    exit_px, xbar, reason = o5[q], q, "stop"; break
                if l5[q] <= stop:
                    exit_px, xbar, reason = stop, q, "stop"; break
            if exit_px is not None:
                break
            q0 = q_end
            if not in_win:                             # window/data end: sell at last close in window
                exit_px, xbar, reason = c5[w1 - 1], w1 - 1, "end"; break
            if cB[m] >= smaB[m] or (m - i) >= TIME_STOP:
                x = e5[m]
                if x >= w1:
                    exit_px, xbar, reason = c5[w1 - 1], w1 - 1, "end"
                else:
                    exit_px, xbar, reason = o5[x], x, ("mean" if cB[m] >= smaB[m] else "time")
                break
            m += 1
        p_in_eff = p_in + half_tick(p_in)
        p_out_eff = exit_px - half_tick(exit_px)
        r = (p_out_eff / p_in_eff) * (1 - SIDE) ** 2 - 1
        trades.append(dict(entry_bar=int(j), exit_bar=int(xbar), signal_t=str(closeT[i])[:19],
                           entry_t=str(t5[j])[:19], exit_t=str(t5[xbar])[:19],
                           p_in=float(p_in_eff), p_out=float(p_out_eff), ret=float(r), reason=reason))
        if reason == "end":
            break
        # flat again: a stop inside TF bar m lets bar m's own close be the next signal;
        # a mean/time exit was decided at bar m's close, so the next candidate is bar m+1
        i_min = m if reason == "stop" else m + 1
    # equity over coin bars [w0, w1), marked at 5m close net of the exit cost
    eq = np.empty(w1 - w0)
    cash = 1.0
    pos = 0
    for tr in trades:
        a, b = tr["entry_bar"] - w0, tr["exit_bar"] - w0
        eq[pos:a] = cash
        units = cash * (1 - SIDE) / tr["p_in"]
        mk = c5[w0 + a:w0 + b]
        eq[a:b] = units * (mk - np.array([half_tick(x) for x in mk])) * (1 - SIDE)
        cash = cash * (1 + tr["ret"])
        eq[b] = cash
        pos = b + 1
    eq[pos:] = cash
    held = sum((t5[tr["exit_bar"]] - t5[tr["entry_bar"]]) / np.timedelta64(1, "s") for tr in trades)
    span = (we64 - max(ws64, t5[0])) / np.timedelta64(1, "s")
    return trades, t5[w0:w1], eq, held / span


def buyhold(coin, ws, we):
    t5, o5, c5 = coin.t, coin.o, coin.c
    w0 = np.searchsorted(t5, np.datetime64(ws), "left"); w1 = np.searchsorted(t5, np.datetime64(we), "left")
    units = (1 - SIDE) / (o5[w0] + half_tick(o5[w0]))
    eq = units * (c5[w0:w1] - np.array([half_tick(x) for x in c5[w0:w1]])) * (1 - SIDE)
    return t5[w0:w1], eq


def portfolio(curves, ws):
    """curves: list of (times, equity). Union grid, forward fill, start at 1."""
    grid = np.unique(np.concatenate([tc for tc, _ in curves]))
    mat = np.ones((len(curves), len(grid)))
    for n, (tc, e) in enumerate(curves):
        idx = np.searchsorted(tc, grid, "right") - 1
        mat[n] = np.where(idx >= 0, e[np.clip(idx, 0, None)], 1.0)
    pe = mat.mean(axis=0)
    return grid, pe


def mdd(pe):
    peak = np.maximum.accumulate(np.concatenate([[1.0], pe]))[1:]
    return float(((pe / peak) - 1).min() * 100)


def run_combo(coins, combo, ws, we):
    tf, k, rg = combo
    curves, per = [], {}
    all_tr = []; tim = []
    for cn in coins:
        tr, tc, eq, tin = simulate(cn, tf, k, rg, ws, we)
        curves.append((tc, eq)); all_tr += tr; tim.append(tin)
        per[cn.m] = dict(ret=round((eq[-1] - 1) * 100, 2), trades=len(tr),
                         win=round(100 * np.mean([x["ret"] > 0 for x in tr]), 1) if tr else None,
                         reasons={r: sum(x["reason"] == r for x in tr) for r in ("mean", "stop", "time", "end")})
    grid, pe = portfolio(curves, ws)
    rets = np.array([x["ret"] for x in all_tr]) if all_tr else np.array([])
    out = dict(combo=f"{tf}/k{k}/{rg}", ret=round((pe[-1] - 1) * 100, 2), mdd=round(mdd(pe), 2), trades=len(all_tr),
               trades_per_coin=len(all_tr) / len(coins),
               win=round(float((rets > 0).mean() * 100), 1) if len(rets) else None,
               avg=round(float(rets.mean() * 100), 3) if len(rets) else None,
               tim=round(float(np.mean(tim) * 100), 1), per_coin=per)
    return out, grid, pe, all_tr


def quarters(grid, pe, ws, we):
    cuts = [np.datetime64(ws)] + [np.datetime64(q) for q in QUARTER_CUTS] + [np.datetime64(we)]
    vals = []
    for c in cuts:
        idx = np.searchsorted(grid, c, "left") - 1
        vals.append(1.0 if idx < 0 else pe[idx])
    vals[-1] = pe[-1]
    return [round((vals[n + 1] / vals[n] - 1) * 100, 2) for n in range(4)]


def main():
    coins = [Coin(m) for m in COINS]
    ws_full = min(pd.Timestamp(c.t[0]) for c in coins)
    we_full = max(pd.Timestamp(c.end) for c in coins)
    W = {"TRAIN": (ws_full, SPLIT), "TEST": (SPLIT, we_full), "FULL": (ws_full, we_full)}
    print("windows:", {k: (str(a), str(b)) for k, (a, b) in W.items()})
    res = {"prereg_grid": [f"{a}/k{b}/{c}" for a, b, c in GRID], "windows": {k: [str(a), str(b)] for k, (a, b) in W.items()}}

    # buy and hold
    res["buyhold"] = {}
    for name, (ws, we) in W.items():
        curves = [buyhold(c, ws, we) for c in coins]
        g, pe = portfolio(curves, ws)
        per = {c.m: round((e[-1] - 1) * 100, 2) for c, (_, e) in zip(coins, curves)}
        q = quarters(g, pe, ws, we) if name == "FULL" else None
        res["buyhold"][name] = dict(ret=round((pe[-1] - 1) * 100, 2), mdd=round(mdd(pe), 2), per_coin=per, quarters=q)
        print(f"BUYHOLD {name:5s} ret {pe[-1]*100-100:+7.2f}% mdd {mdd(pe):+7.2f}% per {per}" + (f" Q {q}" if q else ""))

    # TRAIN over the grid
    print("\n== TRAIN (grid) ==")
    train = {}
    for combo in GRID:
        o, *_ = run_combo(coins, combo, *W["TRAIN"])
        train[o["combo"]] = o
        print(f"{o['combo']:18s} ret {o['ret']:+7.2f}% mdd {o['mdd']:+7.2f}% trades {o['trades']:5d} "
              f"({o['trades_per_coin']:.1f}/coin) win {o['win']}% avg {o['avg']}% tim {o['tim']}%")
    res["train"] = train
    elig = [c for c in train.values() if c["trades_per_coin"] >= MIN_TRAIN_TRADES_PER_COIN]
    flag = not elig
    pool = elig if elig else list(train.values())
    best = sorted(pool, key=lambda x: (-x["ret"], -x["mdd"]))[0]["combo"]
    print(f"\nSELECTED on TRAIN: {best} (eligible combos: {len(elig)}; fallback used: {flag})")
    res["selected"] = best; res["selection_fallback"] = flag
    combo_sel = [cmb for cmb in GRID if f"{cmb[0]}/k{cmb[1]}/{cmb[2]}" == best][0]

    # TEST for every combo (sensitivity), selected highlighted
    print("\n== TEST (all combos, for sensitivity; selection already fixed) ==")
    test = {}
    for combo in GRID:
        o, *_ = run_combo(coins, combo, *W["TEST"])
        test[o["combo"]] = o
        mark = " <== selected" if o["combo"] == best else ""
        print(f"{o['combo']:18s} ret {o['ret']:+7.2f}% mdd {o['mdd']:+7.2f}% trades {o['trades']:5d} win {o['win']}% avg {o['avg']}% tim {o['tim']}%{mark}")
    res["test"] = test

    # FULL year for every combo (context) and selected detail
    print("\n== FULL year ==")
    full = {}
    for combo in GRID:
        o, g, pe, trs = run_combo(coins, combo, *W["FULL"])
        o["quarters"] = quarters(g, pe, *W["FULL"])
        full[o["combo"]] = o
        mark = " <== selected" if o["combo"] == best else ""
        print(f"{o['combo']:18s} ret {o['ret']:+7.2f}% mdd {o['mdd']:+7.2f}% trades {o['trades']:5d} win {o['win']}% avg {o['avg']}% tim {o['tim']}% Q {o['quarters']}{mark}")
    res["full"] = full

    print("\n== SELECTED detail ==")
    for name in ("TRAIN", "TEST", "FULL"):
        o = {"TRAIN": train, "TEST": test, "FULL": full}[name][best]
        print(f"{name:5s} ret {o['ret']:+7.2f}% mdd {o['mdd']:+7.2f}% trades {o['trades']} win {o['win']}% avg {o['avg']}% tim {o['tim']}%")
        for m, p in o["per_coin"].items():
            print(f"      {m:9s} ret {p['ret']:+7.2f}% trades {p['trades']:4d} win {p['win']}% exits {p['reasons']}")
    _, _, _, trs = run_combo(coins, combo_sel, *W["TEST"])
    res["selected_test_trades_sample"] = trs[:5]
    out = os.path.join(HERE, "results_spread.json" if SPREAD else "results.json")
    res["spread_mode"] = SPREAD
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    print("\nsaved", out, "| spread mode:", SPREAD)


if __name__ == "__main__":
    main()
