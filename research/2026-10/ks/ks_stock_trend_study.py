"""10-21: would the KS trend rule work on individual large caps? (long only)
60 days of Yahoo 5m bars for 30 KOSPI/KOSDAQ large caps (bars end 14:55; the
last bar is the exit). Entry 09:15-14:30 when the stock is >= M% above its
open and its 5m close is above VWAP; fill at the next open; one entry per
stock per day. Cost 0.25% round trip (0.03% fees + 0.18% tax + slippage).
Optional market filter: KODEX 200 itself up >= 0.5% and above VWAP.
"""
import glob, os, statistics, io, contextlib, importlib.util
from collections import defaultdict
import pandas as pd
spec = importlib.util.spec_from_file_location("w", "ks_regime_whipsaw.py"); w = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()): spec.loader.exec_module(w)
COST = 0.25
stocks = {os.path.basename(p)[:-4]: w.to_days(pd.read_pickle(p)) for p in glob.glob("ks_stocks_5m/*.pkl")}
idx = w.data["069500"]
days = sorted(set(d for s in stocks.values() for d in s))
half = days[len(days)//2]

def run(bars, day, move, exit_mode, stop, market):
    e = bars.get(day, [])
    if len(e) < 10: return []
    o = e[0]["open"]; im = {b["hm"]: b for b in idx.get(day, [])}; io_ = idx.get(day, [{}])[0].get("open", 0)
    entry, out = None, []
    for i in range(len(e) - 1):
        b, n = e[i], e[i+1]
        mv = (b["close"]/o - 1)*100
        if entry is None:
            if out or not ("09:15" <= b["hm"] <= "14:30"): continue
            if mv >= move and b["close"] > b["vwap"]:
                if market:
                    ib = im.get(b["hm"])
                    if not ib or not io_ or (ib["close"]/io_-1)*100 < 0.5 or ib["close"] < ib["vwap"]: continue
                entry = n["open"]
            continue
        rev = b["close"] < o if exit_mode == "open" else b["close"] < b["vwap"]
        if rev or b["close"] <= entry*(1-stop/100):
            out.append((n["open"]/entry-1)*100 - COST); return out
    if entry: out.append((e[-1]["close"]/entry-1)*100 - COST)
    return out

print(f"{len(stocks)} stocks, {days[0]}~{days[-1]} ({len(days)} days), cost {COST}% RT")
for move in (1, 2, 3):
    for exit_mode in ("open", "vwap"):
        for market in (False, True):
            allt, h1, h2, perday = [], [], [], defaultdict(float)
            for s in stocks.values():
                for d in days:
                    t = run(s, d, move, exit_mode, 3.0, market); allt += t; (h1 if d < half else h2).extend(t); perday[d] += sum(t)
            if not allt: continue
            print(f"move>={move}% exit={exit_mode:4s} mkt={'Y' if market else 'N'}: n {len(allt):4d} win {sum(x>0 for x in allt)/len(allt)*100:3.0f}% "
                  f"avg {statistics.mean(allt):+.3f}% | H1 avg {statistics.mean(h1) if h1 else 0:+.3f}% (n{len(h1)}) H2 avg {statistics.mean(h2) if h2 else 0:+.3f}% (n{len(h2)}) | worst day {min(perday.values()):+.1f}%")
