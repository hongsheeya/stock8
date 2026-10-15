"""PAPER direction-ETF trend strategy (paper_regime_trend).

10-15: KOSPI -8%, inverse ETFs above VWAP 97-98% of the day, yet the scalping
rules' guards blocked all 111 inverse breakout signals. This strategy holds an
inverse (leverage) ETF while its index trends down (up) past VWAP.
"""
import datetime
import unittest
from unittest.mock import patch

from test_daytrade_engine_regressions import _StrategyStub, _engine_with_state, daytrade_engine
from test_daytrade_p0_exit_fixes import _state, _watch_engine

TODAY = "2026-05-26"
STRATEGY = "paper_regime_trend"


def _snap(open_price, close, vwap, date=TODAY):
    session = {"date": date, "bars": [{"open": open_price, "close": open_price}]}
    return session, {"close": close, "vwap": vwap, "price_source": "kis_domestic_quote"}


class RegimeTrendTests(unittest.TestCase):
    def setUp(self):
        for patcher in (patch.object(daytrade_engine, "_PAPER_MODE", True),
                        patch.object(_StrategyStub, "_default_profile_for_market", create=True,
                                     new=lambda self, **_k: {})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _engine(self, snaps, now=(10, 0), state=None):
        engine, _ = _engine_with_state({"114800.KS": state} if state else {}, [])
        engine._now = lambda: datetime.datetime(2026, 5, 26, *now)
        engine._latest_snapshot = lambda symbol, market="KS": snaps[symbol]
        engine._append_runtime_log = lambda *a, **k: None
        return engine

    def _signal(self, engine, symbol="114800"):
        return engine._signal_from_state(symbol, market="KS", seed=10_000_000, strategy_id=STRATEGY,
                                         sync_broker=False)["signal"]

    # -- the index view
    def test_index_below_vwap_and_down_one_percent_is_a_bear_trend(self):
        engine = self._engine({"069500": _snap(100, 98.5, 99.3)})
        view = engine._regime_trend_view("114800")
        self.assertTrue(view["trend"])
        self.assertFalse(view["reversed"])
        self.assertFalse(engine._regime_trend_view("122630")["trend"])

    def test_stale_index_session_is_not_a_view(self):
        engine = self._engine({"069500": _snap(100, 98.5, 99.3, date="2026-05-25")})
        self.assertFalse(engine._regime_trend_view("114800")["ok"])

    # -- entries
    def test_enters_inverse_on_a_down_trend(self):
        engine = self._engine({"069500": _snap(100, 98.5, 99.3), "114800": _snap(1000, 1010, 1000)})
        signal = self._signal(engine)
        self.assertEqual(signal["action"], "BUY1")
        self.assertGreater(signal["order_qty"], 0)

    def test_waits_without_a_trend_outside_hours_or_below_etf_vwap(self):
        flat_index = {"069500": _snap(100, 99.6, 99.8), "114800": _snap(1000, 1010, 1000)}
        self.assertEqual(self._signal(self._engine(flat_index))["action"], "HOLD")
        trend = {"069500": _snap(100, 98.5, 99.3), "114800": _snap(1000, 1010, 1000)}
        self.assertEqual(self._signal(self._engine(trend, now=(9, 20)))["action"], "HOLD")
        weak_etf = {"069500": _snap(100, 98.5, 99.3), "114800": _snap(1000, 995, 1000)}
        self.assertEqual(self._signal(self._engine(weak_etf))["action"], "HOLD")

    def test_waits_ten_minutes_after_an_exit(self):
        state = _state("114800", 0, qty=0, strategy_id=STRATEGY, last_exit_action="SELL_FULL",
                       last_exit_watch_at=f"{TODAY} 09:55:00")
        engine = self._engine({"069500": _snap(100, 98.5, 99.3), "114800": _snap(1000, 1010, 1000)}, state=state)
        self.assertIn("재진입", self._signal(engine)["reason"])

    # -- exits
    def test_exits_when_the_index_reclaims_vwap(self):
        held = _state("114800", 1000, qty=10, strategy_id=STRATEGY)
        engine = self._engine({"069500": _snap(100, 99.5, 99.3), "114800": _snap(1000, 1005, 1000)}, state=held)
        signal = self._signal(engine)
        self.assertEqual((signal["action"], signal["order_qty"]), ("SELL_FULL", 10))
        self.assertTrue(signal["risk_exit"])

    def test_stops_at_minus_one_and_a_half_percent(self):
        held = _state("114800", 1000, qty=10, strategy_id=STRATEGY)
        engine = self._engine({"069500": _snap(100, 98.5, 99.3), "114800": _snap(1000, 984, 990)}, state=held)
        self.assertEqual(self._signal(engine)["action"], "SELL_STOP_LOSS")

    def test_flattens_in_the_close_window(self):
        held = _state("114800", 1000, qty=10, strategy_id=STRATEGY)
        engine = self._engine({"069500": _snap(100, 98.5, 99.3), "114800": _snap(1000, 1020, 1000)}, now=(15, 12), state=held)
        self.assertEqual(self._signal(engine)["action"], "SELL_FULL")

    # -- auto-cycle candidates
    def test_direction_etfs_replace_their_scalping_candidates(self):
        engine = self._engine({})
        engine._risk_sized_entry_seed_krw = lambda *a, **k: 3_000_000
        rows = [{"symbol": "114800", "strategy_id": "volume_breakout", "source": "leaderboard"},
                {"symbol": "069500", "strategy_id": "vrev", "source": "leaderboard"},
                {"symbol": "251340", "strategy_id": STRATEGY, "source": "active_position"}]
        result = engine._with_regime_trend_candidates(rows, {"total_seed_krw": 10_000_000, "remaining_seed_krw": 10_000_000})
        self.assertEqual([(r["symbol"], r["strategy_id"]) for r in result],
                         [("114800", STRATEGY), ("252670", STRATEGY), ("122630", STRATEGY), ("233740", STRATEGY),
                          ("069500", "vrev"), ("251340", STRATEGY)])
        self.assertEqual(result[0]["entry_seed_krw"], 3_000_000)

    def test_live_never_runs_it(self):
        engine = self._engine({})
        with patch.object(daytrade_engine, "_PAPER_MODE", False):
            self.assertFalse(engine._regime_trend_enabled())
            rows = [{"symbol": "114800", "strategy_id": "volume_breakout"}]
            self.assertEqual(engine._with_regime_trend_candidates(rows, {}), rows)
            engine._is_infinite_buy_symbol = lambda *a, **k: False
            self.assertEqual(engine.execute_live("114800", market="KS", strategy_id=STRATEGY)["action"], "PAPER_ONLY")


class RegimeTrendExitWatchTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(daytrade_engine, "_PAPER_MODE", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, view, now=None):
        engine, _saved, _broker, decisions = _watch_engine(
            [_state("114800", 1000, strategy_id=STRATEGY)], {"114800": 1005},
            now=now, bars={"114800": {"close": 1005, "vwap": 1000, "price_source": "kis_domestic_quote"}})
        engine._regime_trend_view = lambda symbol: view
        engine.kr_execute_exit_watch(requested_seed=10_000_000)
        return decisions["114800"]

    def test_fast_watch_exits_when_the_index_reverses(self):
        decision = self._run({"ok": True, "reversed": True, "reason": "지수 +0.2%"})
        self.assertEqual(decision["action"], "SELL_FULL")

    def test_fast_watch_holds_while_the_trend_lasts(self):
        self.assertEqual(self._run({"ok": True, "reversed": False})["action"], "HOLD")

    def test_fast_watch_flattens_before_the_close(self):
        decision = self._run({"ok": True, "reversed": False}, now=datetime.datetime(2026, 5, 26, 15, 12))
        self.assertEqual(decision["action"], "SELL_FULL")


if __name__ == "__main__":
    unittest.main()
