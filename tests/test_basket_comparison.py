import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('basket_comparison', Path(__file__).resolve().parents[1] / 'scripts/compare-basket-strategies.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


class BasketComparisonTests(unittest.TestCase):
    def sessions(self, prices):
        return [dict(date='2026-09-01', prev_close=100, bars=[dict(
            timestamp=f'2026-09-01T09:{i:02}:00+09:00', open=p, close=p, high=p, low=p,
            volume=100, warm=True, ema20=101, ema50=100, trend_rsi=60,
            trend_rsi_prev=59, rsi14=50, bb_upper=1000, protect_add=False)
            for i, p in enumerate(prices)])]

    def test_signal_fills_next_open_not_signal_close(self):
        r = bench.run(self.sessions([100, 103, 103, 103]), mode='trend', cost_scale=0)
        self.assertEqual(r['orders'][0]['price'], 103)
        self.assertLess(r['orders'][0]['signal_time'], r['orders'][0]['time'])

    def test_max_three_entries_and_weighted_basis(self):
        r = bench.run(self.sessions([100,100,99,99,98,98,98]), cost_scale=0)
        self.assertEqual(r['max_entries'], 3)
        self.assertAlmostEqual(r['trades'][0]['average_entry'], 99)
        self.assertEqual(len(set(o['time'] for o in r['orders'] if o['action']=='BUY')), 3)

    def test_flat_zero_cost_and_cost_drag(self):
        s = self.sessions([100]*9)
        self.assertAlmostEqual(bench.run(s, cost_scale=0)['return_pct'], 0)
        self.assertLess(bench.run(s)['return_pct'], 0)

    def test_stop_can_gap_beyond_threshold(self):
        r = bench.run(self.sessions([100,100,94,80,80,80]), cost_scale=0)
        self.assertEqual(r['trades'][0]['reason'], 'stop')
        self.assertEqual(r['trades'][0]['exit_price'], 80)
        self.assertLess(r['trades'][0]['pnl']/r['trades'][0]['basis'], -.05)

    def test_cash_cap_and_conservation_with_multiplier(self):
        r = bench.run(self.sessions([100,100,99,99,98,98,97,97]), multiplier=2)
        self.assertLessEqual(r['max_allocation_pct'], 100)
        self.assertLessEqual(r['max_entries'], 3)
        self.assertAlmostEqual(sum(t['pnl'] for t in r['trades']), r['return_pct']/100*bench.INITIAL)

    def test_trend_protection_stops_adds_not_exits(self):
        s = self.sessions([100,100,99,99,94,90,90])
        for b in s[0]['bars']: b['protect_add'] = True
        r = bench.run(s, cost_scale=0)
        self.assertEqual(r['max_entries'], 1)
        self.assertGreater(r['protected_bars'], 0)
        self.assertEqual(r['trades'][0]['reason'], 'stop')

    def test_cooldown_three_completed_bars(self):
        r = bench.run(self.sessions([100,100,103,103,103,103,103,103,103,103]), mode='trend', cost_scale=0)
        orders = r['orders']
        self.assertEqual(orders[1]['action'], 'SELL')
        self.assertEqual(orders[1]['time'][14:16], '03')
        self.assertEqual(orders[2]['time'][14:16], '07')

    def test_indicators_do_not_change_with_future_suffix(self):
        s = self.sessions([100+i*.1 for i in range(59)])
        a = bench.prepare(s)[0]['bars']
        s[0]['bars'].append(dict(s[0]['bars'][-1], timestamp='2026-09-01T10:00:00+09:00', open=1000,high=1000,low=1000,close=1000))
        b = bench.prepare(s)[0]['bars'][:-1]
        self.assertEqual(a, b)

    def test_vrev_stop_blocks_same_day_reentry(self):
        with patch.object(bench.reference.research, 'vrev_entry_issues', return_value=[]):
            r = bench.run(self.sessions([100,100,97,97,97,97,97,97]), mode='vrev', cost_scale=0)
        self.assertEqual(sum(x['action']=='BUY' for x in r['orders']), 1)

    def test_day_close_vs_carry_and_aggregate(self):
        s = self.sessions([100]*8)
        s2 = copy.deepcopy(s[0])
        s2['date'] = '2026-09-02'
        for b in s2['bars']:
            b['timestamp'] = b['timestamp'].replace('09-01', '09-02')
        s.append(s2)
        flat = bench.run(s, cost_scale=0)
        carry = bench.run(s, carry=True, cost_scale=0)
        self.assertEqual(flat['cycles'], 2)
        self.assertEqual(carry['cycles'], 1)
        self.assertEqual(bench.aggregate([flat,carry])['return_pct'], 0)
