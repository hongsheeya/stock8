"""Research only: replay Stock8's domestic recommendation pipeline day by day.

For every target session D it runs the *unmodified* Daytrade.auto_train() with
offline stubs, exactly as the live worker would before trading D:

  * training data   = the 10 complete 5m sessions before D (production: yfinance
                      period=10d interval=5m), Yahoo-anchored like production
  * decision time   = 08:30 of D (the engine's pre-open refresh window), so the
                      selection never sees D's own bars
  * universe        = Daytrade.candidate_universe(); the KIS volume/fluctuation
                      ranking it merges is rebuilt from the previous session's
                      full-day bars of every symbol in the frozen snapshot
                      (large-cap universe only: real KIS rankings also surface
                      small caps we cannot replay)
  * market regime   = Daytrade._classify_domestic_market_regime on those rows,
                      then the engine's _apply_ks_market_regime_policy rules

Nothing is traded here; selections are written to
data/reconciliation-audits/research-20261014/ks_replay_selections.json and
evaluated by research-20261014-ks-evaluate.py.
"""
import argparse
import datetime as dt
import multiprocessing as mp
import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import research_20261014_lib as L  # noqa: E402

SEED = 2_000_000          # requested_seed in the committed KS recommendation cache
TRAIN_SESSIONS = 10        # production: period=10d
DECISION_TIME = '08:30'    # pre-open refresh window (engine refreshes hourly from 1h before open)

_STATE = {}


def _init_worker(seed=None):
    if seed:
        globals()['SEED'] = seed
    d = L.load_daytrade()
    syms = L.kr_symbol_map()
    sessions = {}
    names = {c['symbol']: c['name'] for c in d.DEFAULT_CANDIDATES + d.KR_REGIME_ETFS}
    for code, sym in syms.items():
        try:
            sessions[code] = L.sessions_from_rows(d, L.kr_rows(sym, '5m'), 'KS')
        except Exception:
            continue
    _STATE.update(d=d, sessions=sessions, names=names, syms=syms)


def _calendar():
    ref = _STATE['sessions']['005930']
    return [s['date'] for s in ref]


def _ranking_rows(day):
    """KIS-like ranking rows as they stand before D's open: the previous
    session's full-day volume, turnover and change versus its own anchor."""
    rows = []
    for code, sess in _STATE['sessions'].items():
        prior = [s for s in sess if s['date'] < day]
        if not prior:
            continue
        s = prior[-1]
        bars = s['bars']
        if not bars or s['prev_close'] <= 0:
            continue
        price = bars[-1]['close']
        vol = sum(int(b['volume']) for b in bars)
        turnover = sum(b['close'] * int(b['volume']) for b in bars)
        change = (price / s['prev_close'] - 1) * 100
        rows.append({'mksc_shrn_iscd': code, 'hts_kor_isnm': _STATE['names'].get(code, code),
                     'stck_prpr': price, 'acml_vol': vol, 'acml_tr_pbmn': turnover,
                     'prdy_ctrt': round(change, 2)})
    return rows


class _KisStub:
    def __init__(self, rows):
        self.rows = rows

    def get_domestic_volume_rank(self, min_price=0, max_price=0, min_volume=0):
        rows = [r for r in self.rows if min_price <= r['stck_prpr'] <= max_price]
        return sorted(rows, key=lambda r: r['acml_tr_pbmn'], reverse=True)[:30]

    def get_domestic_fluctuation_rank(self, min_price=0, max_price=0, min_volume=0,
                                      min_change=2.0, max_change=29.4, count=30):
        rows = [r for r in self.rows if min_price <= r['stck_prpr'] <= max_price
                and min_change <= r['prdy_ctrt'] <= max_change]
        return sorted(rows, key=lambda r: r['prdy_ctrt'], reverse=True)[:count]


def _regime_policy(rows, regime):
    """Copy of DaytradeEngine._apply_ks_market_regime_policy (daytrade_engine.py)."""
    inverse = {'114800', '252670', '251340'}
    bull = {'122630', '233740'}
    allowed, excluded = [], []
    for item in rows:
        sym, mkt = item.get('symbol', ''), str(item.get('market', 'KS')).upper()
        reason = ''
        if regime == 'RISK_OFF':
            if sym in bull:
                reason = 'risk_off_bull_leverage'
            elif mkt == 'KQ' and sym not in inverse:
                reason = 'risk_off_kosdaq'
        elif regime == 'RISK_ON' and sym in inverse:
            reason = 'risk_on_inverse'
        elif regime == 'NEUTRAL' and sym in {'252670', '122630', '233740'}:
            reason = 'neutral_2x'
        (excluded if reason else allowed).append({**item, 'regime_block': reason} if reason else item)

    def priority(item):
        s = item.get('symbol', '')
        if regime == 'RISK_OFF' and s in inverse:
            return 2
        if regime == 'RISK_ON' and s in bull:
            return 2
        return 1
    allowed.sort(key=priority, reverse=True)
    return allowed, excluded


def replay_day(day_index):
    d = _STATE['d']
    cal = _calendar()
    day = cal[day_index]
    hh, mm = map(int, DECISION_TIME.split(':'))
    L.set_clock(dt.datetime.fromisoformat(day) + dt.timedelta(hours=hh, minutes=mm))
    mod = L.daytrade_module()
    # deterministic 5-minute rotation of the static anchors, as at 09:30 of D
    epoch = dt.datetime.fromisoformat(day).replace(hour=hh, minute=mm) - dt.timedelta(hours=9)
    mod._time = types.SimpleNamespace(time=lambda: epoch.timestamp(), monotonic=time.monotonic, sleep=time.sleep)

    rows = _ranking_rows(day)
    d.struct.kis_api = _KisStub(rows)
    mod.Daytrade._DYNAMIC_UNIVERSE_CACHE.clear()

    def prepare(symbol, market='KS', period='10d', interval='5m'):
        sess = _STATE['sessions'].get(str(symbol).upper())
        if not sess:
            raise Exception('no data')
        prior = [s for s in sess if s['date'] < day]
        return prior[-TRAIN_SESSIONS:]

    book = {}
    d._prepare_dataset = prepare
    d._save_recommendation = lambda data, market='KS': None
    d._write_training_artifacts = lambda payload: None
    d._save_profile_book_entries = lambda entries, market='KS': book.update(entries)
    d._resolve_symbol_name = lambda symbol: _STATE['names'].get(symbol, symbol)

    t0 = time.time()
    rec = d.auto_train(seed=SEED, requested_seed=SEED, market='KS')
    regime = d.market_regime_snapshot()
    universe = [c.get('symbol') for c in d.candidate_universe('KS')]
    board = []
    for row in rec.get('leaderboard', []):
        key = f"{row['symbol']}:{row['strategy_id']}"
        board.append({k: row.get(k) for k in (
            'symbol', 'name', 'market', 'strategy_id', 'trade_ready', 'quality_issues', 'rank_score',
            'selection_score', 'total_return', 'validation_return', 'win_rate', 'validation_win_rate',
            'profit_factor', 'validation_profit_factor', 'avg_trades', 'avg_profit', 'max_drawdown',
            'universe_source', 'trend_alignment_score', 'last_price')} | {'profile': (book.get(key) or {}).get('profile')})
    allowed, excluded = _regime_policy(board, regime.get('regime', 'NEUTRAL'))
    return {
        'date': day, 'decision_time': DECISION_TIME, 'seconds': round(time.time() - t0, 1),
        'regime': regime, 'universe': universe,
        'aggregate': rec.get('aggregate'), 'selected': rec.get('selected'),
        'leaderboard': board, 'regime_allowed': [r['symbol'] + ':' + r['strategy_id'] for r in allowed],
        'regime_excluded': [r['symbol'] + ':' + r['strategy_id'] for r in excluded],
        'errors': rec.get('errors', [])[:5],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=20)
    ap.add_argument('--last', type=int, default=0, help='only the last N sessions')
    ap.add_argument('--seed', type=float, default=SEED)
    args = ap.parse_args()
    globals()['SEED'] = args.seed
    _init_worker()
    cal = _calendar()
    targets = list(range(TRAIN_SESSIONS, len(cal)))
    if args.last:
        targets = targets[-args.last:]
    print(f'{len(cal)} sessions {cal[0]}..{cal[-1]}; replaying {len(targets)} days', flush=True)
    with mp.Pool(args.workers, initializer=_init_worker, initargs=(args.seed,)) as pool:
        results = []
        for res in pool.imap(replay_day, targets):
            ready = [r['symbol'] + ':' + r['strategy_id'] for r in res['leaderboard'] if r['trade_ready']]
            print(res['date'], res['regime'].get('regime'), 'universe', len(res['universe']),
                  'selected', (res['selected'] or {}).get('symbol'), (res['selected'] or {}).get('strategy_id'),
                  'trade_ready', ready[:5], f"{res['seconds']}s", flush=True)
            results.append(res)
    name = 'ks_replay_selections.json' if SEED == 2_000_000 else f'ks_replay_selections_seed{int(SEED)}.json'
    path = L.write_json(name, {
        'scope': 'Offline replay of unmodified Daytrade.auto_train selection; research only',
        'seed': SEED, 'train_sessions': TRAIN_SESSIONS, 'decision_time': DECISION_TIME,
        'universe_limitations': 'KIS rankings rebuilt from a frozen large-cap snapshot (94 symbols); '
                                'learned profile-book names unavailable offline',
        'days': results})
    print('wrote', path)


if __name__ == '__main__':
    main()
