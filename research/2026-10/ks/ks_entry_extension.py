"""10-22: are the trend entries late? Current LIVE rule on a year of KIS
1m bars (5m closed-bar signals): normal days from 10:00, gap-up days BULL
from 09:15 / BEAR skipped; exit when the index is back through its open,
-2.5% stop, flat 15:10; 0.10% round trip. Each trade is tagged with how far
the index had already moved from its open and from VWAP at the signal bar,
and filter variants (max move, max VWAP gap, pullback entry) are compared.
Seed-level = trade % x 0.33."""
import importlib.util
import statistics
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
COST = 0.10


def run(etf, day, start, max_move=None, max_vwap=None, pullback=False):
    side, proxy = y.PAIRS[etf]
    e, ix = data[etf].get(day), data[proxy].get(day)
    if not e or not ix:
        return None
    pm = {b["hm"]: b for b in ix}
    o = ix[0]["open"]; sgn = 1 if side == "BULL" else -1
    armed = False
    for i in range(len(e) - 1):
        b, n = e[i], e[i + 1]
        p = pm.get(b["hm"])
        if p is None or not (start <= b["hm"] <= "14:30"):
            continue
        move = (p["close"] / o - 1) * 100 * sgn
        vgap = (p["close"] / p["vwap"] - 1) * 100 * sgn
        signal = move >= 1.0 and vgap > 0 and b["close"] > b["vwap"]
        if not signal and not armed:
            continue
        if pullback:
            # after the first signal, wait for the ETF to come back to within
            # 0.3% of its own VWAP while the index trend still holds
            if signal and not armed:
                armed = True
                continue
            if not (armed and move >= 0.5 and vgap > 0 and (b["close"] / b["vwap"] - 1) * 100 <= 0.3):
                continue
        else:
            if max_move is not None and move > max_move:
                continue
            if max_vwap is not None and vgap > max_vwap:
                continue
        entry = n["open"]
        for j in range(i + 1, len(e) - 1):
            bj, nj = e[j], e[j + 1]
            pj = pm.get(bj["hm"])
            if pj is None:
                continue
            mv = (pj["close"] / o - 1) * 100 * sgn
            if nj["hm"] >= "15:10" or mv < 0 or bj["close"] <= entry * 0.975:
                return {"ret": (nj["open"] / entry - 1) * 100 - COST, "move": move, "vgap": vgap, "hm": b["hm"]}
        return {"ret": (e[-1]["close"] / entry - 1) * 100 - COST, "move": move, "vgap": vgap, "hm": b["hm"]}
    return None


def simulate(**kw):
    trades = []
    for d in days:
        for etf, (side, proxy) in y.PAIRS.items():
            pc = prev.get((proxy, d))
            gap = (data[proxy][d][0]["open"] / pc - 1) * 100 if pc else 0.0
            if gap >= 1.0:
                if side == "BEAR":
                    continue
                start = "09:15"
            else:
                start = "10:00"
            t = run(etf, d, start, **kw)
            if t:
                t["day"] = d
                trades.append(t)
    return trades


def summary(label, trades):
    rets = [t["ret"] for t in trades]
    per_day = defaultdict(float)
    for t in trades:
        per_day[t["day"]] += t["ret"] * 0.33
    eq = peak = dd = 0.0
    for d in days:
        eq += per_day.get(d, 0); peak = max(peak, eq); dd = min(dd, eq - peak)
    q = len(days) // 4
    quarters = [sum(per_day.get(d, 0) for d in days[k * q:(k + 1) * q if k < 3 else len(days)]) for k in range(4)]
    print(f"{label:34s} 거래 {len(rets):3d} 승률 {sum(r > 0 for r in rets) / max(1, len(rets)) * 100:3.0f}% 평균 {statistics.mean(rets) if rets else 0:+.3f}% "
          f"1년 {sum(rets) * 0.33:+6.1f}% 낙폭 {dd:+6.1f}% | 분기 " + " ".join(f"{x:+5.1f}" for x in quarters))


base = simulate()
summary("현재 규칙", base)
print("\n-- 진입 때 지수가 시가 대비 이미 움직인 정도별 (현재 규칙 거래) --")
for lo, hi in ((1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 99)):
    part = [t for t in base if lo <= t["move"] < hi]
    if part:
        rs = [t["ret"] for t in part]
        print(f"  시가 대비 {lo:.1f}~{hi if hi < 99 else '':}%: {len(rs):3d}건 평균 {statistics.mean(rs):+.3f}% 승률 {sum(r > 0 for r in rs) / len(rs) * 100:3.0f}%")
print("-- 진입 때 지수가 VWAP에서 떨어진 정도별 --")
for lo, hi in ((0, 0.3), (0.3, 0.6), (0.6, 1.0), (1.0, 99)):
    part = [t for t in base if lo <= t["vgap"] < hi]
    if part:
        rs = [t["ret"] for t in part]
        print(f"  VWAP 대비 {lo:.1f}~{hi if hi < 99 else '':}%: {len(rs):3d}건 평균 {statistics.mean(rs):+.3f}% 승률 {sum(r > 0 for r in rs) / len(rs) * 100:3.0f}%")
print("-- 진입 시각별 --")
for lo, hi in (("09:15", "10:00"), ("10:00", "10:30"), ("10:30", "11:30"), ("11:30", "14:31")):
    part = [t for t in base if lo <= t["hm"] < hi]
    if part:
        rs = [t["ret"] for t in part]
        print(f"  {lo}~{hi}: {len(rs):3d}건 평균 {statistics.mean(rs):+.3f}% 승률 {sum(r > 0 for r in rs) / len(rs) * 100:3.0f}%")
print()
for mm in (1.5, 2.0, 2.5):
    summary(f"시가 대비 {mm}% 넘게 움직였으면 건너뜀", simulate(max_move=mm))
for mv in (0.5, 0.8):
    summary(f"VWAP 대비 {mv}% 넘게 벌어졌으면 건너뜀", simulate(max_vwap=mv))
summary("신호 뒤 VWAP 근처로 눌릴 때 진입", simulate(pullback=True))
