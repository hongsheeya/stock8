"""Independent re-implementation of the VBO rule (verifier, lens = code).

Pure-python (no pandas) on purpose so it shares no code path with vbo_research.py.

Rule: day = UTC date of the 5m bar open time (t[:10]).
  target_d = open_d + k * (high_{d-1} - low_{d-1}),  filter open_d > mean(close_{d-N..d-1})
  entry    = first 5m bar of day d with high >= target, fill = max(target, bar open)
  exit     = open of first bar of the next available day (last close if none)
  ret      = exit*(1-0.001) / (fill*(1+0.001)) - 1
TRAIN = entry day < 2026-06-21, TEST = entry day >= 2026-06-21.
"""
import json
import math
import os
import statistics as st

BASE = r"C:\Users\변기국~1\AppData\Local\Temp\claude\C--dev\93ae6530-93fd-4894-8774-b698a96bffc9\scratchpad\coin"
MARKETS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]
SPLIT = "2026-06-21"
CS = 0.001


def load(m):
    with open(os.path.join(BASE, "candles", f"{m}_5m.json"), encoding="utf-8") as f:
        rows = json.load(f)
    rows.sort(key=lambda r: r["t"])
    return rows


def daily(rows):
    days, idx = [], {}
    for i, r in enumerate(rows):
        d = r["t"][:10]
        if d not in idx:
            idx[d] = [i, i]
            days.append(d)
        else:
            idx[d][1] = i
    O, H, L, C, A, B = [], [], [], [], [], []
    for d in days:
        a, b = idx[d]
        seg = rows[a:b + 1]
        O.append(seg[0]["o"]); C.append(seg[-1]["c"])
        H.append(max(x["h"] for x in seg)); L.append(min(x["l"] for x in seg))
        A.append(a); B.append(b)
    return days, O, H, L, C, A, B


def run(rows, D, k, n, start_day="2025-11-11", tick_round=False):
    days, O, H, L, C, A, B = D
    nd = len(days)
    trades = []
    for j in range(1, nd):
        if days[j] < start_day:
            continue
        if k == "noise20":
            if j < 21:
                continue
            ns = []
            for q in range(j - 20, j):
                r = H[q] - L[q]
                ns.append(1 - abs(C[q] - O[q]) / r if r > 0 else 1.0)
            kk = sum(ns) / 20
        else:
            kk = k
        if j - n < 0:
            continue
        sma = sum(C[j - n:j]) / n
        if not (O[j] > sma):
            continue
        tgt = O[j] + kk * (H[j - 1] - L[j - 1])
        if tick_round:
            tgt = round_up_tick(tgt)
        ent = None
        for i in range(A[j], B[j] + 1):
            if rows[i]["h"] >= tgt:
                ent = i
                break
        if ent is None:
            continue
        fill = max(tgt, rows[ent]["o"])
        if j + 1 < nd:
            xi = A[j + 1]; px = rows[xi]["o"]
        else:
            xi = len(rows) - 1; px = rows[xi]["c"]
        ret = px * (1 - CS) / (fill * (1 + CS)) - 1
        trades.append(dict(day=days[j], ent=ent, xi=xi, fill=fill, tgt=tgt, exit=px, ret=ret,
                           tin=rows[ent]["t"], tout=rows[xi]["t"]))
    return trades


TICK = {"KRW-BTC": 1000.0, "KRW-ETH": 1000.0, "KRW-XRP": 1.0, "KRW-SOL": 100.0, "KRW-DOGE": 0.1}  # observed min price step in the data
CUR_TICK = [None]


def round_up_tick(p):
    tk = CUR_TICK[0]
    return math.ceil(p / tk - 1e-9) * tk


def compound(trs):
    e = 1.0
    for t in trs:
        e *= 1 + t["ret"]
    return e - 1


def mtm_mdd(all_rows, all_trades, t0, t1):
    """Portfolio MDD on a union 5m timestamp grid in [t0, t1), ffilled closes, exit cost included."""
    ts = sorted(set(r["t"] for m in MARKETS for r in all_rows[m] if t0 <= r["t"] < t1))
    port = [0.0] * len(ts)
    pos = {t: i for i, t in enumerate(ts)}
    for m in MARKETS:
        rows = all_rows[m]
        close_at = {r["t"]: r["c"] for r in rows}
        trs = [t for t in all_trades[m] if t0 <= t["day"] < t1]
        # state per grid bar
        eq = []
        cur = 1.0
        ti = 0
        lastc = None
        open_tr = None
        for t in ts:
            if t in close_at:
                lastc = close_at[t]
            # close trade if this bar is the exit bar (exit at its open -> realized before marking)
            if open_tr is not None and t >= open_tr["tout"] and open_tr["tout"] != rows[-1]["t"]:
                cur *= 1 + open_tr["ret"]; open_tr = None
            if open_tr is None and ti < len(trs) and t == trs[ti]["tin"]:
                open_tr = trs[ti]; ti += 1
            if open_tr is not None:
                eq.append(cur * lastc * (1 - CS) / (open_tr["fill"] * (1 + CS)))
            else:
                eq.append(cur)
        if open_tr is not None:
            cur *= 1 + open_tr["ret"]
            eq[-1] = cur
        for i, v in enumerate(eq):
            port[i] += v / len(MARKETS)
    pk, dd = -1, 0.0
    for v in port:
        pk = max(pk, v); dd = min(dd, v / pk - 1)
    return dd, port[-1] - 1


def main():
    R = {m: load(m) for m in MARKETS}
    DD = {m: daily(R[m]) for m in MARKETS}
    for m in MARKETS:
        d = DD[m][0]
        print(m, "days", len(d), d[0], d[-1], "trade start idx of 2025-11-11:", d.index("2025-11-11"))

    grid = [(k, n) for k in [0.3, 0.5, 0.7, "noise20"] for n in [3, 5, 10]]
    res = {}
    print("\n k      N |  TRAIN    TEST   FULL  (nTR/nTE)")
    for k, n in grid:
        tr = {m: run(R[m], DD[m], k, n) for m in MARKETS}
        trn = st.mean(compound([t for t in tr[m] if t["day"] < SPLIT]) for m in MARKETS)
        tst = st.mean(compound([t for t in tr[m] if t["day"] >= SPLIT]) for m in MARKETS)
        ful = st.mean(compound(tr[m]) for m in MARKETS)
        ntr = sum(1 for m in MARKETS for t in tr[m] if t["day"] < SPLIT)
        nte = sum(1 for m in MARKETS for t in tr[m] if t["day"] >= SPLIT)
        res[(k, n)] = (trn, tst, ful, tr)
        print(f" {str(k):7s}{n:3d} | {100*trn:+7.2f} {100*tst:+7.2f} {100*ful:+7.2f}  ({ntr}/{nte})")
    best = max(res, key=lambda x: res[x][0])
    print("best on TRAIN:", best)

    trn, tst, ful, tr = res[(0.7, 10)]
    print("\nCHOSEN k=0.7 N=10")
    for lab, sel in [("TRAIN", lambda t: t["day"] < SPLIT), ("TEST", lambda t: t["day"] >= SPLIT), ("FULL", lambda t: True)]:
        rr = [t["ret"] for m in MARKETS for t in tr[m] if sel(t)]
        pc = {m[4:]: round(100 * compound([t for t in tr[m] if sel(t)]), 2) for m in MARKETS}
        n_ = {m[4:]: sum(1 for t in tr[m] if sel(t)) for m in MARKETS}
        print(f"  {lab}: port {100*st.mean(pc[m[4:]]/100 for m in MARKETS):+.2f}%  n={len(rr)} win {100*sum(r>0 for r in rr)/len(rr):.1f}% "
              f"avg {100*st.mean(rr):+.3f}%  per-coin {pc}  n {n_}")
    # MDD on TEST (own MTM)
    dd, endr = mtm_mdd(R, tr, SPLIT, "2026-10-22")
    print(f"  TEST MTM portfolio: end {100*endr:+.2f}%  MDD {100*dd:.2f}%")
    # gap entries
    g = sum(1 for m in MARKETS for t in tr[m] if R[m][t["ent"]]["o"] > t["tgt"])
    print("  entries filled at bar open:", g)
    # time stamps checks: exit always at 00:00 of next day?
    bad = [(m, t["day"], t["tout"]) for m in MARKETS for t in tr[m] if not t["tout"].endswith("T00:00:00")]
    print("  exits not at 00:00:00:", bad[:10], len(bad))
    same_bar_first = sum(1 for m in MARKETS for t in tr[m] if t["tin"].endswith("T00:00:00"))
    print("  entries on the 00:00 bar:", same_bar_first)

    # ---- sensitivity checks (verifier's own, not used to re-select)
    print("\nSENSITIVITY (chosen combo, TEST portfolio):")
    trT = {}
    for m in MARKETS:
        CUR_TICK[0] = TICK[m]
        trT[m] = run(R[m], DD[m], 0.7, 10, tick_round=True)
    print("  tick-rounded target:  TEST %+.2f%%  TRAIN %+.2f%%" % (
        100 * st.mean(compound([t for t in trT[m] if t["day"] >= SPLIT]) for m in MARKETS),
        100 * st.mean(compound([t for t in trT[m] if t["day"] < SPLIT]) for m in MARKETS)))
    # conservative fill: wait for the breakout bar to CLOSE, buy at next bar open
    tot = []
    for m in MARKETS:
        rows = R[m]
        out = []
        for t in tr[m]:
            nxt = t["ent"] + 1
            if nxt >= t["xi"]:
                continue  # breakout bar was the last bar of the day -> skip
            fill = rows[nxt]["o"]
            out.append(dict(day=t["day"], ret=t["exit"] * (1 - CS) / (fill * (1 + CS)) - 1))
        tot.append(compound([x for x in out if x["day"] >= SPLIT]))
    print("  next-bar-open fill after breakout bar: TEST %+.2f%%" % (100 * st.mean(tot)))
    # cost doubled
    tot2 = []
    for m in MARKETS:
        e = 1.0
        for t in tr[m]:
            if t["day"] >= SPLIT:
                e *= 1 + (t["exit"] * (1 - 2 * CS) / (t["fill"] * (1 + 2 * CS)) - 1)
        tot2.append(e - 1)
    print("  cost x2 (0.40%% RT): TEST %+.2f%%" % (100 * st.mean(tot2)))
    # earliest-possible start (no common warm-up) TRAIN for all combos -> does selection change?
    print("\nSELECTION ROBUSTNESS: start each combo at its earliest valid day (day idx >= max(N,20 for noise)+1)")
    alt = {}
    for k, n in grid:
        trs = {m: run(R[m], DD[m], k, n, start_day="2025-10-23") for m in MARKETS}
        alt[(k, n)] = st.mean(compound([t for t in trs[m] if t["day"] < SPLIT]) for m in MARKETS)
    for key, v in alt.items():
        print(f"  {key}: TRAIN {100*v:+.2f}%")
    print("  best:", max(alt, key=alt.get))


if __name__ == "__main__":
    main()
