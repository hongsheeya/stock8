import copy
import unittest
from contextlib import nullcontext
from unittest.mock import Mock
from test_daytrade_engine_regressions import _engine_with_state


class UsPendingTests(unittest.TestCase):
    def test_background_reconciliation_tracks_fully_sold_us_position(self):
        from types import SimpleNamespace
        engine, broker, state, fill = self.setup_order('SELL')
        state['position_qty'] = 0
        state['orders'][0]['timestamp'] = '2026-05-26 01:00:00'
        stored = {'NVDA.US':copy.deepcopy(state)}
        engine._load_state_map = lambda: copy.deepcopy(stored)
        def save(payload):
            stored.clear()
            stored.update(copy.deepcopy(payload))
        engine._save_state_map = save
        engine._fs = lambda: SimpleNamespace(write=SimpleNamespace(json=Mock()))
        engine._data_root = lambda: 'unused'
        fill.update(status='FILLED', filled_qty=10)
        result = engine.reconcile_order_history()
        self.assertEqual(result['updated'], 1)
        self.assertEqual(stored['NVDA.US']['pending_sell_order_no'], '')
        self.assertEqual(stored['NVDA.US']['orders'][0]['filled_qty'], 10)
        self.assertEqual(stored['NVDA.US']['orders'][0]['verification'], 'kis')
        self.assertEqual(stored['NVDA.US']['position_qty'], 0)
        engine.reconcile_order_history()
        broker.get_overseas_order_history.assert_called_once()

    def setup_order(self, side='BUY'):
        engine, _ = _engine_with_state({}, [])
        broker = Mock()
        broker.request_options.side_effect = lambda **kw: nullcontext()
        engine._broker = lambda: broker
        prefix = 'pending_' + side.lower()
        state = dict(symbol='NVDA', market='US', position_qty=4, avg_price=100,
                     orders=[dict(order_no='000123', qty=10, filled_qty=0, status='OPEN')])
        state.update({prefix+'_order_no':'000123', prefix+'_qty':10,
                      prefix+'_placed_at':'2026-05-26 01:00:00'})
        fill = dict(symbol='NVDA', side=side, order_no='123', status='PARTIAL',
                    filled_qty=4, filled_price=110)
        broker.get_overseas_order_history.return_value = [fill]
        return engine, broker, state, fill

    def test_buy_partial_restart_cancel_keeps_cumulative_fill(self):
        engine, broker, state, fill = self.setup_order()
        for _ in range(2):
            self.assertEqual(engine._sync_pending_buy(state, 'NVDA', 'US'), 'open')
            state = copy.deepcopy(state)
        self.assertEqual(state['orders'][0]['filled_qty'], 4)
        fill['status'] = 'CANCELLED'
        self.assertEqual(engine._sync_pending_buy(state, 'NVDA', 'US'), 'cancelled')
        self.assertEqual(state['pending_buy_order_no'], '')
        self.assertEqual(state['orders'][0]['filled_qty'], 4)
        self.assertEqual(state['position_qty'], 4)
        broker.buy_order.assert_not_called()

    def test_sell_partial_then_full_never_calls_domestic_or_double_subtracts(self):
        engine, broker, state, fill = self.setup_order('SELL')
        self.assertEqual(engine._sync_pending_sell(state, 'NVDA', 'US'), 'open')
        fill.update(status='FILLED', filled_qty=10)
        self.assertEqual(engine._sync_pending_sell(state, 'NVDA', 'US'), 'filled')
        self.assertEqual(engine._sync_pending_sell(state, 'NVDA', 'US'), 'none')
        self.assertEqual(state['position_qty'], 4)  # Broker balance owns position changes.
        broker.get_domestic_fills_today.assert_not_called()
        broker.cancel_domestic_order.assert_not_called()

    def test_timeout_empty_and_wrong_symbol_do_not_release_order(self):
        for result in ([], [dict(symbol='AMD', side='BUY', order_no='123', status='FILLED')], TimeoutError('timeout')):
            engine, broker, state, _ = self.setup_order()
            if isinstance(result, Exception):
                broker.get_overseas_order_history.side_effect = result
            else:
                broker.get_overseas_order_history.return_value = result
            self.assertEqual(engine._sync_pending_buy(state, 'NVDA', 'US'), 'open')
            self.assertEqual(state['pending_buy_order_no'], '000123')

    def test_stale_cumulative_response_does_not_erase_partial(self):
        engine, broker, state, fill = self.setup_order()
        engine._sync_pending_buy(state, 'NVDA', 'US')
        fill.update(status='CANCELLED', filled_qty=0)
        self.assertEqual(engine._sync_pending_buy(state, 'NVDA', 'US'), 'open')
        self.assertEqual(state['orders'][0]['filled_qty'], 4)

    def test_query_covers_previous_us_date_and_is_strict(self):
        engine, broker, state, _ = self.setup_order()
        engine._sync_pending_buy(state, 'NVDA', 'US')
        kw = broker.get_overseas_order_history.call_args.kwargs
        self.assertEqual(kw['start_date'], '20260525')
        self.assertTrue(kw['strict'])
