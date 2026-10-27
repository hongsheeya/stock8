"""KS: quick take-profit for late entries plus one re-entry (PREREG.md)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "speed"))
import study as s  # noqa: E402

VARIANTS = {"BASE": None, "L1": (1.5, 1.0), "L2": (1.5, 2.0), "L3": (2.0, 1.0), "L4": (2.0, 2.0)}
LABEL = {"BASE": "지금 규칙", "L1": "늦음 1.5% · 익절 1%", "L2": "늦음 1.5% · 익절 2%", "L3": "늦음 2.0% · 익절 1%", "L4": "늦음 2.0% · 익절 2%"}
THR = 0.5


def mins(hm):
    return int(hm[:2]) * 60 + int(hm[3:5])


def one_trade(e, pm, o, sgn, i0, start, late_cfg, prev_close, cost, after=None):
    """Scan from bar i0; returns (trade dict, exit bar index) or (None, None)."""
    for i in range(i0, len(e) - 1):
        b, n = e[i], e[i + 1]
        p = pm.get(b["hm"])
        close_hm = s.add(b["hm"], 5)
        if p is None or close_hm <= start or close_hm > "14:30":
            continue
        move = (p["close"] / o - 1) * 100 * sgn
        if not (move >= THR and (p["close"] - p["vwap"]) * sgn > 0 and b["close"] > b["vwap"]) or move > s.MAX_MOVE:
            continue
        if after is not None:
            t_exit, px_exit = after
            if mins(n["hm"]) < t_exit + 30 or n["open"] > px_exit * 0.995:
                continue
        entry = n["open"]
        from_prev = (p["close"] / prev_close - 1) * 100 * sgn if prev_close else move
        late = late_cfg is not None and from_prev >= late_cfg[0]
        tp = entry * (1 + late_cfg[1] / 100) if late else None
        for j in range(i + 1, len(e) - 1):
            bj, nj = e[j], e[j + 1]
            if tp is not None and bj["high"] >= tp:
                return {"ret": (max(bj["open"], tp) / entry - 1) * 100 - cost, "late": late, "why": "tp"}, j, mins(bj["hm"]) + 5, max(bj["open"], tp)
            pj = pm.get(bj["hm"])
            if pj is None:
                continue
            mv = (pj["close"] / o - 1) * 100 * sgn
            if nj["hm"] >= "15:10" or mv < 0 or bj["close"] <= entry * (1 - s.STOP / 100):
                return {"ret": (nj["open"] / entry - 1) * 100 - cost, "late": late, "why": "exit"}, j + 1, mins(nj["hm"]), nj["open"]
        return {"ret": (e[-1]["close"] / entry - 1) * 100 - cost, "late": late, "why": "eod"}, None, None, None
    return None, None, None, None


def run(B, etf, day, start, late_cfg, prev_close, cost):
    side, proxy = s.PAIRS[etf]
    e, ix = B[etf].get(day), B[proxy].get(day)
    if not e or not ix:
        return []
    pm = {b["hm"]: b for b in ix}
    o = ix[0]["open"]
    sgn = 1 if side == "BULL" else -1
    out = []
    t, j, t_exit, px_exit = one_trade(e, pm, o, sgn, 0, start, late_cfg, prev_close, cost)
    if t:
        out.append(t)
        if late_cfg is not None and t["late"] and j is not None:
            t2, *_ = one_trade(e, pm, o, sgn, j, start, late_cfg, prev_close, cost, after=(t_exit, px_exit))
            if t2:
                t2["reentry"] = True
                out.append(t2)
    return out


def simulate(raw, B, days, prev, late_cfg, cost):
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
            for t in run(B, etf, d, start, late_cfg, pc, cost):
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
        late = [t["ret"] for t in tr if t.get("late") and not t.get("reentry")]
        re = [t["ret"] for t in tr if t.get("reentry")]
        tp = sum(1 for t in tr if t.get("why") == "tp")
        res[name] = (r, r2)
        avg = lambda xs: sum(xs) / len(xs) if xs else 0.0
        print(f"{name:4s} {LABEL[name]:18s} 1년 {r['total']:+6.1f}% 낙폭 {r['dd']:+6.1f}% | 앞 {r['a']:+5.1f} 뒤 {r['b']:+5.1f} | 분기 "
              + " ".join(f"{x:+5.1f}" for x in r["q"]) + f" | 거래 {r['n']} | 늦은 진입 {len(late)}건 평균 {avg(late):+.3f}% "
              f"익절 {tp}건 | 재진입 {len(re)}건 평균 {avg(re):+.3f}% | 비용0.20% {r2['total']:+6.1f}%", flush=True)
    base, base2 = res["BASE"]
    # late entries under the current rule, for reference
    tr0 = simulate(raw, B, days, prev, (1.5, 1000.0), 0.10)
    late0 = [t["ret"] for t in tr0 if t.get("late") and not t.get("reentry")]
    print(f"\n참고: 지금 규칙에서 '늦은 진입(전날 종가 대비 1.5% 이상)' {len(late0)}건 평균 {sum(late0) / len(late0):+.3f}%")
    passed = []
    print("\n== 판정 (BASE 대비) ==")
    for name in ("L1", "L2", "L3", "L4"):
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
