"""10-21: current rule (10:00, skip gap-up days) + a BULL-only allowance on
gap-up days, using ks_year_study.run (the live rule, ETF above its own VWAP).
Seed-level = trade % x 0.33 (one third of the seed per trade)."""
import sys
import importlib.util
from collections import defaultdict

ARCH = r"C:\Users\변기국학부재학지능형반도체공학과\Documents\ChatGPT\New project 3\stock8\data\live\daytrade\f20da15217e609e9eebc99f3\ks_minute_archive"
spec = importlib.util.spec_from_file_location("y", "ks_year_study.py"); y = importlib.util.module_from_spec(spec); spec.loader.exec_module(y)
y.ARCHIVE = ARCH
data = y.load()
days = sorted(set(data["069500"]) & set(data["229200"]))
prev = {}
for idx in ("069500", "229200"):
    last = None
    for d in sorted(data[idx]):
        if last: prev[(idx, d)] = last
        last = data[idx][d][-1]["close"]


def gap(idx, d):
    pc = prev.get((idx, d))
    return (data[idx][d][0]["open"] / pc - 1) * 100 if pc else None


def simulate(gu_bull_start=None, thr=1.0, gu_stop=2.5, gu_bear=False):
    by_day = defaultdict(list); gu_only = defaultdict(list)
    for d in days:
        for etf, (side, proxy) in y.PAIRS.items():
            g = gap(proxy, d)
            if g is not None and g >= thr:
                if side == "BULL" and gu_bull_start:
                    t = y.run(data, etf, d, start=gu_bull_start, stop=gu_stop)
                elif side == "BEAR" and gu_bear:
                    t = y.run(data, etf, d, start="10:00")
                else:
                    continue
                gu_only[d] += t
            else:
                t = y.run(data, etf, d, start="10:00")
            by_day[d] += t
    return by_day, gu_only


def report(label, by_day):
    per = [sum(by_day.get(d, [])) * 0.33 for d in days]
    eq = peak = dd = 0.0
    for p in per:
        eq += p; peak = max(peak, eq); dd = min(dd, eq - peak)
    q = len(days) // 4
    quarters = [sum(per[k * q:(k + 1) * q if k < 3 else len(days)]) for k in range(4)]
    n = sum(len(v) for v in by_day.values())
    top5 = sum(sorted(per, reverse=True)[:5])
    print(f"{label:40s} 거래 {n:3d} | 1년 {sum(per):+6.1f}% | 최대낙폭 {dd:+6.1f}% | 분기 " + " ".join(f"{x:+5.1f}" for x in quarters)
          + f" | 상위5일 제외 {sum(per) - top5:+5.1f}%")


base, _ = simulate()
report("현재 규칙 (10:00, 갭상승일 쉼)", base)
for start in ("09:15", "09:30", "10:00"):
    combo, gu = simulate(gu_bull_start=start)
    report(f"+ 갭상승일 레버리지만 {start}~", combo)
    report(f"    (갭상승일 거래분만)", gu)
combo, gu = simulate(gu_bull_start="09:15", gu_bear=True)
report("+ 갭상승일 레버리지 09:15 + 인버스 10:00", combo)
report("    (갭상승일 거래분만)", gu)
print("-- 갭 기준 민감도 (레버리지 09:15) --")
for thr in (0.7, 1.5, 2.0):
    report(f"갭 기준 {thr}% 현재 규칙", simulate(thr=thr)[0])
    report(f"갭 기준 {thr}% + 레버리지 09:15", simulate(gu_bull_start="09:15", thr=thr)[0])
