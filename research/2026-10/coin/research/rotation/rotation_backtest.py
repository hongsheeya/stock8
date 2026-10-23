"""
FAMILY "rotation" -- cross-sectional momentum rotation across 5 Upbit KRW coins.
LONG-ONLY spot, no leverage. Whole seed is one portfolio.

=====================================================================
PRE-REGISTRATION (written before any backtest was run)
=====================================================================
Universe : KRW-BTC, KRW-ETH, KRW-XRP, KRW-SOL, KRW-DOGE
Bars     : daily bars built from 5m bars, UTC day [00:00, 24:00) (= Upbit 09:00 KST
           daily candle). Daily close = close of the last 5m bar of the UTC day.
Decision : every day at 00:00 UTC, using ONLY completed daily bars (through the
           previous UTC day). Orders fill at the OPEN of the next 5m bar
           (the first available 5m bar at/after 00:00 UTC; gaps -> next bar).
Score    : L-day trailing return  = close[d] / close[d-L] - 1   (d = last completed day)
Selection: rank the 5 coins by score, take the top K.  Each chosen coin is held
           ONLY IF  (a) its score > 0 (absolute momentum)  AND
                    (b) its close[d] > its own SMA20 of daily closes.
           If gate == "btc": additionally BTC close[d] > BTC SMA50 of daily closes,
           otherwise everything goes to cash.
           A chosen coin that fails a filter leaves its slot in cash (we do NOT
           fall through to the next-ranked coin).
Sizing   : K equal slots. A new entry buys min(cash, equity/K) KRW worth.
           A coin that stays selected is NOT rebalanced (no churn). A held coin
           that is no longer selected (or fails a filter) is sold in full.
Costs    : 0.05% fee per side + 0.05% slippage per side (= ~0.20% round trip),
           applied to every buy and every sell.
Grid (12): L in {7, 14, 30}  x  K in {1, 2}  x  gate in {"none", "btc"}
Warm-up  : common for all combos: first decision when BTC SMA50 exists
           (50 daily closes) -> 2025-12-10 00:00 UTC. Cash before that.
Split    : TRAIN = before 2026-06-21T00:00 UTC, TEST = from 2026-06-21T00:00 UTC.
           TRAIN run starts flat at data start and is liquidated at the split bar
           open. TEST run starts flat at the split (indicators use prior data
           only) and is liquidated at the last bar close. FULL = one continuous run.
Choice   : the combo with the highest TRAIN total return (net of costs);
           tie-break = smaller TRAIN max drawdown.  TEST is then reported untouched.
Diagnostics (NOT used for selection, reported only for information):
           L=3 with the chosen K/gate, and the chosen combo with weekly rebalancing.
=====================================================================
"""
import json
import os
import sys
from itertools import product

import numpy as np
import pandas as pd

BASE = r"C:\Users\변기국~1\AppData\Local\Temp\claude\C--dev\93ae6530-93fd-4894-8774-b698a96bffc9\scratchpad\coin"
DATA = os.path.join(BASE, "candles")
OUT = os.path.join(BASE, "research", "rotation")
COINS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]
FEE = 0.0005
SLIP = 0.0005
SPLIT = pd.Timestamp("2026-06-21T00:00:00")
FIRST_DECISION = pd.Timestamp("2025-12-10T00:00:00")
OWN_SMA = 20
BTC_SMA = 50
GRID_L = [7, 14, 30]
GRID_K = [1, 2]
GRID_GATE = ["none", "btc"]
DAY = pd.Timedelta(days=1)


# ----------------------------------------------------------------- data
def load(m):
    with open(os.path.join(DATA, f"{m}_5m.json"), encoding="utf-8") as f:
        d = json.load(f)
    df = pd.DataFrame(d)
    df["t"] = pd.to_datetime(df["t"])
    df = df.set_index("t").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


raw = {m: load(m) for m in COINS}
T_first = min(df.index[0] for df in raw.values())
T0 = max(df.index[0] for df in raw.values())  # first time every coin has traded
T1 = max(df.index[-1] for df in raw.values())
full_grid = pd.date_range(T_first, T1, freq="5min")
grid = pd.date_range(T0, T1, freq="5min")
N = len(grid)

close = np.column_stack([raw[m]["c"].reindex(full_grid).ffill().reindex(grid).values for m in COINS])
open_ = np.column_stack([raw[m]["o"].reindex(grid).values for m in COINS])
# fill price at a decision bar = open of the first existing bar at/after it
open_fill = pd.DataFrame(open_).bfill().values
assert not np.isnan(close).any()

missing = {m: int(np.isnan(open_[:, j]).sum()) for j, m in enumerate(COINS)}

# daily closes (UTC day)
daily = pd.DataFrame({m: raw[m]["c"].resample("1D").last() for m in COINS}).ffill()
dclose = daily.values
dates = daily.index
sma_own = daily.rolling(OWN_SMA).mean().values
sma_btc = daily["KRW-BTC"].rolling(BTC_SMA).mean().values
date_pos = {d: i for i, d in enumerate(dates)}


def targets_for(t, L, K, gate):
    """Coins (column indices) to hold after the decision at time t (00:00 UTC).
    Uses only the daily bar of t - 1 day and earlier."""
    d = date_pos[t - DAY]
    if d - L < 0:
        return []
    if gate == "btc":
        if np.isnan(sma_btc[d]) or not (dclose[d, 0] > sma_btc[d]):
            return []
    score = dclose[d] / dclose[d - L] - 1.0
    order = np.argsort(-score, kind="stable")[:K]
    out = []
    for j in order:
        if score[j] > 0 and not np.isnan(sma_own[d, j]) and dclose[d, j] > sma_own[d, j]:
            out.append(int(j))
    return out


# ----------------------------------------------------------------- simulator
def simulate(L, K, gate, start, end, step_days=1):
    """start/end: timestamps. Equity = 1.0 cash at grid bar >= start.
    Liquidates at the open of the bar at `end` (if inside data) else the last close."""
    i_s = grid.searchsorted(start)
    i_e = grid.searchsorted(end) if end is not None else N
    first = max(FIRST_DECISION, start.ceil("D"))
    last = end if end is not None else grid[-1] + pd.Timedelta(minutes=5)
    dec = pd.date_range(first, last, freq="D")
    dec = [t for t in dec if t < last and grid.searchsorted(t) < i_e][::step_days]

    cash = 1.0
    units = np.zeros(len(COINS))
    open_tr = {}  # j -> dict(entry_time, cost)
    trades = []
    eq = np.empty(i_e - i_s)
    posv = np.empty(i_e - i_s)
    cur = i_s
    for t in dec:
        i = grid.searchsorted(t)
        if i > cur:
            pv = close[cur:i] @ units
            posv[cur - i_s:i - i_s] = pv
            eq[cur - i_s:i - i_s] = cash + pv
            cur = i
        tg = targets_for(t, L, K, gate)
        px = open_fill[i]
        # sells first
        for j in list(open_tr):
            if j not in tg:
                proceeds = units[j] * px[j] * (1 - SLIP) * (1 - FEE)
                cash += proceeds
                tr = open_tr.pop(j)
                trades.append(dict(coin=COINS[j], entry=str(tr["entry"]), exit=str(t),
                                   ret=proceeds / tr["cost"] - 1, days=(t - tr["entry"]) / DAY,
                                   pnl=proceeds - tr["cost"]))
                units[j] = 0.0
        # buys
        eq_now = cash + float(units @ np.nan_to_num(px))
        for j in tg:
            if j in open_tr:
                continue
            alloc = min(cash, eq_now / K)
            if alloc <= 1e-12:
                continue
            units[j] = alloc * (1 - FEE) / (px[j] * (1 + SLIP))
            cash -= alloc
            open_tr[j] = dict(entry=t, cost=alloc)
    if i_e > cur:
        pv = close[cur:i_e] @ units
        posv[cur - i_s:] = pv
        eq[cur - i_s:] = cash + pv
    # final liquidation
    if i_e < N:
        px = open_fill[i_e]
        t_end = grid[i_e]
    else:
        px = close[N - 1]
        t_end = grid[N - 1] + pd.Timedelta(minutes=5)
    for j in list(open_tr):
        proceeds = units[j] * px[j] * (1 - SLIP) * (1 - FEE)
        cash += proceeds
        tr = open_tr.pop(j)
        trades.append(dict(coin=COINS[j], entry=str(tr["entry"]), exit=str(t_end) + " (forced)",
                           ret=proceeds / tr["cost"] - 1, days=(t_end - tr["entry"]) / DAY,
                           pnl=proceeds - tr["cost"]))
        units[j] = 0.0
    final = cash
    return dict(eq=eq, posv=posv, final=final, trades=trades, i_s=i_s, i_e=i_e)


def buy_hold(start, end):
    i_s = grid.searchsorted(start)
    i_e = grid.searchsorted(end) if end is not None else N
    px0 = open_fill[i_s]
    units = 0.2 * (1 - FEE) / (px0 * (1 + SLIP))
    eq = close[i_s:i_e] @ units
    pxe = open_fill[i_e] if i_e < N else close[N - 1]
    final = float((units * pxe * (1 - SLIP) * (1 - FEE)).sum())
    per = units * pxe * (1 - SLIP) * (1 - FEE) / 0.2 - 1
    return dict(eq=eq, final=final, per={m: float(per[j]) for j, m in enumerate(COINS)})


def mdd(curve):
    c = np.asarray(curve, dtype=float)
    peak = np.maximum.accumulate(np.concatenate([[1.0], c]))
    return float(((np.concatenate([[1.0], c]) / peak) - 1).min())


def stats(res):
    curve = np.concatenate([res["eq"], [res["final"]]])
    tr = res["trades"]
    rets = np.array([x["ret"] for x in tr]) if tr else np.array([])
    inmkt = res["posv"] > 1e-12
    return dict(
        return_pct=100 * (res["final"] - 1),
        mdd_pct=100 * mdd(curve),
        trades=len(tr),
        win_rate_pct=100 * float((rets > 0).mean()) if len(rets) else float("nan"),
        avg_trade_pct=100 * float(rets.mean()) if len(rets) else float("nan"),
        time_in_market_pct=100 * float(inmkt.mean()),
        avg_exposure_pct=100 * float((res["posv"] / res["eq"]).mean()),
    )


def per_coin(trades):
    out = {}
    for m in COINS:
        tt = [x for x in trades if x["coin"] == m]
        r = np.array([x["ret"] for x in tt])
        out[m] = dict(trades=len(tt), days_held=round(sum(x["days"] for x in tt), 1),
                      win_rate_pct=round(100 * float((r > 0).mean()), 1) if len(r) else None,
                      avg_trade_pct=round(100 * float(r.mean()), 2) if len(r) else None,
                      sum_trade_pct=round(100 * float(r.sum()), 2) if len(r) else 0.0,
                      pnl_pct_of_seed=round(100 * float(sum(x["pnl"] for x in tt)), 2))
    return out


def quarters(res, bounds):
    """quarterly returns of a run that starts at grid[res.i_s]; bounds: list of timestamps."""
    curve_t = grid[res["i_s"]:res["i_e"]]
    vals = []
    for b in bounds:
        k = curve_t.searchsorted(b) - 1  # last bar strictly before b (close MTM)
        vals.append(1.0 if k < 0 else float(res["eq"][k]))
    vals.append(float(res["final"]))
    return [100 * (vals[q + 1] / vals[q] - 1) for q in range(len(vals) - 1)]


def r2(d):
    return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in d.items()}


# ----------------------------------------------------------------- run grid on TRAIN
log = []


def P(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    log.append(s)


P(f"data grid: {grid[0]} .. {grid[-1]}  bars={N}  missing 5m bars per coin: {missing}")
P(f"daily bars: {dates[0].date()} .. {dates[-1].date()} ({len(dates)})  first decision {FIRST_DECISION}")
combos = list(product(GRID_L, GRID_K, GRID_GATE))
assert len(combos) <= 12

train_res = {}
P("\n=== TRAIN (data start -> 2026-06-21 00:00 UTC), whole-seed portfolio ===")
P(f"{'L':>3} {'K':>2} {'gate':>5} {'ret%':>8} {'mdd%':>8} {'trades':>6} {'win%':>6} {'avg%':>6} {'inmkt%':>7}")
for c in combos:
    L, K, g = c
    s = stats(simulate(L, K, g, grid[0], SPLIT))
    train_res[c] = s
    P(f"{L:>3} {K:>2} {g:>5} {s['return_pct']:8.2f} {s['mdd_pct']:8.2f} {s['trades']:6d} "
      f"{s['win_rate_pct']:6.1f} {s['avg_trade_pct']:6.2f} {s['time_in_market_pct']:7.1f}")

chosen = sorted(combos, key=lambda c: (-round(train_res[c]["return_pct"], 6), -train_res[c]["mdd_pct"]))[0]
P(f"\nCHOSEN BY TRAIN: L={chosen[0]} K={chosen[1]} gate={chosen[2]}")

# ----------------------------------------------------------------- TEST (untouched) + sensitivity
test_res = {}
for c in combos:
    test_res[c] = stats(simulate(*c, SPLIT, None))
P("\n=== TEST (2026-06-21 00:00 UTC -> end) all grid combos (sensitivity; selection was on TRAIN) ===")
P(f"{'L':>3} {'K':>2} {'gate':>5} {'ret%':>8} {'mdd%':>8} {'trades':>6} {'win%':>6} {'avg%':>6} {'inmkt%':>7}")
for c in combos:
    s = test_res[c]
    L, K, g = c
    mark = "  <== chosen" if c == chosen else ""
    P(f"{L:>3} {K:>2} {g:>5} {s['return_pct']:8.2f} {s['mdd_pct']:8.2f} {s['trades']:6d} "
      f"{s['win_rate_pct']:6.1f} {s['avg_trade_pct']:6.2f} {s['time_in_market_pct']:7.1f}{mark}")


def neighbours(c):
    L, K, g = c
    li = GRID_L.index(L)
    nb = []
    for dl in (-1, 1):
        if 0 <= li + dl < len(GRID_L):
            nb.append((GRID_L[li + dl], K, g))
    nb.append((L, 3 - K, g))
    nb.append((L, K, "btc" if g == "none" else "none"))
    return nb


nbs = neighbours(chosen)
P("\nneighbours of chosen (TEST return %): " +
  ", ".join(f"L={n[0]} K={n[1]} gate={n[2]}: {test_res[n]['return_pct']:.2f}" for n in nbs))
tr_all = np.array([test_res[c]["return_pct"] for c in combos])
P(f"TEST across all 12 combos: median {np.median(tr_all):.2f}%  min {tr_all.min():.2f}%  max {tr_all.max():.2f}%  "
  f"#>0: {(tr_all > 0).sum()}/12")

# ----------------------------------------------------------------- chosen combo detail
res_train = simulate(*chosen, grid[0], SPLIT)
res_test = simulate(*chosen, SPLIT, None)
res_full = simulate(*chosen, grid[0], None)
bh_train = buy_hold(grid[0], SPLIT)
bh_test = buy_hold(SPLIT, None)
bh_full = buy_hold(grid[0], None)
bh_active = buy_hold(FIRST_DECISION, None)  # same active window as the strategy

qb = [grid[0], pd.Timestamp("2026-01-21"), pd.Timestamp("2026-04-21"), pd.Timestamp("2026-07-21")]
q_strat = quarters(res_full, qb)
bh_full_res = dict(eq=bh_full["eq"], final=bh_full["final"], i_s=0, i_e=N)
q_bh = quarters(bh_full_res, qb)

summary = {}
for name, r in (("train", res_train), ("test", res_test), ("full", res_full)):
    summary[name] = r2(stats(r))
    summary[name]["per_coin"] = per_coin(r["trades"])
summary["full"]["quarters_pct"] = [round(x, 2) for x in q_strat]
bh = {
    "train": dict(return_pct=100 * (bh_train["final"] - 1), mdd_pct=100 * mdd(np.r_[bh_train["eq"], bh_train["final"]]),
                  per_coin={k: round(100 * v, 2) for k, v in bh_train["per"].items()}),
    "test": dict(return_pct=100 * (bh_test["final"] - 1), mdd_pct=100 * mdd(np.r_[bh_test["eq"], bh_test["final"]]),
                 per_coin={k: round(100 * v, 2) for k, v in bh_test["per"].items()}),
    "full": dict(return_pct=100 * (bh_full["final"] - 1), mdd_pct=100 * mdd(np.r_[bh_full["eq"], bh_full["final"]]),
                 per_coin={k: round(100 * v, 2) for k, v in bh_full["per"].items()},
                 quarters_pct=[round(x, 2) for x in q_bh]),
    "active_window_from_2025-12-10": dict(return_pct=100 * (bh_active["final"] - 1),
                                          mdd_pct=100 * mdd(np.r_[bh_active["eq"], bh_active["final"]])),
}
for k in bh:
    bh[k]["return_pct"] = round(bh[k]["return_pct"], 2)
    bh[k]["mdd_pct"] = round(bh[k]["mdd_pct"], 2)

P("\n=== CHOSEN COMBO DETAIL ===")
for name in ("train", "test", "full"):
    s = summary[name]
    P(f"[{name}] ret {s['return_pct']:.2f}%  mdd {s['mdd_pct']:.2f}%  trades {s['trades']}  win {s['win_rate_pct']}%  "
      f"avg trade {s['avg_trade_pct']}%  time in mkt {s['time_in_market_pct']}%  avg exposure {s['avg_exposure_pct']}%")
    P(f"   B&H eq-weight: ret {bh[name]['return_pct']:.2f}%  mdd {bh[name]['mdd_pct']:.2f}%  per coin {bh[name]['per_coin']}")
    for m, pc in s["per_coin"].items():
        P(f"     {m:9s} {pc}")
P(f"[full] quarterly returns strategy (Q from {qb[0]}, 2026-01-21, 2026-04-21, 2026-07-21): {summary['full']['quarters_pct']}")
P(f"[full] quarterly returns eq-weight B&H: {bh['full']['quarters_pct']}")
P(f"B&H over the strategy's active window (from 2025-12-10 00:00): {bh['active_window_from_2025-12-10']}")

P("\nTEST trades of chosen combo:")
for x in res_test["trades"]:
    P(f"   {x['coin']:9s} {x['entry']} -> {x['exit']}  {100 * x['ret']:7.2f}%  {x['days']:.1f}d")

# ----------------------------------------------------------------- diagnostics (not used for selection)
P("\n=== DIAGNOSTICS (out of grid, NOT used for selection) ===")
diag = {}
for label, args, step in ((f"L=3 K={chosen[1]} gate={chosen[2]}", (3, chosen[1], chosen[2]), 1),
                          (f"chosen, weekly rebalance", chosen, 7)):
    a = stats(simulate(*args, grid[0], SPLIT, step))
    b = stats(simulate(*args, SPLIT, None, step))
    diag[label] = dict(train=r2(a), test=r2(b))
    P(f"{label:28s} TRAIN ret {a['return_pct']:.2f}% mdd {a['mdd_pct']:.2f}% n={a['trades']} | "
      f"TEST ret {b['return_pct']:.2f}% mdd {b['mdd_pct']:.2f}% n={b['trades']}")

result = dict(
    chosen=dict(L=chosen[0], K=chosen[1], gate=chosen[2]),
    train_grid={f"L{c[0]}_K{c[1]}_{c[2]}": r2(v) for c, v in train_res.items()},
    test_grid={f"L{c[0]}_K{c[1]}_{c[2]}": r2(v) for c, v in test_res.items()},
    neighbours_test={f"L{n[0]}_K{n[1]}_{n[2]}": round(test_res[n]["return_pct"], 2) for n in nbs},
    chosen_detail=summary,
    buy_hold=bh,
    diagnostics=diag,
    test_trades=res_test["trades"],
    data=dict(grid_start=str(grid[0]), grid_end=str(grid[-1]), missing_5m=missing),
)
with open(os.path.join(OUT, "rotation_results.json"), "w", encoding="utf-8") as f:
    json.dump(result, f, indent=1, default=str)
with open(os.path.join(OUT, "rotation_output.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(log))
