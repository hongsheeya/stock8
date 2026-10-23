exec(open("ks_entry_extension.py", encoding="utf-8").read().split("def simulate(")[0])
import statistics
half = len(days) // 2
def sim(start_normal="10:00", start_gapdown_bear=None, start_gapdown_bull=None):
    trades = []
    for d in days:
        for etf, (side, proxy) in y.PAIRS.items():
            pc = prev.get((proxy, d)); gap = (data[proxy][d][0]["open"] / pc - 1) * 100 if pc else 0.0
            if gap >= 1.0:
                if side == "BEAR": continue
                start = "09:15"
            elif gap <= -1.0:
                start = (start_gapdown_bear if side == "BEAR" else start_gapdown_bull) or start_normal
            else:
                start = start_normal
            t = run(etf, d, start, max_move=2.5)
            if t: t["day"] = d; t["gap"] = gap; t["side"] = side; trades.append(t)
    return trades
def show(label, tr):
    per = defaultdict(float)
    for t in tr: per[t["day"]] += t["ret"] * 0.33
    eq = pk = dd = 0.0
    for d in days: eq += per.get(d, 0); pk = max(pk, eq); dd = min(dd, eq - pk)
    a = sum(per.get(d, 0) for d in days[:half]); b = sum(per.get(d, 0) for d in days[half:])
    gd = [t["ret"] for t in tr if t["gap"] <= -1.0]
    print(f"{label:40s} 1년 {sum(per.values()):+6.1f}% 낙폭 {dd:+6.1f}% | 앞 {a:+5.1f} 뒤 {b:+5.1f} | 갭하락일 {len(gd):3d}건 평균 {statistics.mean(gd) if gd else 0:+.3f}% 합 {sum(gd)*0.33:+5.1f}%")
show("현재 (보통·갭하락 10:00)", sim())
for s in ("09:15", "09:30", "09:45"):
    show(f"갭하락일 인버스만 {s}부터", sim(start_gapdown_bear=s))
for s in ("09:15", "09:30"):
    show(f"갭하락일 양쪽 {s}부터", sim(start_gapdown_bear=s, start_gapdown_bull=s))
for s in ("09:15", "09:30", "09:45"):
    show(f"모든 보통날 {s}부터", sim(start_normal=s))
