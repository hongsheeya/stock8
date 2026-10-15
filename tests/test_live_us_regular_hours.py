"""LIVE US day-trade orders wait for the regular session, as PAPER does.

The US strategies are backtested on regular hours and the live bars carry no
premarket data, but in LIVE the auto cycle could submit from 04:00 ET.
"""
import unittest
from unittest.mock import Mock, patch

from test_daytrade_engine_regressions import _engine_with_state, daytrade_engine


class LiveUsRegularHoursTests(unittest.TestCase):
    def _engine(self, regular_open):
        engine, _ = _engine_with_state({}, [])
        engine._is_infinite_buy_symbol = lambda *_a, **_k: False
        engine._us_market_open = lambda: regular_open
        engine._hard_locked = Mock(return_value=True)  # the next gate: proves this one passed
        engine.signal_status = Mock(return_value={})
        engine._broker = Mock(side_effect=AssertionError("broker called"))
        return engine

    def test_live_auto_order_waits_outside_regular_hours(self):
        with patch.object(daytrade_engine, "_PAPER_MODE", False):
            result = self._engine(regular_open=False).execute_live("TQQQ", market="US", strategy_id="us_breakout")
        self.assertEqual(result["action"], "WAIT_MARKET")

    def test_live_regular_hours_and_forced_orders_pass(self):
        with patch.object(daytrade_engine, "_PAPER_MODE", False):
            self.assertEqual(self._engine(regular_open=True).execute_live("TQQQ", market="US")["action"], "HARD_LOCKED")
            self.assertEqual(self._engine(regular_open=False).execute_live("TQQQ", market="US", force=True)["action"], "HARD_LOCKED")

    def test_live_ks_is_unchanged(self):
        with patch.object(daytrade_engine, "_PAPER_MODE", False):
            self.assertEqual(self._engine(regular_open=False).execute_live("069500", market="KS")["action"], "HARD_LOCKED")


if __name__ == "__main__":
    unittest.main()
