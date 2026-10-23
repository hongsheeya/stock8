"""Upbit public 5-minute candles, ~1 year, for strategy research (no keys)."""
import json, os, sys, time, datetime, urllib.request, urllib.parse
OUT = os.path.join(os.path.dirname(__file__), "candles")
os.makedirs(OUT, exist_ok=True)
MARKETS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 365
UA = {"User-Agent": "stock8-research/1.0", "Accept": "application/json"}

def get(url):
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as res:
                return json.loads(res.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(1.0 + attempt); continue
            raise
        except Exception:
            time.sleep(1.0 + attempt)
    raise RuntimeError("failed " + url)

for market in MARKETS:
    path = os.path.join(OUT, f"{market}_5m.json")
    rows = {}
    if os.path.exists(path):
        rows = {r["t"]: r for r in json.load(open(path))}
    stop = datetime.datetime.utcnow() - datetime.timedelta(days=DAYS)
    to = None
    calls = 0
    while True:
        q = {"market": market, "count": 200}
        if to: q["to"] = to
        data = get("https://api.upbit.com/v1/candles/minutes/5?" + urllib.parse.urlencode(q))
        calls += 1
        if not data: break
        for c in data:
            t = c["candle_date_time_utc"]
            rows[t] = {"t": t, "o": c["opening_price"], "h": c["high_price"], "l": c["low_price"], "c": c["trade_price"], "v": c["candle_acc_trade_volume"], "krw": c["candle_acc_trade_price"]}
        oldest = data[-1]["candle_date_time_utc"]
        if datetime.datetime.fromisoformat(oldest) <= stop: break
        to = oldest.replace("T", " ")
        time.sleep(0.12)
    out = sorted(rows.values(), key=lambda r: r["t"])
    json.dump(out, open(path, "w"))
    print(market, len(out), out[0]["t"], out[-1]["t"], "calls", calls, flush=True)
