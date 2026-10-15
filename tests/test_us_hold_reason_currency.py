"""A held US position's hold reason is in dollars against its own target.

10-15: the EPAM position (us_premarket, avg $121.62) read "잭팟까지 ₩2 남음"
on the dashboard: a dollar gap shown as won.
"""
import datetime
import unittest
from unittest.mock import patch

from test_daytrade_engine_regressions import _StrategyStub, _engine_with_state


class UsHoldReasonTests(unittest.TestCase):
    def test_us_position_reports_the_dollar_gap_to_its_take_profit(self):
        engine, _ = _engine_with_state({"EPAM.US": {
            "symbol": "EPAM", "market": "US", "strategy_id": "us_premarket", "position_qty": 97,
            "avg_price": 121.615, "session_date": "2026-05-26", "orders": []}}, [])
        engine._now = lambda: datetime.datetime(2026, 5, 26, 23, 30)
        engine._profile_for = lambda *a, **k: {"jackpot_take_profit_pct": 3.0, "stop_loss_pct": 8.0}
        engine._aggregate_ticks_to_candle = lambda *a: None
        engine._market_buy_budget = lambda *a, **k: {"budget_total": 0, "buy_budget": 0}
        engine._append_runtime_log = lambda *a, **k: None
        bars = [{"timestamp": f"2026-05-26 23:{m:02d}", "date": "2026-05-26", "open": 121.6, "high": 121.9,
                 "low": 121.5, "close": 121.8, "volume": 1000, "vwap": 121.7} for m in range(10)]
        engine._latest_snapshot = lambda *a, **k: (
            {"date": "2026-05-26", "prev_close": 115.0, "prev_close_confirmed": True, "bars": bars},
            {"close": 121.8, "open": 121.0, "high": 122.0, "low": 120.9, "vwap": 121.7,
             "price_source": "kis_overseas_quote", "quote_prev_close": 115.0, "indicator_bar_count": 30})
        with patch.object(_StrategyStub, "_event_filter_snapshot", create=True, return_value={"blocked": False}):
            signal = engine._signal_from_state("EPAM", market="US", strategy_id="us_premarket", sync_broker=False)["signal"]
        self.assertEqual(signal["action"], "HOLD")
        self.assertNotIn("₩", signal["reason"])
        self.assertIn("$3.46", signal["reason"])  # 121.615 x 1.03 - 121.80


if __name__ == "__main__":
    unittest.main()
