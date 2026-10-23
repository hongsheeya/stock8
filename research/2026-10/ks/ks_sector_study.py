"""10-21: KS sector ETFs under the live trend rule (long only, self proxy).
Entry 09:15-14:30 when the ETF is >= M% above its open and its closed 5m bar is
above VWAP; next-open fill; exit when back below the open or -2.5%; one entry
per ETF per day; last bar (14:55) exit. Cost 0.10% RT (ETF: no sell tax)."""
import glob, os, statistics, io, contextlib, importlib.util
from collections import defaultdict
import pandas as pd
spec = importlib.util.spec_from_file_location("w", "ks_regime_whipsaw.py"); w = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()): spec.loader.exec_module(w)
NAMES = {"091160":"KODEX 반도체","091230":"TIGER 반도체","305720":"KODEX 2차전지","305540":"TIGER 2차전지테마","091170":"KODEX 은행",
         "091180":"KODEX 자동차","244580":"KODEX 바이오","139260":"TIGER 200 IT","102970":"KODEX 증권","117700":"KODEX 건설",
         "449450":"PLUS K방산","069500":"(참고) KODEX 200","229200":"(참고) KODEX 코스닥150"}
data = {c: w.to_days(pd.read_pickle(f"ks_sector_5m/{c}.pkl")) for c in NAMES}
days = sorted(data["069500"]); half = days[len(days)//2]

def run(bars, day, move, cost, stop=2.5):
    e = bars.get(day, [])
    if len(e) < 10: return []
    o = e[0]["open"]; entry = None
    for i in range(len(e) - 1):
        b, n = e[i], e[i+1]
        if entry is None:
            if "09:15" <= b["hm"] <= "14:30" and (b["close"]/o-1)*100 >= move and b["close"] > b["vwap"]:
                entry = n["open"]
            continue
        if b["close"] < o or b["close"] <= entry*(1-stop/100):
            return [(n["open"]/entry-1)*100 - cost]
    return [(e[-1]["close"]/entry-1)*100 - cost] if entry else []

for move in (1.0, 1.5):
    print(f"\n== entry when ETF >= +{move}% from open (cost 0.10% RT)")
    tot, tot1, tot2 = [], [], []
    for c, name in NAMES.items():
        t1, t2 = [], []
        for d in days:
            (t1 if d < half else t2).extend(run(data[c], d, move, 0.10))
        t = t1 + t2
        if not c.startswith(("069500","229200")): tot += t; tot1 += t1; tot2 += t2
        if t:
            print(f"  {name:16s} n {len(t):2d} win {sum(x>0 for x in t)/len(t)*100:3.0f}% avg {statistics.mean(t):+.2f}% sum {sum(t):+6.1f}% | H1 {sum(t1):+5.1f}% H2 {sum(t2):+5.1f}%")
    print(f"  {'섹터 합계':16s} n {len(tot):2d} win {sum(x>0 for x in tot)/len(tot)*100:3.0f}% avg {statistics.mean(tot):+.3f}% | H1 {sum(tot1):+.1f}% H2 {sum(tot2):+.1f}%")
