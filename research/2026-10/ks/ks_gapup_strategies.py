"""10-21: strategies for gap-up days (index opens >= +1% over the previous close).
A year of KIS 1m bars -> 5m (closed-bar signal, next-bar fill). One trade per
ETF per day, -2.5% stop, 15:10 flatten, 0.10% RT. Index-based signals:
  orb     : after 09:30, index closes above the 09:00-09:30 high -> BULL;
            exit index close below the opening-range low or VWAP
  pullback: after 09:30, index closes below VWAP, later closes back above it
            while still above the previous close -> BULL; exit close below VWAP
  hold    : at 10:00 the index still holds >= half of its gap and is above
            VWAP -> BULL; exit when it gives back more than the gap's half
  fade    : after 09:30, index below its open and VWAP -> BEAR; exit back
            above VWAP
  early   : the old 09:15 trend rule (BULL side) on gap-up days
"""
import sys
import statistics
import importlib.util
from collections import defaultdict

sys.argv = sys.argv[:1] + [r"C:\Users\변기국학부재학지능형반도체공학과\Documents\ChatGPT\New project 3\stock8\data\live\daytrade\f20da15217e609e9eebc99f3\ks_minute_archive"]
spec = importlib.util.spec_from_file_location("y", "ks_year_study.py"); y = importlib.util.module_from_spec(spec); spec.loader.exec_module(y)
y.ARCHIVE = sys.argv[1]
data = y.load()
days = sorted(set(data["069500"]) & set(data["229200"]))
ETF = {"069500": {"BULL": "122630", "BEAR": "252670"}, "229200": {"BULL": "233740", "BEAR": "251340"}}
COST = 0.10
prev = {}
for idx in ETF:
    last = None
    for d in sorted(data[idx]):
        if last: prev[(idx, d)] = last
        last = data[idx][d][-1]["close"]


def gap(idx, d):
    pc = prev.get((idx, d))
    return (data[idx][d][0]["open"] / pc - 1) * 100 if pc else None


def trade(etf, d, i, exit_fn):
    e = data[etf].get(d) or []
    em = {b["hm"]: k for k, b in enumerate(e)}
    if i + 1 >= len(data_idx_cache[d]): return None
    hm_next = data_idx_cache[d][i + 1]["hm"]
    if hm_next not in em: return None
    k0 = em[hm_next]; entry = e[k0]["open"]
    for k in range(k0, len(e) - 1):
        hm = e[k]["hm"]
        if e[k + 1]["hm"] >= "15:10" or e[k]["close"] <= entry * 0.975 or exit_fn(hm):
            return (e[k + 1]["open"] / entry - 1) * 100 - COST
    return (e[-1]["close"] / entry - 1) * 100 - COST


def strategy(name, idx, d):
    ix = data[idx][d]; o = ix[0]["open"]; pc = prev[(idx, d)]; g = gap(idx, d)
    im = {b["hm"]: b for b in ix}
    global data_idx_cache
    data_idx_cache = {d: ix}
    orh = max(b["high"] for b in ix if b["hm"] < "09:30"); orl = min(b["low"] for b in ix if b["hm"] < "09:30")
    bull, bear = ETF[idx]["BULL"], ETF[idx]["BEAR"]
    dipped = False
    for i, b in enumerate(ix[:-1]):
        hm = b["hm"]
        if hm > "14:30": break
        if name == "orb" and hm >= "09:30" and b["close"] > orh:
            return trade(bull, d, i, lambda h: im[h]["close"] < orl or im[h]["close"] < im[h]["vwap"])
        if name == "pullback" and hm >= "09:30":
            if b["close"] < b["vwap"]: dipped = True
            elif dipped and b["close"] > b["vwap"] and b["close"] > pc:
                return trade(bull, d, i, lambda h: im[h]["close"] < im[h]["vwap"])
        if name == "hold" and hm == "10:00":
            if (b["close"] / pc - 1) * 100 >= g / 2 and b["close"] > b["vwap"]:
                return trade(bull, d, i, lambda h: (im[h]["close"] / pc - 1) * 100 < g / 2)
            return None
        if name == "fade" and hm >= "09:30" and b["close"] < o and b["close"] < b["vwap"]:
            return trade(bear, d, i, lambda h: im[h]["close"] > im[h]["vwap"])
        if name == "early" and hm >= "09:15" and (b["close"] / o - 1) * 100 >= 1 and b["close"] > b["vwap"]:
            return trade(bull, d, i, lambda h: im[h]["close"] < o)
    return None


q = len(days) // 4
for name in ("orb", "pullback", "hold", "fade", "early"):
    res = []; quarters = [0.0] * 4; n_days = 0
    for k, d in enumerate(days):
        for idx in ETF:
            g = gap(idx, d)
            if g is None or g < 1: continue
            n_days += 1
            r = strategy(name, idx, d)
            if r is None: continue
            res.append(r); quarters[min(3, k // q)] += r
    if not res:
        print(name, "no trades"); continue
    print(f"{name:9s} 갭상승 지수-일 {n_days} | 거래 {len(res):3d} 승률 {sum(x > 0 for x in res) / len(res) * 100:3.0f}% "
          f"평균 {statistics.mean(res):+.3f}% 합계 {sum(res):+6.1f}% (시드 33%: {sum(res) * 0.33:+5.1f}%) | 분기 "
          + " ".join(f"{x:+6.1f}" for x in quarters))
