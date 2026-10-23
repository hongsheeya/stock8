"""Indicator warm-up history for the "regime" family (no keys, public API).

The 5m files start on 2025-10-21, so a 100-day moving average would not exist
until late January 2026 and every long-lookback rule would be forced into cash
during the first (crashing) months - a free, artificial advantage on TRAIN.
To avoid that bias we fetch Upbit DAILY candles (day = 00:00 UTC, the same
boundary used everywhere else) for the ~200 days BEFORE the 5m data.

These daily closes are used ONLY to compute indicator values for the first
decisions; no trade is ever simulated before 2025-10-22T00:00:00 UTC.
The overlap days 2025-10-21 and 2025-10-22 are kept so regime.py can verify
that the API daily close equals the last 5m close of the same UTC day.
"""
import json
import os
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MARKETS = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]
UA = {"User-Agent": "stock8-research/1.0", "Accept": "application/json"}

for m in MARKETS:
    q = urllib.parse.urlencode({"market": m, "count": 200, "to": "2025-10-23T00:00:00Z"})
    req = urllib.request.Request("https://api.upbit.com/v1/candles/days?" + q, headers=UA)
    data = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
    rows = sorted(({"t": c["candle_date_time_utc"], "o": c["opening_price"], "h": c["high_price"],
                    "l": c["low_price"], "c": c["trade_price"]} for c in data), key=lambda r: r["t"])
    json.dump(rows, open(os.path.join(HERE, f"warmup_daily_{m}.json"), "w"))
    print(m, len(rows), rows[0]["t"], rows[-1]["t"])
    time.sleep(0.2)
