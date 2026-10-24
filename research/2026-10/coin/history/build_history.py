"""Build the /coin "past performance" data (10-24).

Same construction as the live engine: BTC/ETH/XRP/SOL, 25% of the seed each,
every sleeve compounds on its own and is never rebalanced; a sleeve sits in
cash before its KRW listing. Trades come from the app's own
coin_strategy.replay on Upbit 60m candles; cost 0.10% per side plus half a
tick (G1's conservative setting; Upbit charges 0.05%). Benchmark: the same
four sleeves bought and held from the start (or listing).

Writes src/portal/trading/model/coin_backtest.py (a static data model).
Needs the hourly candles from ../universe/fetch.py (COIN_UNIVERSE_DATA).
"""
import datetime
import importlib.util
import json
import os
import pprint
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("study", os.path.join(HERE, "..", "universe", "study.py"))
st = importlib.util.module_from_spec(spec)
spec.loader.exec_module(st)
S = st.S
ROOT = st.ROOT
OUT = os.path.join(ROOT, "src", "portal", "trading", "model", "coin_backtest.py")

MARKETS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"]
START, END = "2019-10-21", "2026-10-24"
G1 = ("2019-10-21", "2025-10-21")
FEE = 0.001
H = 3600


def ymd(sec):
    return datetime.datetime.fromtimestamp(sec, datetime.timezone.utc).strftime("%Y-%m-%d")


def sleeve(market, start, end):
    candles = st.hourly(market)
    tk = st.ticks(candles)
    month = lambda sec: datetime.datetime.fromtimestamp(sec, datetime.timezone.utc).strftime("%Y-%m")
    trades = []
    for et, epx, xt, xpx, why in S.replay(candles, start, end):
        trades.append((et, epx + tk.get(month(et), 0) / 2, xt, xpx - tk.get(month(xt), 0) / 2, why))
    close = {r["t"]: r["c"] for r in candles}
    first_open = next((r for r in candles if r["t"] >= start), None)
    strat, bh = {}, {}
    cash, qty, ti = 1.0, 0.0, 0
    bh_qty = 0.0
    last = None
    t = start
    while t < end:
        if first_open and t == first_open["t"]:
            bh_qty = 1.0 / (first_open["o"] * (1 + FEE))
        while ti < len(trades) and trades[ti][2] == t and qty > 0:
            cash = qty * trades[ti][3] * (1 - FEE)
            qty = 0.0
            ti += 1
        if ti < len(trades) and trades[ti][0] == t and qty == 0:
            qty = cash / (trades[ti][1] * (1 + FEE))
            cash = 0.0
            if trades[ti][2] == t:  # stopped inside the entry candle
                cash = qty * trades[ti][3] * (1 - FEE)
                qty = 0.0
                ti += 1
        last = close.get(t, last)
        strat[t] = cash + qty * (last or 0)
        bh[t] = bh_qty * last if bh_qty and last else 1.0
        t += H
    stats = []
    for et, epx, xt, xpx, why in trades:
        stats.append({"ret": (xpx * (1 - FEE)) / (epx * (1 + FEE)) - 1, "days": (xt - et) / 86400, "why": why})
    return strat, bh, stats


def mdd(values):
    peak, worst = 0.0, 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst * 100


def cagr(a, b, years):
    return ((b / a) ** (1 / years) - 1) * 100 if a > 0 and b > 0 else -100.0


def main():
    start, end = st.epoch(START), st.epoch(END)
    sleeves = {m: sleeve(m, start, end) for m in MARKETS}
    hours = sorted(sleeves[MARKETS[0]][0])
    port = [sum(sleeves[m][0][t] for m in MARKETS) / len(MARKETS) for t in hours]
    bench = [sum(sleeves[m][1][t] for m in MARKETS) / len(MARKETS) for t in hours]
    years = (end - start) / (365.25 * 86400)

    daily, seen = [], set()
    peak = 0.0
    for t, p, b in zip(hours, port, bench):
        peak = max(peak, p)
        day = ymd(t)
        if day in seen:
            daily[-1] = [day, round(p, 4), round(b, 4), round((p / peak - 1) * 100, 2)]
        else:
            seen.add(day)
            daily.append([day, round(p, 4), round(b, 4), round((p / peak - 1) * 100, 2)])

    by_year = []
    index = {ymd(t)[:4]: [] for t in hours}
    for t, p, b in zip(hours, port, bench):
        index[ymd(t)[:4]].append((p, b))
    prev_p, prev_b = 1.0, 1.0
    for year in sorted(index):
        p_end, b_end = index[year][-1]
        by_year.append({"year": int(year), "strategy": round((p_end / prev_p - 1) * 100, 1),
                        "buy_hold": round((b_end / prev_b - 1) * 100, 1),
                        "partial": year in (START[:4], END[:4])})
        prev_p, prev_b = p_end, b_end

    coins = []
    all_trades = []
    for m in MARKETS:
        strat, bh, stats = sleeves[m]
        all_trades += stats
        wins = [s for s in stats if s["ret"] > 0]
        coins.append({"market": m, "strategy_pct": round((strat[hours[-1]] - 1) * 100, 1),
                      "buy_hold_pct": round((bh[hours[-1]] - 1) * 100, 1), "trades": len(stats),
                      "win_pct": round(len(wins) / len(stats) * 100, 1) if stats else 0.0,
                      "avg_hold_days": round(sum(s["days"] for s in stats) / len(stats), 1) if stats else 0.0,
                      "best_pct": round(max(s["ret"] for s in stats) * 100, 1) if stats else 0.0,
                      "worst_pct": round(min(s["ret"] for s in stats) * 100, 1) if stats else 0.0,
                      "first": ymd(next(t for t in hours if st.hourly(m) and t >= st.hourly(m)[0]["t"]))})

    g1_end = st.epoch(G1[1])
    i_g1 = next(i for i, t in enumerate(hours) if t >= g1_end)
    wins = [s["ret"] for s in all_trades if s["ret"] > 0]
    losses = [s["ret"] for s in all_trades if s["ret"] <= 0]
    data = {
        "meta": {"start": START, "end": END, "markets": MARKETS, "fee_side_pct": FEE * 100, "half_tick": True,
                 "candles": "업비트 60분봉", "generated": time.strftime("%Y-%m-%d")},
        "stats": {
            "cagr": round(cagr(1.0, port[-1], years), 1), "total": round((port[-1] - 1) * 100, 1), "mdd": round(mdd(port), 1),
            "bh_cagr": round(cagr(1.0, bench[-1], years), 1), "bh_total": round((bench[-1] - 1) * 100, 1), "bh_mdd": round(mdd(bench), 1),
            "trades": len(all_trades), "win_pct": round(len(wins) / len(all_trades) * 100, 1),
            "avg_win_pct": round(sum(wins) / len(wins) * 100, 2), "avg_loss_pct": round(sum(losses) / len(losses) * 100, 2),
            "g1_cagr": round(cagr(1.0, port[i_g1], (g1_end - start) / (365.25 * 86400)), 1), "g1_mdd": round(mdd(port[:i_g1 + 1]), 1),
            "recent_pct": round((port[-1] / port[i_g1] - 1) * 100, 1),
        },
        "years": by_year,
        "coins": coins,
        "daily": daily,
    }
    body = pprint.pformat(data, width=160, compact=True, sort_dicts=False)
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        handle.write('"""Coin rule past performance for the /coin chart (generated by\n'
                     'research/2026-10/coin/history/build_history.py; do not edit by hand)."""\n\n'
                     f"DATA = {body}\n\n\nclass CoinBacktest:\n    DATA = DATA\n\n\nModel = CoinBacktest\n")
    print(json.dumps(data["stats"], ensure_ascii=False))
    print(json.dumps(data["years"], ensure_ascii=False))
    for c in coins:
        print(json.dumps(c, ensure_ascii=False))
    print("daily points", len(daily), "bytes", os.path.getsize(OUT))


if __name__ == "__main__":
    main()
