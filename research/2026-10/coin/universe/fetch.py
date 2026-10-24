"""Upbit public candles for the universe study (no keys).

  python fetch.py daily            all current KRW markets, daily candles since listing
  python fetch.py hourly A,B,C     60m candles 2019-08-01 .. now for the given markets

Data goes to $COIN_UNIVERSE_DATA (default: ./data, not committed).
"""
import datetime
import json
import os
import sys
import time
import urllib.parse
import urllib.request

DATA = os.environ.get("COIN_UNIVERSE_DATA") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
UA = {"User-Agent": "stock8-research/1.0", "Accept": "application/json"}
PAUSE = 0.15  # ~7 req/s, under Upbit's 10/s quotation limit (the LIVE coin worker shares the IP)
HOURLY_START = "2019-08-01T00:00:00"


def get(url):
    for attempt in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as res:
                return json.loads(res.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return []
            time.sleep(1.0 + attempt)
        except Exception:
            time.sleep(1.0 + attempt)
    raise RuntimeError("failed " + url)


def krw_markets():
    rows = get("https://api.upbit.com/v1/market/all?isDetails=false")
    return sorted(r["market"] for r in rows if r["market"].startswith("KRW-"))


def candles(kind, market, start_iso):
    url = "https://api.upbit.com/v1/candles/" + kind
    rows, to = {}, ""
    stop = datetime.datetime.fromisoformat(start_iso)
    while True:
        params = {"market": market, "count": 200}
        if to:
            params["to"] = to
        data = get(url + "?" + urllib.parse.urlencode(params))
        time.sleep(PAUSE)
        if not data:
            break
        for c in data:
            t = c["candle_date_time_utc"]
            rows[t] = {"t": t, "o": c["opening_price"], "h": c["high_price"], "l": c["low_price"],
                       "c": c["trade_price"], "v": c["candle_acc_trade_volume"], "krw": c["candle_acc_trade_price"]}
        oldest = data[-1]["candle_date_time_utc"]
        if datetime.datetime.fromisoformat(oldest) <= stop or len(data) < 200:
            break
        to = oldest.replace("T", " ")
    return sorted((r for r in rows.values() if r["t"] >= start_iso), key=lambda r: r["t"])


def main():
    mode = sys.argv[1]
    os.makedirs(os.path.join(DATA, mode), exist_ok=True)
    markets = krw_markets() if mode == "daily" else sys.argv[2].split(",")
    for i, market in enumerate(markets):
        path = os.path.join(DATA, mode, f"{market}.json")
        if os.path.exists(path):
            continue
        rows = candles("days" if mode == "daily" else "minutes/60", market, "2017-01-01T00:00:00" if mode == "daily" else HOURLY_START)
        json.dump(rows, open(path, "w"))
        print(f"{i + 1}/{len(markets)} {market} {len(rows)} {rows[0]['t'] if rows else '-'}", flush=True)


if __name__ == "__main__":
    main()
