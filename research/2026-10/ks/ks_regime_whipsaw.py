"""10-19 whipsaw study: KS regime trend variants on 60 days of 5m bars + today.

Same rule as ks_regime_60d.py (signal on closed 5m bars, fill at the next open,
09:15 start, no stop block), plus anti-whipsaw variants fixed before running.
Cost 0.10% round trip (fees 0.03% + slippage). Halves are checked separately.
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


data = {}
for c in set(PAIRS) | {"069500", "229200"}:
    data[c] = to_days(pd.read_pickle(f"ks_5m/{c}.pkl"))
days = sorted(data["069500"])
half = days[len(days) // 2]


def run(etf, side, proxy, day, entry_gap=0.0, exit_gap=0.0, max_entries=99, cooldown_bars=2, no_reentry_after_rev=False):
    e, pmap = data[etf].get(day, []), {b["hm"]: b for b in data[proxy].get(day, [])}
    if not e or not data[proxy].get(day):
        return []
    popen = data[proxy][day][0]["open"]
    trades, entry, last_exit, entries, done = [], None, -99, 0, False
    sgn = 1 if side == "BULL" else -1
    for i in range(len(e) - 1):
        bar, nxt = e[i], e[i + 1]
        pb = pmap.get(bar["hm"])
        if pb is None:
            continue
        move = (pb["close"] / popen - 1) * 100
        gap = (pb["close"] / pb["vwap"] - 1) * 100 * sgn  # >0 = on the trend side of VWAP
        if entry is None:
            if (not done and entries < max_entries and "09:15" <= bar["hm"] <= "14:30" and gap > entry_gap
                    and move * sgn >= 1.0 and i - last_exit >= cooldown_bars and bar["close"] > bar["vwap"]):
                entry = nxt["open"]; entries += 1
            continue
        stop_hit = bar["close"] <= entry * 0.985
        rev = gap < -exit_gap
        if nxt["hm"] >= "15:10" or rev or stop_hit:
            trades.append((nxt["open"] / entry - 1) * 100 - COST)
            entry, last_exit = None, i
            if rev and no_reentry_after_rev:
                done = True
    if entry is not None:
        trades.append((e[-1]["close"] / entry - 1) * 100 - COST)
    return trades


VARIANTS = [
    ("current", {}),
    ("exit gap 0.3%", {"exit_gap": 0.3}),
    ("exit gap 0.5%", {"exit_gap": 0.5}),
    ("entry gap 0.3%", {"entry_gap": 0.3}),
    ("entry+exit gap 0.3%", {"entry_gap": 0.3, "exit_gap": 0.3}),
    ("cooldown 30m", {"cooldown_bars": 6}),
    ("max 2 entries/day", {"max_entries": 2}),
    ("max 1 entry/day", {"max_entries": 1}),
    ("no re-entry after VWAP exit", {"no_reentry_after_rev": True}),
    ("exit gap 0.3% + max 2", {"exit_gap": 0.3, "max_entries": 2}),
]
print(f"days {days[0]} ~ {days[-1]} ({len(days)}), split at {half}, cost {COST}% RT")
for label, kw in VARIANTS:
    allt, h1, h2, perday = [], [], [], defaultdict(float)
    for etf, (side, proxy) in PAIRS.items():
        for day in days:
            t = run(etf, side, proxy, day, **kw)
            allt += t; (h1 if day < half else h2).extend(t); perday[day] += sum(t)
    worst = min(perday.values())
    print(f"{label:30s} n {len(allt):4d} win {sum(x > 0 for x in allt) / max(1, len(allt)) * 100:3.0f}% "
          f"avg {statistics.mean(allt) if allt else 0:+.3f}% sum {sum(allt):+6.1f}% | H1 {sum(h1):+6.1f}% H2 {sum(h2):+6.1f}% | worst day {worst:+.1f}%")
