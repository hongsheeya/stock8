"""Independent verifier for the 'breakout' family claim (chosen combo 4h_N55_atr2).

Written from the stated rule only; does NOT import the researcher's module.
Structure differs on purpose: a single pass over 5m bars (event loop), 4h
buckets from integer epoch seconds (sec // 14400), daily closes from
sec // 86400, Wilder ATR seeded with the simple mean of the first 14 TRs
(researcher used pandas ewm seeded at the first TR; difference should decay).

Rule:
  - 4h bar J closes -> if flat: signal if close[J] > max(high[J-55..J-1]) and
    close[J] > SMA50 of completed UTC-day closes (days whose end <= bar end).
    Enter at open of the first 5m bar of the next existing 4h bar.
  - Initial stop = high[J] - 2*ATR14[J]; after each closed 4h bar while long:
    hh = max(hh, high), stop = max(stop, hh - 2*ATR14). Stop fixed within a
    4h bar; checked on each 5m bar (incl. the entry 5m bar): low <= stop ->
    exit at min(open, stop).
  - Re-entry allowed at the close of the bar where the stop was hit.
  - Cost 0.10% per side. Each period starts flat; open position closed at
    the last 5m close of the period.
"""
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CANDLES = os.path.join(HERE, "..", "..", "..", "candles")
MARKETS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]
FEE = 0.001
N_DON = 55
K_ATR = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
ATR_N = 14
SMA_N = 50
B4 = 4 * 3600
DAY = 86400


def ts(s):
    return int(datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())


def load(m):
    rows = json.load(open(os.path.join(CANDLES, f"{m}_5m.json"), encoding="utf-8"))
    d = {}
    for r in rows:
        d[ts(r["t"])] = (float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"]))
    keys = sorted(d)
    T = np.array(keys, dtype=np.int64)
    A = np.array([d[k] for k in keys])
    return T, A[:, 0], A[:, 1], A[:, 2], A[:, 3]


def build4h(T, O, H, L, C):
    bk = T // B4
    rows = []
    cur = None
    for i in range(len(T)):
        if cur is None or cur[0] != bk[i]:
            if cur is not None:
                rows.append(cur)
            cur = [int(bk[i]), O[i], H[i], L[i], C[i]]
        else:
            cur[2] = max(cur[2], H[i])
            cur[3] = min(cur[3], L[i])
            cur[4] = C[i]
    rows.append(cur)
    bkt = np.array([r[0] for r in rows], dtype=np.int64)
    h = np.array([r[2] for r in rows])
    l = np.array([r[3] for r in rows])
    c = np.array([r[4] for r in rows])
    n = len(rows)
    # Wilder ATR, seeded with SMA of first 14 TRs
    tr = np.empty(n)
    tr[0] = h[0] - l[0]
    for j in range(1, n):
        tr[j] = max(h[j] - l[j], abs(h[j] - c[j - 1]), abs(l[j] - c[j - 1]))
    atr = np.full(n, np.nan)
    atr[ATR_N - 1] = tr[:ATR_N].mean()
    for j in range(ATR_N, n):
        atr[j] = (atr[j - 1] * (ATR_N - 1) + tr[j]) / ATR_N
    # Donchian of previous 55 bars
    don = np.full(n, np.nan)
    for j in range(N_DON, n):
        don[j] = h[j - N_DON:j].max()
    return bkt, h, l, c, atr, don


def daily_sma(T, C):
    dk = T // DAY
    days, closes = [], []
    for i in range(len(T)):
        if days and days[-1] == dk[i]:
            closes[-1] = C[i]
        else:
            days.append(int(dk[i]))
            closes.append(C[i])
    days = np.array(days, dtype=np.int64)
    closes = np.array(closes)
    sma = np.full(len(days), np.nan)
    for i in range(SMA_N - 1, len(days)):
        sma[i] = closes[i - SMA_N + 1:i + 1].mean()
    return days, sma


def sma_at(days, sma, bar_end_sec):
    # completed days: (d+1)*DAY <= bar_end_sec
    last_day = bar_end_sec // DAY - 1
    i = int(np.searchsorted(days, last_day, "right")) - 1
    return np.nan if i < 0 else sma[i]


def simulate(T, O, H, L, C, ps, pe):
    bkt, h4, l4, c4, atr, don = build4h(T, O, H, L, C)
    days, sma = daily_sma(T, C)
    bidx = {int(b): j for j, b in enumerate(bkt)}
    k0 = int(np.searchsorted(T, ps, "left"))
    k1 = int(np.searchsorted(T, pe, "left"))
    trades = []
    long = False
    stop = hh = None
    eprice = ek = None
    for k in range(k0, k1):
        b = T[k] // B4
        prevb = T[k - 1] // B4 if k > 0 else None
        if prevb is not None and prevb != b:
            J = bidx[int(prevb)]  # bar that just closed
            if long:
                hh = max(hh, h4[J])
                stop = max(stop, hh - K_ATR * atr[J])
            if not long:
                bar_end = (int(prevb) + 1) * B4
                s = sma_at(days, sma, bar_end)
                if (not np.isnan(don[J]) and not np.isnan(atr[J]) and not np.isnan(s)
                        and c4[J] > don[J] and c4[J] > s):
                    long = True
                    ek, eprice = k, O[k]
                    hh = h4[J]
                    stop = hh - K_ATR * atr[J]
        if long and L[k] <= stop:
            px = min(O[k], stop)
            trades.append((ek, eprice, k, px))
            long = False
    if long:
        trades.append((ek, eprice, k1 - 1, C[k1 - 1]))
    return trades, k0, k1


def equity(T, C, trades, k0, k1):
    eq = np.empty(k1 - k0)
    cash = 1.0
    p = k0
    for ek, ep, xk, xp in trades:
        eq[p - k0:ek - k0] = cash
        u = cash / (ep * (1 + FEE))
        eq[ek - k0:xk - k0] = u * C[ek:xk]
        cash = u * xp * (1 - FEE)
        p = xk
    eq[p - k0:] = cash
    return eq


def mdd(x):
    pk = np.maximum.accumulate(np.concatenate([[1.0], x]))[1:]
    return (x / pk - 1).min() * 100


def main():
    data = {m: load(m) for m in MARKETS}
    first = max(d[0][0] for d in data.values())
    ps_full = -(-first // 3600) * 3600
    pe = min(d[0][-1] for d in data.values()) + 300
    split = ts("2026-06-21T00:00:00")
    periods = {"TRAIN": (ps_full, split), "TEST": (split, pe), "FULL": (ps_full, pe)}
    print(f"window {datetime.fromtimestamp(ps_full, timezone.utc)} .. {datetime.fromtimestamp(pe, timezone.utc)}  K_ATR={K_ATR}")
    out = {}
    for p, (a, b) in periods.items():
        grid = np.arange(a, b, 300, dtype=np.int64)
        eqs, rets, finals, tim = [], [], {}, []
        for m, (T, O, H, L, C) in data.items():
            tr, k0, k1 = simulate(T, O, H, L, C, a, b)
            eq = equity(T, C, tr, k0, k1)
            pos = np.searchsorted(T[k0:k1], grid, "right") - 1
            eqs.append(np.where(pos >= 0, eq[np.clip(pos, 0, None)], 1.0))
            r = [(xp * (1 - FEE)) / (ep * (1 + FEE)) - 1 for _, ep, _, xp in tr]
            rets += r
            finals[m] = (eq[-1] - 1) * 100
            tim.append(sum(T[xk] - T[ek] for ek, _, xk, _ in tr) / (b - a))
            if p == "TEST":
                for ek, ep, xk, xp in tr:
                    print(f"   {m:9s} {datetime.fromtimestamp(T[ek], timezone.utc):%Y-%m-%d %H:%M} buy {ep:>14,.1f} -> "
                          f"{datetime.fromtimestamp(T[xk], timezone.utc):%Y-%m-%d %H:%M} sell {xp:>14,.1f} "
                          f"{((xp * (1 - FEE)) / (ep * (1 + FEE)) - 1) * 100:+6.2f}%")
        port = np.mean(eqs, axis=0)
        ret = (port[-1] - 1) * 100
        mean_final = np.mean(list(finals.values()))
        print(f"{p:5s} port ret {ret:+7.2f}% (mean of coin finals {mean_final:+7.2f}%)  mdd {mdd(port):+6.2f}%  trades {len(rets)}"
              f"  win {np.mean([x > 0 for x in rets]) * 100:5.1f}%  avg {np.mean(rets) * 100:+5.2f}%  tim {np.mean(tim) * 100:4.1f}%")
        print("      " + "  ".join(f"{m.split('-')[1]} {v:+6.2f}" for m, v in finals.items()))
        if p == "FULL":
            cuts = [a] + [ts(x) for x in ("2026-01-21T00:00:00", "2026-04-21T00:00:00", "2026-07-21T00:00:00")] + [b]
            vals = []
            for cut in cuts:
                i = int(np.searchsorted(grid, cut, "left")) - 1
                vals.append(1.0 if i < 0 else port[i])
            print("      quarters " + " ".join(f"{(vals[i + 1] / vals[i] - 1) * 100:+6.2f}%" for i in range(4)))
        out[p] = ret
    return 0


if __name__ == "__main__":
    sys.exit(main())
