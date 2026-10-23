exec(open("ks_entry_extension.py", encoding="utf-8").read().split("def simulate(")[0])
import statistics
def run_tp(etf, day, start, tp):
    side, proxy = y.PAIRS[etf]
    e, ix = data[etf].get(day), data[proxy].get(day)
    if not e or not ix: return None
    pm = {b["hm"]: b for b in ix}; o = ix[0]["open"]; sgn = 1 if side == "BULL" else -1
    for i in range(len(e) - 1):
        b, n = e[i], e[i + 1]; p = pm.get(b["hm"])
        if p is None or not (start <= b["hm"] <= "14:30"): continue
        move = (p["close"] / o - 1) * 100 * sgn; vgap = (p["close"] / p["vwap"] - 1) * 100 * sgn
        if not (move >= 1.0 and vgap > 0 and b["close"] > b["vwap"]) or move > 2.5: continue
        entry = n["open"]
        for j in range(i + 1, len(e) - 1):
            bj, nj = e[j], e[j + 1]; pj = pm.get(bj["hm"])
            if pj is None: continue
            if tp and bj["high"] >= entry * (1 + tp / 100):          # resting limit sell at the target
                return (tp - COST, b["hm"])
            mv = (pj["close"] / o - 1) * 100 * sgn
            if nj["hm"] >= "15:10" or mv < 0 or bj["close"] <= entry * 0.975:
                return ((nj["open"] / entry - 1) * 100 - COST, b["hm"])
        return ((e[-1]["close"] / entry - 1) * 100 - COST, b["hm"])
    return None
half = len(days) // 2
for etfs, label in ((["252670"], "252670만"), (["252670", "114800", "251340"], "인버스 3종")):
    print("==", label)
    for tp in (None, 0.5, 1.0, 1.5, 2.0, 3.0):
        rets, first, second = [], 0.0, 0.0
        for k, d in enumerate(days):
            for etf in etfs:
                side, proxy = y.PAIRS[etf]
                pc = prev.get((proxy, d)); gap = (data[proxy][d][0]["open"] / pc - 1) * 100 if pc else 0
                if gap >= 1.0: continue
                r = run_tp(etf, d, "10:00", tp)
                if r:
                    rets.append(r[0])
                    if k < half: first += r[0] * 0.33
                    else: second += r[0] * 0.33
        print(f"  익절 {('없음' if tp is None else f'+{tp}%'):6s} 거래 {len(rets):3d} 승률 {sum(x > 0 for x in rets) / len(rets) * 100:3.0f}% 평균 {statistics.mean(rets):+.3f}% 1년 {sum(rets) * 0.33:+6.1f}% | 앞 {first:+5.1f}% 뒤 {second:+5.1f}%")
