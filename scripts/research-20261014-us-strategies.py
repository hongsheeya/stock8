"""Research only: Stock8's own US day-trade simulators on the last 60 sessions.

Runs Daytrade.simulate_session for each US strategy with the default US profile
on every symbol of the frozen snapshot (regular session 5m bars, i.e. what
Daytrade._prepare_dataset(prepost=False) sees). No parameter search.

Known biases of these simulators (see the report): entries/exits fill at the
signal bar's close (optimistic), and _trade_cost adds the Korean 18bp sell tax
to US sells (pessimistic). Both cost settings are reported.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import research_20261014_lib as L  # noqa: E402

STRATS = ['us_premarket', 'us_breakout', 'us_pullback', 'us_vwap', 'us_opening_reclaim']
TEST_START = '2026-09-16'


def main():
    d = L.load_daytrade()
    syms = sorted(p.stem for p in (L.BARS / 'us5m').glob('*.csv'))
    out = {}
    for cost_name, extra in (('as_coded', {}), ('us_fees_only', {'sell_tax_bps': 0.0})):
        for sid in STRATS:
            prof = {**d.US_DEFAULT_PROFILE, **extra}
            per_trade, by_period = [], {'design': [], 'test': []}
            for sym in syms:
                rows = L.us_rows_regular(sym)
                sessions = d._rows_to_sessions([dict(r) for r in rows], market='US')
                for s in sessions[1:]:
                    res = d.simulate_session(s, 1_000_000, profile=prof, strategy_id=sid)
                    for t in res.get('trades', []):
                        if t.get('side') == 'SELL':
                            per_trade.append(t['pnl'])
                    pnl = res.get('net_profit', 0)
                    if res.get('trade_count'):
                        key = 'test' if s['date'] >= TEST_START else 'design'
                        by_period[key].append(pnl / 1_000_000 * 100)
            stats = L.cycle_stats(per_trade)
            out[f'{sid}:{cost_name}'] = {
                'sell_legs': stats, 'active_sessions': {k: len(v) for k, v in by_period.items()},
                'avg_session_return_pct': {k: round(sum(v) / len(v), 4) if v else None for k, v in by_period.items()},
                'sum_session_return_pct': {k: round(sum(v), 3) for k, v in by_period.items()},
            }
            print(sid, cost_name, json.dumps(out[f'{sid}:{cost_name}']), flush=True)
    L.write_json('us_strategies_default_profile.json', out)


if __name__ == '__main__':
    main()
