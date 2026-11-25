"""A failed KIS quote refresh must not pass an old price off as a live quote.

_latest_snapshot reuses a dataset for up to 180 s and refreshes only the price
from the KIS quote. When that refresh failed (exception or price <= 0) the old
bar came back still labelled kis_domestic_quote / kis_overseas_quote and the
cache ts moved to now, so a price up to 180 s old cleared the buy guards and
KS bought at market on it. Now the bar says kis_quote_stale, the cache ts stays
put, new buys refuse it (PAPER and LIVE, KS and US) and exits are untouched.

US LIVE also used to accept a Yahoo-bar (yfinance_intraday) buy with only a
warning; it now needs a KIS quote like KS.
"""
import datetime
import sys
import unittest
from unittest.mock import Mock, patch

from test_breakout_strategy_stop import BELOW, _run as _run_exit_watch
from test_daytrade_engine_regressions import _StrategyStub, _engine_with_state
from test_daytrade_p0_exit_fixes import LIVE_PROFILE, _state

NOW = datetime.datetime(2026, 11, 25, 10, 30, 0)
_SNAP_KEY = "_trading_snapshot_cache_v3"


def _engine():
    engine, _ = _engine_with_state({}, [])
    engine._now = lambda: NOW
    engine.logs = []
    engine._append_runtime_log = lambda level, message, **kwargs: engine.logs.append((level, message))
    return engine


def _cached_entry(market, ts_age=20, dataset_age=60, close=1000.0):
    source = "kis_overseas_quote" if market == "US" else "kis_domestic_quote"
    bar = {"timestamp": "2026-11-25 10:29", "close": close, "open": close, "high": close, "low": close,
           "volume": 100, "price_source": source}
    return {"session": {"date": "2026-11-25", "prev_close": close, "bars": [bar]}, "bar": bar,
            "ts": NOW - datetime.timedelta(seconds=ts_age),
            "dataset_ts": NOW - datetime.timedelta(seconds=dataset_age)}


class _SnapshotCase(unittest.TestCase):
    """Runs the real _latest_snapshot against a pre-filled process cache."""

    def _snapshot(self, market, symbol, broker):
        engine = _engine()
        del engine._latest_snapshot
        engine._broker = lambda: broker
        cache = {f"{symbol}.{market}": _cached_entry(market)}
        prepare = Mock(side_effect=AssertionError("cache reuse must not reload the dataset"))
        with patch.object(sys, _SNAP_KEY, cache, create=True), \
                patch.object(type(engine.strategy), "prepare_live_dataset", prepare, create=True):
            _session, bar = engine._latest_snapshot(symbol, market=market)
        return engine, cache[f"{symbol}.{market}"], bar


class StaleQuoteSnapshotTests(_SnapshotCase):
    def test_ks_quote_exception_marks_the_bar_stale_and_keeps_the_cache_ts(self):
        broker = Mock()
        broker.get_domestic_current_price.side_effect = RuntimeError("EGW00201 초당 거래건수 초과")
        engine, entry, bar = self._snapshot("KS", "005930", broker)
        self.assertEqual(bar["price_source"], "kis_quote_stale")
        self.assertTrue(bar["quote_stale"])
        self.assertEqual(bar["quote_stale_prev_source"], "kis_domestic_quote")
        self.assertEqual(bar["close"], 1000.0)
        self.assertEqual(entry["ts"], NOW - datetime.timedelta(seconds=20))
        self.assertEqual(entry["dataset_ts"], NOW - datetime.timedelta(seconds=60))
        self.assertEqual(entry["quote_fail_ts"], NOW)
        self.assertEqual(entry["bar"]["price_source"], "kis_domestic_quote")
        self.assertNotIn("quote_stale", entry["bar"])
        self.assertTrue(any("묵은 시세" in message for _level, message in engine.logs))

    def test_us_quote_exception_marks_the_bar_stale_and_keeps_the_cache_ts(self):
        broker = Mock()
        broker.get_current_price.side_effect = RuntimeError("현재가 조회 실패 [AAPL:NAS]")
        _engine_, entry, bar = self._snapshot("US", "AAPL", broker)
        self.assertEqual(bar["price_source"], "kis_quote_stale")
        self.assertEqual(bar["quote_stale_prev_source"], "kis_overseas_quote")
        self.assertEqual(entry["ts"], NOW - datetime.timedelta(seconds=20))

    def test_zero_price_is_a_failed_refresh_too(self):
        for market, symbol, method in (("KS", "005930", "get_domestic_current_price"),
                                       ("US", "AAPL", "get_current_price")):
            with self.subTest(market=market):
                broker = Mock()
                getattr(broker, method).return_value = {"price": 0}
                _engine_, entry, bar = self._snapshot(market, symbol, broker)
                self.assertEqual(bar["price_source"], "kis_quote_stale")
                self.assertTrue(bar["quote_stale"])
                self.assertEqual(entry["ts"], NOW - datetime.timedelta(seconds=20))

    def test_good_quote_refreshes_as_before(self):
        broker = Mock()
        broker.get_domestic_current_price.return_value = {"price": 1010.0, "source": "kis_domestic_quote"}
        _engine_, entry, bar = self._snapshot("KS", "005930", broker)
        self.assertEqual(bar["price_source"], "kis_domestic_quote")
        self.assertEqual(bar["close"], 1010.0)
        self.assertNotIn("quote_stale", bar)
        self.assertEqual(entry["ts"], NOW)
        self.assertEqual(entry["dataset_ts"], NOW - datetime.timedelta(seconds=60))

        broker = Mock()
        broker.get_current_price.return_value = {"price": 201.5}
        _engine_, entry, bar = self._snapshot("US", "AAPL", broker)
        self.assertEqual(bar["price_source"], "kis_overseas_quote")
        self.assertEqual(bar["close"], 201.5)
        self.assertEqual(entry["ts"], NOW)

    def _clocked(self, quotes):
        engine = _engine()
        del engine._latest_snapshot
        clock = {"now": NOW}
        engine._now = lambda: clock["now"]
        broker = Mock()
        broker.get_domestic_current_price.side_effect = quotes
        engine._broker = lambda: broker
        return engine, clock, broker, {"005930.KS": _cached_entry("KS")}

    def test_within_ttl_after_a_failure_kis_is_not_called_and_the_bar_stays_stale(self):
        engine, clock, broker, cache = self._clocked([RuntimeError("EGW00201")])
        with patch.object(sys, _SNAP_KEY, cache, create=True):
            _s, first = engine._latest_snapshot("005930", market="KS")
            for seconds in (1, 6, 11.9):
                clock["now"] = NOW + datetime.timedelta(seconds=seconds)
                _s, again = engine._latest_snapshot("005930", market="KS")
                self.assertEqual(again["price_source"], "kis_quote_stale")
                self.assertTrue(again["quote_stale"])
                self.assertEqual(again["quote_stale_prev_source"], "kis_domestic_quote")
                self.assertEqual(again["close"], 1000.0)
        self.assertEqual(first["price_source"], "kis_quote_stale")
        self.assertEqual(broker.get_domestic_current_price.call_count, 1)
        self.assertEqual(cache["005930.KS"]["quote_fail_ts"], NOW)
        self.assertEqual(cache["005930.KS"]["bar"]["price_source"], "kis_domestic_quote")

    def test_after_ttl_kis_is_asked_again(self):
        engine, clock, broker, cache = self._clocked([RuntimeError("timeout"), RuntimeError("timeout")])
        with patch.object(sys, _SNAP_KEY, cache, create=True):
            engine._latest_snapshot("005930", market="KS")
            clock["now"] = NOW + datetime.timedelta(seconds=12)
            _s, again = engine._latest_snapshot("005930", market="KS")
        self.assertEqual(broker.get_domestic_current_price.call_count, 2)
        self.assertEqual(again["price_source"], "kis_quote_stale")
        entry = cache["005930.KS"]
        self.assertEqual(entry["quote_fail_ts"], NOW + datetime.timedelta(seconds=12))
        self.assertEqual(entry["ts"], NOW - datetime.timedelta(seconds=20))

    def test_a_successful_retry_returns_to_the_kis_source(self):
        engine, clock, broker, cache = self._clocked([RuntimeError("timeout"), {"price": 1020.0}])
        with patch.object(sys, _SNAP_KEY, cache, create=True):
            engine._latest_snapshot("005930", market="KS")
            clock["now"] = NOW + datetime.timedelta(seconds=13)
            _s, recovered = engine._latest_snapshot("005930", market="KS")
            clock["now"] = NOW + datetime.timedelta(seconds=14)
            _s, hit = engine._latest_snapshot("005930", market="KS")
        self.assertEqual(recovered["price_source"], "kis_domestic_quote")
        self.assertEqual(recovered["close"], 1020.0)
        self.assertNotIn("quote_stale", recovered)
        self.assertNotIn("quote_stale_prev_source", recovered)
        entry = cache["005930.KS"]
        self.assertNotIn("quote_fail_ts", entry)
        self.assertEqual(entry["ts"], NOW + datetime.timedelta(seconds=13))
        # The ordinary 12 s cache hit works again after recovery.
        self.assertEqual(hit["price_source"], "kis_domestic_quote")
        self.assertEqual(broker.get_domestic_current_price.call_count, 2)

    def test_expired_dataset_after_a_failure_reloads_the_dataset(self):
        engine, clock, broker, cache = self._clocked([RuntimeError("timeout"), {"price": 1030.0}])
        bars = [{"timestamp": "2026-11-25 10:31", "close": 1025.0}, {"timestamp": "2026-11-25 10:32", "close": 1028.0}]
        session = {"date": "2026-11-25", "prev_close": 990.0, "bars": bars}
        prepare = Mock(return_value=[session])
        with patch.object(sys, _SNAP_KEY, cache, create=True), \
                patch.object(type(engine.strategy), "prepare_live_dataset", prepare, create=True):
            engine._latest_snapshot("005930", market="KS")
            # dataset_ts was 60 s old; 125 s later it passes the 180 s limit.
            clock["now"] = NOW + datetime.timedelta(seconds=125)
            _s, bar = engine._latest_snapshot("005930", market="KS")
        prepare.assert_called_once()
        self.assertEqual(bar["price_source"], "kis_domestic_quote")
        self.assertEqual(bar["close"], 1030.0)
        self.assertNotIn("quote_fail_ts", cache["005930.KS"])

    def test_fresh_dataset_path_still_ignores_a_failed_quote(self):
        """The new-dataset path keeps its old behaviour: the bar is unchanged."""
        engine = _engine()
        del engine._latest_snapshot
        broker = Mock()
        broker.get_domestic_current_price.side_effect = RuntimeError("timeout")
        engine._broker = lambda: broker
        bars = [{"timestamp": "2026-11-25 10:28", "close": 990.0},
                {"timestamp": "2026-11-25 10:29", "close": 995.0}]
        session = {"date": "2026-11-25", "prev_close": 980.0, "bars": bars}
        with patch.object(sys, _SNAP_KEY, {}, create=True), \
                patch.object(type(engine.strategy), "prepare_live_dataset", Mock(return_value=[session]), create=True):
            _s, bar = engine._latest_snapshot("005930", market="KS")
        self.assertEqual(bar["close"], 995.0)
        self.assertNotIn("price_source", bar)
        self.assertNotIn("quote_stale", bar)


class _ReachedBroker(BaseException):
    """Raised by the stubbed order submit: the order got past every gate.
    BaseException so the engine's own except Exception handlers let it out."""


def _order_ready_engine():
    engine = _engine()
    engine._us_market_open = lambda: True
    engine._us_premarket_open = lambda: False
    engine._daytrade_market_open = lambda market="KS": True
    engine._broker = lambda: Mock()
    engine._submit_order = Mock(side_effect=_ReachedBroker())
    return engine


def _status(action, price_source, symbol="005930", market="KS", position_qty=0):
    return {
        "state": {"symbol": symbol, "market": market, "position_qty": position_qty, "avg_price": 1000},
        "signal": {"action": action, "reason": "테스트용 구체적 매매 사유입니다", "order_qty": 1,
                   "current_price": 1000, "price_source": price_source, "strategy_id": "vrev"},
        "runtime": {"risk_status": "SAFE", "issues": [], "warnings": []},
    }


class EvidenceGateTests(unittest.TestCase):
    def setUp(self):
        # Strategy ownership is a separate gate; let it pass so only the price
        # source decides here.
        ownership = patch.object(_StrategyStub, "daytrade_entry_issue", lambda self, symbol: "", create=True)
        ownership.start()
        self.addCleanup(ownership.stop)
        self.engine = _engine()
        self.engine._us_market_open = lambda: True
        self.engine._us_premarket_open = lambda: False
        self.engine._daytrade_market_open = lambda market="KS": True

    def test_stale_quote_buy_is_refused_in_ks_and_us(self):
        for symbol, market in (("005930", "KS"), ("AAPL", "US")):
            with self.subTest(market=market):
                result = self.engine.execute_live(symbol, market=market, seed=1000000, allow_buy=True,
                                                  sync_broker=False,
                                                  precomputed_status=_status("BUY1", "kis_quote_stale", symbol, market))
                self.assertFalse(result["executed"])
                self.assertTrue(result.get("evidence_blocked"))
                self.assertIn("묵은 시세", result["message"])
                self.assertNotIn("소유", result["message"])

    def test_live_quote_buy_still_passes_the_evidence_gate(self):
        engine = _order_ready_engine()
        with self.assertRaises(_ReachedBroker):
            engine.execute_live("005930", market="KS", seed=1000000, allow_buy=True, sync_broker=False,
                                precomputed_status=_status("BUY1", "kis_domestic_quote"))
        engine._submit_order.assert_called_once()
        # US checks overseas buying power after the evidence gate; the stub
        # broker has none, so stop at "not blocked by the evidence gate".
        engine = _order_ready_engine()
        result = engine.execute_live("AAPL", market="US", seed=1000000, allow_buy=True, sync_broker=False,
                                     precomputed_status=_status("BUY1", "kis_overseas_quote", "AAPL", "US"))
        self.assertFalse(result.get("evidence_blocked", False))
        self.assertNotIn("가격 출처", result.get("message", ""))

    def test_stale_quote_buy_never_reaches_the_broker(self):
        for symbol, market in (("005930", "KS"), ("AAPL", "US")):
            with self.subTest(market=market):
                engine = _order_ready_engine()
                result = engine.execute_live(symbol, market=market, seed=1000000, allow_buy=True, sync_broker=False,
                                             precomputed_status=_status("BUY1", "kis_quote_stale", symbol, market))
                self.assertTrue(result.get("evidence_blocked"))
                engine._submit_order.assert_not_called()

    def test_stale_quote_never_blocks_a_sell(self):
        for symbol, market in (("005930", "KS"), ("AAPL", "US")):
            with self.subTest(market=market):
                engine = _order_ready_engine()
                state = engine._state_for(symbol, market=market, seed=1000000, name="", strategy_id="vrev")
                state.update(position_qty=1, avg_price=1000)
                engine._store_state(state)
                with self.assertRaises(_ReachedBroker):
                    engine.execute_live(symbol, market=market, seed=1000000, allow_buy=False, sync_broker=False,
                                        precomputed_status=_status("SELL_STOP_LOSS", "kis_quote_stale",
                                                                   symbol, market, position_qty=1))
                engine._submit_order.assert_called_once()
                self.assertEqual(engine._submit_order.call_args.kwargs.get("side"), "SELL")


class GuardrailTests(unittest.TestCase):
    def _guardrails(self, market, action, price_source, is_real=True, bar=None):
        engine = _engine()
        engine.check_kis_connection = lambda: {"connected": True, "is_real": is_real}
        engine.portfolio_usage = lambda *args, **kwargs: {"active_entry_seed_krw": 0, "active_cost_krw": 0}
        engine.shared_budget_status = lambda **kwargs: {"capacity_daytrade_seed_krw": 5000000, "total_seed_krw": 5000000}
        engine.daily_loss_status = lambda **kwargs: {"halt_new_buys": False}
        symbol = "AAPL" if market == "US" else "005930"
        return engine._guardrails(
            symbol, market, 1000000,
            {"position_qty": 1 if action.startswith("SELL") else 0, "avg_price": 1000, "orders": []},
            {"action": action, "strategy_id": "vrev", "current_price": 1000, "order_qty": 1, "price_source": price_source},
            {}, {"intraday_range_pct": 1.0, "gap_from_open_pct": 0.5, **(bar or {})},
            {"budget_ratio": 1.0, "max_order_cooldown_sec": 0, "max_live_day_range_pct": 8.5, "max_live_gap_pct": 5.5},
        )

    def test_stale_quote_buy_halts_in_live_and_paper(self):
        for market in ("KS", "US"):
            for is_real in (True, False):
                with self.subTest(market=market, is_real=is_real):
                    result = self._guardrails(market, "BUY1", "kis_quote_stale", is_real=is_real)
                    self.assertEqual(result["risk_status"], "HALT")
                    self.assertTrue(any("묵은 시세" in issue for issue in result["issues"]))

    def test_stale_quote_sell_only_warns(self):
        for market in ("KS", "US"):
            with self.subTest(market=market):
                result = self._guardrails(market, "SELL_STOP_LOSS", "kis_quote_stale")
                self.assertEqual(result["issues"], [])
                self.assertNotEqual(result["risk_status"], "HALT")
                self.assertTrue(result["warnings"])

    def test_us_live_buy_needs_a_kis_quote(self):
        result = self._guardrails("US", "BUY1", "yfinance_intraday")
        self.assertEqual(result["risk_status"], "HALT")
        self.assertTrue(any("KIS 실시간 시세가 아니면" in issue for issue in result["issues"]))
        ok = self._guardrails("US", "BUY1", "kis_overseas_quote")
        self.assertEqual(ok["issues"], [])

    def test_us_paper_yahoo_buy_still_only_warns(self):
        result = self._guardrails("US", "BUY1", "yfinance_intraday", is_real=False)
        self.assertEqual(result["issues"], [])
        self.assertIn("지연 시세 기반입니다.", result["warnings"])

    def test_ks_rules_unchanged(self):
        self.assertTrue(any("KIS 실시간 시세가 아니면" in issue
                            for issue in self._guardrails("KS", "BUY1", "yfinance_intraday")["issues"]))
        self.assertEqual(self._guardrails("KS", "BUY1", "kis_domestic_quote")["issues"], [])
        sell = self._guardrails("KS", "SELL_STOP_LOSS", "yfinance_intraday")
        self.assertEqual(sell["issues"], [])
        self.assertTrue(any("청산 신호는 지연 시세" in warning for warning in sell["warnings"]))

    def test_us_live_fallback_bar_vrev_buy_halts(self):
        """Intended tightening (review R2): with no US minute dataset the
        state fallback bar carries synthetic indicators and the source
        kis_overseas_quote_fallback, so a US LIVE vrev buy is refused."""
        result = self._guardrails("US", "BUY1", "kis_overseas_quote_fallback", bar={"intraday_unavailable": True})
        self.assertEqual(result["risk_status"], "HALT")
        self.assertTrue(any("KIS 실시간 시세가 아니면" in issue for issue in result["issues"]))

    def test_ks_fallback_bar_with_a_kis_quote_still_lets_vrev_buy(self):
        result = self._guardrails("KS", "BUY1", "kis_domestic_quote", bar={"intraday_unavailable": True})
        self.assertEqual(result["issues"], [])
        self.assertNotEqual(result["risk_status"], "HALT")


class StaleExitWatchTests(unittest.TestCase):
    """kr_execute_exit_watch reads the stale bar with its pre-failure label."""

    def test_stale_bar_that_was_a_kis_quote_still_sets_the_breakout_exit_price(self):
        bar = {**BELOW, "close": 9915, "price_source": "kis_quote_stale", "quote_stale": True,
               "quote_stale_prev_source": "kis_domestic_quote"}
        decisions = _run_exit_watch([_state("BRK", 10000, strategy_id="volume_breakout")], {"BRK": 9990}, {"BRK": bar})
        self.assertEqual(decisions["BRK"]["action"], "SELL_STOP_LOSS")

    def test_stale_bar_that_was_yahoo_keeps_the_balance_price(self):
        bar = {**BELOW, "close": 9000, "price_source": "kis_quote_stale", "quote_stale": True,
               "quote_stale_prev_source": "yfinance_intraday"}
        decisions = _run_exit_watch([_state("BRK", 10000, strategy_id="volume_breakout")], {"BRK": 9990}, {"BRK": bar})
        self.assertEqual(decisions["BRK"]["action"], "HOLD")


class StaleSnapshotToSignalTests(unittest.TestCase):
    """Cache reuse + failed quote -> signal_status(vrev) -> execute_live."""

    def test_stale_label_survives_into_the_vrev_signal_and_the_buy_is_blocked(self):
        now = datetime.datetime(2026, 5, 26, 10, 0, 0)
        engine, _ = _engine_with_state({}, [])
        del engine._latest_snapshot
        engine._now = lambda: now
        engine._profile_for = lambda *a, **k: dict(LIVE_PROFILE)
        engine._aggregate_ticks_to_candle = lambda *a: None
        engine._market_buy_budget = lambda *a, **k: {"budget_total": 1000000, "buy_budget": 1000000}
        engine._append_runtime_log = lambda *a, **k: None
        engine._load_runtime_logs = lambda *a, **k: []
        engine.check_kis_connection = lambda: {"connected": True, "is_real": True}
        engine.portfolio_usage = lambda *a, **k: {"active_entry_seed_krw": 0, "active_cost_krw": 0}
        engine.shared_budget_status = lambda **k: {"capacity_daytrade_seed_krw": 5000000, "total_seed_krw": 5000000}
        engine.daily_loss_status = lambda **k: {"halt_new_buys": False}
        engine._daytrade_market_open = lambda market="KS": True
        engine._submit_order = Mock(side_effect=_ReachedBroker())
        broker = Mock()
        broker.get_domestic_current_price.side_effect = RuntimeError("EGW00201")
        engine._broker = lambda: broker
        bar = {"timestamp": "2026-05-26 09:59", "close": 99.8, "open": 100, "vwap": 99.9, "rsi14": 45,
               "indicator_bar_count": 380, "price_source": "kis_domestic_quote"}
        session = {"date": "2026-05-26", "prev_close": 100, "prev_close_confirmed": True, "bars": [bar]}
        cache = {"TEST.KS": {"session": session, "bar": bar, "ts": now - datetime.timedelta(seconds=20),
                             "dataset_ts": now - datetime.timedelta(seconds=60)}}
        with patch.object(_StrategyStub, "_event_filter_snapshot", create=True, return_value={"blocked": False}), \
                patch.object(_StrategyStub, "daytrade_entry_issue", lambda self, symbol: "", create=True), \
                patch.object(sys, _SNAP_KEY, cache, create=True):
            status = engine.signal_status("TEST", market="KS", seed=1000000, strategy_id="vrev",
                                          sync_broker=False, allow_buy=True)
            # Without the stale quote this snapshot is a vrev BUY1.
            self.assertEqual(status["signal"]["action"], "BUY1")
            self.assertEqual(status["signal"]["price_source"], "kis_quote_stale")
            self.assertEqual(status["runtime"]["risk_status"], "HALT")
            self.assertTrue(any("묵은 시세" in issue for issue in status["runtime"]["issues"]))
            result = engine.execute_live("TEST", market="KS", seed=1000000, strategy_id="vrev", allow_buy=True,
                                         sync_broker=False, precomputed_status=status)
        self.assertTrue(result.get("evidence_blocked"))
        self.assertIn("묵은 시세", result["message"])
        engine._submit_order.assert_not_called()
        self.assertEqual(broker.get_domestic_current_price.call_count, 1)


if __name__ == "__main__":
    unittest.main()
