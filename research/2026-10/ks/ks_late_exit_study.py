"""10-19 late-session study for the KS trend rule.

Yahoo KS intraday bars stop at 14:55 (5m) / 14:59 (1m), so the 15:00->close
move comes from the daily close (15:30 auction). Live flattens 15:10~15:20,
between the two; "hold to close" is the pessimistic/optimistic bound of that.
Base rule = live: reversal block, no stop block, no TP, -1.5% stop, 0.10% RT.
"""
import io, contextlib, statistics, importlib.util
from collections import defaultdict
import pandas as pd

spec = importlib.util.spec_from_file_location("w", "ks_regime_whipsaw.py"); w = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(w)
data, PAIRS, COST = w.data, w.PAIRS, w.COST
days = sorted(data["069500"]); half = days[len(days) // 2]
daily = {c: {str(t)[:10]: float(r["Close"]) for t, r in pd.read_pickle(f"ks_1d/{c}.pkl").iterrows()}
         for c in set(PAIRS) | {"069500", "229200"}}

print("== index: last intraday bar (14:55 5m close ~ 15:00) -> daily close (15:30)")
for proxy in ("069500", "229200"):
    by_month = defaultdict(list)
    for d in days:
        last = data[proxy][d][-1]
        if last["hm"] != "14:55" or d not in daily[proxy]:
            continue
        by_month[d[:7]].append((daily[proxy][d] / last["close"] - 1) * 100)
    allm = [x for v in by_month.values() for x in v]
    print(f"{proxy}: n {len(allm)} avg {statistics.mean(allm):+.3f}% | <=-0.5% {sum(x <= -0.5 for x in allm)} "
          f"| <=-1% {sum(x <= -1 for x in allm)} | >=+0.5% {sum(x >= 0.5 for x in allm)} | worst {min(allm):+.2f}% best {max(allm):+.2f}%")
    print("   by month:", ", ".join(f"{m} avg {statistics.mean(v):+.2f}% drops<=-0.5% {sum(x <= -0.5 for x in v)}/{len(v)}"
                                  for m, v in sorted(by_month.items())))
    # 14:00 -> close as well
    seg = []
    for d in days:
        m = {b["hm"]: b for b in data[proxy][d]}
        if "14:00" in m and d in daily[proxy]:
            seg.append((daily[proxy][d] / m["14:00"]["close"] - 1) * 100)
    print(f"   14:00 -> close: avg {statistics.mean(seg):+.3f}% | <=-1% {sum(x <= -1 for x in seg)}/{len(seg)}")


def run(etf, side, proxy, day, flat=None, to_close=False, late_from=None, late_trail=None, late_etf_vwap=False):
    e, pmap = data[etf].get(day, []), {b["hm"]: b for b in data[proxy].get(day, [])}
    if not e or not data[proxy].get(day):
        return [], None
    popen = data[proxy][day][0]["open"]; sgn = 1 if side == "BULL" else -1
    trades, entry, last_exit, done, peak = [], None, -99, False, 0
    for i in range(len(e) - 1):
        bar, nxt = e[i], e[i + 1]; pb = pmap.get(bar["hm"])
        if pb is None:
            continue
        move = (pb["close"] / popen - 1) * 100; gap = (pb["close"] / pb["vwap"] - 1) * 100 * sgn
        if entry is None:
            if (not done and "09:15" <= bar["hm"] <= "14:30" and gap > 0 and move * sgn >= 1.0
                    and i - last_exit >= 2 and bar["close"] > bar["vwap"]):
                entry, peak = nxt["open"], nxt["open"]
            continue
        peak = max(peak, bar["high"])
        stop_hit = bar["close"] <= entry * 0.985; rev = gap < 0
        late = late_from is not None and bar["hm"] >= late_from
        late_exit = late and ((late_trail is not None and bar["close"] <= peak * (1 - late_trail / 100))
                              or (late_etf_vwap and bar["close"] < bar["vwap"]))
        if (flat and nxt["hm"] >= flat) or rev or stop_hit or late_exit:
            trades.append((nxt["open"] / entry - 1) * 100 - COST); entry, last_exit = None, i
            if rev:
                done = True
    carried = None
    if entry is not None:
        last = e[-1]
        exit_px = daily[etf].get(day, last["close"]) if to_close else last["close"]
        trades.append((exit_px / entry - 1) * 100 - COST)
        carried = (daily[etf].get(day, last["close"]) / last["close"] - 1) * 100
    return trades, carried


VARIANTS = [
    ("hold to the close (≈ live 15:10~15:20)", dict(to_close=True)),
    ("flatten 15:00 (old backtest)", dict()),
    ("flatten 14:45", dict(flat="14:45")),
    ("flatten 14:30", dict(flat="14:30")),
    ("to close + after 14:30 trail 0.5%", dict(to_close=True, late_from="14:30", late_trail=0.5)),
    ("to close + after 14:30 trail 1.0%", dict(to_close=True, late_from="14:30", late_trail=1.0)),
    ("to close + after 14:30 ETF < own VWAP", dict(to_close=True, late_from="14:30", late_etf_vwap=True)),
]
print(f"\n== variants: {days[0]} ~ {days[-1]} ({len(days)}), split {half}, cost {COST}% RT")
for label, kw in VARIANTS:
    allt, h1, h2, perday, carried = [], [], [], defaultdict(float), []
    for etf, (side, proxy) in PAIRS.items():
        for day in days:
            t, c = run(etf, side, proxy, day, **kw)
            allt += t; (h1 if day < half else h2).extend(t); perday[day] += sum(t)
            if c is not None:
                carried.append((side, c))
    extra = ""
    if kw.get("to_close") and not kw.get("late_from"):
        bull = [c for s, c in carried if s == "BULL"]; bear = [c for s, c in carried if s == "BEAR"]
        extra = (f" | held past 15:00: {len(carried)} (BULL {len(bull)} {sum(bull):+.1f}%, BEAR {len(bear)} {sum(bear):+.1f}%; "
                 f"<=-1%: {sum(c <= -1 for _, c in carried)})")
    print(f"{label:40s} n {len(allt):3d} sum {sum(allt):+6.1f}% | H1 {sum(h1):+6.1f}% H2 {sum(h2):+6.1f}% "
          f"| worst day {min(perday.values()):+5.1f}%{extra}")
