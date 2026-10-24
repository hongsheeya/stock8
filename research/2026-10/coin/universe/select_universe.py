"""Point-in-time universes (PREREG.md): top N KRW markets by trailing 90-day
KRW trading value, re-selected on Jan/Apr/Jul/Oct 1 (00:00 UTC); eligible
with >= 180 daily candles before the date; stablecoins excluded.

Writes universes.json {"U10": {"2019-10-01": [...], ...}, "U20": {...}} into
the data folder and prints the union of markets (for fetch.py hourly)."""
import datetime
import glob
import json
import os

DATA = os.environ.get("COIN_UNIVERSE_DATA") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
STABLE = {"USDT", "USDC", "USDS", "DAI", "TUSD", "BUSD", "USDE", "PYUSD", "FDUSD", "USD1", "USDP"}
SIZES = (10, 20)


def dates():
    out, d = [], datetime.date(2019, 10, 1)
    while d <= datetime.date(2026, 10, 1):
        out.append(d)
        d = datetime.date(d.year + (d.month == 10), (d.month + 2) % 12 + 1, 1)
    return out


def main():
    daily = {}
    for path in glob.glob(os.path.join(DATA, "daily", "KRW-*.json")):
        market = os.path.basename(path)[:-5]
        if market.split("-", 1)[1] in STABLE:
            continue
        rows = json.load(open(path))
        daily[market] = [(r["t"][:10], float(r["krw"] or 0)) for r in rows]
    out = {f"U{n}": {} for n in SIZES}
    union = set()
    for d in dates():
        iso = d.isoformat()
        lo = (d - datetime.timedelta(days=90)).isoformat()
        ranked = []
        for market, rows in daily.items():
            before = [krw for day, krw in rows if day < iso]
            if len(before) < 180:
                continue
            ranked.append((sum(krw for day, krw in rows if lo <= day < iso), market))
        ranked.sort(reverse=True)
        for n in SIZES:
            pick = [m for _v, m in ranked[:n]]
            out[f"U{n}"][iso] = pick
            union |= set(pick)
        print(iso, " ".join(m.split("-")[1] for _v, m in ranked[:20]))
    json.dump(out, open(os.path.join(DATA, "universes.json"), "w"), indent=1)
    union |= {"KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL"}
    print(len(union), ",".join(sorted(union)))


if __name__ == "__main__":
    main()
