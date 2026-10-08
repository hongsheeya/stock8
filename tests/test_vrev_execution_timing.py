import importlib.util
from pathlib import Path
from unittest.mock import patch
import unittest

spec = importlib.util.spec_from_file_location('vrev_timing', Path(__file__).resolve().parents[1] / 'src/portal/trading/model/struct/daytrade.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class VrevExecutionTimingTests(unittest.TestCase):
    def simulate(self, prices, **profile):
        service = module.Daytrade.__new__(module.Daytrade)
        bars = [dict(timestamp=f'2026-09-01T09:{i*5:02}:00', open=o,close=c,
                     vwap=1, rsi14=50, bb_upper=10000) for i,(o,c) in enumerate(prices)]
        with patch.object(service, 'vrev_entry_issues', return_value=[]), patch.object(service, '_event_filter_snapshot', return_value={}):
            return service._simulate_vrev_session(dict(prev_close=100, bars=bars), 10000,
                dict(commission_bps=0, slippage_bps=0, sell_tax_bps=0, **profile))

    def test_no_same_bar_or_favourable_vwap_execution(self):
        result = self.simulate([(100,99), (105,105), (105,105), (105,105)])
        first = result['trades'][0]
        self.assertEqual(first['price'],105)
        self.assertEqual(first['timestamp'],'2026-09-01T09:05:00')
        self.assertFalse(result['live_parity_verified'])

    def test_stop_blocks_reentry_and_fills_next_open(self):
        r = self.simulate([(100,100),(100,97),(90,90),(90,90),(90,90),(90,90)])
        self.assertEqual(sum(t['side']=='BUY' for t in r['trades']), 1)
        self.assertEqual(r['trades'][1]['reason'],'Auto stop loss')
        self.assertEqual(r['trades'][1]['price'],90)

    def test_reentry_can_be_explicitly_enabled(self):
        r = self.simulate([(100,100),(100,97),(90,90),(90,90),(90,90),(90,90)], stop_reentry_same_day_block=False)
        self.assertEqual(sum(t['side']=='BUY' for t in r['trades']), 2)

    def test_future_exit_cannot_happen_on_entry_bar(self):
        r = self.simulate([(100,99),(100,110),(120,120),(120,120)])
        self.assertEqual(r['trades'][1]['price'],120)
        self.assertEqual(r['trades'][1]['timestamp'],'2026-09-01T09:10:00')

    def test_single_bar_cannot_create_fictional_fill(self):
        self.assertEqual(self.simulate([(100,99)])['trade_count'],0)
