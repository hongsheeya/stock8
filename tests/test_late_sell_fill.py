"""10-23 PAPER: a market sell seen partly filled at submission must book the
rest of its fill once reconciliation sees it (122630: 109 of 495 booked)."""
import datetime
import unittest

from test_daytrade_engine_regressions import _engine_with_state

AVG = 64743.85


def _state():
    return {"symbol": "122630", "market": "KS", "position_qty": 0, "avg_price": 0.0,
            "realized_profit": 0.0, "daily_realized_profit": 0.0, "daily_realized_date": "2026-10-23",
            "orders": [{"timestamp": "2026-10-23 10:20:02", "action": "SELL_FULL", "qty": 495, "order_no": "0000017997",
                        "status": "PARTIAL", "filled_qty": 109, "filled_price": 63557.0,
                        "entry_avg": AVG, "booked_qty": 109, "booked_price": 63557.0}]}


class LateSellFillTests(unittest.TestCase):
    def setUp(self):
        self.engine, _ = _engine_with_state({}, [])
        self.engine._now = lambda: datetime.datetime(2026, 10, 23, 10, 30)
        self.engine._append_runtime_log = lambda *a, **k: None

    def test_full_fill_books_the_unbooked_shares_once(self):
        state = _state()
        self.engine._book_realized(state, (63557.0 - AVG) * 109)
        fill = {"order_no": "17997", "status": "FILLED", "filled_qty": 495, "filled_price": 63554.75}
        self.engine._mark_state_order_fill(state, "0000017997", fill)
        expected = 495 * (63554.75 - AVG)
        self.assertAlmostEqual(state["daily_realized_profit"], round(expected, 2), places=0)
        self.assertEqual(state["orders"][0]["booked_qty"], 495)
        # the same evidence again books nothing more
        self.engine._mark_state_order_fill(state, "0000017997", fill)
        self.assertAlmostEqual(state["daily_realized_profit"], round(expected, 2), places=0)

    def test_orders_without_a_booking_record_are_left_alone(self):
        state = _state()
        for key in ("entry_avg", "booked_qty", "booked_price"):
            state["orders"][0].pop(key)
        self.engine._mark_state_order_fill(state, "0000017997", {"status": "FILLED", "filled_qty": 495, "filled_price": 63554.75})
        self.assertEqual(state["daily_realized_profit"], 0.0)

    def test_buys_are_never_booked(self):
        state = _state()
        state["orders"][0]["action"] = "BUY1"
        self.assertEqual(self.engine._book_late_sell_fill(state, state["orders"][0] | {"filled_qty": 495}), 0.0)


if __name__ == "__main__":
    unittest.main()
