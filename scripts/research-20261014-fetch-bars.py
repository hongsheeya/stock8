"""Research only: download public Yahoo bars for the 2026-10-14 strategy review.

No broker imports, credentials or order endpoints. Output is a frozen snapshot so
every simulation in this review reads identical inputs:

  data/reconciliation-audits/research-20261014/bars/{interval}/{symbol}.csv

Usage: .venv/Scripts/python scripts/research-20261014-fetch-bars.py [--only kr5m kr1m us5m daily]
"""
import argparse
import datetime as dt
import json
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/reconciliation-audits/research-20261014/bars'

# Every domestic code that appears in Stock8's own recommendation/profile/live
# caches (data/daytrade/**). Using the system's own historical universe avoids
# hand-picking winners, but it is still a large-cap, currently-listed universe.
KR_CODES = [
    '004020', '006260', '015760', '042660', '112610', '008770', '035420', '017670',
    '047050', '139480', '000100', '005940', '285130', '068270', '028260', '036570',
    '051910', '005830', '007070', '005930', '066970', '010140', '105560', '021240',
    '001450', '003670', '035720', '034020', '011780', '253450', '228340', '086520',
    '196170', '004170', '000810', '000720', '267260', '009150', '000270', '011070',
    '138040', '028670', '042700', '005490', '036460', '024110', '088350', '454910',
    '128940', '161390', '004370', '180640', '079550', '012330', '001040', '383220',
    '066570', '010950', '078930', '071050', '000880', '086790', '069620', '271560',
    '018260', '352820', '010120', '011170', '006400', '005380', '003550', '034230',
    '329180', '086280', '316140', '012450', '000660', '034220', '247540', '047920',
    '161890', '069500',
    # Daytrade.DEFAULT_CANDIDATES / KR_REGIME_ETFS members not in the caches above
    '277810', '214150', '348370', '033780', '030200', '000080',
    '229200', '114800', '252670', '251340', '122630', '233740',
]
US_SYMBOLS = [
    'AAPL', 'AMD', 'AMZN', 'APP', 'ARM', 'ASTS', 'AVGO', 'COIN', 'CRWD', 'GOOGL',
    'HOOD', 'IONQ', 'IWM', 'MELI', 'META', 'MSFT', 'MSTR', 'MU', 'NET', 'NFLX',
    'NVDA', 'PANW', 'PLTR', 'QQQ', 'RIVN', 'RKLB', 'SERV', 'SMCI', 'SNOW', 'SOXL',
    'SPXL', 'SPY', 'TEM', 'TQQQ', 'TSLA', 'TSM', 'UPRO',
]
DAILY_SYMBOLS = ['SOXL', 'TQQQ', 'SOXX', 'QQQ', 'UPRO', 'SPXL', 'TECL', 'FNGU', 'BULZ', 'USD=X', 'KRW=X']


def _frame(symbol, **kw):
    for attempt in range(3):
        try:
            df = yf.Ticker(symbol).history(auto_adjust=True, timeout=20, **kw)
            if not df.empty:
                return df
        except Exception as exc:  # network hiccups / throttling
            print('  retry', symbol, type(exc).__name__, str(exc)[:80], flush=True)
        time.sleep(2 + 3 * attempt)
    return pd.DataFrame()


def _save(df, path, tz):
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
    df.columns = ['open', 'high', 'low', 'close', 'volume']
    idx = df.index.tz_convert(tz) if df.index.tz is not None else df.index
    df.index = idx
    df.index.name = 'timestamp'
    df = df[~df.index.duplicated(keep='last')].sort_index()
    df = df[(df[['open', 'high', 'low', 'close']] > 0).all(axis=1)]
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path)
    return len(df)


def kr_symbol(code):
    """Resolve .KS/.KQ by probing a short daily request."""
    for suffix in ('.KS', '.KQ'):
        if not _frame(code + suffix, period='5d', interval='1d').empty:
            return code + suffix
    return None


def fetch_kr(intervals):
    resolved_path = OUT / 'kr_symbols.json'
    resolved = json.loads(resolved_path.read_text()) if resolved_path.exists() else {}
    for code in KR_CODES:
        if code not in resolved:
            resolved[code] = kr_symbol(code)
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            resolved_path.write_text(json.dumps(resolved, indent=1))
        sym = resolved[code]
        if not sym:
            print('skip (no Yahoo data)', code, flush=True)
            continue
        if SKIP_EXISTING and all((OUT / i / f'{sym}.csv').exists() for i in intervals):
            continue
        if '5m' in intervals:
            n = _save(_frame(sym, period='60d', interval='5m', prepost=False),
                      OUT / '5m' / f'{sym}.csv', 'Asia/Seoul')
            print('5m', sym, n, flush=True)
        if '1m' in intervals:
            # Yahoo keeps ~30 days of 1m bars, max 8 days per request.
            end = dt.datetime.now(dt.timezone.utc)
            parts = []
            for k in range(4):
                e = end - dt.timedelta(days=7 * k)
                s = e - dt.timedelta(days=7)
                part = _frame(sym, start=s, end=e, interval='1m', prepost=False)
                if not part.empty:
                    parts.append(part)
            if parts:
                n = _save(pd.concat(parts), OUT / '1m' / f'{sym}.csv', 'Asia/Seoul')
                print('1m', sym, n, flush=True)
        time.sleep(0.5)


def fetch_us():
    for sym in US_SYMBOLS:
        n = _save(_frame(sym, period='60d', interval='5m', prepost=True),
                  OUT / 'us5m' / f'{sym}.csv', 'America/New_York')
        print('us5m', sym, n, flush=True)
        time.sleep(0.5)


def fetch_daily():
    for sym in DAILY_SYMBOLS:
        df = _frame(sym, period='max', interval='1d')
        if df.empty:
            print('daily skip', sym)
            continue
        df.index = df.index.tz_localize(None) if df.index.tz is not None else df.index
        n = _save(df, OUT / 'daily' / f'{sym}.csv', None)
        print('daily', sym, n, flush=True)


SKIP_EXISTING = False


def main():
    global SKIP_EXISTING
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', nargs='*', default=['kr5m', 'kr1m', 'us5m', 'daily'])
    ap.add_argument('--skip-existing', action='store_true')
    args = ap.parse_args()
    SKIP_EXISTING = args.skip_existing
    if 'daily' in args.only:
        fetch_daily()
    if 'us5m' in args.only:
        fetch_us()
    kr = [x[2:] for x in args.only if x.startswith('kr')]
    if kr:
        fetch_kr(kr)
    (OUT / 'fetched_at.txt').write_text(dt.datetime.now().isoformat())


if __name__ == '__main__':
    main()
