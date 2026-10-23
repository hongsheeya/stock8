"""10-20 exit-confirmation study for the KS trend rule.

LIVE 10-20: 252670 bought 09:29:50, sold 09:30:53 on an index VWAP touch.
The live rule checks the index every ~15 s; the 60-day backtest used closed 5m
bars. Variants (fixed before running): the index must stay on the wrong side
of its VWAP for N bars, or by a buffer, before the trend exit. Everything else
= live rule: 09:15-14:30 entries, -1.5% stop, no re-entry after a VWAP exit,
0.10% RT cost, flat at the day's last bar.
"""
import statistics
from collections import defaultdict
import pandas as pd

PAIRS = {"114800": ("BEAR", "069500"), "252670": ("BEAR", "069500"), "251340": ("BEAR", "229200"),
         "122630": ("BULL", "069500"), "233740": ("BULL", "229200")}
COST = 0.10


def to_days(df):
    days = defaultdict(list)
    for ts, r in df.iterrows():
        hm = ts.strftime("%H:%M")
        if not ("09:00" <= hm < "15:30") or r["Close"] <= 0:
            continue
        days[ts.strftime("%Y-%m-%d")].append({"hm": hm, "open": float(r["Open"]), "high": float(r["High"]),
                                              "low": float(r["Low"]), "close": float(r["Close"]), "volume": float(r["Volume"])})
    for bars in days.values():
        pv = v = 0.0
        for b in bars:
            tp = (b["high"] + b["low"] + b["close"]) / 3
            pv += tp * b["volume"]; v += b["volume"]
            b["vwap"] = pv / v if v > 0 else tp
    return days


def load(folder):
    return {c: to_days(pd.read_pickle(f"{folder}/{c}.pkl")) for c in set(PAIRS) | {"069500", "229200"}}


def run(data, etf, side, proxy, day, cooldown, confirm=1, buffer=0.0):
    e, pmap = data[etf].get(day, []), {b["hm"]: b for b in data[proxy].get(day, [])}
    if not e or not data[proxy].get(day):
        return []
    popen = data[proxy][day][0]["open"]; sgn = 1 if side == "BULL" else -1
    trades, entry, last_exit, done, wrong = [], None, -999, False, 0
    for i in range(len(e) - 1):
        bar, nxt = e[i], e[i + 1]; pb = pmap.get(bar["hm"])
        if pb is None:
            continue
        move = (pb["close"] / popen - 1) * 100; gap = (pb["close"] / pb["vwap"] - 1) * 100 * sgn
        if entry is None:
            if (not done and "09:15" <= bar["hm"] <= "14:30" and gap > 0 and move * sgn >= 1.0
                    and i - last_exit >= cooldown and bar["close"] > bar["vwap"]):
                entry, wrong = nxt["open"], 0
            continue
        wrong = wrong + 1 if gap < -buffer else 0
        rev = wrong >= confirm
        stop_hit = bar["close"] <= entry * 0.985
        if rev or stop_hit:
            trades.append((nxt["open"] / entry - 1) * 100 - COST); entry, last_exit = None, i
            if rev:
                done = True
    if entry is not None:
        trades.append((e[-1]["close"] / entry - 1) * 100 - COST)
    return trades


def report(label, data, cooldown, **kw):
    days = sorted(data["069500"]); half = days[len(days) // 2]
    allt, h1, h2, perday = [], [], [], defaultdict(float)
    for etf, (side, proxy) in PAIRS.items():
        for day in days:
            t = run(data, etf, side, proxy, day, cooldown, **kw)
            allt += t; (h1 if day < half else h2).extend(t); perday[day] += sum(t)
    short = sum(1 for x in allt if abs(x + COST) < 0.3)
    print(f"  {label:34s} n {len(allt):3d} win {sum(x > 0 for x in allt) / max(1, len(allt)) * 100:3.0f}% sum {sum(allt):+6.1f}% "
          f"| H1 {sum(h1):+6.1f}% H2 {sum(h2):+6.1f}% | worst day {min(perday.values()):+5.1f}% | tiny moves {short}")


d1 = load("ks_1m")
print(f"== 1-minute bars (live-like), {min(d1['069500'])} ~ {max(d1['069500'])} ({len(d1['069500'])} days)")
for label, kw in [("now: exit on first 1m close", {}), ("2 consecutive 1m closes", dict(confirm=2)),
                  ("3 consecutive 1m closes", dict(confirm=3)), ("5 consecutive 1m closes", dict(confirm=5)),
                  ("buffer 0.1%", dict(buffer=0.1)), ("buffer 0.2%", dict(buffer=0.2)),
                  ("3 closes + buffer 0.1%", dict(confirm=3, buffer=0.1))]:
    report(label, d1, 10, **kw)

d5 = load("ks_5m")
print(f"\n== 5-minute bars, {min(d5['069500'])} ~ {max(d5['069500'])} ({len(d5['069500'])} days)")
for label, kw in [("exit on first 5m close (backtest)", {}), ("2 consecutive 5m closes", dict(confirm=2)),
                  ("buffer 0.1%", dict(buffer=0.1)), ("buffer 0.2%", dict(buffer=0.2)), ("buffer 0.3%", dict(buffer=0.3))]:
    report(label, d5, 2, **kw)
