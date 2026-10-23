"""Research only: trade the replayed selections with the live-path replica.

Inputs : ks_replay_selections.json (research-20261014-ks-replay.py)
Outputs: ks_live_replay_<variant>_<interval>.json + console summary

Modes
  LIVE  : only trade_ready vrev rows survive the live quality gate; volume
          breakout is shadow-only in LIVE, so it never orders.
  PAPER : as LIVE when anything is trade_ready, otherwise the engine's
          "exploration" takes the top 3 regime-allowed rows (vrev and
          volume_breakout) and trades them with the same live guards.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import research_20261014_lib as L  # noqa: E402
import research_20261014_live_replica as R  # noqa: E402


def candidate_lists(day, mode):
    board = day['leaderboard']
    allowed = set(day['regime_allowed'])
    rows = [r for r in board if f"{r['symbol']}:{r['strategy_id']}" in allowed and r.get('profile')]
    ready = [r for r in rows if r['trade_ready']]
    if mode == 'LIVE':
        rows = [r for r in ready if r['strategy_id'] == 'vrev']
    else:
        rows = ready if ready else rows[:3]
    return [(r['symbol'], r['strategy_id'], r['profile']) for r in rows]


class BarStore:
    def __init__(self, d, interval):
        self.d, self.interval = d, interval
        self.syms = L.kr_symbol_map()
        self.cache = {}

    def day_bars(self, code, day):
        if code not in self.cache:
            sym = self.syms.get(code)
            rows = L.kr_rows(sym, self.interval) if sym else []
            by_day = {}
            for r in rows:
                if r['time'] < '09:00' or r['time'] >= '15:30':
                    continue
                by_day.setdefault(r['date'], []).append(r)
            closes = L.kr_official_closes(sym) if sym else {}
            days = sorted(by_day)
            prev = {days[i]: closes.get(days[i - 1], by_day[days[i - 1]][-1]['close']) for i in range(1, len(days))}
            self.cache[code] = (by_day, prev)
        by_day, prev = self.cache[code]
        raw = by_day.get(day)
        if not raw or len(raw) < 5:
            return None
        return R.decorate_day(self.d, raw, prev.get(day, 0.0))


def run(selections, interval, mode, policy=None, cost_scale=1.0, seed=2_000_000, start=None, end=None):
    d = L.load_daytrade()
    store = BarStore(d, interval)
    rep = R.LiveReplica(d, seed=seed, costs=R.Costs(scale=cost_scale), mode=mode, policy=policy,
                        bar_minutes=int(interval.rstrip('m')))
    days = [x for x in selections['days'] if (start is None or x['date'] >= start) and (end is None or x['date'] <= end)]
    traded_days, gated_days = 0, 0
    last_bars = {}
    for day in days:
        cands = candidate_lists(day, mode)
        if policy and policy.get('candidate_filter'):
            cands = policy['candidate_filter'](day, cands)
        gated_days += 0 if cands else 1
        bars = {}
        for code, _, _ in cands:
            b = store.day_bars(code, day['date'])
            if b:
                bars[code] = b
        if rep.pos and rep.pos['code'] not in bars:
            b = store.day_bars(rep.pos['code'], day['date'])
            if b:
                bars[rep.pos['code']] = b
        n_before = len(rep.trades)
        if bars:
            rep.run_day(day['date'], [c for c in cands if c[0] in bars], bars)
            last_bars, last_day = bars, day['date']
        traded_days += 1 if len(rep.trades) > n_before else 0
    if rep.pos and last_bars:
        rep.close_out(last_bars, last_day)
    pnls = [t['pnl'] for t in rep.trades]
    stats = L.cycle_stats(pnls)
    equity = [seed + x['equity_pnl'] for x in rep.daily]
    reasons = {}
    for t in rep.trades:
        reasons.setdefault(t['reason'], []).append(t['ret_pct'])
    return {
        'interval': interval, 'mode': mode, 'days': len(days), 'first': days[0]['date'] if days else None,
        'last': days[-1]['date'] if days else None, 'gated_days': gated_days, 'cost_scale': cost_scale,
        'net_krw': round(rep.cash_pnl, 1), 'return_on_seed_pct': round(rep.cash_pnl / seed * 100, 3),
        'mdd_pct': L.max_drawdown_pct(equity), **stats,
        'avg_ret_pct': round(sum(t['ret_pct'] for t in rep.trades) / len(rep.trades), 4) if rep.trades else None,
        'exit_reasons': {k: {'n': len(v), 'avg_ret_pct': round(sum(v) / len(v), 3)} for k, v in sorted(reasons.items())},
        'overnight_trades': sum(1 for t in rep.trades if t['days_held'] > 0),
        'trades': rep.trades, 'daily': rep.daily,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--interval', default='1m')
    ap.add_argument('--modes', nargs='*', default=['LIVE', 'PAPER'])
    ap.add_argument('--selections', default='ks_replay_selections.json')
    ap.add_argument('--seed', type=float, default=2_000_000)
    args = ap.parse_args()
    sel = json.loads((L.OUT / args.selections).read_text(encoding='utf-8'))
    tag = '' if args.seed == 2_000_000 else f'_seed{int(args.seed)}'
    start = '2026-09-16' if args.interval == '1m' else None
    for mode in args.modes:
        res = run(sel, args.interval, mode, start=start, seed=args.seed)
        L.write_json(f'ks_live_replay_{mode.lower()}_{args.interval}{tag}.json', res)
        brief = {k: v for k, v in res.items() if k not in ('trades', 'daily')}
        print(json.dumps(brief, ensure_ascii=False))


if __name__ == '__main__':
    main()
