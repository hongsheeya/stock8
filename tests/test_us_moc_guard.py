"""US close guard: a resting MOC sell while a day-trade position is held.

10-17: PAPER bought four inverse ETFs on Friday afternoon and the PC slept,
so the 15:40 ET flatten never ran (+$726 at the close, -$1,000 on Monday).
"""
import contextlib
import unittest
from unittest.mock import Mock, patch

from test_daytrade_engine_regressions import _engine_with_state, daytrade_engine


def _state(qty=10, **extra):
    row = dict(symbol="TEST", market="US", strategy_id="paper_regime_trend", position_qty=qty, avg_price=30.0,
               orders=[], last_price=30.0)
    row.update(extra)
    return row


class UsMocGuardTests(unittest.TestCase):
    def _engine(self, state, rows=None, enabled=True, window=True):
        engine, saved = _engine_with_state({"TEST.US": state}, [])
        engine._config = lambda key, default=None: ("true" if enabled else "false") if key == "daytrade_us_moc_guard_enabled" else default
        engine._us_moc_window_open = lambda: window
        engine._us_exchange = lambda _symbol: "NASD"
        engine._append_runtime_log = lambda *a, **k: None
        broker = Mock()
        broker.request_options = lambda **_k: contextlib.nullcontext()
        broker.get_overseas_order_history.return_value = rows or []
        broker.sell_order.return_value = {"order_no": "M1", "order_type": "MOC"}
        engine._broker = lambda: broker
        return engine, broker, saved

    def test_off_by_default_places_nothing(self):
        state = _state()
        engine, broker, _ = self._engine(state, enabled=False)
        self.assertEqual(engine._us_moc_guard(state, "TEST"), "off")
        broker.sell_order.assert_not_called()

    def test_places_one_moc_for_the_held_quantity(self):
        state = _state()
        engine, broker, _ = self._engine(state)
        self.assertEqual(engine._us_moc_guard(state, "TEST"), "placed")
        broker.sell_order.assert_called_once_with("TEST", 10, price=0, order_type="MOC", exchange="NASD")
        self.assertEqual((state["moc_order_no"], state["moc_qty"]), ("M1", 10))
        self.assertEqual(state["orders"][-1]["action"], "SELL_MOC")
        self.assertEqual(engine._us_moc_guard(state, "TEST"), "kept")
        broker.sell_order.assert_called_once()

    def test_no_moc_while_another_order_is_pending_or_after_the_cutoff(self):
        for extra, window in (({"pending_buy_order_no": "B1"}, True), ({"pending_sell_order_no": "S1"}, True), ({}, False)):
            state = _state(**extra)
            engine, broker, _ = self._engine(state, window=window)
            engine._us_moc_guard(state, "TEST")
            broker.sell_order.assert_not_called()

    def test_moc_filled_at_the_close_is_booked(self):
        state = _state(moc_order_no="M1", moc_qty=10, moc_placed_at="2026-05-26 23:00:00",
                       orders=[{"order_no": "M1", "action": "SELL_MOC", "qty": 10, "filled_qty": 0, "status": "OPEN"}])
        engine, _, _ = self._engine(state, rows=[{"order_no": "M1", "symbol": "TEST", "side": "SELL", "status": "FILLED",
                                                  "filled_qty": 10, "filled_price": 31.0}])
        self.assertEqual(engine._us_moc_guard(state, "TEST"), "moc_filled")
        self.assertEqual(state["position_qty"], 0)
        self.assertEqual(state["last_exit_action"], "SELL_MOC")
        self.assertEqual(state["orders"][-1]["status"], "FILLED")
        self.assertNotIn("moc_order_no", state)

    def test_an_app_sell_cancels_the_moc_first(self):
        state = _state(moc_order_no="M1", moc_qty=10, moc_placed_at="2026-05-26 23:00:00")
        engine, broker, _ = self._engine(state)
        broker.get_overseas_order_history.side_effect = [
            [],  # still open before the cancel
            [{"order_no": "M1", "symbol": "TEST", "side": "SELL", "status": "CANCELLED", "filled_qty": 0}],
        ]
        with patch.object(daytrade_engine._clock, "sleep"):
            self.assertTrue(engine._us_moc_release(state, "TEST"))
        broker.cancel_overseas_order.assert_called_once_with("M1", "TEST", 10, exchange="NASD")
        self.assertNotIn("moc_order_no", state)
        self.assertEqual(state["position_qty"], 10)

    def test_an_unconfirmed_or_failed_cancel_never_frees_the_shares(self):
        state = _state(moc_order_no="M1", moc_qty=10, moc_placed_at="2026-05-26 23:00:00")
        engine, broker, _ = self._engine(state)
        with patch.object(daytrade_engine._clock, "sleep"):
            self.assertFalse(engine._us_moc_release(state, "TEST"))
            broker.cancel_overseas_order.side_effect = RuntimeError("rate limit")
            state["moc_cancel_error"] = "x"
            self.assertFalse(engine._us_moc_release(state, "TEST"))
        self.assertEqual(state["moc_order_no"], "M1")

    def test_a_moc_that_already_sold_the_shares_blocks_the_app_sell(self):
        state = _state(moc_order_no="M1", moc_qty=10, moc_placed_at="2026-05-26 23:00:00")
        engine, _, _ = self._engine(state, rows=[{"order_no": "M1", "symbol": "TEST", "side": "SELL", "status": "FILLED",
                                                  "filled_qty": 10, "filled_price": 31.0}])
        self.assertFalse(engine._us_moc_release(state, "TEST"))
        self.assertEqual(state["position_qty"], 0)

    def test_reconcile_all_books_a_flat_slot_left_by_the_balance_sync(self):
        state = _state(qty=0, avg_price=0.0, moc_order_no="M1", moc_qty=10, moc_placed_at="2026-05-26 23:00:00")
        engine, _, saved = self._engine(state, rows=[{"order_no": "M1", "symbol": "TEST", "side": "SELL", "status": "FILLED",
                                                      "filled_qty": 10, "filled_price": 31.0}])
        engine._us_moc_reconcile_all()
        self.assertNotIn("moc_order_no", saved()["TEST.US"])

    def test_scale_in_resizes_the_moc(self):
        state = _state(qty=15, moc_order_no="M1", moc_qty=10, moc_placed_at="2026-05-26 23:00:00")
        engine, broker, _ = self._engine(state)
        with patch.object(daytrade_engine._clock, "sleep"):
            self.assertEqual(engine._us_moc_guard(state, "TEST"), "resizing")
        broker.cancel_overseas_order.assert_called_once()


if __name__ == "__main__":
    unittest.main()
