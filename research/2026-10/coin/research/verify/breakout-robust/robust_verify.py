"""Adversarial robustness verification of the breakout family claim (4h_N55_atr2).

Re-uses breakout_wf.py (copied verbatim from research/breakout/) for data loading
and the reference simulator, and adds a parameterised re-implementation so that
neighbouring parameters, bar phase, alternative splits, cost and
best-day/best-trade removal can be tested.

Checks
 (0) sanity: generalised simulator reproduces breakout_wf.run for all 12 combos
 (a) neighbours: 12-grid neighbours + finer N / ATR-mult / ATR-len / SMA-len /
     timeframe / 4h-bar phase offsets
 (b) alternative splits: cut 2026-04-21 (train before / test after, and reversed),
     cut 2026-06-21 reversed; fixed chosen combo AND re-running the pre-registered
     selection rule on the new TRAIN
 (c) best 5 portfolio days removed; best 5 trades removed; trades entered on the
     5 best entry-days removed
 (d) per-coin breakdown, leave-one-coin-out, per-coin vs buy-and-hold
 (e) cost doubled to 0.40% RT for all 12 combos
 (f) exposure-matched random-entry benchmark on TEST (Monte Carlo)
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import breakout_wf as W  # noqa: E402

# the copy sits one directory deeper than the original; point it at the candles
W.CANDLES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "candles")

FIVE = W.FIVE_MIN
DAY = np.timedelta64(1, "D").astype("timedelta64[ns]")
CUT_A = np.datetime64("2026-04-21T00:00:00", "ns")
CUT_B = W.SPLIT  # 2026-06-21


# ---------------------------------------------------------------- bar builder
_cache = {}


def build(coin, freq="4h", offset_h=0, Ns=(55,), atr_n=14, sma_len=50, chan_ms=(20,)):
    key = (coin.m, freq, offset_h, tuple(Ns), atr_n, sma_len, tuple(chan_ms))
    if key in _cache:
        return _cache[key]
    t = pd.Series(pd.to_datetime(coin.t))
    off = pd.Timedelta(hours=offset_h)
    k = (t - off).dt.floor(freq) + off
    pos = np.arange(len(t))
    df = pd.DataFrame({"key": k, "o": coin.o, "h": coin.h, "l": coin.l, "c": coin.c, "pos": pos})
    agg = df.groupby("key", sort=True).agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"),
                                          a=("pos", "first"), b=("pos", "last"))
    start = agg.index.values.astype("datetime64[ns]")
    end = start + pd.Timedelta(freq).to_timedelta64().astype("timedelta64[ns]")
    h, l, c = agg["h"], agg["l"], agg["c"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / atr_n, adjust=False, min_periods=atr_n).mean()
    day = t.dt.floor("1D")
    dclose = pd.Series(coin.c).groupby(day.values).last()
    day_start = dclose.index.values.astype("datetime64[ns]")
    if sma_len:
        dsma = dclose.rolling(sma_len).mean().values
    else:
        dsma = np.full(len(dclose), -np.inf)
    didx = np.searchsorted(day_start, end - DAY, side="right") - 1
    sma = np.where(didx >= 0, dsma[np.clip(didx, 0, None)], np.nan)
    T = {"start": start, "end": end, "h": h.values, "l": l.values, "c": c.values,
         "a": agg["a"].values, "b": agg["b"].values, "atr": atr.values, "sma": sma,
         "hh": {n: h.rolling(n).max().shift(1).values for n in Ns},
         "ll": {m: l.rolling(m).min().values for m in chan_ms}}
    _cache[key] = T
    return T


def simulate(coin, T, N, katr, M, ps, pe, use_filter=True):
    """Identical logic to breakout_wf.simulate, with T / N / katr / M passed in."""
    k_ps = int(np.searchsorted(coin.t, ps, "left"))
    k_pe = int(np.searchsorted(coin.t, pe, "left"))
    a, b = T["a"], T["b"]
    hhp, h, c, atr, sma = T["hh"][N], T["h"], T["c"], T["atr"], T["sma"]
    llw = T["ll"][M]
    j0 = max(int(np.searchsorted(a, k_ps, "left")) - 1, 0)
    j1 = int(np.searchsorted(a, k_pe, "left"))
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


def coin_equity(coin, trades, k_ps, k_pe, C):
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


class Spec:
    def __init__(self, freq="4h", N=55, exit="atr2", katr=None, atr_n=14, sma_len=50, offset_h=0, M=None):
        self.freq, self.N, self.exit, self.atr_n, self.sma_len, self.offset_h = freq, N, exit, atr_n, sma_len, offset_h
        if exit == "chan":
            self.katr = None
            self.M = M if M is not None else W.CHAN_EXIT.get(N, max(N // 2, 2))
        else:
            self.katr = katr if katr is not None else {"atr2": 2.0, "atr3": 3.0}[exit]
            self.M = 20
        self.name = f"{freq}_N{N}_{exit if exit == 'chan' else 'k' + str(self.katr)}_atr{atr_n}_sma{sma_len}_off{offset_h}"


def run(coins, spec, ps, pe, C=W.C, use_filter=True, drop=None, keep_coins=None):
    """Portfolio run. drop: set of (market, ek) trades to replace by cash."""
    grid = np.arange(ps, pe, FIVE)
    span = (pe - ps) / np.timedelta64(1, "ns")
    per, eqs, all_tr, tim, tlist = {}, [], [], [], []
    for cn in coins:
        if keep_coins is not None and cn.m not in keep_coins:
            continue
        T = build(cn, spec.freq, spec.offset_h, (spec.N,), spec.atr_n, spec.sma_len, (spec.M,))
        tr, k_ps, k_pe = simulate(cn, T, spec.N, spec.katr, spec.M, ps, pe, use_filter)
        if drop:
            tr = [x for x in tr if (cn.m, x[0]) not in drop]
        eq = coin_equity(cn, tr, k_ps, k_pe, C)
        # contribution of each trade to the coin sleeve (in sleeve-equity units, sleeve starts at 1)
        cash = 1.0
        for ek, epx, xk, xpx, why in tr:
            r = (xpx * (1 - C)) / (epx * (1 + C)) - 1
            tlist.append({"m": cn.m, "ek": ek, "et": cn.t[ek], "xt": cn.t[xk], "ret": r, "pnl": cash * r})
            cash *= 1 + r
            all_tr.append(r)
        per[cn.m] = float((eq[-1] - 1) * 100)
        tim.append(sum((cn.t[xk] - cn.t[ek]) / np.timedelta64(1, "ns") for ek, _, xk, _, _ in tr) / span)
        eqs.append(W.to_grid(cn, eq, k_ps, grid))
    port = np.mean(eqs, axis=0)
    return {"ret": float((port[-1] - 1) * 100), "mdd": W.mdd(port), "trades": len(all_tr),
            "win": float(np.mean([r > 0 for r in all_tr]) * 100) if all_tr else float("nan"),
            "avg": float(np.mean(all_tr) * 100) if all_tr else float("nan"),
            "tim": float(np.mean(tim) * 100), "coins": per, "grid": grid, "port": port, "tlist": tlist}


def f(r):
    return (f"ret {r['ret']:+7.2f}%  mdd {r['mdd']:+7.2f}%  n {r['trades']:3d}  win {r['win']:5.1f}%  "
            f"avg {r['avg']:+6.2f}%  tim {r['tim']:4.1f}%")


def cl(r):
    return " ".join(f"{m.split('-')[1]} {v:+6.1f}" for m, v in r["coins"].items())


def grid12():
    return [Spec(tf, n, ex) for tf in ("1h", "4h") for n in (20, 55) for ex in ("chan", "atr2", "atr3")]


def select(coins, specs, ps, pe, min_tr=15):
    res = {s.name: (s, run(coins, s, ps, pe)) for s in specs}
    ok = [k for k, (s, r) in res.items() if r["trades"] >= min_tr]
    best = sorted(ok, key=lambda k: (-res[k][1]["ret"], -res[k][1]["mdd"]))[0]
    return best, res


def daily_returns(grid, port):
    s = pd.Series(port, index=pd.to_datetime(grid))
    d = s.groupby(s.index.floor("1D")).last()
    prev = np.concatenate([[1.0], d.values[:-1]])
    return pd.Series(d.values / prev - 1, index=d.index)


def main():
    coins = [W.Coin(m) for m in W.MARKETS]
    first = max(cn.t[0] for cn in coins)
    hour = np.timedelta64(1, "h").astype("timedelta64[ns]")
    ps = (first + hour - np.timedelta64(1, "ns")).astype("datetime64[h]").astype("datetime64[ns]")
    pe = min(cn.t[-1] for cn in coins) + FIVE
    P = {"TRAIN": (ps, CUT_B), "TEST": (CUT_B, pe), "FULL": (ps, pe)}
    chosen = Spec("4h", 55, "atr2")
    print(f"window {ps} .. {pe}")

    # ---------------------------------------------------------------- (0) sanity
    print("\n(0) SANITY: generalised simulator vs breakout_wf.run (TRAIN/TEST/FULL ret)")
    maxdiff = 0.0
    for s, c in zip(grid12(), W.combos()):
        for p, (a, b) in P.items():
            r1 = W.run(coins, c, a, b)["ret"]
            r2 = run(coins, s, a, b)["ret"]
            maxdiff = max(maxdiff, abs(r1 - r2))
    print(f"  max |diff| over 12 combos x 3 periods = {maxdiff:.2e}")
    for p, (a, b) in P.items():
        r = run(coins, chosen, a, b)
        print(f"  chosen {p:5s} {f(r)}   {cl(r)}")

    # ---------------------------------------------------------------- (a) neighbours
    print("\n(a) NEIGHBOURS  (TRAIN | TEST | FULL return %, TEST trades, coins>0 on TEST)")
    variants = []
    variants += [("grid-12", s) for s in grid12()]
    variants += [("N", Spec("4h", n, "atr2")) for n in (30, 40, 45, 50, 60, 65, 70, 80)]
    variants += [("k", Spec("4h", 55, "atrk", katr=k)) for k in (1.5, 2.5, 3.0, 4.0)]
    variants += [("atr_n", Spec("4h", 55, "atr2", atr_n=n)) for n in (7, 10, 20, 28)]
    variants += [("sma", Spec("4h", 55, "atr2", sma_len=n)) for n in (20, 30, 100, 200, 0)]
    variants += [("tf", Spec(tf, 55, "atr2")) for tf in ("2h", "3h", "6h", "8h", "12h")]
    variants += [("phase", Spec("4h", 55, "atr2", offset_h=o)) for o in (1, 2, 3)]
    variants += [("phase-N20", Spec("4h", 20, "atr2", offset_h=o)) for o in (1, 2, 3)]
    rows = []
    for grp, s in variants:
        rt = run(coins, s, *P["TRAIN"])
        rs = run(coins, s, *P["TEST"])
        rf = run(coins, s, *P["FULL"])
        pos = sum(v > 0 for v in rs["coins"].values())
        rows.append((grp, s.name, rt["ret"], rs["ret"], rf["ret"], rs["trades"], pos, rs["mdd"]))
        tag = "  <== chosen" if s.name == chosen.name else ""
        print(f"  {grp:9s} {s.name:34s} TRAIN {rt['ret']:+7.2f} | TEST {rs['ret']:+7.2f} (n {rs['trades']:3d}, "
              f"{pos}/5>0, mdd {rs['mdd']:+6.2f}) | FULL {rf['ret']:+7.2f}{tag}")
    allr = np.array([r[3] for r in rows])
    fullr = np.array([r[4] for r in rows])
    trr = np.array([r[2] for r in rows])
    print(f"  over {len(rows)} variants: TEST>0 {np.sum(allr > 0)}/{len(rows)}, TEST>BH(+11.29) {np.sum(allr > 11.29)}, "
          f"FULL>0 {np.sum(fullr > 0)}/{len(rows)}, TRAIN>0 {np.sum(trr > 0)}/{len(rows)}; "
          f"TEST median {np.median(allr):+.2f}, FULL median {np.median(fullr):+.2f}")

    # ---------------------------------------------------------------- (b) alt splits
    print("\n(b) ALTERNATIVE SPLITS")
    bh = {}
    splits = {
        "A: train<04-21 test>=04-21": ((ps, CUT_A), (CUT_A, pe)),
        "A-rev: train>=04-21 test<04-21": ((CUT_A, pe), (ps, CUT_A)),
        "B-rev: train>=06-21 test<06-21": ((CUT_B, pe), (ps, CUT_B)),
        "orig: train<06-21 test>=06-21": ((ps, CUT_B), (CUT_B, pe)),
    }
    for nm, (tr_, te_) in splits.items():
        bt = W.buy_hold(coins, *tr_)["ret"]
        be = W.buy_hold(coins, *te_)["ret"]
        fixed_tr = run(coins, chosen, *tr_)
        fixed_te = run(coins, chosen, *te_)
        best, res = select(coins, grid12(), *tr_)
        pick_te = run(coins, res[best][0], *te_)
        all_te = {k: run(coins, s, *te_)["ret"] for k, (s, _) in res.items()}
        print(f"  {nm}")
        print(f"    buy&hold: train {bt:+7.2f}  test {be:+7.2f}")
        print(f"    fixed chosen 4h_N55_atr2: train {f(fixed_tr)}")
        print(f"                              test  {f(fixed_te)}   {cl(fixed_te)}")
        print(f"    re-selected on this TRAIN: {best} (train {res[best][1]['ret']:+.2f}) -> TEST {f(pick_te)}")
        print("    all 12 TRAIN: " + ", ".join(f"{k.split('_off')[0].replace('_atr14_sma50','')} {r['ret']:+.2f}" for k, (s, r) in res.items()))
        print("    all 12 TEST : " + ", ".join(f"{k.split('_off')[0].replace('_atr14_sma50','')} {v:+.2f}" for k, v in all_te.items()))
        print(f"    TEST>0: {sum(v > 0 for v in all_te.values())}/12, TEST>BH: {sum(v > be for v in all_te.values())}/12")

    # ---------------------------------------------------------------- (c) best days / trades removed
    print("\n(c) BEST DAYS / TRADES REMOVED (chosen combo)")
    for p in ("TEST", "FULL", "TRAIN"):
        a, b = P[p]
        r = run(coins, chosen, a, b)
        dr = daily_returns(r["grid"], r["port"])
        top = dr.sort_values(ascending=False).head(5)
        comp = float(np.prod(1 + dr.values) - 1) * 100
        rem = dr.copy()
        rem[top.index] = 0.0
        comp_rem = float(np.prod(1 + rem.values) - 1) * 100
        print(f"  {p}: ret {r['ret']:+.2f}% (daily compounding check {comp:+.2f}%)")
        print(f"    5 best portfolio days: " + ", ".join(f"{d.date()} {v * 100:+.2f}%" for d, v in top.items()))
        print(f"    -> with those 5 days set to 0%: {comp_rem:+.2f}%")
        tl = sorted(r["tlist"], key=lambda x: -x["pnl"])
        top5 = tl[:5]
        drop = {(x["m"], x["ek"]) for x in top5}
        r2 = run(coins, chosen, a, b, drop=drop)
        print(f"    5 best trades: " + ", ".join(f"{x['m'].split('-')[1]} {str(x['et'])[:16]} {x['ret'] * 100:+.2f}%" for x in top5))
        print(f"    -> those 5 trades removed (stay in cash): {r2['ret']:+.2f}%  (mdd {r2['mdd']:+.2f})")
        # trades grouped by entry day
        byday = {}
        for x in r["tlist"]:
            d = str(x["et"])[:10]
            byday.setdefault(d, []).append(x)
        dd = sorted(byday.items(), key=lambda kv: -sum(x["pnl"] for x in kv[1]))[:5]
        drop2 = {(x["m"], x["ek"]) for _, xs in dd for x in xs}
        r3 = run(coins, chosen, a, b, drop=drop2)
        print(f"    5 best entry-days: " + ", ".join(f"{d} ({len(xs)} tr, sleeve-pnl sum {sum(x['pnl'] for x in xs) * 100:+.2f}%)" for d, xs in dd))
        print(f"    -> all trades entered on those 5 days removed: {r3['ret']:+.2f}%  ({len(drop2)} trades dropped of {r['trades']})")
        # Aug 19-22 window removal
        if p in ("TEST", "FULL"):
            lo, hi = np.datetime64("2026-08-19", "ns"), np.datetime64("2026-08-23", "ns")
            drop3 = {(x["m"], x["ek"]) for x in r["tlist"] if lo <= x["et"] < hi}
            r4 = run(coins, chosen, a, b, drop=drop3)
            print(f"    -> trades entered 2026-08-19..22 removed ({len(drop3)} trades): {r4['ret']:+.2f}%")
        # monthly breakdown
        s = pd.Series(r["port"], index=pd.to_datetime(r["grid"]))
        mon = s.groupby(s.index.to_period("M")).last()
        prev = mon.shift(1).fillna(1.0)
        print("    monthly portfolio %: " + ", ".join(f"{k} {v * 100:+.2f}" for k, v in (mon / prev - 1).items()))

    # ---------------------------------------------------------------- (d) per coin
    print("\n(d) PER-COIN (chosen combo)")
    for p in ("TRAIN", "TEST", "FULL"):
        a, b = P[p]
        r = run(coins, chosen, a, b)
        bhr = W.buy_hold(coins, a, b)
        print(f"  {p:5s} strat: {cl(r)}")
        print(f"        b&h  : " + " ".join(f"{m.split('-')[1]} {v['ret']:+6.1f}" for m, v in bhr["coins"].items()))
        loo = []
        for m in W.MARKETS:
            keep = [x for x in W.MARKETS if x != m]
            loo.append(f"-{m.split('-')[1]} {run(coins, chosen, a, b, keep_coins=keep)['ret']:+.2f}")
        print(f"        leave-one-coin-out portfolio: " + ", ".join(loo))
        tl = r["tlist"]
        tot = sum(x["pnl"] for x in tl)
        pc = {m: sum(x["pnl"] for x in tl if x["m"] == m) for m in W.MARKETS}
        print(f"        sum sleeve pnl by coin (% of sleeve): " + ", ".join(f"{m.split('-')[1]} {v * 100:+.2f}" for m, v in pc.items()))

    # ---------------------------------------------------------------- (e) cost doubled
    print("\n(e) COST 0.40% RT (0.20%/side), all 12 combos  TRAIN | TEST | FULL")
    for s in grid12():
        rt = run(coins, s, *P["TRAIN"], C=0.002)
        rs = run(coins, s, *P["TEST"], C=0.002)
        rf = run(coins, s, *P["FULL"], C=0.002)
        tag = "  <== chosen" if s.name == chosen.name else ""
        print(f"  {s.name:34s} {rt['ret']:+7.2f} | {rs['ret']:+7.2f} | {rf['ret']:+7.2f}{tag}")
    best, res = select(coins, grid12(), *P["TRAIN"])
    print(f"  (selection at base cost unchanged: {best})")
    # re-select under doubled cost
    resd = {s.name: (s, run(coins, s, *P["TRAIN"], C=0.002)) for s in grid12()}
    ok = [k for k, (s, r) in resd.items() if r["trades"] >= 15]
    bd = sorted(ok, key=lambda k: (-resd[k][1]["ret"], -resd[k][1]["mdd"]))[0]
    print(f"  selection re-run at 0.40% cost picks {bd}: TEST {run(coins, resd[bd][0], *P['TEST'], C=0.002)['ret']:+.2f}")
    for p in P:
        r = run(coins, chosen, *P[p], C=0.002)
        print(f"  chosen @0.40% {p:5s} {f(r)}  {cl(r)}")
    for p in P:
        r = run(coins, chosen, *P[p], C=0.003)
        print(f"  chosen @0.60% {p:5s} {f(r)}  {cl(r)}")

    # ---------------------------------------------------------------- (f) random-entry benchmark
    print("\n(f) EXPOSURE-MATCHED RANDOM ENTRY on TEST (same per-coin trade count and holding lengths, random non-overlapping start times, 0.20% RT)")
    rng = np.random.default_rng(12345)
    a, b = P["TEST"]
    r = run(coins, chosen, a, b)
    obs = r["ret"]
    sims = []
    per_coin = {}
    for cn in coins:
        T = build(cn, "4h", 0, (55,), 14, 50, (20,))
        tr, k_ps, k_pe = simulate(cn, T, 55, 2.0, 20, a, b)
        per_coin[cn.m] = (tr, k_ps, k_pe)
    NSIM = 2000
    for _ in range(NSIM):
        eqs = []
        for cn in coins:
            tr, k_ps, k_pe = per_coin[cn.m]
            lens = [max(xk - ek, 1) for ek, _, xk, _, _ in tr]
            n = k_pe - k_ps
            # place holding blocks at random non-overlapping positions
            total = sum(lens)
            free = n - 1 - total
            cuts = np.sort(rng.integers(0, free + 1, size=len(lens)))
            order = rng.permutation(len(lens))
            cash, used = 1.0, 0
            for i, o in enumerate(order):
                e = k_ps + cuts[i] + used
                x = e + lens[o]
                used += lens[o]
                cash *= (cn.c[x - 1] * (1 - W.C)) / (cn.o[e] * (1 + W.C))  # buy open e, sell close x-1
            eqs.append(cash)
        sims.append((np.mean(eqs) - 1) * 100)
    sims = np.array(sims)
    print(f"  observed TEST {obs:+.2f}% ; random: mean {sims.mean():+.2f}%, median {np.median(sims):+.2f}%, "
          f"95th pct {np.percentile(sims, 95):+.2f}%, 99th {np.percentile(sims, 99):+.2f}%; "
          f"P(random >= observed) = {np.mean(sims >= obs):.3f}")
    # same on TRAIN
    a, b = P["TRAIN"]
    obs_tr = run(coins, chosen, a, b)["ret"]
    per_coin = {}
    for cn in coins:
        T = build(cn, "4h", 0, (55,), 14, 50, (20,))
        per_coin[cn.m] = simulate(cn, T, 55, 2.0, 20, a, b)
    sims = []
    for _ in range(NSIM):
        eqs = []
        for cn in coins:
            tr, k_ps, k_pe = per_coin[cn.m]
            lens = [max(xk - ek, 1) for ek, _, xk, _, _ in tr]
            n = k_pe - k_ps
            free = n - 1 - sum(lens)
            cuts = np.sort(rng.integers(0, free + 1, size=len(lens)))
            order = rng.permutation(len(lens))
            cash, used = 1.0, 0
            for i, o in enumerate(order):
                e = k_ps + cuts[i] + used
                x = e + lens[o]
                used += lens[o]
                cash *= (cn.c[x - 1] * (1 - W.C)) / (cn.o[e] * (1 + W.C))
            eqs.append(cash)
        sims.append((np.mean(eqs) - 1) * 100)
    sims = np.array(sims)
    print(f"  TRAIN observed {obs_tr:+.2f}% ; random: mean {sims.mean():+.2f}%, median {np.median(sims):+.2f}%, "
          f"5th pct {np.percentile(sims, 5):+.2f}%, 95th {np.percentile(sims, 95):+.2f}%; P(random >= observed) = {np.mean(sims >= obs_tr):.3f}")


if __name__ == "__main__":
    main()
