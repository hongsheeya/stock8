"""Execute production reconciliation with a broker double; no network orders."""
import copy
import unittest
from unittest.mock import Mock
from test_daytrade_engine_regressions import _engine_with_state
from test_history_fill_pipeline import ns as history


class CancelRecoveryTests(unittest.TestCase):
    def test_partial_then_cancel_preserves_fill_and_history_profit(self):
        engine, _ = _engine_with_state({}, [])
        fill = dict(order_no='123', status='PARTIAL', filled_qty=4, filled_price=110)
        engine._domestic_fills_for_pending = Mock(return_value=[fill])
        state = dict(symbol='069500', market='KS', position_qty=6, avg_price=100,
            pending_sell_order_no='123', pending_sell_qty=10, pending_sell_price=110,
            orders=[dict(timestamp='2026-05-26 09:00:00', action='BUY1', order_no='122',
                         qty=10, price=100, filled_qty=10, filled_price=100, status='FILLED'),
                    dict(timestamp='2026-05-26 09:10:00', action='SELL_FULL', order_no='123',
                         qty=10, price=110, status='OPEN')])
        for _ in range(2):
            self.assertEqual(engine._sync_pending_sell(state, '069500', 'KS', 110), 'open')
        state = copy.deepcopy(state)
        fill['status'] = 'CANCELLED'
        self.assertEqual(engine._sync_pending_sell(state, '069500', 'KS', 110), 'cancelled')
        records = history['_daytrade_records_from_state_orders']('069500.KS', state)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[-1]['qty'], 4)
        self.assertEqual(records[-1]['matched_buy_amount'], 400)
        self.assertGreater(records[-1]['realized'], 0)
        self.assertEqual(state['position_qty'], 6)

    def test_ambiguous_cancel_survives_restart_and_eventual_fill(self):
        for failure in (None, TimeoutError('response lost after broker acceptance')):
            with self.subTest(failure=type(failure).__name__):
                engine, _ = _engine_with_state({}, [])
                broker = Mock()
                broker.cancel_domestic_order.side_effect = failure
                engine._broker = lambda: broker
                engine._domestic_fills_for_pending = Mock(return_value=[])
                engine._log_execution = Mock()
                state = dict(position_qty=10, avg_price=100, realized_profit=0,
                    pending_sell_order_no='000123', pending_sell_qty=10,
                    pending_sell_price=110, pending_sell_placed_at='2026-05-26 09:00:00')
                self.assertEqual(engine._sync_pending_sell(state, '069500', 'KS', 105), 'open')
                self.assertEqual(state['pending_sell_order_no'], '000123')
                # Persist/reload and re-run the same observation: never replay cancel.
                state = copy.deepcopy(state)
                self.assertEqual(engine._sync_pending_sell(state, '069500', 'KS', 105), 'open')
                broker.cancel_domestic_order.assert_called_once()
                engine._domestic_fills_for_pending.return_value = [dict(order_no='123',
                    status='FILLED', filled_qty=10, filled_price=110)]
                self.assertEqual(engine._sync_pending_sell(state, '069500', 'KS', 105), 'filled')
                self.assertEqual(state['position_qty'], 0)
                self.assertEqual(state['realized_profit'], 100)
                self.assertEqual(engine._sync_pending_sell(state, '069500', 'KS', 105), 'none')
                engine._log_execution.assert_called_once()

    def test_confirmed_cancel_clears_tracking(self):
        engine, _ = _engine_with_state({}, [])
        engine._domestic_fills_for_pending = Mock(return_value=[dict(order_no='123', status='CANCELLED')])
        state = dict(pending_sell_order_no='123', pending_sell_cancel_requested_order='123')
        self.assertEqual(engine._sync_pending_sell(state, '069500', 'KS'), 'cancelled')
        self.assertEqual(state['pending_sell_order_no'], '')
        self.assertNotIn('pending_sell_cancel_requested_order', state)
