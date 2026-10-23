"""Independent verifier for the "regime" family claim (B100).

Written from the rule text only, without importing regime.py, and without pandas.
Rule: at each UTC daily close (close of the last 5m bar of the UTC day), hold coin X
during the NEXT UTC day iff  C_X > SMA100(C_X)  AND  C_BTC > SMA100(C_BTC)
(SMA over the last 100 daily closes, including today's). Entries/exits fill at the
open of the first 5m bar of the next day. 0.10% cost per side. Each 20% slice compounds
alone. Open positions at the window end are liquidated at the last close (exit cost).

Daily closes before 2025-10-22 come from the researcher's warm-up files (Upbit API daily
candles); they are integrity-checked here against the 5m data on the overlap day.
"""
import json
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
CANDLES = os.path.join(ROOT, "candles")
WARM = os.path.join(ROOT, "research", "regime")
MKTS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]
SIDE = 0.001
START = "2025-10-22T00:00:00"
SPLIT = "2026-06-21T00:00:00"


def load(m):
    rows = json.load(open(os.path.join(CANDLES, f"{m}_5m.json"), encoding="utf-8"))
    seen, out = set(), []
    for r in rows:
        if r["t"] in seen:
            continue
        seen.add(r["t"])
        out.append(r)
    out.sort(key=lambda r: r["t"])
    return out


def daily_close_map(m, bars):
    """date-string -> close; 5m-derived from START on, API warm-up before."""
    d5 = {}
    for r in bars:
        d5[r["t"][:10]] = r["c"]  # sorted, so last bar of the day wins
    warm = json.load(open(os.path.join(WARM, f"warmup_daily_{m}.json"), encoding="utf-8"))
    wmap = {w["t"][:10]: w["c"] for w in warm}
    # integrity: overlap day(s)
    chk = []
    for d in ("2025-10-21", "2025-10-22"):
        if d in wmap and d in d5:
            chk.append((d, wmap[d], d5[d]))
    out = {}
    for d, c in wmap.items():
        if d < START[:10]:
            out[d] = c
    for d, c in d5.items():
        if d >= START[:10]:
            out[d] = c
    # contiguous day list with ffill
    days = sorted(out)
    d0 = date.fromisoformat(days[0])
    d1 = date.fromisoformat(days[-1])
    seq, last, missing = [], None, 0
    cur = d0
    while cur <= d1:
        k = cur.isoformat()
        if k in out:
            last = out[k]
        else:
            missing += 1
        seq.append((k, last))
        cur += timedelta(days=1)
    return seq, chk, missing


def sma_signal(seq, n):
    """dict day -> bool (close > mean of last n closes incl. today); False if not enough history."""
    res = {}
    vals = [c for _, c in seq]
    for i, (d, c) in enumerate(seq):
        if i + 1 < n:
            res[d] = False
            continue
        s = sum(vals[i + 1 - n:i + 1]) / n
        res[d] = c > s
    return res


from functools import lru_cache


@lru_cache(maxsize=None)
def prev_day(d):
    return (date.fromisoformat(d) - timedelta(days=1)).isoformat()


def sim(bars, sig, lo, hi):
    """Returns (ret, trades list, curve list[(t, equity)], bars_in_market, nbars)."""
    w = [r for r in bars if lo <= r["t"] < hi]
    cash, units = 1.0, 0.0
    entry_px = None
    trades = []
    curve = []
    inm = 0
    for r in w:
        want = sig.get(prev_day(r["t"][:10]), False)
        if want and units == 0.0:
            units = cash * (1 - SIDE) / r["o"]
            cash = 0.0
            entry_px = r["o"]
        elif (not want) and units > 0.0:
            cash = units * r["o"] * (1 - SIDE)
            trades.append(r["o"] / entry_px * (1 - SIDE) ** 2 - 1)
            units = 0.0
        if units > 0.0:
            inm += 1
        curve.append((r["t"], cash + units * r["c"]))
    if units > 0.0:
        cash = units * w[-1]["c"] * (1 - SIDE)
        trades.append(w[-1]["c"] / entry_px * (1 - SIDE) ** 2 - 1)
        units = 0.0
        curve[-1] = (curve[-1][0], cash)
    return cash - 1, trades, curve, inm, len(w)


def port_mdd(curves):
    ts = sorted(set(t for cv in curves for t, _ in cv))
    idx = [0] * len(curves)
    last = [1.0] * len(curves)
    peak, mdd = 1.0, 0.0
    for t in ts:
        for k, cv in enumerate(curves):
            while idx[k] < len(cv) and cv[idx[k]][0] <= t:
                last[k] = cv[idx[k]][1]
                idx[k] += 1
        v = sum(last) / len(last)
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return mdd


def main():
    bars = {m: load(m) for m in MKTS}
    seqs = {}
    for m in MKTS:
        seq, chk, miss = daily_close_map(m, bars[m])
        seqs[m] = seq
        print(m, "daily closes", len(seq), seq[0][0], "->", seq[-1][0], "ffilled days", miss,
              "| overlap check", [(d, a, b, "OK" if abs(a / b - 1) < 1e-9 else "DIFF") for d, a, b in chk])
    end = max(bars[m][-1]["t"] for m in MKTS) + "Z"  # any string > last t
    windows = {"TRAIN": (START, SPLIT), "TEST": (SPLIT, end), "FULL": (START, end)}

    def btc_gate_sig(m, n):
        a = sma_signal(seqs[m], n)
        b = sma_signal(seqs["KRW-BTC"], n)
        return {d: a[d] and b.get(d, False) for d in a}

    def plain_sma(m, n):
        return sma_signal(seqs[m], n)

    def mom(m, L):
        seq = seqs[m]
        return {d: (i >= L and c > seq[i - L][1]) for i, (d, c) in enumerate(seq)}

    def dual(m, f, s):
        seq = seqs[m]
        vals = [c for _, c in seq]
        out = {}
        for i, (d, _) in enumerate(seq):
            if i + 1 < s:
                out[d] = False
            else:
                out[d] = sum(vals[i + 1 - f:i + 1]) / f > sum(vals[i + 1 - s:i + 1]) / s
        return out

    combos = {
        "S20": lambda m: plain_sma(m, 20), "S50": lambda m: plain_sma(m, 50), "S100": lambda m: plain_sma(m, 100),
        "M7": lambda m: mom(m, 7), "M14": lambda m: mom(m, 14), "M30": lambda m: mom(m, 30),
        "X5_20": lambda m: dual(m, 5, 20), "X10_50": lambda m: dual(m, 10, 50), "X20_100": lambda m: dual(m, 20, 100),
        "B20": lambda m: btc_gate_sig(m, 20), "B50": lambda m: btc_gate_sig(m, 50), "B100": lambda m: btc_gate_sig(m, 100),
    }

    summary = {}
    for name, fn in combos.items():
        summary[name] = {}
        sigs = {m: fn(m) for m in MKTS}
        for wn, (lo, hi) in windows.items():
            rets, trs, curves, inm, nb = [], [], [], [], []
            per = {}
            for m in MKTS:
                r, t, cv, im, n = sim(bars[m], sigs[m], lo, hi)
                rets.append(r); trs += t; curves.append(cv); inm.append(im / n)
                per[m] = (r, len(t))
            summary[name][wn] = {
                "ret": sum(rets) / 5, "trades": len(trs),
                "win": (sum(1 for x in trs if x > 0) / len(trs)) if trs else float("nan"),
                "avg": (sum(trs) / len(trs)) if trs else float("nan"),
                "tim": sum(inm) / 5, "per": per, "curves": curves,
            }
    print("\nTRAIN portfolio return by combo (selection = max):")
    for n in combos:
        print(f"  {n:8s} {summary[n]['TRAIN']['ret']*100:+7.2f}%   TEST {summary[n]['TEST']['ret']*100:+7.2f}%   FULL {summary[n]['FULL']['ret']*100:+7.2f}%")
    best = max(combos, key=lambda n: summary[n]["TRAIN"]["ret"])
    print("selected on TRAIN:", best)
    sel = summary["B100"]
    for wn in windows:
        s = sel[wn]
        print(f"\nB100 {wn}: ret {s['ret']*100:+.2f}% mdd {port_mdd(s['curves'])*100:+.2f}% trades {s['trades']} "
              f"win {s['win']*100:.1f}% avg {s['avg']*100:+.2f}% tim {s['tim']*100:.1f}%")
        for m in MKTS:
            r, n = s["per"][m]
            print(f"   {m:9s} {r*100:+7.2f}%  trades {n}")
    # B100 position changes
    sig = combos["B100"]
    for m in MKTS:
        sg = sig(m)
        ch, prev = [], None
        for d, _ in seqs[m]:
            if d < "2025-10-21":
                continue
            v = sg[d]
            if v != prev:
                ch.append(f"{d}:{'ON' if v else 'OFF'}")
            prev = v
        print(m, "signal (at close of day) changes:", " ".join(ch))


if __name__ == "__main__":
    main()
