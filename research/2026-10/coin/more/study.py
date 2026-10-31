"""Coin W1-W4 vs V1 (PREREG.md). Reuses ../variants and ../universe (set
COIN_UNIVERSE_DATA to the hourly data folder). `python study.py fetch` caches
Binance BTCUSDT daily closes and USD/KRW in ./ext (not committed)."""
import datetime
import importlib.util
import json
import os
import sys
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("vstudy", os.path.join(HERE, "..", "variants", "study.py"))
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)
U, S = V.U, V.S
H, DAY, WEEK = 3600, 86400, 7 * 86400
EXT = os.environ.get("COIN_EXT_DATA") or os.path.join(HERE, "ext")
MARKETS = V.MARKETS
SELECT, HOLDOUT = V.SELECT, V.HOLDOUT
FEE, FEE_HI = 0.001, 0.002


def fetch():
    os.makedirs(EXT, exist_ok=True)
    rows, start = [], 1502928000000
    while True:
        url = f"https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1d&startTime={start}&limit=1000"
        part = json.loads(urllib.request.urlopen(url, timeout=20).read())
        if not part:
            break
        rows += [(int(r[0]) // 1000, float(r[4])) for r in part]
        start = int(part[-1][0]) + DAY * 1000
        if len(part) < 1000:
            break
    json.dump(rows, open(os.path.join(EXT, "binance_btcusdt_1d.json"), "w"))
    import yfinance as yf
    k = yf.Ticker("KRW=X").history(period="max")
    fx = [(d.strftime("%Y-%m-%d"), float(c)) for d, c in k["Close"].dropna().items()]
    json.dump(fx, open(os.path.join(EXT, "usdkrw.json"), "w"))
    print("binance", len(rows), "fx", len(fx))


# ------------------------------------------------------------------ helpers
_C = {}


def candles(m):
    if m not in _C:
        _C[m] = V.candles(m)
    return _C[m]


def daily_closes(c):
    """[(day_start, close)] of completed UTC days."""
    return [(b["start"], b["c"]) for b in S.build_bars(c, S.DAY_SEC)]


def completed_before(daily, t):
    """closes of days that ended at or before t."""
    lo, hi = 0, len(daily)
    while lo < hi:
        mid = (lo + hi) // 2
        if daily[mid][0] + DAY <= t:
            lo = mid + 1
        else:
            hi = mid
    return daily[:lo]


def sleeve_curve(c, trades, start, end, fee, weights=None):
    """V.sleeve_curve with an optional per-trade invested fraction."""
    tk = U.ticks(c)
    month = lambda sec: datetime.datetime.fromtimestamp(sec, datetime.timezone.utc).strftime("%Y-%m")
    adj = [(et, epx + tk.get(month(et), 0) / 2, xt, xpx - tk.get(month(xt), 0) / 2) for et, epx, xt, xpx, _w in trades]
    weights = weights or [1.0] * len(adj)
    close = {r["t"]: r["c"] for r in c}
    eq, cash, qty, ti, last, idle = {}, 1.0, 0.0, 0, None, 0.0
    t = start
    while t < end:
        while ti < len(adj) and adj[ti][2] == t and qty > 0:
            cash, qty = idle + qty * adj[ti][3] * (1 - fee), 0.0
            idle = 0.0
            ti += 1
        if ti < len(adj) and adj[ti][0] == t and qty == 0:
            w = max(0.0, min(1.0, weights[ti]))
            invest = cash * w
            idle, qty, cash = cash - invest, invest / (adj[ti][1] * (1 + fee)), 0.0
            if adj[ti][2] == t:
                cash, qty, idle = idle + qty * adj[ti][3] * (1 - fee), 0.0, 0.0
                ti += 1
        last = close.get(t, last)
        eq[t] = cash + idle + qty * (last or 0)
        t += H
    return eq


def summarize(curves, start, end):
    hours = sorted(curves[0])
    port = [sum(cv[t] for cv in curves) / len(curves) for t in hours]
    years = (end - start) / (365.25 * DAY)
    peak, mdd = 0.0, 0.0
    for v in port:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    cagr = (port[-1] ** (1 / years) - 1) * 100 if port[-1] > 0 else -100.0
    return {"cagr": round(cagr, 1), "mdd": round(mdd * 100, 1), "mar": round(cagr / abs(mdd * 100), 2) if mdd < 0 else 99.0}


def markets_for(period):
    """As in ../variants: the selection period uses all 4 (SOL is a cash sleeve
    until it lists), the holdout BTC/ETH/XRP."""
    return list(MARKETS) if period == SELECT else list(MARKETS[:3])


# ------------------------------------------------------------------ rules
def v1_trades(m, a, b, allowed=lambda t: True):
    return U.gated_replay(candles(m), a, b, allowed)


_DC = {}


def daily_of(m):
    if m not in _DC:
        _DC[m] = daily_closes(candles(m))
    return _DC[m]


def vol30(m, t):
    d = completed_before(daily_of(m), t)[-31:]
    if len(d) < 31:
        return None
    rets = [d[i][1] / d[i - 1][1] - 1 for i in range(1, len(d))]
    mu = sum(rets) / len(rets)
    return (sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5 * 365 ** 0.5


_DAILY = {}


def btc_filter(n):
    if "btc" not in _DAILY:
        _DAILY["btc"] = daily_closes(candles("KRW-BTC"))
    daily = _DAILY["btc"]

    def allowed(t):
        done = completed_before(daily, t)
        if len(done) < n:
            return False
        return done[-1][1] > sum(x for _t, x in done[-n:]) / n
    return allowed


_PREM = {}


def premium_series():
    if not _PREM:
        bn = {d: c for d, c in json.load(open(os.path.join(EXT, "binance_btcusdt_1d.json")))}
        fx = dict(json.load(open(os.path.join(EXT, "usdkrw.json"))))
        fx_days = sorted(fx)
        up = daily_closes(candles("KRW-BTC"))
        j, last_fx = 0, None
        for start, close in up:
            day = datetime.datetime.utcfromtimestamp(start).strftime("%Y-%m-%d")
            while j < len(fx_days) and fx_days[j] <= day:
                last_fx = fx[fx_days[j]]
                j += 1
            if start in bn and last_fx:
                _PREM[start] = close / (bn[start] * last_fx) - 1
    return _PREM


def premium_filter(th):
    import bisect
    prem = premium_series()
    days = sorted(prem)

    def allowed(t):
        i = bisect.bisect_right(days, t - DAY)  # days that ended at or before t
        if i == 0:
            return True
        return prem[days[i - 1]] < th
    return allowed


def run_sleeves(period, fee, rule, kw, exclude=()):
    a, b = U.epoch(period[0]), U.epoch(period[1])
    curves = []
    for m in markets_for(period):
        if m in exclude:
            continue
        c = candles(m)
        weights = None
        if rule == "V1":
            tr = v1_trades(m, a, b)
        elif rule == "W1":
            tr = v1_trades(m, a, b)
            weights = []
            for et, *_rest in tr:
                v = vol30(m, et)
                weights.append(1.0 if not v else min(1.0, kw["target"] / v))
        elif rule == "W2":
            tr = v1_trades(m, a, b, allowed=(lambda t: True) if m == "KRW-BTC" else btc_filter(kw["n"]))
        elif rule == "W4":
            tr = v1_trades(m, a, b, allowed=premium_filter(kw["th"]))
        curves.append(sleeve_curve(c, tr, a, b, fee, weights))
    return summarize(curves, a, b)


def run_rotation(period, fee, kw, exclude=()):
    """W3: Monday 00:00 UTC, top-k by `weeks` return among coins above SMA50."""
    a, b = U.epoch(period[0]), U.epoch(period[1])
    mk = [m for m in markets_for(period) if m not in exclude]
    data = {m: candles(m) for m in mk}
    opens = {m: {r["t"]: r["o"] for r in data[m]} for m in mk}
    closes = {m: {r["t"]: r["c"] for r in data[m]} for m in mk}
    daily = {m: daily_of(m) for m in mk}
    tks = {m: U.ticks(data[m]) for m in mk}
    month = lambda sec: datetime.datetime.utcfromtimestamp(sec).strftime("%Y-%m")
    first_monday = a + ((7 - datetime.datetime.utcfromtimestamp(a).weekday()) % 7) * DAY
    first_monday -= first_monday % DAY
    cash, qty, eq, last = 1.0, {}, {}, {}
    t = a
    while t < b:
        if t >= first_monday and (t - first_monday) % WEEK == 0:
            scores = []
            for m in mk:
                done = completed_before(daily[m], t)
                n = kw["weeks"] * 7
                if len(done) < max(50, n + 1):
                    continue
                if done[-1][1] <= sum(x for _t, x in done[-50:]) / 50:
                    continue
                scores.append((done[-1][1] / done[-1 - n][1] - 1, m))
            pick = [m for _s, m in sorted(scores, reverse=True)[:kw["top"]]]
            value = cash + sum(q * last.get(m, 0) for m, q in qty.items())
            target = {m: value / kw["top"] for m in pick}
            # sell what is not kept or is over target, then buy
            for m in list(qty):
                px = opens[m].get(t)
                if px is None:
                    continue
                keep = target.get(m, 0.0)
                cur = qty[m] * px
                if cur > keep + 1e-9:
                    sell_q = (cur - keep) / px
                    cash += sell_q * (px - tks[m].get(month(t), 0) / 2) * (1 - fee)
                    qty[m] -= sell_q
                    if qty[m] <= 1e-12:
                        del qty[m]
            for m, keep in target.items():
                px = opens[m].get(t)
                if px is None:
                    continue
                cur = qty.get(m, 0.0) * px
                if keep > cur + 1e-9:
                    spend = min(cash, keep - cur)
                    qty[m] = qty.get(m, 0.0) + spend / ((px + tks[m].get(month(t), 0) / 2) * (1 + fee))
                    cash -= spend
        for m in mk:
            if t in closes[m]:
                last[m] = closes[m][t]
        eq[t] = cash + sum(q * last.get(m, 0) for m, q in qty.items())
        t += H
    return summarize([eq], a, b)


def run(rule, period, fee=FEE, exclude=(), **kw):
    if rule == "W3":
        return run_rotation(period, fee, kw, exclude)
    return run_sleeves(period, fee, rule, kw, exclude)


MAIN = {"W1": {"target": 0.60}, "W2": {"n": 50}, "W3": {"top": 2, "weeks": 4}, "W4": {"th": 0.05}}
NEIGHBORS = {"W1": [{"target": 0.40}, {"target": 0.80}], "W2": [{"n": 20}, {"n": 100}],
             "W3": [{"top": 1, "weeks": 4}, {"top": 2, "weeks": 2}, {"top": 2, "weeks": 8}], "W4": [{"th": 0.03}, {"th": 0.08}]}


def main():
    a, b = U.epoch(SELECT[0]), U.epoch(SELECT[1])
    c0 = candles("KRW-BTC")
    assert v1_trades("KRW-BTC", a, b) == V.replay_4h(c0, a, b, k=4.0), "baseline must equal V1"
    prem = premium_series()
    vals = sorted(prem.values())
    print(f"kimchi premium days {len(vals)}: median {vals[len(vals) // 2] * 100:+.1f}%, "
          f">=5% on {sum(v >= 0.05 for v in vals) / len(vals) * 100:.0f}% of days")
    base = {"sel": run("V1", SELECT), "hold": run("V1", HOLDOUT), "sel_hi": run("V1", SELECT, FEE_HI)}
    # the coin that made the most for V1 in the selection period
    best = max(MARKETS, key=lambda m: run("V1", SELECT, exclude=tuple(x for x in MARKETS if x != m))["cagr"])
    base["sel_ex"] = run("V1", SELECT, exclude=(best,))
    print("V1", base, "best coin", best)
    verdict = {}
    for name, kw in MAIN.items():
        r = {"sel": run(name, SELECT, **kw), "hold": run(name, HOLDOUT, **kw), "sel_hi": run(name, SELECT, FEE_HI, **kw),
             "sel_ex": run(name, SELECT, exclude=(best,), **kw)}
        nb = [(k, run(name, SELECT, **k)) for k in NEIGHBORS[name]]
        need = 2  # 2 of 2; W3 lists 3 neighbors in the PREREG table, so 2 of 3
        beats = sum(1 for _k, x in nb if x["mar"] > base["sel"]["mar"])
        gates = {
            "1 sel MAR>=V1x1.1": r["sel"]["mar"] >= base["sel"]["mar"] * 1.10,
            "2 holdout MAR>=V1 & MDD>-35": r["hold"]["mar"] >= base["hold"]["mar"] and r["hold"]["mdd"] > -35,
            "3 cost x2 MAR>=V1": r["sel_hi"]["mar"] >= base["sel_hi"]["mar"],
            f"4 neighbors {beats}/{len(nb)}": beats >= need,
            "5 ex-best MAR>=V1": r["sel_ex"]["mar"] >= base["sel_ex"]["mar"],
        }
        verdict[name] = all(gates.values())
        print(f"\n{name} {kw}: sel {r['sel']} | hold {r['hold']} | x2 {r['sel_hi']} | ex-best {r['sel_ex']}")
        print("   neighbors:", [(k, x) for k, x in nb])
        print("   gates:", gates, "->", "PASS" if verdict[name] else "FAIL")
    print("\nverdict:", verdict)


if __name__ == "__main__":
    if sys.argv[1:] == ["fetch"]:
        fetch()
    else:
        main()
