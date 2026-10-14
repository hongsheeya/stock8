"""No broker traffic: warmup, previous-session anchor and cache regressions."""
import datetime
import sys
import unittest
from unittest.mock import Mock, patch

from test_vrev_execution_timing import module
from test_daytrade_engine_regressions import _engine_with_state, _StrategyStub
from test_daytrade_p0_exit_fixes import LIVE_PROFILE


class WarmupTests(unittest.TestCase):
    def setUp(self):
        self.strategy = module.Daytrade.__new__(module.Daytrade)

    def bars(self, day="2026-05-26", price=100):
        return [dict(timestamp=f"{day} 09:{i:02d}", date=day, time=f"09:{i:02d}",
                     open=price, high=price, low=price, close=price, volume=100) for i in range(25)]

    def test_first_nineteen_bars_are_blocked_twentieth_is_ready(self):
        bars = self.strategy._decorate_bars(self.bars(), 100)
        for bar in bars[:19]:
            self.assertTrue(any("20" in x for x in self.strategy.vrev_entry_issues(bar)))
        self.assertFalse(any("20" in x for x in self.strategy.vrev_entry_issues(bars[19])))

    def test_sessions_use_prior_close_not_today_open_and_reset_warmup(self):
        sessions = self.strategy._rows_to_sessions(self.bars("2026-05-25", 100) + self.bars(price=110))
        self.assertEqual(sessions[0]["prev_close"], 0)
        self.assertFalse(sessions[0]["prev_close_confirmed"])
        self.assertEqual(sessions[1]["prev_close"], 100)
        self.assertEqual(sessions[1]["bars"][0]["indicator_bar_count"], 1)

    def test_missing_indicator_history_fails_closed(self):
        self.assertTrue(any("20" in x for x in self.strategy.vrev_entry_issues({"close": 100})))

    def test_snapshot_requests_multiple_sessions_and_refreshes_dataset(self):
        engine, _ = _engine_with_state({}, [])
        del engine._latest_snapshot
        now = datetime.datetime(2026, 5, 26, 10)
        engine._now = lambda: now
        broker = Mock()
        broker.get_domestic_current_price.return_value = {"price": 110}
        engine._broker = lambda: broker
        sessions = self.strategy._rows_to_sessions(self.bars("2026-05-25", 100) + self.bars(price=110))
        with patch.object(_StrategyStub, "_prepare_dataset", create=True, return_value=sessions) as prepare, \
                patch.object(sys, "_trading_snapshot_cache_v3", {}, create=True):
            engine._latest_snapshot("TEST")
            for minute in (1, 2, 3):
                now = datetime.datetime(2026, 5, 26, 10, minute)
                engine._latest_snapshot("TEST")
            self.assertEqual(prepare.call_count, 2)
            self.assertEqual(prepare.call_args.kwargs["period"], "5d")

    def test_signal_anchor_uses_previous_close_even_when_open_vwap_higher(self):
        engine, _ = _engine_with_state({}, [])
        engine._profile_for = lambda *args, **kwargs: dict(LIVE_PROFILE)
        engine._aggregate_ticks_to_candle = lambda *args: None
        engine._market_buy_budget = lambda *args, **kwargs: {"budget_total": 1000000, "buy_budget": 1000000}
        engine._append_runtime_log = lambda *args, **kwargs: None
        engine._guardrails = lambda *args, **kwargs: {"issues": [], "warnings": []}
        engine._latest_snapshot = lambda *args, **kwargs: (
            {"date": "2026-05-26", "prev_close": 100, "prev_close_confirmed": True},
            {"close": 99, "open": 110, "vwap": 105, "indicator_bar_count": 19})
        with patch.object(_StrategyStub, "_event_filter_snapshot", create=True, return_value={"blocked": False}):
            result = engine._signal_from_state("TEST", sync_broker=False)
        self.assertEqual(result["signal"]["anchor_price"], 100)
        self.assertEqual(result["signal"]["action"], "HOLD")
        self.assertIn("20", result["signal"]["reason"])
