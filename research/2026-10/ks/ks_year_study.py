"""10-21: re-validate the KS trend rule on a year of KIS 1-minute bars.

Bars: data/live/.../ks_minute_archive/<date>.json (KIS 주식일별분봉조회), grouped
into 5-minute bars (signal on a closed 5m bar, fill at the next bar's open),
VWAP cumulative from 09:00. Live rule: 09:15-14:30 entries, index >= 1% from
its open on the trend side of VWAP and the ETF above its own VWAP; one entry
per ETF per day; -2.5% stop; exit when the index is back through its open
("open") or crosses VWAP ("vwap"); flat at 15:10. Cost 0.10% round trip.
Day type from the index gap (open vs previous close): GU >= +1%, GD <= -1%.
"""
import glob
import json
import os
import statistics
import sys
from collections import defaultdict

ARCHIVE = sys.argv[1] if len(sys.argv) > 1 else ""
PAIRS = {"122630": ("BULL", "069500"), "233740": ("BULL", "229200"), "252670": ("BEAR", "069500"),
         "114800": ("BEAR", "069500"), "251340": ("BEAR", "229200")}
COST = 0.10


def five_minute(rows):
    out, cur = [], None
    for r in rows:
        hm = r["time"]
        m = int(hm[:2]) * 60 + int(hm[3:5])
        bucket = f"{m // 5 * 5 // 60:02d}:{m // 5 * 5 % 60:02d}"
        if cur is None or cur["hm"] != bucket:
            if cur: out.append(cur)
            cur = {"hm": bucket, "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "vol": r["volume"]}
        else:
            cur["high"] = max(cur["high"], r["high"]); cur["low"] = min(cur["low"], r["low"])
            cur["close"] = r["close"]; cur["vol"] += r["volume"]
    if cur: out.append(cur)
    pv = v = 0.0
    for b in out:
        tp = (b["high"] + b["low"] + b["close"]) / 3
        pv += tp * b["vol"]; v += b["vol"]
        b["vwap"] = pv / v if v else tp
    return out


def load():
    data = defaultdict(dict)
    for path in sorted(glob.glob(os.path.join(ARCHIVE, "*.json"))):
        j = json.load(open(path, encoding="utf-8"))
        for sym, rows in (j.get("bars") or {}).items():
            if len(rows) > 300:
                data[sym][j["date"]] = five_minute(rows)
    return data


def run(data, etf, day, exit_mode="open", stop=2.5, start="09:15", end="14:30", flat="15:10", reentry=False):
    side, proxy = PAIRS[etf]
    e, ix = data[etf].get(day), data[proxy].get(day)
    if not e or not ix:
        return []
    pm = {b["hm"]: b for b in ix}
    o = ix[0]["open"]; sgn = 1 if side == "BULL" else -1
    trades, entry, done = [], None, False
    for i in range(len(e) - 1):
        b, n = e[i], e[i + 1]
        p = pm.get(b["hm"])
        if p is None:
            continue
        move = (p["close"] / o - 1) * 100 * sgn
        gap = (p["close"] - p["vwap"]) * sgn
        if entry is None:
            if not done and start <= b["hm"] <= end and move >= 1.0 and gap > 0 and b["close"] > b["vwap"]:
                entry = n["open"]
            continue
        rev = (move < 0) if exit_mode == "open" else (gap < 0)
        stop_hit = b["close"] <= entry * (1 - stop / 100)
        if n["hm"] >= flat or rev or stop_hit:
            trades.append((n["open"] / entry - 1) * 100 - COST)
            entry = None
            done = not (reentry and stop_hit and not rev)
            if n["hm"] >= flat:
                break
    if entry is not None:
        trades.append((e[-1]["close"] / entry - 1) * 100 - COST)
    return trades


def summary(label, trades_by_day, days):
    allt = [t for d in days for t in trades_by_day.get(d, [])]
    if not allt:
        print(f"{label:44s} no trades"); return
    q = len(days) // 4
    quarters = [sum(t for d in days[k * q:(k + 1) * q if k < 3 else len(days)] for t in trades_by_day.get(d, [])) for k in range(4)]
    perday = [sum(trades_by_day.get(d, [])) for d in days]
    print(f"{label:44s} n {len(allt):4d} win {sum(x > 0 for x in allt) / len(allt) * 100:3.0f}% avg {statistics.mean(allt):+.3f}% "
          f"sum {sum(allt):+7.1f}% | quarters " + " ".join(f"{x:+6.1f}" for x in quarters) + f" | worst day {min(perday):+.1f}%")


if __name__ == "__main__":
    data = load()
    days = sorted(set(data["069500"]) & set(data["229200"]))
    print(f"{len(days)} days {days[0]} ~ {days[-1]}")
    prev_close = {}
    for idx in ("069500", "229200"):
        last = None
        for d in sorted(data[idx]):
            if last is not None:
                prev_close[(idx, d)] = last
            last = data[idx][d][-1]["close"]

    def kind(etf, d):
        proxy = PAIRS[etf][1]
        pc = prev_close.get((proxy, d))
        if not pc: return "?"
        g = (data[proxy][d][0]["open"] / pc - 1) * 100
        return "GU" if g >= 1 else ("GD" if g <= -1 else "FLAT")

    variants = [("live: open exit, -2.5%, 1 entry", {}),
                ("vwap exit, -2.5%, 1 entry", dict(exit_mode="vwap")),
                ("vwap exit, -1.5%, re-entry after stop", dict(exit_mode="vwap", stop=1.5, reentry=True)),
                ("open exit, -2.5%, entries from 10:00", dict(start="10:00")),
                ("open exit, -4%", dict(stop=4.0))]
    for label, kw in variants:
        by_day, by_kind = defaultdict(list), defaultdict(lambda: defaultdict(list))
        for d in days:
            for etf in PAIRS:
                t = run(data, etf, d, **kw)
                by_day[d] += t
                by_kind[kind(etf, d)][d] += t
        summary(label, by_day, days)
        for k in ("FLAT", "GU", "GD"):
            summary(f"   {k}", by_kind[k], days)
