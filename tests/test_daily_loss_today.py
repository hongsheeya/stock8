"""The daily loss limit counts today's P&L only, in KRW, per market lane.

10-15: realized_profit is lifetime (the session rollover carries it), so the
9/3-10/1 losses on 069500/114800 (-1.97M) counted as today's against the 1M
limit and blocked every KS entry with no trade that day.
"""
import unittest

from test_daytrade_engine_regressions import _engine_with_state

HALT = {"daytrade_daily_loss_limit_krw": "1000000", "daytrade_daily_loss_halt_enabled": "true"}


def _status(engine, market=None):
    return engine.daily_loss_status(requested_seed=1000000, use_live_price=False, use_cache_only=True, market=market)


class DailyLossTodayTests(unittest.TestCase):
    def test_lifetime_losses_from_earlier_days_do_not_halt_today(self):
        engine, _ = _engine_with_state({
            "069500.KS": {"symbol": "069500", "market": "KS", "session_date": "2026-05-26",
                          "position_qty": 0, "realized_profit": -1050992.27},
            "114800.KS": {"symbol": "114800", "market": "KS", "session_date": "2026-05-26",
                          "position_qty": 0, "realized_profit": -920891.3},
        }, [], configs=HALT)
        status = _status(engine, market="KS")
        self.assertEqual(status["realized_profit"], 0)
        self.assertFalse(status["halt_new_buys"])

    def test_todays_bookings_accumulate_and_reset_the_next_day(self):
        engine, _ = _engine_with_state({}, [], configs=HALT)
        state = {"symbol": "069500", "market": "KS", "realized_profit": -500000.0,
                 "daily_realized_profit": -300000.0, "daily_realized_date": "2026-05-25"}
        engine._book_realized(state, -700000)
        self.assertEqual((state["realized_profit"], state["daily_realized_profit"], state["daily_realized_date"]),
                         (-1200000.0, -700000.0, "2026-05-26"))
        engine._book_realized(state, -400000)
        self.assertEqual(state["daily_realized_profit"], -1100000.0)

        engine._load_state_map = lambda: {"069500.KS": {**state, "position_qty": 0, "session_date": "2026-05-26"}}
        status = _status(engine, market="KS")
        self.assertEqual(status["realized_profit"], -1100000.0)
        self.assertTrue(status["halt_new_buys"])

    def test_us_loss_is_converted_and_stays_in_the_us_lane(self):
        # 10:00 KST belongs to the US session of the previous date.
        engine, _ = _engine_with_state({
            "TQQQ.US": {"symbol": "TQQQ", "market": "US", "session_date": "2026-05-25", "position_qty": 0,
                        "realized_profit": -900.0, "daily_realized_profit": -800.0,
                        "daily_realized_date": "2026-05-25"},
        }, [], configs=HALT)
        engine._usd_krw_rate = lambda cached_only=False: 1400.0
        engine._is_infinite_buy_symbol = lambda symbol, market="US": False
        self.assertEqual(_status(engine, market="US")["realized_profit"], -1120000.0)
        self.assertTrue(_status(engine, market="US")["halt_new_buys"])
        self.assertEqual(_status(engine, market="KS")["realized_profit"], 0)
        self.assertFalse(_status(engine, market="KS")["halt_new_buys"])

    def test_infinite_buy_symbols_never_count(self):
        engine, _ = _engine_with_state({
            "SOXL.US": {"symbol": "SOXL", "market": "US", "session_date": "2026-05-25", "position_qty": 10,
                        "avg_price": 30.0, "last_price": 20.0, "daily_realized_profit": -900.0,
                        "daily_realized_date": "2026-05-25"},
        }, [], configs=HALT)
        engine._usd_krw_rate = lambda cached_only=False: 1400.0
        status = _status(engine)
        self.assertEqual((status["realized_profit"], status["unrealized_profit"]), (0, 0))
        self.assertEqual(status["tracked_symbols"], [])


if __name__ == "__main__":
    unittest.main()
