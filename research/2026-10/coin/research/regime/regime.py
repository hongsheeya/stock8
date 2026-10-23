"""Family "regime": hold a coin only while its daily trend/regime is up, cash otherwise.

PRE-REGISTRATION (written before any result was computed; do not edit the grid)
------------------------------------------------------------------------------
Universe : KRW-BTC, KRW-ETH, KRW-XRP, KRW-SOL, KRW-DOGE (Upbit spot, long only).
Clock    : Upbit daily candle = 00:00 UTC. A decision is taken on each daily
           CLOSE (= close of the last 5m bar of the UTC day) and filled at the
           open of the NEXT 5m bar (normally the 00:00 UTC bar of the next day).
           The position is held for that whole day; it can only change at the
           next daily close. No intraday stops, no same-bar fills.
Cost     : 0.10% per side (0.05% fee + 0.05% slippage), i.e. ~0.20% per round
           trip, charged multiplicatively on every entry and every exit.
Sizing   : 20% of the seed per coin, all-in on that slice when the signal is on,
           cash otherwise; each slice compounds on its own (no rebalancing).
           Portfolio equity = mean of the 5 slice equities.
Grid (12 combos, same combo for all 5 coins), C = daily close:
  S20  S50  S100  : C > SMA_N(C)                       N = 20 / 50 / 100
  M7   M14  M30   : C / C[L days ago] - 1 > 0           L = 7 / 14 / 30
  X5_20 X10_50 X20_100 : SMA_fast(C) > SMA_slow(C)      (5,20) (10,50) (20,100)
  B20  B50  B100  : C > SMA_N(C) AND BTC_C > SMA_N(BTC_C) (BTC regime gate)
Selection: the combo with the highest TRAIN portfolio return (after costs).
           TEST is then reported untouched; no re-tuning on TEST.
Windows  : TRAIN = 2025-10-22T00:00 .. 2026-06-21T00:00 UTC (exclusive)
           TEST  = 2026-06-21T00:00 .. end of data
           FULL  = 2025-10-22T00:00 .. end of data
           Each window is simulated stand-alone: flat at the window start,
           first fill at the window's first bar open if the last daily signal
           before the window is ON, and any open position is liquidated at the
           window's last close (with exit cost) so returns are net.
Warm-up  : indicator history before 2025-10-22 comes from Upbit daily candles
           (fetch_warmup.py); no trade is simulated before 2025-10-22.
Drawdown : on the portfolio equity marked to market at every 5m close.
Quarters : FULL split at 2026-01-21, 2026-04-22, 2026-07-22 (00:00 UTC).
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CANDLES = os.path.normpath(os.path.join(HERE, "..", "..", "candles"))
MARKETS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]
SIDE = 0.001
START = pd.Timestamp("2025-10-22")
SPLIT = pd.Timestamp("2026-06-21")
QBOUNDS = [pd.Timestamp("2026-01-21"), pd.Timestamp("2026-04-22"), pd.Timestamp("2026-07-22")]

GRID = [
    ("S20", "sma", 20), ("S50", "sma", 50), ("S100", "sma", 100),
    ("M7", "mom", 7), ("M14", "mom", 14), ("M30", "mom", 30),
    ("X5_20", "dual", (5, 20)), ("X10_50", "dual", (10, 50)), ("X20_100", "dual", (20, 100)),
    ("B20", "btc", 20), ("B50", "btc", 50), ("B100", "btc", 100),
]
NEIGHBOURS = {
    "S20": ["S50", "B20"], "S50": ["S20", "S100", "B50"], "S100": ["S50", "B100"],
    "M7": ["M14"], "M14": ["M7", "M30"], "M30": ["M14"],
    "X5_20": ["X10_50"], "X10_50": ["X5_20", "X20_100"], "X20_100": ["X10_50"],
    "B20": ["B50", "S20"], "B50": ["B20", "B100", "S50"], "B100": ["B50", "S100"],
}


def load5m(m):
    df = pd.DataFrame(json.load(open(os.path.join(CANDLES, f"{m}_5m.json"))))
    df["t"] = pd.to_datetime(df["t"])
    df = df.sort_values("t").drop_duplicates("t").reset_index(drop=True)
    df["day"] = df["t"].dt.floor("D")
    return df


def daily_closes(m, df):
    w = pd.DataFrame(json.load(open(os.path.join(HERE, f"warmup_daily_{m}.json"))))
    w["t"] = pd.to_datetime(w["t"])
    ws = w.set_index("t")["c"]
    ds = df.groupby("day")["c"].last()
    for d in [pd.Timestamp("2025-10-21"), pd.Timestamp("2025-10-22")]:
        if d in ws.index and d in ds.index and abs(ws[d] / ds[d] - 1) > 1e-9:
            print(f"  WARN {m} {d.date()} api close {ws[d]} != 5m close {ds[d]}")
    s = pd.concat([ws[ws.index < START], ds[ds.index >= START]])
    full = pd.date_range(s.index[0], s.index[-1], freq="D")
    nmiss = len(full.difference(s.index))
    return s.reindex(full).ffill(), nmiss


def signal(kind, p, C, B):
    if kind == "sma":
        return C > C.rolling(p).mean()
    if kind == "mom":
        return C > C.shift(p)
    if kind == "dual":
        return C.rolling(p[0]).mean() > C.rolling(p[1]).mean()
    if kind == "btc":
        B = B.reindex(C.index).ffill()
        return (C > C.rolling(p).mean()) & (B > B.rolling(p).mean())
    raise ValueError(kind)


def simulate(o, c, pos):
    """pos[i] = 1 if long during bar i (entered at o[i] when pos[i-1] == 0)."""
    n = len(pos)
    prev = np.concatenate([[0], pos[:-1]])
    cprev = np.concatenate([[np.nan], c[:-1]])
    r = np.ones(n)
    hold = (pos == 1) & (prev == 1)
    ent = (pos == 1) & (prev == 0)
    ex = (pos == 0) & (prev == 1)
    r[hold] = c[hold] / cprev[hold]
    r[ent] = c[ent] / o[ent] * (1 - SIDE)
    r[ex] = o[ex] / cprev[ex] * (1 - SIDE)
    eq = np.cumprod(r)
    if pos[-1] == 1:
        eq[-1] *= (1 - SIDE)  # liquidate at the window's last close
    ent_i, ex_i = np.where(ent)[0], np.where(ex)[0]
    trades = []
    for i in ent_i:
        later = ex_i[ex_i > i]
        px = o[later[0]] if len(later) else c[-1]
        trades.append(px / o[i] * (1 - SIDE) ** 2 - 1)
    return eq, trades


def mdd(curve):
    v = np.concatenate([[1.0], curve])
    return float((v / np.maximum.accumulate(v) - 1).min())


def run_window(data, posmap, lo, hi):
    """posmap[m]: pd.Series bar-position aligned to data[m] rows."""
    coin = {}
    curves = []
    for m in MARKETS:
        df = data[m]
        sel = (df["t"] >= lo) & (df["t"] < hi)
        o, c = df.loc[sel, "o"].to_numpy(), df.loc[sel, "c"].to_numpy()
        pos = posmap[m][sel].to_numpy().astype(int)
        eq, tr = simulate(o, c, pos)
        t = df.loc[sel, "t"].to_numpy()
        coin[m] = {"ret": eq[-1] - 1, "mdd": mdd(eq), "trades": tr, "tim": pos.mean(),
                   "curve": pd.Series(eq, index=t)}
        curves.append(coin[m]["curve"])
    idx = sorted(set().union(*[s.index for s in curves]))
    port = pd.concat([s.reindex(idx).ffill().fillna(1.0) for s in curves], axis=1).mean(axis=1)
    alltr = [x for m in MARKETS for x in coin[m]["trades"]]
    out = {
        "ret": float(np.mean([coin[m]["ret"] for m in MARKETS])),
        "mdd": mdd(port.to_numpy()),
        "trades": len(alltr),
        "win": float(np.mean([x > 0 for x in alltr])) if alltr else float("nan"),
        "avg": float(np.mean(alltr)) if alltr else float("nan"),
        "tim": float(np.mean([coin[m]["tim"] for m in MARKETS])),
        "coin": {m: {k: v for k, v in coin[m].items() if k != "curve"} for m in MARKETS},
        "port": port,
    }
    for m in MARKETS:
        tr = coin[m]["trades"]
        out["coin"][m]["n"] = len(tr)
        out["coin"][m]["win"] = float(np.mean([x > 0 for x in tr])) if tr else float("nan")
        del out["coin"][m]["trades"]
    return out


def quarters(port):
    edges = [1.0]
    for b in QBOUNDS:
        edges.append(float(port[port.index < b].iloc[-1]))
    edges.append(float(port.iloc[-1]))
    return [edges[k + 1] / edges[k] - 1 for k in range(4)]


def pct(x):
    return f"{x * 100:+7.2f}%"


def line(name, r):
    return (f"{name:8s} ret {pct(r['ret'])} mdd {pct(r['mdd'])} trades {r['trades']:4d} "
            f"win {r['win'] * 100:5.1f}% avg {pct(r['avg'])} tim {r['tim'] * 100:5.1f}%")


def main():
    data, closes, gaps = {}, {}, {}
    for m in MARKETS:
        df = load5m(m)
        data[m] = df
        closes[m], nmiss = daily_closes(m, df)
        span = df[df["t"] >= START]
        exp = int((span["t"].iloc[-1] - span["t"].iloc[0]) / pd.Timedelta("5min")) + 1
        no00 = (span.groupby("day")["t"].min().dt.hour != 0).sum() + 0
        gaps[m] = (exp - len(span), nmiss, int(no00))
        print(f"{m}: 5m bars from START {len(span)}, missing 5m bars {exp - len(span)}, "
              f"missing whole days {nmiss}, days whose first bar is not 00:00 {no00}")
    end = max(data[m]["t"].iloc[-1] for m in MARKETS) + pd.Timedelta("5min")
    windows = {"TRAIN": (START, SPLIT), "TEST": (SPLIT, end), "FULL": (START, end)}

    def posmap_for(kind, p):
        pm = {}
        for m in MARKETS:
            sig = signal(kind, p, closes[m], closes["KRW-BTC"]).astype(int)
            pos_day = sig.shift(1)  # signal at close of D-1 -> held during day D
            pm[m] = data[m]["day"].map(pos_day).fillna(0).astype(int)
        return pm

    ones = {m: pd.Series(1, index=data[m].index) for m in MARKETS}
    bh = {w: run_window(data, ones, *windows[w]) for w in windows}
    print("\nBUY & HOLD (equal weight, same windows, entry+exit cost)")
    for w in windows:
        print(" ", line(w, bh[w]), "| per coin " + " ".join(f"{m[4:]} {pct(bh[w]['coin'][m]['ret'])}" for m in MARKETS))
    print("  FULL quarters", " ".join(pct(x) for x in quarters(bh["FULL"]["port"])))

    res = {}
    print("\nGRID - TRAIN (selection uses TRAIN return only)")
    for name, kind, p in GRID:
        pm = posmap_for(kind, p)
        res[name] = {w: run_window(data, pm, *windows[w]) for w in windows}
        r = res[name]["TRAIN"]
        print(" ", line(name, r), "| " + " ".join(f"{m[4:]} {pct(r['coin'][m]['ret'])}" for m in MARKETS))
    best = max(GRID, key=lambda g: res[g[0]]["TRAIN"]["ret"])[0]
    print(f"\nSELECTED on TRAIN: {best} (TRAIN portfolio {pct(res[best]['TRAIN']['ret'])})")

    print("\nGRID - TEST (reported after selection; not used to choose)")
    for name, _, _ in GRID:
        r = res[name]["TEST"]
        tag = " <== selected" if name == best else (" (neighbour)" if name in NEIGHBOURS[best] else "")
        print(" ", line(name, r), "| " + " ".join(f"{m[4:]} {pct(r['coin'][m]['ret'])}" for m in MARKETS) + tag)
    print("\nGRID - FULL")
    for name, _, _ in GRID:
        r = res[name]["FULL"]
        print(" ", line(name, r), "| Q " + " ".join(pct(x) for x in quarters(r["port"])))

    sel = res[best]
    print(f"\n==== SELECTED {best} ====")
    for w in windows:
        r = sel[w]
        print(" ", line(w, r), f"| B&H {pct(bh[w]['ret'])} (mdd {pct(bh[w]['mdd'])}) | cash +0.00%")
        for m in MARKETS:
            c = sel[w]["coin"][m]
            print(f"     {m:9s} ret {pct(c['ret'])} mdd {pct(c['mdd'])} trades {c['n']:3d} "
                  f"win {c['win'] * 100:5.1f}% tim {c['tim'] * 100:5.1f}% | B&H {pct(bh[w]['coin'][m]['ret'])}")
    print("  FULL quarters  ", " ".join(pct(x) for x in quarters(sel["FULL"]["port"])))
    print("  B&H quarters   ", " ".join(pct(x) for x in quarters(bh["FULL"]["port"])))
    print("  neighbours TEST", ", ".join(f"{n} {pct(res[n]['TEST']['ret'])}" for n in NEIGHBOURS[best]))
    beat_cash = [n for n, _, _ in GRID if res[n]["TEST"]["ret"] > 0]
    beat_bh = [n for n, _, _ in GRID if res[n]["TEST"]["ret"] > bh["TEST"]["ret"]]
    print(f"  combos > cash on TEST: {len(beat_cash)}/12 {beat_cash}")
    print(f"  combos > B&H  on TEST: {len(beat_bh)}/12")

    def strip(r):
        return {k: v for k, v in r.items() if k != "port"}
    dump = {"selected": best, "gaps": gaps, "bh": {w: strip(bh[w]) for w in windows},
            "bh_quarters": quarters(bh["FULL"]["port"]),
            "grid": {n: {w: strip(res[n][w]) for w in windows} | {"quarters": quarters(res[n]["FULL"]["port"])}
                     for n, _, _ in GRID}}
    json.dump(dump, open(os.path.join(HERE, "results.json"), "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
