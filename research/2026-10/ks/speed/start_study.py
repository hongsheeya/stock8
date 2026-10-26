"""KS: earlier normal-day starts with the 0.5% threshold (PREREG_START.md)."""
import statistics
import study as s

VARIANTS = {"BASE": [("10:00", 0.5)], "S1": [("09:45", 0.5)], "S2": [("09:30", 0.5)],
            "S3": [("09:30", 1.0), ("10:00", 0.5)], "S4": [("09:45", 1.0), ("10:00", 0.5)]}
LABEL = {"BASE": "지금 (10:00부터 0.5%)", "S1": "09:45부터 0.5%", "S2": "09:30부터 0.5%",
         "S3": "09:30부터 1.0%, 10시 이후 0.5%", "S4": "09:45부터 1.0%, 10시 이후 0.5%"}


def threshold_at(schedule, close_hm):
    thr = None
    for start, t in schedule:
        if close_hm > start:
            thr = t
    return thr


def run(B, etf, day, schedule, cost):
    side, proxy = s.PAIRS[etf]
    e, ix = B[etf].get(day), B[proxy].get(day)
    if not e or not ix:
        return None
    pm = {b["hm"]: b for b in ix}
    o = ix[0]["open"]
    sgn = 1 if side == "BULL" else -1
    for i in range(len(e) - 1):
        b, n = e[i], e[i + 1]
        p = pm.get(b["hm"])
        close_hm = s.add(b["hm"], 5)
        thr = threshold_at(schedule, close_hm)
        if p is None or thr is None or close_hm > "14:30":
            continue
        move = (p["close"] / o - 1) * 100 * sgn
        if not (move >= thr and (p["close"] - p["vwap"]) * sgn > 0 and b["close"] > b["vwap"]) or move > s.MAX_MOVE:
            continue
        entry = n["open"]
        for j in range(i + 1, len(e) - 1):
            bj, nj = e[j], e[j + 1]
            pj = pm.get(bj["hm"])
            if pj is None:
                continue
            mv = (pj["close"] / o - 1) * 100 * sgn
            if nj["hm"] >= "15:10" or mv < 0 or bj["close"] <= entry * (1 - s.STOP / 100):
                return {"ret": (nj["open"] / entry - 1) * 100 - cost, "hm": n["hm"], "already": 0.0}
        return {"ret": (e[-1]["close"] / entry - 1) * 100 - cost, "hm": n["hm"], "already": 0.0}
    return None


def simulate(raw, B, days, prev, schedule, cost):
    trades = []
    for d in days:
        for etf, (side, proxy) in s.PAIRS.items():
            pc = prev.get((proxy, d))
            gap = (raw[proxy][d][0]["open"] / pc - 1) * 100 if pc else 0.0
            if gap >= 1.0:
                if side == "BEAR":
                    continue
                sched = [("09:15", 0.5)]
            else:
                sched = schedule
            t = run(B, etf, d, sched, cost)
            if t:
                t["day"] = d
                t["early"] = gap < 1.0 and t["hm"] < "10:05"
                trades.append(t)
    return trades


def main():
    raw = s.load()
    days = sorted(set(raw["069500"]) & set(raw["229200"]))
    prev = {}
    for idx in ("069500", "229200"):
        last = None
        for d in sorted(raw[idx]):
            if last is not None:
                prev[(idx, d)] = last
            last = raw[idx][d][-1]["close"]
    B = {sym: {d: s.bars(rows, 5) for d, rows in by_day.items()} for sym, by_day in raw.items()}
    res = {}
    for name, sched in VARIANTS.items():
        tr = simulate(raw, B, days, prev, sched, 0.10)
        r = s.summary(tr, days)
        r2 = s.summary(simulate(raw, B, days, prev, sched, 0.20), days)
        early = [t["ret"] for t in tr if t["early"]]
        res[name] = (r, r2, early)
        print(f"{name:4s} {LABEL[name]:26s} 1년 {r['total']:+6.1f}% 낙폭 {r['dd']:+6.1f}% | 앞 {r['a']:+5.1f} 뒤 {r['b']:+5.1f} | 분기 "
              + " ".join(f"{x:+5.1f}" for x in r["q"]) + f" | 거래 {r['n']} 평균 {r['avg']:+.3f}% | 10시 전 진입 {len(early)}건 평균 "
              f"{statistics.mean(early) if early else 0:+.3f}% | 비용0.20% {r2['total']:+6.1f}%", flush=True)
    base, base2, _ = res["BASE"]
    passed = []
    print("\n== 판정 (BASE 대비) ==")
    for name in ("S1", "S2", "S3", "S4"):
        r, r2, early = res[name]
        checks = [r["total"] > base["total"], r["a"] >= base["a"] and r["b"] >= base["b"],
                  sum(x >= y for x, y in zip(r["q"], base["q"])) >= 3, r["dd"] >= base["dd"] - 3, r2["total"] > base2["total"],
                  bool(early) and statistics.mean(early) > 0]
        ok = all(checks)
        print(f"  {name} {LABEL[name]}: {'통과' if ok else '탈락'} " + " ".join("O" if c else "X" for c in checks))
        if ok:
            passed.append(name)
    print("결론:", f"후보 {max(passed, key=lambda n: res[n][0]['total'])}" if passed else "통과 없음 — 10:00 시작 유지")


if __name__ == "__main__":
    main()
