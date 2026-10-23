"""
Adversarial robustness check (lens "robust") for the VBO family claim.
Reuses the researcher's engine (vbo_research.py, copied unchanged into this folder) and perturbs:
  (0) reproduction of the claimed numbers
  (a) neighbouring / all 12 grid combos
  (b) other walk-forward splits: train<2026-04-21/test>=, train>=2026-04-21/test<, and the reverse of the original
  (c) best 5 trade days removed (day = entry day, ranked by portfolio contribution = 0.2*sum of coin trade returns)
  (d) per-coin breakdown and leave-one-coin-out
  (e) cost doubled (0.40% round trip -> 0.2% per side)
  (f) extra: day-boundary phase shift (day starts at 00,03,...,21 UTC) for the chosen rule
  (g) extra: fair placebo -- n-matched random days (any / filter-pass), random intraday entry, next-open exit
  (h) extra: k=0 (filter only, buy at day open) as a control
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vbo_research as V  # noqa: E402

CS1 = 0.001
CS2 = 0.002
coins = {m: V.Coin(m, V.load(m)) for m in V.MARKETS}
grid = V.Grid(coins)
T_START = pd.Timestamp(str(grid.t[0])).floor("D")
T_END = pd.Timestamp(str(grid.t[-1])) + pd.Timedelta(minutes=5)
S1 = V.SPLIT
S2 = pd.Timestamp("2026-04-21")
COMBOS = [(k, n) for k in V.K_GRID for n in V.N_GRID]
CHOSEN = (0.7, 10)
pct = V.pct


def sim_all(cs, combos=COMBOS, coinset=None):
    V.CS = cs
    cs_ = coinset or coins
    return {key: {m: V.simulate(cs_[m], key[0], key[1]) for m in V.MARKETS} for key in combos}


def rep(trades, T0, T1, cs, coinset=None):
    V.CS = cs
    return V.period_report(grid, coinset or coins, trades, T0, T1)


def bh(T0, T1):
    return V.buyhold(grid, coins, T0, T1)


SPLITS = {
    "A orig  train<06-21 test>=06-21": ((T_START, S1), (S1, T_END)),
    "A' rev  train>=06-21 test<06-21": ((S1, T_END), (T_START, S1)),
    "B       train<04-21 test>=04-21": ((T_START, S2), (S2, T_END)),
    "C rev   train>=04-21 test<04-21": ((S2, T_END), (T_START, S2)),
}


def walk_forward(all_tr, cs, label):
    print(f"\n### (b) walk-forward splits, cost/side {cs*100:.2f}% [{label}]")
    out = {}
    for name, ((a0, a1), (b0, b1)) in SPLITS.items():
        tr_r = {key: rep(all_tr[key], a0, a1, cs)["ret"] for key in COMBOS}
        te_r = {key: rep(all_tr[key], b0, b1, cs)["ret"] for key in COMBOS}
        best = max(tr_r, key=tr_r.get)
        te = np.array(list(te_r.values()))
        b = bh(b0, b1)
        print(f"  {name}: chosen k={best[0]} N={best[1]} TRAIN {pct(tr_r[best])} -> TEST {pct(te_r[best])} | "
              f"fixed k=0.7,N=10 TEST {pct(te_r[CHOSEN])} | 12-combo TEST median {pct(np.median(te))} "
              f"min {pct(te.min())} max {pct(te.max())} #>0 {(te > 0).sum()}/12 | B&H TEST {pct(b['ret'])}")
        print("     TEST by combo: " + ", ".join(f"{k}/{n}:{100*te_r[(k, n)]:+.2f}" for k, n in COMBOS))
        out[name] = (best, tr_r[best], te_r[best], te)
    return out


def day_contrib(trs):
    d = {}
    for m in V.MARKETS:
        for x in trs[m]:
            d[x["entry_day"]] = d.get(x["entry_day"], 0.0) + 0.2 * x["ret"]
    return d


def drop_days(trs, days):
    return {m: [x for x in trs[m] if x["entry_day"] not in days] for m in V.MARKETS}


def best_days(trs, T0, T1, k=5):
    d = {dd: v for dd, v in day_contrib(trs).items() if T0 <= dd < T1}
    return sorted(d, key=d.get, reverse=True)[:k], d


def main():
    print("data", T_START, "->", T_END)
    # ------------------------------------------------------------------ (0)+(a)
    TR1 = sim_all(CS1)
    print("\n### (0) reproduction, chosen k=0.7 N=10, cost 0.10%/side")
    for p, (a, b) in {"TRAIN": (T_START, S1), "TEST": (S1, T_END), "FULL": (T_START, T_END)}.items():
        r = rep(TR1[CHOSEN], a, b, CS1)
        print(f"  {p:5s} ret {pct(r['ret'])} mdd {pct(r['mdd'])} n {r['n']} win {100*r['win']:.1f}% avg {pct(r['avg'])} "
              f"tim {100*r['tim']:.1f}%  per-coin " + ", ".join(f"{m[4:]} {pct(v['ret'])}" for m, v in r['per_coin'].items()))

    print("\n### (a) all 12 combos, cost 0.10%/side: TRAIN | TEST | FULL")
    for key in COMBOS:
        rr = [rep(TR1[key], a, b, CS1)["ret"] for a, b in [(T_START, S1), (S1, T_END), (T_START, T_END)]]
        print(f"  k={str(key[0]):>7s} N={key[1]:2d}: {pct(rr[0])} | {pct(rr[1])} | {pct(rr[2])}")

    wf1 = walk_forward(TR1, CS1, "base cost")

    # ------------------------------------------------------------------ (c) best 5 days removed
    print("\n### (c) best-5 entry days removed (per period), cost 0.10%/side")
    for p, (a, b) in {"TRAIN": (T_START, S1), "TEST": (S1, T_END), "FULL": (T_START, T_END),
                      "B-test>=04-21": (S2, T_END), "C-test<04-21": (T_START, S2)}.items():
        bd, d = best_days(TR1[CHOSEN], a, b)
        base = rep(TR1[CHOSEN], a, b, CS1)["ret"]
        cut = rep(drop_days(TR1[CHOSEN], set(bd)), a, b, CS1)["ret"]
        tot = sum(d.values())
        top = sum(d[x] for x in bd)
        print(f"  chosen {p:14s}: base {pct(base)} -> best5 removed {pct(cut)} | sum day-contrib {pct(tot)}, "
              f"top5 days contribute {pct(top)} ({', '.join(str(x.date()) for x in bd)})")
    for p, (a, b) in {"TEST": (S1, T_END), "FULL": (T_START, T_END)}.items():
        vals = []
        for key in COMBOS:
            bd, _ = best_days(TR1[key], a, b)
            vals.append(rep(drop_days(TR1[key], set(bd)), a, b, CS1)["ret"])
        vals = np.array(vals)
        print(f"  all 12 combos {p} with best5 days removed: median {pct(np.median(vals))} min {pct(vals.min())} "
              f"max {pct(vals.max())} #>0 {(vals > 0).sum()}/12")
    # best 5 single trades removed
    allx = [(m, i, x) for m in V.MARKETS for i, x in enumerate(TR1[CHOSEN][m])]
    for p, (a, b) in {"TEST": (S1, T_END), "FULL": (T_START, T_END)}.items():
        sel = sorted([t for t in allx if a <= t[2]["entry_day"] < b], key=lambda t: t[2]["ret"], reverse=True)[:5]
        ids = {(m, i) for m, i, _ in sel}
        trs = {m: [x for i, x in enumerate(TR1[CHOSEN][m]) if (m, i) not in ids] for m in V.MARKETS}
        print(f"  chosen {p}: best 5 single trades removed {pct(rep(trs, a, b, CS1)['ret'])}  (removed: " +
              ", ".join(f"{m[4:]} {str(x['entry_day'].date())} {100*x['ret']:+.2f}%" for m, _, x in sel) + ")")

    # ------------------------------------------------------------------ (d) per coin
    print("\n### (d) per-coin, chosen k=0.7 N=10, cost 0.10%/side")
    per = {}
    for p, (a, b) in {"TRAIN": (T_START, S1), "TEST": (S1, T_END), "FULL": (T_START, T_END),
                      "B-test>=04-21": (S2, T_END), "C-test<04-21": (T_START, S2)}.items():
        r = rep(TR1[CHOSEN], a, b, CS1)
        pc = {m: v["ret"] for m, v in r["per_coin"].items()}
        per[p] = pc
        loo = {m: np.mean([pc[x] for x in V.MARKETS if x != m]) for m in V.MARKETS}
        print(f"  {p:14s} " + ", ".join(f"{m[4:]} {pct(v)}" for m, v in pc.items()) +
              " | leave-one-out port: " + ", ".join(f"-{m[4:]} {pct(v)}" for m, v in loo.items()))
    for p, (a, b) in {"TEST": (S1, T_END), "FULL": (T_START, T_END)}.items():
        cnt = {m: 0 for m in V.MARKETS}
        for key in COMBOS:
            r = rep(TR1[key], a, b, CS1)
            for m in V.MARKETS:
                cnt[m] += r["per_coin"][m]["ret"] > 0
        print(f"  #combos (of 12) with positive {p} sleeve return: " + ", ".join(f"{m[4:]} {v}" for m, v in cnt.items()))

    # ------------------------------------------------------------------ (e) doubled cost
    TR2 = sim_all(CS2)
    print("\n### (e) cost doubled (0.20%/side = 0.40% round trip): TRAIN | TEST | FULL")
    tr2 = {}
    for key in COMBOS:
        rr = [rep(TR2[key], a, b, CS2) for a, b in [(T_START, S1), (S1, T_END), (T_START, T_END)]]
        tr2[key] = rr[0]["ret"]
        print(f"  k={str(key[0]):>7s} N={key[1]:2d}: {pct(rr[0]['ret'])} | {pct(rr[1]['ret'])} (mdd {pct(rr[1]['mdd'])}) | {pct(rr[2]['ret'])}")
    best2 = max(tr2, key=tr2.get)
    print(f"  selection on TRAIN at 2x cost -> k={best2[0]} N={best2[1]}")
    walk_forward(TR2, CS2, "2x cost")

    # ------------------------------------------------------------------ (f) day-boundary phase
    print("\n### (f) day-boundary phase shift for k=0.7 N=10 (and grid-wide TEST), cost 0.10%/side")

    class ShiftCoin(V.Coin):
        def __init__(self, market, df, off_h):
            off = pd.Timedelta(hours=off_h)
            df2 = df.copy()
            # group by shifted day, but keep true bar timestamps
            tt = df2["t"]
            df2["t"] = tt - off
            super().__init__(market, df2)
            self.t = tt.values.astype("datetime64[ns]")
            self.days = (pd.to_datetime(self.days) + off).values.astype("datetime64[ns]")
            self.day_index = {pd.Timestamp(d): j for j, d in enumerate(self.days)}

    raw = {m: V.load(m) for m in V.MARKETS}
    for off in [0, 3, 6, 9, 12, 15, 18, 21]:
        sc = {m: ShiftCoin(m, raw[m], off) for m in V.MARKETS}
        V.CS = CS1
        trs = {key: {m: V.simulate(sc[m], key[0], key[1]) for m in V.MARKETS} for key in COMBOS}
        S1o = S1 + pd.Timedelta(hours=off)
        rr = [rep(trs[CHOSEN], a, b, CS1, sc) for a, b in [(T_START, S1o), (S1o, T_END), (T_START, T_END)]]
        tr_r = {key: rep(trs[key], T_START, S1o, CS1, sc)["ret"] for key in COMBOS}
        te_r = {key: rep(trs[key], S1o, T_END, CS1, sc)["ret"] for key in COMBOS}
        bk = max(tr_r, key=tr_r.get)
        te = np.array(list(te_r.values()))
        print(f"  day starts {off:02d}:00 UTC: k0.7N10 TRAIN {pct(rr[0]['ret'])} TEST {pct(rr[1]['ret'])} FULL {pct(rr[2]['ret'])} "
              f"| WF pick k={bk[0]} N={bk[1]} TEST {pct(te_r[bk])} | 12-combo TEST median {pct(np.median(te))} #>0 {(te > 0).sum()}/12")

    # ------------------------------------------------------------------ (g) placebo entry timing
    # NOTE: an earlier draft drew random entries on the REAL trade days; that is biased (those days are selected
    # because the high later exceeded the target) and was discarded. Fair placebo below: same NUMBER of trades per
    # coin and period, but days drawn at random (P1: any day after warm-up; P2: only days where open > SMA10),
    # entry at the open of a uniformly random 5m bar of that day, exit at next day's first open, same costs.
    print("\n### (g) fair placebo vs k=0.7 N=10: n-matched random days, random intraday entry, exit next open; "
          "1000 reps, compounded per coin (no MTM), cost 0.10%/side")
    rng = np.random.default_rng(12345)
    V.CS = CS1
    per_period = {"TRAIN": (T_START, S1), "TEST": (S1, T_END), "FULL": (T_START, T_END)}

    def comp_list(lst):
        return np.prod([1 + r for r in lst]) - 1 if lst else 0.0

    real = {p: np.mean([comp_list([x["ret"] for x in TR1[CHOSEN][m] if a <= x["entry_day"] < b])
                        for m in V.MARKETS]) for p, (a, b) in per_period.items()}
    for pname, use_filter in [("P1 any day", False), ("P2 filter days (open>SMA10)", True)]:
        res = {p: [] for p in per_period}
        for p, (a, b) in per_period.items():
            pools, nreal = {}, {}
            for m in V.MARKETS:
                c = coins[m]
                js = [j for j in range(V.WARMUP_DAY_IDX, len(c.days) - 1)
                      if a <= pd.Timestamp(c.days[j]) < b and (not use_filter or c.D_o[j] > c.sma_prev(j, 10))]
                pools[m] = js
                nreal[m] = sum(1 for x in TR1[CHOSEN][m] if a <= x["entry_day"] < b)
            for _ in range(1000):
                vals = []
                for m in V.MARKETS:
                    c = coins[m]
                    n = min(nreal[m], len(pools[m]))
                    js = rng.choice(pools[m], size=n, replace=False) if n else []
                    rr = []
                    for j in js:
                        i = rng.integers(c.first[j], c.last[j] + 1)
                        px_out = c.o[c.first[j + 1]]
                        rr.append(px_out * (1 - CS1) / (c.o[i] * (1 + CS1)) - 1)
                    vals.append(comp_list(rr))
                res[p].append(np.mean(vals))
        for p in per_period:
            s_ = np.array(res[p])
            print(f"  {pname:28s} {p:5s}: real {pct(real[p])} | placebo mean {pct(s_.mean())} median {pct(np.median(s_))} "
                  f"5-95% [{pct(np.percentile(s_, 5))}, {pct(np.percentile(s_, 95))}] | P(placebo>=real) {(s_ >= real[p]).mean():.3f}")

    # ------------------------------------------------------------------ (h) k=0 control
    print("\n### (h) control k=0 (filter only, buy at day open, sell next day open), cost 0.10%/side: TRAIN | TEST | FULL")
    TR0 = sim_all(CS1, combos=[(0.0, 3), (0.0, 5), (0.0, 10)])
    for key, trs in TR0.items():
        rr = [rep(trs, a, b, CS1) for a, b in [(T_START, S1), (S1, T_END), (T_START, T_END)]]
        print(f"  k=0 N={key[1]:2d}: {pct(rr[0]['ret'])} (n {rr[0]['n']}) | {pct(rr[1]['ret'])} (n {rr[1]['n']}) | {pct(rr[2]['ret'])}")


if __name__ == "__main__":
    main()
