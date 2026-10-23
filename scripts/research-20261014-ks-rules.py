"""Research only: the live V-REV rules applied to every symbol independently.

Separates "do the entry/exit rules have an edge?" from "did the recommender pick
well?". Each symbol gets its own single-slot replica with the default profile.

Variants are fixed here BEFORE looking at the test window and all are reported:
  live_asis      exact live path (incl. reserved-limit stop gap, carry-all)
  live_bugfix    same signals, engineering bugs fixed: stop also guards a
                 pending reserved limit, cooldown after any exit, and the
                 intended close rule (carry only if pnl > -0.8% and price >=
                 VWAP*0.997, else sell at the last bar)
  bugfix_window  + entries only 09:30-14:00 (indicators warmed up, no late entries)
  bugfix_prevclose + window + documented V-REV anchor: price <= official prev close
  bugfix_2to1    + window + jackpot 2.4% / stop 1.2% (break-even win rate ~40%)
  bugfix_2to1_mkt + market filter: KODEX200 (069500) at/above its own VWAP

Periods: design = 5m bars before 2026-09-16, test = 2026-09-16..2026-10-13
(5m and 1m), the last 6 sessions (2026-10-05..13) are newer than every report
in docs/.
"""
import argparse
import json
import multiprocessing as mp
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import research_20261014_lib as L  # noqa: E402
import research_20261014_live_replica as R  # noqa: E402

TEST_START = '2026-09-16'
NEW_START = '2026-10-05'


def _bugfix_exit(rep, bar):
    p = rep.pos
    prof = p['profile']
    price = bar['close']
    jackpot = p['avg'] * (1 + float(prof.get('jackpot_take_profit_pct', 1.2)) / 100)
    if price >= jackpot:
        return ('SELL', 'SELL_FULL')
    if bar['time'] >= rep.policy.get('close_time', '14:55'):
        pnl_pct = (price / p['avg'] - 1) * 100
        if pnl_pct <= -0.8 or price < bar.get('vwap', 0) * 0.997:
            return ('SELL', 'SELL_CLOSE_RULE')
    return None


def _make_market_filter(market_bars):
    def f(code, bar, profile):
        m = market_bars.get(bar['date'], {}).get(bar['time'])
        return bool(m) and m['close'] >= m.get('vwap', 0)
    return f


VARIANTS = {
    'live_asis': dict(profile={}, policy={}),
    'live_bugfix': dict(profile={}, policy={'custom_exit': _bugfix_exit, 'cooldown_after_limit_fill': True,
                                             'no_reserved_limit': True}),
    'bugfix_window': dict(profile={}, policy={'custom_exit': _bugfix_exit, 'cooldown_after_limit_fill': True,
                                               'no_reserved_limit': True, 'entry_window': ('09:30', '14:00')}),
    'bugfix_prevclose': dict(profile={}, policy={'custom_exit': _bugfix_exit, 'cooldown_after_limit_fill': True,
                                                  'no_reserved_limit': True, 'entry_window': ('09:30', '14:00'),
                                                  'anchor': 'prev_close'}),
    'bugfix_2to1': dict(profile={'jackpot_take_profit_pct': 2.4, 'stop_loss_pct': 1.2},
                        policy={'custom_exit': _bugfix_exit, 'cooldown_after_limit_fill': True,
                                'no_reserved_limit': True, 'entry_window': ('09:30', '14:00')}),
    'bugfix_2to1_mkt': dict(profile={'jackpot_take_profit_pct': 2.4, 'stop_loss_pct': 1.2},
                            policy={'custom_exit': _bugfix_exit, 'cooldown_after_limit_fill': True,
                                    'no_reserved_limit': True, 'entry_window': ('09:30', '14:00'),
                                    'market_filter': True}),
}

_W = {}


def _init(interval):
    d = L.load_daytrade()
    _W.update(d=d, interval=interval, syms=L.kr_symbol_map())
    # market proxy bars (KODEX 200), decorated like the live engine
    store = _store('069500')
    _W['market'] = {day: {b['time']: b for b in bars} for day, bars in store.items()}


def _store(code):
    d, interval = _W['d'], _W['interval']
    sym = _W['syms'][code]
    rows = [r for r in L.kr_rows(sym, interval) if '09:00' <= r['time'] < '15:30']
    by_day = {}
    for r in rows:
        by_day.setdefault(r['date'], []).append(r)
    closes = L.kr_official_closes(sym)
    days = sorted(by_day)
    out = {}
    for i, day in enumerate(days):
        if i == 0 or len(by_day[day]) < 5:
            continue
        prev = closes.get(days[i - 1], by_day[days[i - 1]][-1]['close'])
        out[day] = R.decorate_day(d, by_day[day], prev)
    return out


def run_symbol(args):
    code, variant = args
    d = _W['d']
    spec = VARIANTS[variant]
    profile = {**d.DEFAULT_PROFILE, **spec['profile']}
    policy = dict(spec['policy'])
    if policy.pop('market_filter', False):
        market = _W['market']
        policy['extra_entry_filter'] = lambda c, bar, prof: bool(market.get(bar['date'], {}).get(bar['time'])) and \
            market[bar['date']][bar['time']]['close'] >= market[bar['date']][bar['time']].get('vwap', 0)
    days = _store(code)
    rep = R.LiveReplica(d, seed=2_000_000, mode='LIVE', policy=policy, bar_minutes=int(_W['interval'].rstrip('m')))
    last = None
    for day in sorted(days):
        rep.run_day(day, [(code, 'vrev', profile)], {code: days[day]})
        last = day
    if rep.pos and last:
        rep.close_out({code: days[last]}, last)
    for t in rep.trades:
        t['entry_time'] = t['entry_ts'][11:16]
    return code, rep.trades


def summarize(trades, start=None, end=None):
    sel = [t for t in trades if (start is None or t['entry_ts'][:10] >= start) and (end is None or t['entry_ts'][:10] <= end)]
    s = L.cycle_stats([t['pnl'] for t in sel])
    if sel:
        s['avg_ret_pct'] = round(sum(t['ret_pct'] for t in sel) / len(sel), 4)
        s['median_ret_pct'] = round(sorted(t['ret_pct'] for t in sel)[len(sel) // 2], 4)
        s['overnight_share_pct'] = round(100 * sum(t['days_held'] > 0 for t in sel) / len(sel), 1)
        reasons = {}
        for t in sel:
            reasons.setdefault(t['reason'], []).append(t['ret_pct'])
        s['exit_reasons'] = {k: {'n': len(v), 'avg_ret_pct': round(sum(v) / len(v), 3)} for k, v in sorted(reasons.items())}
        buckets = {}
        for t in sel:
            h = t['entry_time'][:2] + (':00' if t['entry_time'][3:] < '30' else ':30')
            buckets.setdefault(h, []).append(t['ret_pct'])
        s['by_entry_halfhour'] = {k: {'n': len(v), 'avg_ret_pct': round(sum(v) / len(v), 3)} for k, v in sorted(buckets.items())}
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--interval', default='5m')
    ap.add_argument('--variants', nargs='*', default=list(VARIANTS))
    ap.add_argument('--workers', type=int, default=20)
    args = ap.parse_args()
    _init(args.interval)
    codes = sorted(_W['syms'])
    out = {'interval': args.interval, 'test_start': TEST_START, 'new_start': NEW_START, 'variants': {}}
    with mp.Pool(args.workers, initializer=_init, initargs=(args.interval,)) as pool:
        for variant in args.variants:
            all_trades = []
            for code, trades in pool.imap_unordered(run_symbol, [(c, variant) for c in codes]):
                all_trades.extend(trades)
            res = {
                'all': summarize(all_trades),
                'design': summarize(all_trades, end='2026-09-15'),
                'test': summarize(all_trades, start=TEST_START),
                'new_6_sessions': summarize(all_trades, start=NEW_START),
            }
            out['variants'][variant] = {'summary': res, 'trades': all_trades}
            brief = {k: {kk: v.get(kk) for kk in ('cycles', 'win_rate_pct', 'avg_ret_pct', 'profit_factor', 'overnight_share_pct')}
                     for k, v in res.items()}
            print(variant, json.dumps(brief), flush=True)
    L.write_json(f'ks_rules_{args.interval}.json', out)


if __name__ == '__main__':
    main()
