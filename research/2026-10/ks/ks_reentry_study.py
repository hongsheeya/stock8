"""10-19 re-entry rule study for the KS trend rule (60 days of 5m bars).

Same engine as ks_regime_whipsaw.py (closed 5m signal, next-open fill, 09:15
start, -1.5% stop, 15:10 flatten, 0.10% RT cost). Variants fixed before running.
"""
import io, contextlib, statistics, importlib.util
from collections import defaultdict

spec = importlib.util.spec_from_file_location("w", "ks_regime_whipsaw.py"); w = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(w)
data, PAIRS, COST = w.data, w.PAIRS, w.COST
days = sorted(data["069500"]); half = days[len(days) // 2]


def run(etf, side, proxy, day, block="none", stop_block=False, max_rev=1):
    e, pmap = data[etf].get(day, []), {b["hm"]: b for b in data[proxy].get(day, [])}
    if not e or not data[proxy].get(day):
        return []
    popen = data[proxy][day][0]["open"]
    sgn = 1 if side == "BULL" else -1
    trades, entry, last_exit, done = [], None, -99, False
    rev_exits, last_exit_px, last_pnl = 0, None, None
    for i in range(len(e) - 1):
        bar, nxt = e[i], e[i + 1]
        pb = pmap.get(bar["hm"])
        if pb is None:
            continue
        move = (pb["close"] / popen - 1) * 100
        gap = (pb["close"] / pb["vwap"] - 1) * 100 * sgn
        if entry is None:
            ok = (not done and "09:15" <= bar["hm"] <= "14:30" and gap > 0 and move * sgn >= 1.0
                  and i - last_exit >= 2 and bar["close"] > bar["vwap"])
            if ok and block == "higher_than_exit" and last_exit_px is not None and bar["close"] > last_exit_px:
                ok = False  # never buy back above the price we just sold at
            if ok:
                entry = nxt["open"]
            continue
        stop_hit = bar["close"] <= entry * 0.985
        rev = gap < 0
        if nxt["hm"] >= "15:10" or rev or stop_hit:
            pnl = (nxt["open"] / entry - 1) * 100 - COST
            trades.append(pnl)
            entry, last_exit, last_exit_px, last_pnl = None, i, nxt["open"], pnl
            if rev:
                rev_exits += 1
            if block == "after_reversal" and rev and rev_exits >= max_rev:
                done = True
            if block == "after_losing_reversal" and rev and pnl < 0:
                done = True
            if block == "after_any_loss" and pnl < 0:
                done = True
            if stop_block and stop_hit and not rev:
                done = True
    if entry is not None:
        trades.append((e[-1]["close"] / entry - 1) * 100 - COST)
    return trades


VARIANTS = [
    ("A no block (10m cooldown only)", dict(block="none")),
    ("B block after any VWAP exit (now)", dict(block="after_reversal")),
    ("C block after 2nd VWAP exit", dict(block="after_reversal", max_rev=2)),
    ("D block after a LOSING VWAP exit", dict(block="after_losing_reversal")),
    ("E block after any losing exit", dict(block="after_any_loss")),
    ("F no buy-back above last exit px", dict(block="higher_than_exit")),
    ("B + stop block", dict(block="after_reversal", stop_block=True)),
]
print(f"days {days[0]} ~ {days[-1]} ({len(days)}), split {half}, cost {COST}% RT")
for label, kw in VARIANTS:
    allt, h1, h2, perday, first, reent = [], [], [], defaultdict(float), [], []
    for etf, (side, proxy) in PAIRS.items():
        for day in days:
            t = run(etf, side, proxy, day, **kw)
            allt += t; (h1 if day < half else h2).extend(t); perday[day] += sum(t)
            first += t[:1]; reent += t[1:]
    loss_days = sum(1 for v in perday.values() if v < 0)
    print(f"{label:36s} n {len(allt):3d} win {sum(x > 0 for x in allt) / max(1, len(allt)) * 100:3.0f}% sum {sum(allt):+6.1f}% "
          f"| H1 {sum(h1):+6.1f}% H2 {sum(h2):+6.1f}% | worst {min(perday.values()):+5.1f}% lossdays {loss_days:2d} "
          f"| 1st {len(first)}/{sum(first):+.1f}% re {len(reent)}/{sum(reent):+.1f}% ({statistics.mean(reent) if reent else 0:+.2f}%/t)")
