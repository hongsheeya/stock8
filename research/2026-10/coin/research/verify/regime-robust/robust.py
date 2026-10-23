"""Adversarial ROBUSTNESS check of the "regime" family claim (selected B100).

Reuses the researcher's regime.py (copied here unchanged) for loading, signals,
the bar simulator and the window runner. Perturbations:
  0  reproduce the claim (TRAIN/TEST/FULL of all 12 combos, selection)
  a  neighbouring / off-grid parameters (coin N x BTC N, gate-only, S100 ...)
  b  different splits: early=START..2026-04-21, late=2026-04-21..end
     select on early -> report late, select on late -> report early
  c  best 5 portfolio days removed (TEST and FULL)
  d  per-coin breakdown + leave-one-coin-out
  e  cost doubled (0.20%/side = 0.40% round trip), whole grid re-selected
  f  extra: decision clock shifted (06/12/18 UTC), fill delay (1 bar, 12 bars),
     TEST end date moved earlier (end-of-data mark sensitivity)
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import regime as R  # noqa: E402

R.CANDLES = os.path.normpath(os.path.join(HERE, "..", "..", "..", "candles"))
M = R.MARKETS
SPLIT2 = pd.Timestamp("2026-04-21")


def pct(x):
    return f"{x * 100:+7.2f}%"


data = {m: R.load5m(m) for m in M}
closes = {m: R.daily_closes(m, data[m])[0] for m in M}
END = max(data[m]["t"].iloc[-1] for m in M) + pd.Timedelta("5min")
W = {"TRAIN": (R.START, R.SPLIT), "TEST": (R.SPLIT, END), "FULL": (R.START, END),
     "EARLY": (R.START, SPLIT2), "LATE": (SPLIT2, END)}


def posmap_from_daily(sigs, delay=0):
    """sigs[m]: daily bool Series (decision at close of that UTC day)."""
    pm = {}
    for m in M:
        pos_day = sigs[m].astype(int).shift(1)
        p = data[m]["day"].map(pos_day).fillna(0).astype(int)
        if delay:
            p = p.shift(delay).fillna(0).astype(int)
        pm[m] = p
    return pm


def sig_grid(kind, p):
    return {m: R.signal(kind, p, closes[m], closes["KRW-BTC"]) for m in M}


def sig_gate(nc, nb, coin_filter=True, btc_filter=True):
    out = {}
    B = closes["KRW-BTC"]
    bg = B > B.rolling(nb).mean() if btc_filter else pd.Series(True, index=B.index)
    for m in M:
        C = closes[m]
        cf = C > C.rolling(nc).mean() if coin_filter else pd.Series(True, index=C.index)
        out[m] = cf & bg.reindex(C.index).ffill().fillna(False).astype(bool)
    return out


def run(pm, wins=("TRAIN", "TEST", "FULL", "EARLY", "LATE")):
    return {w: R.run_window(data, pm, *W[w]) for w in wins}


def coinstr(r):
    return " ".join(f"{m[4:]} {pct(r['coin'][m]['ret'])}" for m in M)


ones = {m: pd.Series(1, index=data[m].index) for m in M}
BH = run(ones)

# ---------------------------------------------------------------- 0 reproduce
print("== 0. REPRODUCTION (cost 0.10%/side) ==")
GRIDRES = {}
for name, kind, p in R.GRID:
    GRIDRES[name] = run(posmap_from_daily(sig_grid(kind, p)))
print(f"{'combo':8s} {'TRAIN':>9s} {'TEST':>9s} {'FULL':>9s} {'EARLY':>9s} {'LATE':>9s}")
for name, _, _ in R.GRID:
    r = GRIDRES[name]
    print(f"{name:8s} " + " ".join(f"{pct(r[w]['ret'])}" for w in ["TRAIN", "TEST", "FULL", "EARLY", "LATE"]))
print(f"{'B&H':8s} " + " ".join(f"{pct(BH[w]['ret'])}" for w in ["TRAIN", "TEST", "FULL", "EARLY", "LATE"]))
best = max(GRIDRES, key=lambda n: GRIDRES[n]["TRAIN"]["ret"])
b = GRIDRES["B100"]
print(f"selected on TRAIN: {best}; B100 TRAIN {pct(b['TRAIN']['ret'])} mdd {pct(b['TRAIN']['mdd'])} n {b['TRAIN']['trades']}"
      f" | TEST {pct(b['TEST']['ret'])} mdd {pct(b['TEST']['mdd'])} n {b['TEST']['trades']} win {b['TEST']['win']*100:.1f}% tim {b['TEST']['tim']*100:.1f}%"
      f" | FULL {pct(b['FULL']['ret'])} mdd {pct(b['FULL']['mdd'])} n {b['FULL']['trades']}")
print("FULL quarters B100:", " ".join(pct(x) for x in R.quarters(b["FULL"]["port"])))

# ------------------------------------------------------------- a neighbours
print("\n== a. NEIGHBOURING / OFF-GRID PARAMETERS (TEST and FULL, cost 0.10%/side) ==")
print(f"{'variant':26s} {'TRAIN':>9s} {'TEST':>9s} {'FULL':>9s} {'EARLY':>9s} {'LATE':>9s} | TEST per coin")
variants = []
for nc in [60, 80, 90, 100, 110, 120, 150]:
    variants.append((f"coin{nc}&btc{nc}", sig_gate(nc, nc)))
for nc, nb in [(80, 100), (120, 100), (100, 80), (100, 120), (50, 100), (100, 50), (20, 100), (100, 20)]:
    variants.append((f"coin{nc}&btc{nb}", sig_gate(nc, nb)))
variants.append(("S100 (no BTC gate)", sig_gate(100, 100, btc_filter=False)))
variants.append(("BTCgate100 only", sig_gate(100, 100, coin_filter=False)))
variants.append(("BTCgate50 only", sig_gate(50, 50, coin_filter=False)))
variants.append(("BTCgate200 only", sig_gate(200, 200, coin_filter=False)))
NB = {}
for name, s in variants:
    r = run(posmap_from_daily(s))
    NB[name] = r
    print(f"{name:26s} " + " ".join(pct(r[w]["ret"]) for w in ["TRAIN", "TEST", "FULL", "EARLY", "LATE"])
          + " | " + coinstr(r["TEST"]))
tv = [NB[n]["TEST"]["ret"] for n in NB]
print(f"variants: {len(tv)}; TEST > cash: {sum(x > 0 for x in tv)}; TEST > B&H ({pct(BH['TEST']['ret'])}): "
      f"{sum(x > BH['TEST']['ret'] for x in tv)}; TEST median {pct(float(np.median(tv)))}")
fv = [NB[n]["FULL"]["ret"] for n in NB]
print(f"FULL > cash: {sum(x > 0 for x in fv)}/{len(fv)}; FULL median {pct(float(np.median(fv)))}")

# ------------------------------------------------------------ b other splits
print("\n== b. DIFFERENT SPLITS (split 2026-04-21) ==")
for tr, te in [("EARLY", "LATE"), ("LATE", "EARLY")]:
    rank = sorted(GRIDRES, key=lambda n: -GRIDRES[n][tr]["ret"])
    sel = rank[0]
    print(f"train={tr} {W[tr][0].date()}..{W[tr][1].date()}  test={te}")
    print("  train ranking:", ", ".join(f"{n} {pct(GRIDRES[n][tr]['ret'])}" for n in rank[:5]))
    print(f"  selected {sel}: train {pct(GRIDRES[sel][tr]['ret'])}  TEST {pct(GRIDRES[sel][te]['ret'])} "
          f"mdd {pct(GRIDRES[sel][te]['mdd'])} n {GRIDRES[sel][te]['trades']} | {coinstr(GRIDRES[sel][te])}")
    print(f"  B100 on this test: {pct(GRIDRES['B100'][te]['ret'])} mdd {pct(GRIDRES['B100'][te]['mdd'])} "
          f"n {GRIDRES['B100'][te]['trades']} | {coinstr(GRIDRES['B100'][te])}")
    print(f"  B&H on this test: {pct(BH[te]['ret'])} mdd {pct(BH[te]['mdd'])}; "
          f"combos > cash on this test {sum(GRIDRES[n][te]['ret'] > 0 for n in GRIDRES)}/12")

# ------------------------------------------------------ c best 5 days removed
print("\n== c. BEST 5 PORTFOLIO DAYS REMOVED (B100) ==")


def drop_best(port, k=5):
    d = port.resample("D").last().dropna()
    v = np.concatenate([[1.0], d.to_numpy()])
    r = pd.Series(v[1:] / v[:-1] - 1, index=d.index)
    top = r.sort_values(ascending=False).head(k)
    tot = float(np.prod(1 + r) - 1)
    rest = float(np.prod(1 + r.drop(top.index)) - 1)
    return tot, rest, top


for w in ["TEST", "FULL", "TRAIN", "LATE"]:
    for nm, res in [("B100", GRIDRES["B100"][w]), ("B&H", BH[w])]:
        tot, rest, top = drop_best(res["port"])
        print(f"  {w:5s} {nm:5s} ret {pct(tot)} -> without best 5 days {pct(rest)} | best days "
              + ", ".join(f"{d.date()} {pct(x)}" for d, x in top.items()))

# also the best 5 single coin-days, removed per coin, B100 TEST
print("  B100 TEST, best 5 coin-days removed (across all coins):")
cd = []
for m in M:
    lo, hi = W["TEST"]
    df = data[m]
    sel = (df["t"] >= lo) & (df["t"] < hi)
    eq, _ = R.simulate(df.loc[sel, "o"].to_numpy(), df.loc[sel, "c"].to_numpy(),
                       posmap_from_daily(sig_grid("btc", 100))[m][sel].to_numpy())
    s = pd.Series(eq, index=df.loc[sel, "t"].to_numpy()).resample("D").last().dropna()
    v = np.concatenate([[1.0], s.to_numpy()])
    for d, x in zip(s.index, v[1:] / v[:-1] - 1):
        cd.append((x, m, d))
coin_eq = {m: 1.0 for m in M}
top5 = sorted(cd, reverse=True)[:5]
for x, m, d in cd:
    if (x, m, d) not in top5:
        coin_eq[m] *= 1 + x
print("   removed:", ", ".join(f"{m[4:]} {d.date()} {pct(x)}" for x, m, d in top5))
print(f"   portfolio TEST without them {pct(np.mean([coin_eq[m] - 1 for m in M]))}")

# ---------------------------------------------------------------- d per coin
print("\n== d. PER-COIN AND LEAVE-ONE-COIN-OUT (B100) ==")
for w in ["TRAIN", "TEST", "FULL", "EARLY", "LATE"]:
    r = GRIDRES["B100"][w]
    rets = {m: r["coin"][m]["ret"] for m in M}
    loo = {m: np.mean([rets[k] for k in M if k != m]) for m in M}
    print(f"  {w:5s} port {pct(r['ret'])} | {coinstr(r)}")
    print(f"        leave-one-out: " + " ".join(f"-{m[4:]} {pct(loo[m])}" for m in M)
          + f" | coins > 0: {sum(v > 0 for v in rets.values())}/5"
          + f" | coins > B&H: {sum(rets[m] > BH[w]['coin'][m]['ret'] for m in M)}/5")

# ------------------------------------------------------------ e cost doubled
print("\n== e. COST DOUBLED (0.20%/side = 0.40% round trip) ==")
R.SIDE = 0.002
G2 = {}
for name, kind, p in R.GRID:
    G2[name] = run(posmap_from_daily(sig_grid(kind, p)), ("TRAIN", "TEST", "FULL", "EARLY", "LATE"))
BH2 = run(ones, ("TRAIN", "TEST", "FULL"))
for name, _, _ in R.GRID:
    print(f"  {name:8s} TRAIN {pct(G2[name]['TRAIN']['ret'])} TEST {pct(G2[name]['TEST']['ret'])} FULL {pct(G2[name]['FULL']['ret'])}")
best2 = max(G2, key=lambda n: G2[n]["TRAIN"]["ret"])
print(f"  selected on TRAIN at 2x cost: {best2}; TEST {pct(G2[best2]['TEST']['ret'])} FULL {pct(G2[best2]['FULL']['ret'])}")
print(f"  B100 2x cost: TRAIN {pct(G2['B100']['TRAIN']['ret'])} TEST {pct(G2['B100']['TEST']['ret'])} "
      f"FULL {pct(G2['B100']['FULL']['ret'])} | TEST {coinstr(G2['B100']['TEST'])}")
print(f"  B&H 2x cost: TEST {pct(BH2['TEST']['ret'])} FULL {pct(BH2['FULL']['ret'])}")
print(f"  combos > cash on TEST at 2x cost: {sum(G2[n]['TEST']['ret'] > 0 for n in G2)}/12")
for tr, te in [("EARLY", "LATE"), ("LATE", "EARLY")]:
    s2 = max(G2, key=lambda n: G2[n][tr]["ret"])
    print(f"  2x cost split train={tr}: selected {s2} -> {te} {pct(G2[s2][te]['ret'])}; B100 {te} {pct(G2['B100'][te]['ret'])}")
R.SIDE = 0.001

# ------------------------------------------------------------ f extra checks
print("\n== f1. DECISION CLOCK SHIFTED (B100, close at H:00 UTC, held H..H+24h) ==")
warm = {}
for m in M:
    w = pd.read_json(os.path.join(HERE, f"warmup_daily_{m}.json"))
    w["t"] = pd.to_datetime(w["t"])
    warm[m] = w.set_index("t")["c"]
for H in [0, 3, 6, 9, 12, 15, 18, 21]:
    ch, dh = {}, {}
    for m in M:
        df = data[m]
        dh[m] = (df["t"] - pd.Timedelta(hours=H)).dt.floor("D")
        cs = df.groupby(dh[m])["c"].last()
        first = R.START - pd.Timedelta("1D")  # session label 2025-10-21 = 10-21 H:00 .. 10-22 H:00
        s = pd.concat([warm[m][warm[m].index < first], cs[cs.index >= first]])
        ch[m] = s.reindex(pd.date_range(s.index[0], s.index[-1], freq="D")).ffill()
    B = ch["KRW-BTC"]
    bg = B > B.rolling(100).mean()
    pm = {}
    for m in M:
        sg = ((ch[m] > ch[m].rolling(100).mean()) & bg.reindex(ch[m].index).ffill()).astype(int).shift(1)
        pm[m] = dh[m].map(sg).fillna(0).astype(int)
    r = run(pm, ("TRAIN", "TEST", "FULL"))
    print(f"  H={H:02d} TRAIN {pct(r['TRAIN']['ret'])} TEST {pct(r['TEST']['ret'])} mdd {pct(r['TEST']['mdd'])} "
          f"FULL {pct(r['FULL']['ret'])} | TEST {coinstr(r['TEST'])}")

print("\n== f2. FILL DELAY (B100) ==")
for dly in [0, 1, 12, 72]:
    r = run(posmap_from_daily(sig_grid("btc", 100), delay=dly), ("TRAIN", "TEST", "FULL"))
    print(f"  delay {dly:3d} bars: TRAIN {pct(r['TRAIN']['ret'])} TEST {pct(r['TEST']['ret'])} FULL {pct(r['FULL']['ret'])}")

print("\n== f3. TEST END MOVED EARLIER (B100 vs B&H, positions liquidated at new end) ==")
pmB = posmap_from_daily(sig_grid("btc", 100))
for k in [0, 1, 3, 7, 14, 21, 30]:
    e = END - pd.Timedelta(days=k)
    r = R.run_window(data, pmB, R.SPLIT, e)
    bh = R.run_window(data, ones, R.SPLIT, e)
    print(f"  end {str(e)[:16]}: B100 TEST {pct(r['ret'])} | B&H {pct(bh['ret'])} | {coinstr(r)}")
p = GRIDRES["B100"]["TEST"]["port"]
pd_ = p.resample("D").last()
print(f"  B100 TEST portfolio equity: min {pct(pd_.min() - 1)} on {pd_.idxmin().date()}, max {pct(pd_.max() - 1)} on {pd_.idxmax().date()}; "
      f"days with equity > 1: {(pd_ > 1).sum()}/{len(pd_)}")

print("\n== B100 TEST trades ==")
for m in M:
    s = R.signal("btc", 100, closes[m], closes["KRW-BTC"]).astype(int).shift(1)
    s = s[s.index >= R.SPLIT - pd.Timedelta("1D")]
    ch_ = s[s.diff() != 0].dropna()
    print(f"  {m}: " + " ".join(f"{d.date()}:{'IN' if v else 'OUT'}" for d, v in ch_.items()))
