"""Upbit 5m candles for a fixed historical window (G1 out-of-sample test)."""
import json, os, sys, time, datetime, urllib.request, urllib.parse
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "candles_hist")
os.makedirs(OUT, exist_ok=True)
MARKETS = sys.argv[1].split(",")
END = sys.argv[2]      # e.g. 2025-10-21T00:00:00 (UTC, exclusive)
START = sys.argv[3]    # e.g. 2019-10-21T00:00:00
UA = {"User-Agent": "stock8-research/1.0", "Accept": "application/json"}

def get(url):
    for attempt in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as res:
                return json.loads(res.read().decode())
        except Exception:
            time.sleep(1.0 + attempt)
    raise RuntimeError("failed " + url)

for market in MARKETS:
    path = os.path.join(OUT, f"{market}_5m.json")
    if os.path.exists(path):
        print(market, "exists", flush=True); continue
    rows = {}; to = END.replace("T", " "); calls = 0
    stop = datetime.datetime.fromisoformat(START)
    while True:
        data = get("https://api.upbit.com/v1/candles/minutes/5?" + urllib.parse.urlencode({"market": market, "count": 200, "to": to}))
        calls += 1
        if not data: break
        for c in data:
            t = c["candle_date_time_utc"]
            rows[t] = {"t": t, "o": c["opening_price"], "h": c["high_price"], "l": c["low_price"], "c": c["trade_price"], "v": c["candle_acc_trade_volume"], "krw": c["candle_acc_trade_price"]}
        oldest = data[-1]["candle_date_time_utc"]
        if datetime.datetime.fromisoformat(oldest) <= stop or len(data) < 200: break
        to = oldest.replace("T", " ")
        if calls % 500 == 0: print(market, "progress", oldest, calls, flush=True)
        time.sleep(0.11)
    out = sorted((r for r in rows.values() if r["t"] >= START), key=lambda r: r["t"])
    json.dump(out, open(path, "w"))
    print(market, len(out), out[0]["t"] if out else "-", out[-1]["t"] if out else "-", "calls", calls, flush=True)
