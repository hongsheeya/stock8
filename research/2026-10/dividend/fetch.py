"""Download UNADJUSTED daily OHLC + dividends + splits for the dividend study.

yfinance history(auto_adjust=False, actions=True): Open/High/Low/Close are split-adjusted
but NOT dividend-adjusted (Adj Close is). Dividends are aligned on the ex-date row and are
split-adjusted the same way as prices, so (price, dividend) pairs stay consistent.
Cached as CSV under ./cache so reruns are cheap.
"""
import json
import os
import sys
import time

import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
os.makedirs(CACHE, exist_ok=True)

US_STOCKS = ["T", "VZ", "MO", "PM", "KO", "PEP", "JNJ", "PFE", "ABBV", "XOM", "CVX", "IBM", "MMM", "KMI",
             "ENB", "BTI", "O", "MAIN", "VICI", "WPC", "UPS", "CVS", "BMY", "GILD", "DUK", "SO"]
US_DIV_ETFS = ["SCHD", "VYM", "HDV", "SPYD", "DVY", "NOBL", "SDIV"]
US_CC_ETFS = ["JEPI", "JEPQ", "QYLD", "XYLD", "RYLD", "DIVO"]
KR_STOCKS = ["033780.KS", "086790.KS", "105560.KS", "055550.KS", "316140.KS", "024110.KS", "017670.KS",
             "030200.KS", "005935.KS", "000810.KS", "138040.KS", "088980.KS"]
KR_ETFS = ["458730.KS", "279530.KS", "161510.KS"]
MARKET = ["^GSPC", "^KS11", "SPY", "069500.KS", "KRW=X"]
ALL = US_STOCKS + US_DIV_ETFS + US_CC_ETFS + KR_STOCKS + KR_ETFS + MARKET


def path_for(sym):
    return os.path.join(CACHE, sym.replace("^", "_").replace("=", "_") + ".csv")


def fetch(sym, force=False):
    p = path_for(sym)
    if os.path.exists(p) and not force:
        return "cached"
    last_err = None
    for attempt in range(5):
        try:
            tk = yf.Ticker(sym)
            df = tk.history(period="max", auto_adjust=False, actions=True)
            if df is None or df.empty:
                raise RuntimeError("empty frame")
            df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            df.index.name = "Date"
            df.to_csv(p)
            meta = getattr(tk, "history_metadata", {}) or {}
            keep = {k: meta.get(k) for k in ("currency", "exchangeName", "exchangeTimezoneName", "instrumentType",
                                             "longName", "shortName", "firstTradeDate")}
            with open(p.replace(".csv", ".meta.json"), "w", encoding="utf-8") as fh:
                json.dump(keep, fh, ensure_ascii=False, default=str)
            return f"ok rows={len(df)} {df.index[0].date()}..{df.index[-1].date()} divs={(df['Dividends'] > 0).sum()}"
        except Exception as exc:  # rate limit or transient error: back off
            last_err = exc
            time.sleep(5 * (attempt + 1))
    return f"FAILED {last_err!r}"


if __name__ == "__main__":
    force = "--force" in sys.argv
    for s in ALL:
        print(s, fetch(s, force=force), flush=True)
        time.sleep(0.7)
