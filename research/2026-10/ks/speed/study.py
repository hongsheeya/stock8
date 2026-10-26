"""KS trend rule: earlier entries (PREREG.md). Same rule as LIVE, on 5m or 1m
closed bars (fill at the next bar's open), index-move threshold 1.0/0.7/0.5%.
Archive: KIS 1-minute bars (KS_ARCHIVE folder of <date>.json)."""
import glob
import json
import os
import statistics
from collections import defaultdict

ARCHIVE = os.environ["KS_ARCHIVE"]
PAIRS = {"122630": ("BULL", "069500"), "233740": ("BULL", "229200"), "252670": ("BEAR", "069500"),
         "114800": ("BEAR", "069500"), "251340": ("BEAR", "229200")}
VARIANTS = {"BASE": (5, 1.0), "E1": (5, 0.7), "E2": (5, 0.5), "E3": (1, 1.0), "E4": (1, 0.7)}
LABEL = {"BASE": "현재 (5분봉·1.0%)", "E1": "5분봉·0.7%", "E2": "5분봉·0.5%", "E3": "1분봉·1.0%", "E4": "1분봉·0.7%"}
MAX_MOVE = 2.5
STOP = 2.5


def bars(rows, size):
    out, cur = [], None
    for r in rows:
        hm = r["time"]
        m = int(hm[:2]) * 60 + int(hm[3:5])
        k = m // size * size
        bucket = f"{k // 60:02d}:{k % 60:02d}"
        if cur is None or cur["hm"] != bucket:
            if cur:
                out.append(cur)
            cur = {"hm": bucket, "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "vol": r["volume"]}
        else:
            cur["high"] = max(cur["high"], r["high"])
            cur["low"] = min(cur["low"], r["low"])
            cur["close"] = r["close"]
            cur["vol"] += r["volume"]
    if cur:
        out.append(cur)
    pv = v = 0.0
    for b in out:
        tp = (b["high"] + b["low"] + b["close"]) / 3
        pv += tp * b["vol"]
        v += b["vol"]
        b["vwap"] = pv / v if v else tp
    return out


def load():
    raw = defaultdict(dict)
    for path in sorted(glob.glob(os.path.join(ARCHIVE, "*.json"))):
        j = json.load(open(path, encoding="utf-8"))
        for sym, rows in (j.get("bars") or {}).items():
            if len(rows) > 300 and sym in set(PAIRS) | {"069500", "229200"}:
                raw[sym][j["date"]] = rows
    return raw


def add(hm, minutes):
    m = int(hm[:2]) * 60 + int(hm[3:5]) + minutes
    return f"{m // 60:02d}:{m % 60:02d}"


def run(B, etf, day, start, size, thr, cost):
    side, proxy = PAIRS[etf]
    e, ix = B[etf].get(day), B[proxy].get(day)
    if not e or not ix:
        return None
    pm = {b["hm"]: b for b in ix}
    o = ix[0]["open"]
    sgn = 1 if side == "BULL" else -1
    for i in range(len(e) - 1):
        b, n = e[i], e[i + 1]
        p = pm.get(b["hm"])
        close_hm = add(b["hm"], size)  # the bar is closed at this time
        if p is None or close_hm <= start or close_hm > "14:30":
            continue
        move = (p["close"] / o - 1) * 100 * sgn
        if not (move >= thr and (p["close"] - p["vwap"]) * sgn > 0 and b["close"] > b["vwap"]):
            continue
        if move > MAX_MOVE:
            continue
        entry = n["open"]
        already = (entry / e[0]["open"] - 1) * 100
        for j in range(i + 1, len(e) - 1):
            bj, nj = e[j], e[j + 1]
            pj = pm.get(bj["hm"])
            if pj is None:
                continue
            mv = (pj["close"] / o - 1) * 100 * sgn
            if nj["hm"] >= "15:10" or mv < 0 or bj["close"] <= entry * (1 - STOP / 100):
                return {"ret": (nj["open"] / entry - 1) * 100 - cost, "already": already, "hm": n["hm"]}
        return {"ret": (e[-1]["close"] / entry - 1) * 100 - cost, "already": already, "hm": n["hm"]}
    return None


def simulate(raw, days, prev, size, thr, cost):
    B = {sym: {d: bars(rows, size) for d, rows in by_day.items()} for sym, by_day in raw.items()}
    trades = []
    for d in days:
        for etf, (side, proxy) in PAIRS.items():
            pc = prev.get((proxy, d))
            gap = (raw[proxy][d][0]["open"] / pc - 1) * 100 if pc else 0.0
            if gap >= 1.0:
                if side == "BEAR":
                    continue
                start = "09:15"
            else:
                start = "10:00"
            t = run(B, etf, d, start, size, thr, cost)
            if t:
                t["day"] = d
                trades.append(t)
    return trades


def summary(trades, days):
    per = defaultdict(float)
    for t in trades:
        per[t["day"]] += t["ret"] * 0.33
    eq = pk = dd = 0.0
    for d in days:
        eq += per.get(d, 0)
        pk = max(pk, eq)
        dd = min(dd, eq - pk)
    half = len(days) // 2
    q = len(days) // 4
    quarters = [sum(per.get(d, 0) for d in days[k * q:(k + 1) * q if k < 3 else len(days)]) for k in range(4)]
    rets = [t["ret"] for t in trades]
    return {"total": sum(per.values()), "dd": dd, "a": sum(per.get(d, 0) for d in days[:half]),
            "b": sum(per.get(d, 0) for d in days[half:]), "q": quarters, "n": len(rets),
            "avg": statistics.mean(rets) if rets else 0.0, "win": sum(r > 0 for r in rets) / len(rets) * 100 if rets else 0.0,
            "already": statistics.mean([t["already"] for t in trades]) if trades else 0.0}


def main():
    raw = load()
    days = sorted(set(raw["069500"]) & set(raw["229200"]))
    prev = {}
    for idx in ("069500", "229200"):
        last = None
        for d in sorted(raw[idx]):
            if last is not None:
                prev[(idx, d)] = last
            last = raw[idx][d][-1]["close"]
    print(f"{len(days)}일 {days[0]} ~ {days[-1]}")
    res = {}
    for name, (size, thr) in VARIANTS.items():
        r = summary(simulate(raw, days, prev, size, thr, 0.10), days)
        r2 = summary(simulate(raw, days, prev, size, thr, 0.20), days)
        res[name] = (r, r2)
        print(f"{name:4s} {LABEL[name]:16s} 1년 {r['total']:+6.1f}% 낙폭 {r['dd']:+6.1f}% | 앞 {r['a']:+5.1f} 뒤 {r['b']:+5.1f} | 분기 "
              + " ".join(f"{x:+5.1f}" for x in r["q"]) + f" | 거래 {r['n']} 승률 {r['win']:.0f}% 평균 {r['avg']:+.3f}% "
              f"| 진입 때 ETF가 이미 시가 대비 {r['already']:+.2f}% | 비용0.20% 1년 {r2['total']:+6.1f}%", flush=True)
    base, base2 = res["BASE"]
    passed = []
    print("\n== 판정 (BASE 대비) ==")
    for name in ("E1", "E2", "E3", "E4"):
        r, r2 = res[name]
        checks = [r["total"] > base["total"], r["a"] >= base["a"] and r["b"] >= base["b"],
                  sum(x >= y for x, y in zip(r["q"], base["q"])) >= 3, r["dd"] >= base["dd"] - 3, r2["total"] > base2["total"]]
        ok = all(checks)
        print(f"  {name} {LABEL[name]}: {'통과' if ok else '탈락'} " + " ".join(("O" if c else "X") for c in checks))
        if ok:
            passed.append(name)
    print("결론:", f"후보 {max(passed, key=lambda n: res[n][0]['total'])}" if passed else "통과 없음 — 지금 규칙 유지")


if __name__ == "__main__":
    main()
