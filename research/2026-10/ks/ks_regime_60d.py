"""KS regime-trend replay on 60 days of 5m bars (same rule as live, fixed before running).

BEAR ETF on proxy (069500 / 229200): proxy below its VWAP and down >= 1% from
the open; BULL mirror. ETF above its own VWAP. Entries 09:30-14:30, exit at the
next open on proxy VWAP reversal, -1.5% stop, or 15:10 flatten. 10-minute
cooldown; no re-entry for the day after a stop. Cost 0.05% round trip.
"""
import os
import statistics
from collections import defaultdict
import yfinance as yf

PAIRS = {"114800": ("BEAR", "069500"), "252670": ("BEAR", "069500"), "251340": ("BEAR", "229200"),
         "122630": ("BULL", "069500"), "233740": ("BULL", "229200")}
CACHE = os.path.join(os.path.dirname(__file__), "ks_5m")
os.makedirs(CACHE, exist_ok=True)


def load(code):
    path = os.path.join(CACHE, f"{code}.pkl")
    if os.path.exists(path):
        import pandas as pd
        df = pd.read_pickle(path)
    else:
        df = yf.Ticker(f"{code}.KS").history(period="60d", interval="5m", auto_adjust=False)
        df = df.tz_convert("Asia/Seoul")
        df.to_pickle(path)
    days = defaultdict(list)
    for ts, r in df.iterrows():
        hm = ts.strftime("%H:%M")
        if not ("09:00" <= hm < "15:30") or r["Close"] <= 0:
            continue
        days[ts.strftime("%Y-%m-%d")].append({"hm": hm, "open": float(r["Open"]), "high": float(r["High"]),
                                              "low": float(r["Low"]), "close": float(r["Close"]), "volume": float(r["Volume"])})
    out = {}
    for d, bars in days.items():
        pv = v = 0.0
        for b in bars:
            tp = (b["high"] + b["low"] + b["close"]) / 3
            pv += tp * b["volume"]
            v += b["volume"]
            b["vwap"] = pv / v if v > 0 else tp
        out[d] = bars
    return out


data = {c: load(c) for c in set(PAIRS) | {"069500", "229200"}}
days = sorted(data["069500"])


def run(etf, side, proxy, day, start="09:30", stop_block=True):
    e, pmap = data[etf].get(day, []), {b["hm"]: b for b in data[proxy].get(day, [])}
    if not e or not data[proxy].get(day):
        return []
    popen = data[proxy][day][0]["open"]
    trades, entry, last_exit, stopped = [], None, -99, False
    for i in range(len(e) - 1):
        bar, nxt = e[i], e[i + 1]
        pb = pmap.get(bar["hm"])
        if pb is None:
            continue
        move = (pb["close"] / popen - 1) * 100
        if side == "BEAR":
            trend, rev = pb["close"] < pb["vwap"] and move <= -1.0, pb["close"] > pb["vwap"]
        else:
            trend, rev = pb["close"] > pb["vwap"] and move >= 1.0, pb["close"] < pb["vwap"]
        if entry is None:
            if start <= bar["hm"] <= "14:30" and trend and not stopped and i - last_exit >= 2 and bar["close"] > bar["vwap"]:
                entry = nxt["open"]
            continue
        stop_hit = bar["close"] <= entry * 0.985
        if nxt["hm"] >= "15:10" or rev or stop_hit:
            trades.append((nxt["open"] / entry - 1) * 100 - 0.05)
            entry, last_exit = None, i
            if stop_hit and not rev and stop_block:
                stopped = True
    if entry is not None:
        trades.append((e[-1]["close"] / entry - 1) * 100 - 0.05)
    return trades


print(f"days {days[0]} ~ {days[-1]} ({len(days)})")
for label, kw in (("current (stop block)", {}), ("no stop block", {"stop_block": False})):
    by_period, by_etf, allt = defaultdict(list), defaultdict(list), []
    for etf, (side, proxy) in PAIRS.items():
        for day in days:
            t = run(etf, side, proxy, day, **kw)
            allt += t
            by_etf[etf] += t
            by_period["~09-15" if day < "2026-09-16" else "09-16~"] += t
    print(f"{label}: trades {len(allt)} win {sum(1 for x in allt if x > 0) / max(1, len(allt)) * 100:.0f}% "
          f"avg {statistics.mean(allt) if allt else 0:+.3f}% sum {sum(allt):+.2f}%")
    for k in sorted(by_period):
        v = by_period[k]
        print(f"   {k}: n {len(v)} win {sum(1 for x in v if x > 0) / max(1, len(v)) * 100:.0f}% sum {sum(v):+.2f}%")
    print("   by ETF:", ", ".join(f"{k} {sum(v):+.1f}%/{len(v)}" for k, v in sorted(by_etf.items(), key=lambda kv: sum(kv[1]))))
