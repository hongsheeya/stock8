"""KS: breakeven / trailing protection after a gain (PREREG.md)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "speed"))
import study as s  # noqa: E402

VARIANTS = {"BASE": None, "BE1": (1.0, None), "BE2": (2.0, None), "BE3": (3.0, None), "TR2": (2.0, 1.5)}
LABEL = {"BASE": "지금 규칙", "BE1": "+1% 후 본전 보호", "BE2": "+2% 후 본전 보호", "BE3": "+3% 후 본전 보호", "TR2": "+2% 후 최고가-1.5% 추적"}
THR = 0.5
BE_BUFFER = 0.1


def run(B, etf, day, start, cfg, cost):
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
        if p is None or close_hm <= start or close_hm > "14:30":
            continue
        move = (p["close"] / o - 1) * 100 * sgn
        if not (move >= THR and (p["close"] - p["vwap"]) * sgn > 0 and b["close"] > b["vwap"]) or move > s.MAX_MOVE:
            continue
        entry = n["open"]
        armed, peak, prot = False, entry, None
        for j in range(i + 1, len(e) - 1):
            bj, nj = e[j], e[j + 1]
            if armed and bj["low"] <= prot:
                return {"ret": (min(bj["open"], prot) / entry - 1) * 100 - cost, "why": "protect"}
            peak = max(peak, bj["high"])
            if cfg is not None:
                if not armed and peak >= entry * (1 + cfg[0] / 100):
                    armed = True
                if armed:
                    floor = entry * (1 + BE_BUFFER / 100)
                    prot = max(floor, peak * (1 - cfg[1] / 100)) if cfg[1] else floor
                    prot = max(prot, floor)
            pj = pm.get(bj["hm"])
            if pj is None:
                continue
            mv = (pj["close"] / o - 1) * 100 * sgn
            if nj["hm"] >= "15:10" or mv < 0 or bj["close"] <= entry * (1 - s.STOP / 100):
                return {"ret": (nj["open"] / entry - 1) * 100 - cost, "why": "exit"}
        return {"ret": (e[-1]["close"] / entry - 1) * 100 - cost, "why": "eod"}
    return None


def simulate(raw, B, days, prev, cfg, cost):
    trades = []
    for d in days:
        for etf, (side, proxy) in s.PAIRS.items():
            pc = prev.get((proxy, d))
            gap = (raw[proxy][d][0]["open"] / pc - 1) * 100 if pc else 0.0
            if gap >= 1.0:
                if side == "BEAR":
                    continue
                start = "09:15"
            else:
                start = "10:00"
            t = run(B, etf, d, start, cfg, cost)
            if t:
                t["day"] = d
                t["already"] = 0.0
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
    for name, cfg in VARIANTS.items():
        tr = simulate(raw, B, days, prev, cfg, 0.10)
        r = s.summary(tr, days)
        r2 = s.summary(simulate(raw, B, days, prev, cfg, 0.20), days)
        prot = [t["ret"] for t in tr if t["why"] == "protect"]
        losers = sum(1 for t in tr if t["ret"] < -1.0)
        res[name] = (r, r2)
        print(f"{name:4s} {LABEL[name]:20s} 1년 {r['total']:+6.1f}% 낙폭 {r['dd']:+6.1f}% | 앞 {r['a']:+5.1f} 뒤 {r['b']:+5.1f} | 분기 "
              + " ".join(f"{x:+5.1f}" for x in r["q"]) + f" | 거래 {r['n']} 승률 {r['win']:.0f}% 평균 {r['avg']:+.3f}% | 보호 청산 {len(prot)}건 "
              f"| -1% 넘게 잃은 거래 {losers}건 | 비용0.20% {r2['total']:+6.1f}%", flush=True)
    base, base2 = res["BASE"]
    passed = []
    print("\n== 판정 (BASE 대비) ==")
    for name in ("BE1", "BE2", "BE3", "TR2"):
        r, r2 = res[name]
        checks = [r["total"] > base["total"], r["a"] >= base["a"] and r["b"] >= base["b"],
                  sum(x >= y for x, y in zip(r["q"], base["q"])) >= 3, r["dd"] >= base["dd"] - 3, r2["total"] > base2["total"]]
        ok = all(checks)
        print(f"  {name} {LABEL[name]}: {'통과' if ok else '탈락'} " + " ".join("O" if c else "X" for c in checks))
        if ok:
            passed.append(name)
    print("결론:", f"후보 {max(passed, key=lambda n: res[n][0]['total'])}" if passed else "통과 없음 — 지금 규칙 유지")


if __name__ == "__main__":
    main()
