"""10-20: 'buy once, hold to the close, sell only when unavoidable' vs the VWAP exit.

60 days of 5m bars; exit at the daily close (15:30 auction) when held to the
end. Entry = live rule (09:15-14:30, index >=1% move and past VWAP, ETF above
its VWAP). Each variant allows ONE entry per ETF per day unless noted.
Cost 0.10% RT. Variants fixed before running.
"""
import io, contextlib, statistics, importlib.util
from collections import defaultdict
import pandas as pd

spec = importlib.util.spec_from_file_location("w", "ks_regime_whipsaw.py"); w = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(w)
data, PAIRS, COST = w.data, w.PAIRS, w.COST
days = sorted(data["069500"]); half = days[len(days) // 2]
daily = {c: {str(t)[:10]: float(r["Close"]) for t, r in pd.read_pickle(f"ks_1d/{c}.pkl").iterrows()} for c in PAIRS}


def run(etf, side, proxy, day, exit_rule, stop=1.5, one_entry=True):
    e, pmap = data[etf].get(day, []), {b["hm"]: b for b in data[proxy].get(day, [])}
    if not e or not data[proxy].get(day):
        return []
    popen = data[proxy][day][0]["open"]; sgn = 1 if side == "BULL" else -1
    trades, entry, last_exit, done = [], None, -99, False
    for i in range(len(e) - 1):
        bar, nxt = e[i], e[i + 1]; pb = pmap.get(bar["hm"])
        if pb is None:
            continue
        move = (pb["close"] / popen - 1) * 100 * sgn; gap = (pb["close"] / pb["vwap"] - 1) * 100 * sgn
        if entry is None:
            if not done and "09:15" <= bar["hm"] <= "14:30" and gap > 0 and move >= 1.0 and i - last_exit >= 2 and bar["close"] > bar["vwap"]:
                entry = nxt["open"]
            continue
        stop_hit = stop and bar["close"] <= entry * (1 - stop / 100)
        if exit_rule == "vwap":
            rev = gap < 0
        elif exit_rule == "open":      # trend fully gone: index back through its day open
            rev = move < 0
        elif exit_rule == "half":      # index move back under half the entry threshold
            rev = move < 0.5
        else:
            rev = False
        if rev or stop_hit:
            trades.append((nxt["open"] / entry - 1) * 100 - COST); entry, last_exit = None, i
            if one_entry or rev:
                done = True
    if entry is not None:
        trades.append((daily[etf].get(day, e[-1]["close"]) / entry - 1) * 100 - COST)
    return trades


V = [("now: VWAP exit, re-entry after stop", dict(exit_rule="vwap", one_entry=False)),
     ("hold to close, stop -1.5% only", dict(exit_rule="none", stop=1.5)),
     ("hold to close, stop -2.5% only", dict(exit_rule="none", stop=2.5)),
     ("hold to close, stop -4% only", dict(exit_rule="none", stop=4.0)),
     ("hold to close, no stop at all", dict(exit_rule="none", stop=0)),
     ("exit when index back under its open", dict(exit_rule="open", stop=2.5)),
     ("exit when index move < +0.5%", dict(exit_rule="half", stop=2.5))]
print(f"{days[0]} ~ {days[-1]} ({len(days)} days), split {half}, cost {COST}% RT, sums of per-trade %")
for label, kw in V:
    allt, h1, h2, perday, holds = [], [], [], defaultdict(float), 0
    for etf, (side, proxy) in PAIRS.items():
        for day in days:
            t = run(etf, side, proxy, day, **kw)
            allt += t; (h1 if day < half else h2).extend(t); perday[day] += sum(t)
    losses = [x for x in allt if x < 0]
    print(f"{label:38s} n {len(allt):3d} win {sum(x > 0 for x in allt) / len(allt) * 100:3.0f}% sum {sum(allt):+6.1f}% "
          f"| H1 {sum(h1):+6.1f}% H2 {sum(h2):+6.1f}% | worst day {min(perday.values()):+5.1f}% | worst trade {min(allt):+.1f}% avg loss {statistics.mean(losses):+.2f}%")
