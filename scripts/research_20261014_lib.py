"""Shared helpers for the 2026-10-14 strategy review (research only).

No broker imports, credentials or order endpoints. Loads Stock8's own Daytrade /
Engine classes with in-memory WIZ stubs (same pattern as tests/) and reads the
frozen bar snapshot written by research-20261014-fetch-bars.py.
"""
import builtins
import csv
import datetime as dt
import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
BARS = ROOT / 'data/reconciliation-audits/research-20261014/bars'
OUT = ROOT / 'data/reconciliation-audits/research-20261014'


# --------------------------------------------------------------------------- stubs
class _Clock:
    current = dt.datetime(2026, 10, 14, 9, 0, 0)

    @classmethod
    def now(cls):
        return cls.current


class _FsStub:
    def exists(self, _path):
        return False

    def read(self, _path):
        return ''

    def read_json(self, _path, default=None):
        return default

    def write(self, _path, _content):
        return None

    def write_json(self, _path, _content):
        return None

    def makedirs(self, _path):
        return None


class _ProjectStub:
    def fs(self):
        return _FsStub()


class _WizStub:
    project = _ProjectStub()

    @staticmethod
    def model(name):
        if name == 'portal/trading/kst':
            return _Clock
        raise AssertionError(f'unexpected wiz.model({name})')


class StructStub:
    def __init__(self, configs=None):
        self.configs = dict(configs or {})

    def get_config(self, key, default=None):
        return self.configs.get(key, default)


builtins.wiz = _WizStub()


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, SRC / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_DAYTRADE_MOD = None


def daytrade_module():
    global _DAYTRADE_MOD
    if _DAYTRADE_MOD is None:
        _DAYTRADE_MOD = _load('stock8_daytrade_research', 'portal/trading/model/struct/daytrade.py')
    return _DAYTRADE_MOD


def load_daytrade(configs=None):
    return daytrade_module().Daytrade(StructStub(configs))


def set_clock(when):
    _Clock.current = when


# --------------------------------------------------------------------------- data
def kr_symbol_map():
    return {k: v for k, v in json.loads((BARS / 'kr_symbols.json').read_text()).items() if v}


def _parse_ts(text):
    # CSV timestamps look like 2026-10-13 14:55:00+09:00 (KR) / -04:00 (US)
    return dt.datetime.fromisoformat(text)


def read_bars(path, to_tz_offset_hours=9):
    """Rows in Daytrade._prepare_dataset format, timestamps converted to KST."""
    rows = []
    tz = dt.timezone(dt.timedelta(hours=to_tz_offset_hours))
    with open(path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            ts = _parse_ts(r['timestamp']).astimezone(tz)
            o, h, l, c = (float(r[k]) for k in ('open', 'high', 'low', 'close'))
            if min(o, h, l, c) <= 0 or not all(math.isfinite(x) for x in (o, h, l, c)):
                continue
            rows.append({
                'timestamp': ts.strftime('%Y-%m-%d %H:%M'),
                'date': ts.strftime('%Y-%m-%d'),
                'time': ts.strftime('%H:%M'),
                'open': o, 'high': h, 'low': l, 'close': c,
                'volume': int(float(r['volume'] or 0)),
            })
    rows.sort(key=lambda x: x['timestamp'])
    return rows


def kr_rows(symbol, interval='5m'):
    return read_bars(BARS / interval / f'{symbol}.csv')


def kr_official_closes(symbol):
    path = BARS / 'kr_daily' / f'{symbol}.csv'
    out = {}
    if not path.exists():
        return out
    with open(path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            try:
                c = float(r['close'])
            except (TypeError, ValueError):
                continue
            if math.isfinite(c) and c > 0:
                out[r['date']] = c
    return out


def us_rows_regular(symbol):
    """US 5m bars restricted to the regular session (09:30-16:00 ET), KST stamps,
    i.e. what Daytrade._prepare_dataset(prepost=False) would see."""
    rows = []
    with open(BARS / 'us5m' / f'{symbol}.csv', newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            ts_et = _parse_ts(r['timestamp'])
            hm = ts_et.hour * 60 + ts_et.minute
            if hm < 9 * 60 + 30 or hm >= 16 * 60:
                continue
            ts = ts_et.astimezone(dt.timezone(dt.timedelta(hours=9)))
            o, h, l, c = (float(r[k]) for k in ('open', 'high', 'low', 'close'))
            if min(o, h, l, c) <= 0:
                continue
            rows.append({
                'timestamp': ts.strftime('%Y-%m-%d %H:%M'),
                'date': ts.strftime('%Y-%m-%d'),
                'time': ts.strftime('%H:%M'),
                'open': o, 'high': h, 'low': l, 'close': c,
                'volume': int(float(r['volume'] or 0)),
                'et_date': ts_et.strftime('%Y-%m-%d'),
            })
    rows.sort(key=lambda x: x['timestamp'])
    return rows


def sessions_from_rows(daytrade, rows, market='KS'):
    """Exactly Daytrade._rows_to_sessions: anchor = previous session's last bar."""
    return daytrade._rows_to_sessions([dict(r) for r in rows], market=market)


def with_official_anchor(daytrade, sessions, closes):
    """Re-decorate sessions using the official previous-day close as the anchor
    (the live engine anchors on the broker's previous close, not Yahoo's last
    intraday bar). Falls back to the Yahoo anchor when the close is missing."""
    dates = [s['date'] for s in sessions]
    out = []
    for i, s in enumerate(sessions):
        anchor = s['prev_close']
        if i > 0 and dates[i - 1] in closes:
            anchor = closes[dates[i - 1]]
        raw = [{k: v for k, v in b.items() if k in ('timestamp', 'date', 'time', 'open', 'high', 'low', 'close', 'volume')}
               for b in s['bars']]
        out.append({'date': s['date'], 'prev_close': anchor, 'bars': daytrade._decorate_bars(raw, anchor)})
    return out


# --------------------------------------------------------------------------- metrics
def cycle_stats(pnls):
    pnls = [p for p in pnls if p is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gain, loss = sum(wins), -sum(losses)
    return {
        'cycles': len(pnls),
        'win_rate_pct': round(100 * len(wins) / len(pnls), 2) if pnls else None,
        'avg_win': round(gain / len(wins), 2) if wins else None,
        'avg_loss': round(-loss / len(losses), 2) if losses else None,
        'profit_factor': round(gain / loss, 3) if loss > 0 else (None if gain == 0 else float('inf')),
        'net': round(sum(pnls), 2),
    }


def max_drawdown_pct(equity):
    peak, mdd = -math.inf, 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak * 100)
    return round(mdd, 3)


def write_json(name, payload):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    return path
