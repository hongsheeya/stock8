"""Orders are refused when the signal is old or the session closed (10-17).

The PC slept at 02:53 in the middle of a cycle; at 08:37 the thread resumed
and sent an SOXS BUY computed six hours earlier, after the US close.
"""
import unittest
from unittest.mock import patch

from test_daytrade_engine_regressions import _engine_with_state, daytrade_engine


class StaleSignalTests(unittest.TestCase):
    def setUp(self):
        self.engine, _ = _engine_with_state({}, [])
        self.engine._us_market_open = lambda: True
        self.engine._us_premarket_open = lambda: False
        self.engine._daytrade_market_open = lambda market="KS": True

    def test_old_signal_is_refused(self):
        with patch.object(daytrade_engine._clock, "time", return_value=1_000_000 + 6 * 3600):
            reason = self.engine._order_blocked_reason(1_000_000, "BUY1", "US")
        self.assertIn("오래된 신호", reason)

    def test_fresh_signal_in_session_passes(self):
        with patch.object(daytrade_engine._clock, "time", return_value=1_000_010):
            self.assertEqual(self.engine._order_blocked_reason(1_000_000, "BUY1", "US"), "")
            self.assertEqual(self.engine._order_blocked_reason(1_000_000, "SELL_FULL", "KS"), "")

    def test_buy_after_the_close_is_refused_but_a_sell_is_not(self):
        self.engine._us_market_open = lambda: False
        with patch.object(daytrade_engine._clock, "time", return_value=1_000_010):
            self.assertIn("장이 닫혀", self.engine._order_blocked_reason(1_000_000, "BUY1", "US"))
            self.assertEqual(self.engine._order_blocked_reason(1_000_000, "SELL_FULL", "US"), "")


if __name__ == "__main__":
    unittest.main()
