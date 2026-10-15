"""Live US strategy decisions replay the backtest's own entry/exit rules."""
import datetime
import unittest
from unittest.mock import patch

from test_daytrade_engine_regressions import _engine_with_state, _StrategyStub, daytrade_engine
from test_vrev_execution_timing import module as daytrade_module

LOOSE = {**daytrade_module.Daytrade.US_DEFAULT_PROFILE, "breakout_volume_ratio": 0.0, "min_change_pct": -100.0,
         "breakout_take_profit_pct": 4.0, "breakout_stop_loss_pct": 2.5, "high_stop_pct": 10.0}


def _strategy():
    real = daytrade_module.Daytrade.__new__(daytrade_module.Daytrade)
    real._event_filter_snapshot = lambda *_a, **_k: {"blocked": False}
    return real


def _session(prices, start=datetime.datetime(2026, 5, 26, 22, 30)):
    # One US regular session (KST evening): flat open, then a steady climb.
    rows = [{"timestamp": (start + datetime.timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M"),
             "date": (start + datetime.timedelta(minutes=i)).strftime("%Y-%m-%d"),
             "time": (start + datetime.timedelta(minutes=i)).strftime("%H:%M"),
             "open": p, "high": p * 1.001, "low": p * 0.999, "close": p, "volume": 1000 + 100 * i}
            for i, p in enumerate(prices)]
    return _strategy()._rows_to_sessions(rows, market="US")[-1]


PRICES = [100.0] * 6 + [100.0 + 0.4 * i for i in range(1, 40)]


_REAL = _strategy()


def _shared_rules(_self, strategy_id, profile):
    # engine.strategy builds a fresh stub per access: patch the class.
    return _REAL._us_session_rules(strategy_id, profile)


def _engine(now):
    engine, store = _engine_with_state({}, [])
    engine._now = lambda: now
    return engine, store


class _RulesTestCase(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(_StrategyStub, "_us_session_rules", create=True, new=_shared_rules))


class EntryParityTests(_RulesTestCase):
    def test_live_replay_decides_like_the_backtest_rule_on_every_bar(self):
        session = _session(PRICES)
        entry_rule, _ = _strategy()._us_session_rules("us_breakout", LOOSE)
        state, prev, expected = {}, None, []
        for index, row in enumerate(session["bars"]):
            expected.append(bool(entry_rule(row, prev, index, session, LOOSE, state)))
            prev = row
        self.assertTrue(any(expected))
        for length in range(1, len(session["bars"]) + 1):
            prefix = {**session, "bars": session["bars"][:length]}
            last = datetime.datetime.strptime(prefix["bars"][-1]["timestamp"], "%Y-%m-%d %H:%M")
            engine, _ = _engine(last + datetime.timedelta(minutes=1, seconds=5))
            replay = engine._us_rule_replay("us_breakout", LOOSE, prefix)
            self.assertEqual(replay["fired"], expected[length - 1], length)
            self.assertFalse(replay["stale"])

    def test_backtest_enters_on_the_bar_the_live_replay_first_fires(self):
        session = _session(PRICES)
        result = _strategy()._simulate_us_breakout_session(session, 1_000_000, dict(LOOSE))
        entry_time = next(t for t in result["trades"] if str(t.get("side", t.get("action", ""))).upper().startswith("B"))["timestamp"]
        bars = session["bars"]
        first_fire = None
        for length in range(1, len(bars) + 1):
            last = datetime.datetime.strptime(bars[length - 1]["timestamp"], "%Y-%m-%d %H:%M")
            engine, _ = _engine(last + datetime.timedelta(minutes=1, seconds=5))
            if engine._us_rule_replay("us_breakout", LOOSE, {**session, "bars": bars[:length]})["fired"]:
                first_fire = bars[length - 1]["timestamp"]
                break
        self.assertEqual(first_fire, entry_time)

    def test_forming_minute_and_stale_bars_never_enter(self):
        session = _session(PRICES[:12])
        last = datetime.datetime.strptime(session["bars"][-1]["timestamp"], "%Y-%m-%d %H:%M")
        engine, _ = _engine(last + datetime.timedelta(seconds=20))
        self.assertEqual(engine._us_rule_replay("us_breakout", LOOSE, session)["bars"], 11)
        engine, _ = _engine(last + datetime.timedelta(minutes=9))
        self.assertTrue(engine._us_rule_replay("us_breakout", LOOSE, session)["stale"])

    def test_live_signal_buys_when_the_rule_fires_on_the_last_closed_bar(self):
        session = _session(PRICES)
        entry_rule, _ = _strategy()._us_session_rules("us_breakout", LOOSE)
        state, prev, fire_at = {}, None, None
        for index, row in enumerate(session["bars"]):
            if entry_rule(row, prev, index, session, LOOSE, state) and fire_at is None:
                fire_at = index
            prev = row
        prefix = {**session, "bars": session["bars"][:fire_at + 1]}
        last = datetime.datetime.strptime(prefix["bars"][-1]["timestamp"], "%Y-%m-%d %H:%M")
        engine, _ = _engine(last + datetime.timedelta(minutes=1, seconds=5))
        engine._profile_for = lambda *_a, **_k: dict(LOOSE)
        engine._aggregate_ticks_to_candle = lambda *_a: None
        engine._market_buy_budget = lambda *_a, **_k: {"budget_total": 1000.0, "buy_budget": 1000.0}
        engine._append_runtime_log = lambda *_a, **_k: None
        engine._guardrails = lambda *_a, **_k: {"issues": [], "warnings": []}
        bar = dict(prefix["bars"][-1], quote_prev_close=100.0, indicator_bar_count=60)
        engine._latest_snapshot = lambda *_a, **_k: (prefix, bar)
        with patch.object(_StrategyStub, "_event_filter_snapshot", create=True,
                          new=lambda *_a, **_k: {"blocked": False}):
            signal = engine._signal_from_state("TEST", market="US", seed=1000000,
                                               strategy_id="us_breakout", sync_broker=False)["signal"]
        self.assertEqual(signal["action"], "BUY")
        self.assertIn("백테스트 진입 규칙 충족", signal["reason"])


class FastPathExitTests(_RulesTestCase):
    def _state(self, **extra):
        row = dict(symbol="TEST", market="US", strategy_id="us_breakout", position_qty=5, avg_price=100.0,
                   session_date="2026-05-26", orders=[])
        row.update(extra)
        return row

    def test_breakout_trailing_stop_uses_the_stored_high(self):
        # high_stop 10% -> trail max(2.5, 10 * 0.25) = 2.5%: 103.90 -> 101.20 is
        # -2.6% while the +4% target and the -2.5% stop are both untouched.
        state = self._state(us_highest_since_entry=103.9, us_tracking_avg=100.0)
        engine, store = _engine_with_state({"TEST.US": dict(state)}, [])
        reason = engine._us_rule_exit("us_breakout", LOOSE, {"bars": []}, state, 100.0, 101.2)
        self.assertIn("트레일링", reason)
        state = self._state(us_highest_since_entry=103.0, us_tracking_avg=100.0)
        self.assertEqual(engine._us_rule_exit("us_breakout", LOOSE, {"bars": []}, state, 100.0, 101.2), "")

    def test_new_position_does_not_inherit_the_old_high(self):
        state = self._state(us_highest_since_entry=110.0, us_tracking_avg=95.0)
        engine, store = _engine_with_state({"TEST.US": dict(state)}, [])
        self.assertEqual(engine._us_rule_exit("us_breakout", LOOSE, {"bars": []}, state, 100.0, 101.0), "")
        self.assertEqual(store()["TEST.US"]["us_highest_since_entry"], 101.0)
        self.assertEqual(store()["TEST.US"]["us_tracking_avg"], 100.0)

    def test_take_profit_and_stop_still_apply_without_bars(self):
        engine, _ = _engine_with_state({"TEST.US": self._state()}, [])
        self.assertIn("목표", engine._us_rule_exit("us_breakout", LOOSE, {"bars": []}, self._state(), 100.0, 104.1))
        self.assertIn("손절", engine._us_rule_exit("us_breakout", LOOSE, {"bars": []}, self._state(), 100.0, 97.4))


if __name__ == "__main__":
    unittest.main()
