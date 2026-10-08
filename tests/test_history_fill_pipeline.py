"""Regression: a confirmed presell must replace pending log and yield FIFO P&L."""
import ast
import datetime
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
source = (ROOT / 'src/app/page.history/api.py').read_text(encoding='utf-8-sig')
tree = ast.parse(source)
functions = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef)], type_ignores=[])

class Time:
    @staticmethod
    def to_kst(value, **kwargs):
        return datetime.datetime.fromisoformat(str(value))

ns = {'re': re, '_TIME': Time, 'datetime': datetime}
exec(compile(functions, 'history-functions', 'exec'), ns)

class HistoryFillPipelineTests(unittest.TestCase):
    def test_confirmed_presell_replaces_pending_and_uses_actual_fill(self):
        state = {'symbol': '229200', 'market': 'KS', 'position_qty': 0, 'orders': [
            {'timestamp': '2026-09-04 10:18:03', 'action': 'BUY1', 'order_no': '000017359', 'qty': 66, 'price': 13545,
             'status': 'FILLED', 'filled_qty': 66, 'filled_price': 13540, 'verification': 'kis'},
            {'timestamp': '2026-09-04 11:08:40', 'action': 'PRE_SELL_JACKPOT', 'order_no': '000022163', 'qty': 66, 'price': 13740,
             'status': 'FILLED', 'filled_qty': 66, 'filled_price': 13745, 'verification': 'kis'},
        ]}
        records = ns['_daytrade_records_from_state_orders']('229200.KS', state)
        sell = records[1]
        self.assertTrue(ns['_is_executable_daytrade_record'](sell))
        self.assertEqual(sell['price'], 13745)
        self.assertEqual(sell['matched_buy_amount'], 66 * 13540)
        self.assertGreater(sell['realized'], 0)
        pending = dict(sell, action='PENDING', status='ACCEPTED_UNVERIFIED', verification='', source='trade_log', realized=0)
        merged = ns['_merge_daytrade_record'](pending, sell)
        self.assertEqual(merged['action'], 'SELL')
        self.assertEqual(merged['status'], 'FILLED')
        self.assertGreater(merged['realized'], 0)

    def test_same_order_number_on_different_days_does_not_merge(self):
        a = dict(symbol='229200', market='KS', order_no='0000123', timestamp='2026-09-04 10:00:00')
        b = dict(a, order_no='123')
        self.assertEqual(ns['_daytrade_record_key'](a), ns['_daytrade_record_key'](b))
        b['timestamp'] = '2026-09-05 10:00:00'
        self.assertNotEqual(ns['_daytrade_record_key'](a), ns['_daytrade_record_key'](b))
