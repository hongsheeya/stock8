"""A domestic order from a closed trading day is final, not pending forever.

KRX orders are day orders, but the past-day history still reports an
unfilled remainder as OPEN/PARTIAL (rmn_qty > 0). Read as-is, yesterday's
reservation stayed pending forever and kept the stop-loss suspended.
"""
import unittest
from unittest.mock import Mock

from test_daytrade_engine_regressions import _engine_with_state

YESTERDAY = "2026-05-25 14:00:00"  # the harness clock is 2026-05-26 10:00


def _engine(rows):
    engine, _ = _engine_with_state({}, [])
    engine._domestic_fills_for_pending = Mock(return_value=rows)
    engine._log_execution = Mock()
    engine._broker = lambda: Mock()
    return engine


def _reservation(placed_at=YESTERDAY):
    return dict(symbol="069500", market="KS", position_qty=10, avg_price=100, realized_profit=0,
                pending_sell_order_no="555", pending_sell_type="JACKPOT", pending_sell_qty=10,
                pending_sell_price=110, pending_sell_placed_at=placed_at,
                orders=[dict(action="PRE_SELL_JACKPOT", order_no="555", qty=10, price=110, status="OPEN")])


class ExpiredDayOrderTests(unittest.TestCase):
    def test_unfilled_reservation_from_yesterday_is_released(self):
        engine = _engine([dict(order_no="555", status="OPEN", filled_qty=0, rmn_qty=10)])
        state = _reservation()
        self.assertEqual(engine._sync_pending_sell(state, "069500", "KS", 105), "cancelled")
        self.assertEqual((state["pending_sell_order_no"], state["position_qty"]), ("", 10))
        self.assertEqual(state["orders"][-1]["status"], "CANCELLED")

    def test_partly_filled_reservation_from_yesterday_books_the_fill(self):
        engine = _engine([dict(order_no="555", status="PARTIAL", filled_qty=4, filled_price=110, rmn_qty=6)])
        state = _reservation()
        self.assertEqual(engine._sync_pending_sell(state, "069500", "KS", 105), "filled")
        self.assertEqual((state["pending_sell_order_no"], state["position_qty"], state["realized_profit"]), ("", 6, 40))
        self.assertEqual(state["orders"][-1]["status"], "FILLED")

    def test_todays_open_order_keeps_waiting(self):
        engine = _engine([dict(order_no="555", status="OPEN", filled_qty=0, rmn_qty=10)])
        state = _reservation(placed_at="2026-05-26 09:50:00")
        self.assertEqual(engine._sync_pending_sell(state, "069500", "KS", 109), "open")
        self.assertEqual(state["pending_sell_order_no"], "555")

    def test_unfilled_buy_from_yesterday_is_released(self):
        engine = _engine([dict(order_no="777", status="OPEN", filled_qty=0, rmn_qty=5)])
        state = dict(symbol="069500", market="KS", position_qty=0, avg_price=0, pending_buy_order_no="777",
                     pending_buy_action="BUY1", pending_buy_qty=5, pending_buy_price=100,
                     pending_buy_placed_at=YESTERDAY, orders=[])
        self.assertEqual(engine._sync_pending_buy(state, "069500", "KS"), "cancelled")
        self.assertEqual((state["pending_buy_order_no"], state["position_qty"]), ("", 0))


if __name__ == "__main__":
    unittest.main()
