"""10-21: which rule for gap days? 2 years of hourly bars (signal on a closed
hour, fill at the next hour's open, last bar = close). Day type by the index
gap (open vs previous close): GU >= +1%, GD <= -1%, else FLAT.
Strategies per index (KOSPI200: 122630 BULL / 252670 BEAR, KOSDAQ150: 233740 /
251340), one entry per ETF per day, -2.5% stop, 0.10% RT:
  trend : current rule (index >= 1% from open on its side of VWAP; exit when
          the index is back through the open)
  late  : trend, but entries only from the 3rd hour (gap days settle)
  fade  : gap-up day -> buy the BEAR ETF once the index is below its open and
          VWAP (mirror on gap-down); exit when back over VWAP
"""
import statistics
from collections import defaultdict
import pandas as pd

def days_of(code, src="ks_1h"):
    df = pd.read_pickle(f"{src}/{code}.pkl")
    out = defaultdict(list)
    for ts, r in df.iterrows():
        if r["Close"] > 0 and r["Volume"] >= 0:
            out[ts.strftime("%Y-%m-%d")].append({"hm": ts.strftime("%H:%M"), "open": r.Open, "high": r.High, "low": r.Low, "close": r.Close, "vol": r.Volume})
    for bars in out.values():
        pv = v = 0.0
        for b in bars:
            tp = (b["high"] + b["low"] + b["close"]) / 3; pv += tp * b["vol"]; v += b["vol"]
            b["vwap"] = pv / v if v else tp
    return out

PAIRS = {"069500": ("122630", "252670"), "229200": ("233740", "251340")}
data = {c: days_of(c) for c in ["069500", "229200", "122630", "252670", "233740", "251340"]}
daily = {c: pd.read_pickle(f"ks_1d/{c}_3y.pkl")["Close"] for c in PAIRS}
days = sorted(d for d in data["069500"] if len(data["069500"][d]) >= 5)
half = days[len(days) // 2]
COST = 0.10

def gap(index, day):
    s = daily[index]; idx = [str(t)[:10] for t in s.index]
    if day not in idx: return None
    i = idx.index(day)
    if i == 0: return None
    return (data[index][day][0]["open"] / s.iloc[i - 1] - 1) * 100

def trade(etf, day, entry_i, exit_fn):
    e = data[etf].get(day, [])
    if entry_i + 1 >= len(e): return None
    entry = e[entry_i + 1]["open"]
    for j in range(entry_i + 1, len(e) - 1):
        if exit_fn(j) or e[j]["close"] <= entry * 0.975:
            return (e[j + 1]["open"] / entry - 1) * 100 - COST
    return (e[-1]["close"] / entry - 1) * 100 - COST

def run(index, day, mode, first_bar=0):
    bull, bear = PAIRS[index]; ix = data[index].get(day, []); g = gap(index, day)
    if len(ix) < 4 or g is None: return []
    o = ix[0]["open"]; out = []
    for side, etf in (("BULL", bull), ("BEAR", bear)):
        sgn = 1 if side == "BULL" else -1
        for i in range(first_bar, len(ix) - 1):
            b = ix[i]; mv = (b["close"] / o - 1) * 100 * sgn; above = (b["close"] - b["vwap"]) * sgn > 0
            if mode in ("trend", "late"):
                if mv >= 1.0 and above:
                    r = trade(etf, day, i, lambda j: (ix[j]["close"] / o - 1) * sgn < 0)
                    if r is not None: out.append(r)
                    break
            elif mode == "fade":
                # gap up -> fade with BEAR; gap down -> fade with BULL
                if (g >= 1 and side == "BEAR") or (g <= -1 and side == "BULL"):
                    if mv > 0 and above:
                        r = trade(etf, day, i, lambda j: (ix[j]["close"] - ix[j]["vwap"]) * sgn < 0)
                        if r is not None: out.append(r)
                        break
    return out

def kind(g): return "GU" if g >= 1 else ("GD" if g <= -1 else "FLAT")
print(f"{days[0]} ~ {days[-1]}: {len(days)} days, split {half}")
res = defaultdict(lambda: {"h1": [], "h2": []})
counts = defaultdict(int)
for d in days:
    for index in PAIRS:
        g = gap(index, d)
        if g is None: continue
        k = kind(g); counts[(index, k)] += 1
        for mode, fb in (("trend", 0), ("late", 2), ("fade", 0)):
            res[(k, mode)]["h1" if d < half else "h2"] += run(index, d, mode, fb)
print("days by type (index-days):", {f"{i}:{k}": n for (i, k), n in sorted(counts.items())})
for k in ("FLAT", "GU", "GD"):
    for mode in ("trend", "late", "fade"):
        r = res[(k, mode)]; t = r["h1"] + r["h2"]
        if not t: continue
        print(f"{k:4s} {mode:5s} n {len(t):3d} win {sum(x>0 for x in t)/len(t)*100:3.0f}% avg {statistics.mean(t):+.3f}% sum {sum(t):+6.1f}% | H1 {sum(r['h1']):+6.1f}% H2 {sum(r['h2']):+6.1f}%")
