"""10-21: which spot (long-only) rule is worth automating on Upbit KRW markets.

Rules fixed before running; a year of 5m candles; signal on a closed bar,
fill at the next bar's open; round trip cost 0.20% (0.05% fee per side plus
slippage). Upbit's day starts 09:00 KST (00:00 UTC).
  hold   : buy and hold (benchmark)
  vbo    : volatility breakout - buy when price > today open + 0.5 x yesterday
           range, only if yesterday close > 5-day MA; sell at the next 09:00
  trend  : like the KS rule - from 1h after the open, price >= +1% over the
           day open and above the session VWAP; exit back under the open,
           -2.5% stop, or the session end
  donch  : 1h bars - close above the 20-bar high and above the 200-bar MA;
           exit close below the 10-bar low
  rsi    : 1h bars - RSI(14) < 25 and above the 200-bar MA; exit RSI > 55,
           -5% stop or 48 h
"""
import datetime
import json
import os
import statistics
import sys

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "candles")
COST = 0.20


def load(market):
    rows = json.load(open(os.path.join(DIR, f"{market}_5m.json")))
    for r in rows:
        r["dt"] = datetime.datetime.fromisoformat(r["t"])
        r["day"] = r["dt"].date()  # UTC date == Upbit's 09:00 KST day
    return rows


def hourly(rows):
    out, cur = [], None
    for r in rows:
        key = r["dt"].replace(minute=0)
        if cur is None or cur["dt"] != key:
            if cur: out.append(cur)
            cur = {"dt": key, "o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"]}
        else:
            cur["h"] = max(cur["h"], r["h"]); cur["l"] = min(cur["l"], r["l"]); cur["c"] = r["c"]
    if cur: out.append(cur)
    return out


def by_day(rows):
    days = {}
    for r in rows:
        days.setdefault(r["day"], []).append(r)
    return days


def trades_hold(rows):
    return [(rows[0]["dt"], (rows[-1]["c"] / rows[0]["o"] - 1) * 100 - COST)]


def trades_vbo(rows, k=0.5):
    days = by_day(rows)
    keys = sorted(days)
    closes = [days[d][-1]["c"] for d in keys]
    out = []
    for i in range(5, len(keys) - 1):
        y = days[keys[i - 1]]
        rng = max(b["h"] for b in y) - min(b["l"] for b in y)
        ma5 = sum(closes[i - 5:i]) / 5
        if closes[i - 1] <= ma5:
            continue
        today = days[keys[i]]
        target = today[0]["o"] + k * rng
        for j, b in enumerate(today[:-1]):
            if b["c"] > target:
                entry = today[j + 1]["o"]
                exit_ = days[keys[i + 1]][0]["o"]
                out.append((b["dt"], (exit_ / entry - 1) * 100 - COST))
                break
    return out


def trades_trend(rows):
    out = []
    for d, bars in sorted(by_day(rows).items()):
        o = bars[0]["o"]; pv = v = 0.0; entry = None
        for j, b in enumerate(bars[:-1]):
            tp = (b["h"] + b["l"] + b["c"]) / 3
            pv += tp * b["v"]; v += b["v"]
            vwap = pv / v if v else tp
            if entry is None:
                if j >= 12 and b["c"] >= o * 1.01 and b["c"] > vwap:
                    entry = bars[j + 1]["o"]; t0 = b["dt"]
                continue
            if b["c"] < o or b["c"] <= entry * 0.975:
                out.append((t0, (bars[j + 1]["o"] / entry - 1) * 100 - COST)); entry = None
                break
        if entry is not None:
            out.append((t0, (bars[-1]["c"] / entry - 1) * 100 - COST))
    return out


def trades_donch(rows):
    h = hourly(rows); out = []; entry = None
    for i in range(200, len(h) - 1):
        ma = sum(b["c"] for b in h[i - 200:i]) / 200
        hi = max(b["h"] for b in h[i - 20:i]); lo = min(b["l"] for b in h[i - 10:i])
        b = h[i]
        if entry is None:
            if b["c"] > hi and b["c"] > ma:
                entry = h[i + 1]["o"]; t0 = b["dt"]
        elif b["c"] < lo:
            out.append((t0, (h[i + 1]["o"] / entry - 1) * 100 - COST)); entry = None
    return out


def trades_rsi(rows):
    h = hourly(rows); out = []; entry = None
    gains, losses = [], []
    rsi = [None] * len(h)
    ag = al = None
    for i in range(1, len(h)):
        ch = h[i]["c"] - h[i - 1]["c"]
        g, l = max(ch, 0), max(-ch, 0)
        if i <= 14:
            gains.append(g); losses.append(l)
            if i == 14:
                ag, al = sum(gains) / 14, sum(losses) / 14
        else:
            ag = (ag * 13 + g) / 14; al = (al * 13 + l) / 14
        if ag is not None:
            rsi[i] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(200, len(h) - 1):
        ma = sum(b["c"] for b in h[i - 200:i]) / 200
        b = h[i]
        if entry is None:
            if rsi[i] is not None and rsi[i] < 25 and b["c"] > ma:
                entry = h[i + 1]["o"]; t0 = b["dt"]; i0 = i
        elif (rsi[i] or 0) > 55 or b["c"] <= entry * 0.95 or i - i0 >= 48:
            out.append((t0, (h[i + 1]["o"] / entry - 1) * 100 - COST)); entry = None
    return out


RULES = {"hold": trades_hold, "vbo": trades_vbo, "trend": trades_trend, "donch": trades_donch, "rsi": trades_rsi}


def report(market, rows):
    t_start, t_end = rows[0]["dt"], rows[-1]["dt"]
    span = (t_end - t_start) / 4
    for name, fn in RULES.items():
        tr = fn(rows)
        if not tr:
            print(f"{market:9s} {name:6s} no trades"); continue
        eq = peak = dd = 0.0
        for _, r in tr:
            eq += r; peak = max(peak, eq); dd = min(dd, eq - peak)
        q = [sum(r for t, r in tr if t_start + span * k <= t < t_start + span * (k + 1) or (k == 3 and t >= t_start + span * 3)) for k in range(4)]
        rs = [r for _, r in tr]
        print(f"{market:9s} {name:6s} 거래 {len(rs):4d} 승률 {sum(r > 0 for r in rs) / len(rs) * 100:3.0f}% 평균 {statistics.mean(rs):+6.2f}% "
              f"합계 {sum(rs):+7.1f}% 최대낙폭 {dd:+6.1f}% | 분기 " + " ".join(f"{x:+6.1f}" for x in q))


if __name__ == "__main__":
    markets = sys.argv[1].split(",") if len(sys.argv) > 1 else ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]
    for m in markets:
        if os.path.exists(os.path.join(DIR, f"{m}_5m.json")):
            rows = load(m)
            print(f"-- {m} {rows[0]['t']} ~ {rows[-1]['t']} ({len(rows)} bars)")
            report(m, rows)
