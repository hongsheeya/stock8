"""PAPER direction-ETF trend strategy (paper_regime_trend).

10-15: KOSPI -8%, inverse ETFs above VWAP 97-98% of the day, yet the scalping
rules' guards blocked all 111 inverse breakout signals. This strategy holds an
inverse (leverage) ETF while its index trends down (up) past VWAP.
"""
import datetime
import unittest
from unittest.mock import MagicMock, Mock, patch

from test_daytrade_engine_regressions import _StrategyStub, _engine_with_state, daytrade_engine
from test_daytrade_p0_exit_fixes import _state, _watch_engine

TODAY = "2026-05-26"
STRATEGY = "paper_regime_trend"


def _snap(open_price, close, vwap, date=TODAY):
    session = {"date": date, "bars": [{"open": open_price, "close": open_price, "bar_source": "kis_minute"}]}
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

    def test_index_view_uses_the_last_closed_five_minute_bar(self):
        # 10-20: a momentary VWAP touch at 09:30:53 closed a 1-minute-old entry.
        bars = [{"time": "09:00", "open": 100, "close": 100, "vwap": 100},
                {"time": "09:24", "open": 98.6, "close": 98.5, "vwap": 99.3},   # last bar of 09:20-09:25
                {"time": "09:26", "open": 99.6, "close": 99.6, "vwap": 99.25}]  # forming bucket: above VWAP
        snaps = {"069500": ({"date": TODAY, "bars": bars}, {"close": 99.6, "vwap": 99.25})}
        view = self._engine(snaps, now=(9, 27))._regime_trend_view("114800")
        self.assertTrue(view["trend"])
        self.assertFalse(view["reversed"])
        engine = self._engine(snaps, now=(9, 27))
        engine._config = lambda key, default=None: "0" if key == "daytrade_regime_trend_signal_bar_min" else default
        self.assertTrue(engine._regime_trend_view("114800")["reversed"])  # live price: exits at once

    def test_closed_bar_lookup(self):
        engine = self._engine({}, now=(9, 35))
        bars = [{"time": "09:33", "close": 1}, {"time": "09:34", "close": 2}, {"time": "09:35", "close": 3}]
        self.assertEqual(engine._regime_closed_bar(bars, "KS", 5)["close"], 2)
        self.assertIsNone(engine._regime_closed_bar([{"close": 1}], "KS", 5))
        self.assertEqual(engine._regime_closed_bar([{"timestamp": "2026-05-26 09:29:00", "close": 7}], "KS", 5)["close"], 7)
        self.assertEqual(engine._regime_signal_bar_minutes("US"), 0)

    def test_a_half_built_bucket_from_a_stale_session_is_not_closed(self):
        # 10-20 11:40:35: the reused session ended at 11:37.
        engine = self._engine({}, now=(11, 40))
        stale = [{"time": "11:33", "close": 1}, {"time": "11:34", "close": 2},
                 {"time": "11:36", "close": 3}, {"time": "11:37", "close": 4}]
        self.assertEqual(engine._regime_closed_bar(stale, "KS", 5)["close"], 2)
        fresh = stale + [{"time": "11:39", "close": 5}]
        self.assertEqual(engine._regime_closed_bar(fresh, "KS", 5)["close"], 5)
        gap = [{"time": "11:33", "close": 1}, {"time": "11:38", "close": 6}, {"time": "11:41", "close": 7}]
        engine = self._engine({}, now=(11, 42))
        self.assertEqual(engine._regime_closed_bar(gap, "KS", 5)["close"], 6)  # a later bar closes it

    def test_open_exit_mode_holds_through_vwap_touches(self):
        configs = {"daytrade_regime_trend_exit_mode": "open"}
        # BEAR, index back above VWAP but still below its open: keep holding.
        engine = self._engine({"069500": _snap(100, 99.5, 99.3)})
        self.assertTrue(engine._regime_trend_view("114800")["reversed"])
        engine._config = lambda key, default=None: configs.get(key, default)
        self.assertFalse(engine._regime_trend_view("114800")["reversed"])
        # The index back above its open: the move is gone, exit.
        engine = self._engine({"069500": _snap(100, 100.2, 99.3)})
        engine._config = lambda key, default=None: configs.get(key, default)
        self.assertTrue(engine._regime_trend_view("114800")["reversed"])
        exit_signal = engine._regime_trend_exit("114800", 1000, 1000, market="KS")
        self.assertTrue(exit_signal["reason"].startswith("지수 시가 복귀"))
        state = {}
        engine._mark_exit_watch(state, reason=exit_signal["reason"], action="SELL_FULL")
        self.assertIn("regime_reversal_exit_at", state)  # one entry per day

    def test_paper_extra_etf_uses_itself_as_proxy(self):
        snaps = {"449450": _snap(100, 101.5, 100.8)}
        engine = self._engine(snaps)
        engine._config = lambda key, default=None: "449450:BULL:449450" if key == "daytrade_regime_trend_extra_etfs" else default
        self.assertEqual(engine._regime_trend_market("449450"), "KS")
        self.assertTrue(engine._regime_trend_view("449450")["trend"])
        self.assertIn("449450", [r["symbol"] for r in engine._with_regime_trend_candidates([], {}, market="KS")])
        with patch.object(daytrade_engine, "_PAPER_MODE", False):
            self.assertNotIn("449450", engine._regime_trend_pairs("KS"))

    def test_delayed_index_bars_hold_new_entries(self):
        snaps = {"069500": _snap(100, 98.5, 99.3), "114800": _snap(1000, 1010, 1000)}
        self.assertEqual(self._signal(self._engine(snaps))["action"], "BUY1")
        snaps["069500"][0]["bars"][-1].pop("bar_source")  # Yahoo fallback bars carry no source
        signal = self._signal(self._engine(snaps))
        self.assertEqual(signal["action"], "HOLD")
        self.assertIn("지연", signal["reason"])

    def test_gap_up_day_skips_new_entries_when_configured(self):
        snaps = {"069500": _snap(100, 98.5, 99.3), "114800": _snap(1000, 1010, 1000)}
        snaps["069500"][1]["quote_prev_close"] = 98.8  # opened +1.21% above the previous close
        engine = self._engine(snaps)
        self.assertEqual(self._signal(engine)["action"], "BUY1")
        engine._config = lambda key, default=None: "1.0" if key == "daytrade_regime_trend_skip_gap_up_pct" else default
        signal = self._signal(engine)
        self.assertEqual(signal["action"], "HOLD")
        self.assertIn("갭상승일", signal["reason"])
        snaps["069500"][1]["quote_prev_close"] = 99.5  # +0.5% gap: trades
        self.assertEqual(self._signal(engine)["action"], "BUY1")

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

    def test_a_vwap_reversal_exit_blocks_the_day_when_configured(self):
        trend = {"069500": _snap(100, 98.5, 99.3), "114800": _snap(1000, 1010, 1000)}
        reversed_ = _state("114800", 0, qty=0, strategy_id=STRATEGY, last_exit_action="SELL_FULL",
                           last_exit_watch_at=f"{TODAY} 09:35:00", regime_reversal_exit_at=f"{TODAY} 09:35:00")
        engine = self._engine(trend, now=(12, 0), state=reversed_)
        self.assertEqual(self._signal(engine)["action"], "BUY1")
        engine._config = lambda key, default=None: "true" if key == "daytrade_regime_trend_reversal_block" else default
        signal = self._signal(engine)
        self.assertEqual(signal["action"], "HOLD")
        self.assertIn("VWAP 이탈", signal["reason"])
        yesterday = dict(reversed_, regime_reversal_exit_at="2026-05-25 14:00:00")
        engine = self._engine(trend, now=(12, 0), state=yesterday)
        engine._config = lambda key, default=None: "true" if key == "daytrade_regime_trend_reversal_block" else default
        self.assertEqual(self._signal(engine)["action"], "BUY1")

    def test_a_reversal_sell_order_blocks_even_when_confirmed_later(self):
        trend = {"069500": _snap(100, 98.5, 99.3), "114800": _snap(1000, 1010, 1000)}
        orders = [{"timestamp": f"{TODAY} 09:55:30", "action": "SELL_FULL", "status": "FILLED",
                   "reason": "지수 VWAP 회복 — 방향 추세 종료 청산 (x)"}]
        state = _state("114800", 0, qty=0, strategy_id=STRATEGY, orders=orders,
                       last_exit_action="SELL_FULL", last_exit_watch_at=f"{TODAY} 09:56:00")
        engine = self._engine(trend, now=(12, 0), state=state)
        engine._config = lambda key, default=None: "true" if key == "daytrade_regime_trend_reversal_block" else default
        self.assertIn("VWAP 이탈", self._signal(engine)["reason"])
        old = dict(state, orders=[dict(orders[0], timestamp="2026-05-25 09:55:30")])
        engine = self._engine(trend, now=(12, 0), state=old)
        engine._config = lambda key, default=None: "true" if key == "daytrade_regime_trend_reversal_block" else default
        self.assertEqual(self._signal(engine)["action"], "BUY1")

    def test_an_operator_reset_forgives_earlier_reversal_exits(self):
        trend = {"069500": _snap(100, 98.5, 99.3), "114800": _snap(1000, 1010, 1000)}
        state = _state("114800", 0, qty=0, strategy_id=STRATEGY, last_exit_action="SELL_FULL",
                       last_exit_watch_at=f"{TODAY} 09:35:00", regime_reversal_exit_at=f"{TODAY} 09:35:00")
        configs = {"daytrade_regime_trend_reversal_block": "true",
                   "daytrade_regime_trend_reversal_reset_at": f"{TODAY} 11:00:00"}
        engine = self._engine(trend, now=(12, 0), state=state)
        engine._config = lambda key, default=None: configs.get(key, default)
        self.assertEqual(self._signal(engine)["action"], "BUY1")
        later = dict(state, regime_reversal_exit_at=f"{TODAY} 11:30:00")
        engine = self._engine(trend, now=(12, 0), state=later)
        engine._config = lambda key, default=None: configs.get(key, default)
        self.assertIn("VWAP 이탈", self._signal(engine)["reason"])
        configs["daytrade_regime_trend_reversal_reset_at"] = "2026-05-25 11:00:00"  # yesterday's reset: ignored
        engine = self._engine(trend, now=(12, 0), state=state)
        engine._config = lambda key, default=None: configs.get(key, default)
        self.assertIn("VWAP 이탈", self._signal(engine)["reason"])

    def test_reversal_exit_is_recorded_apart_from_the_exit_reason(self):
        engine = self._engine({})
        state = {}
        engine._mark_exit_watch(state, reason="지수 VWAP 회복 — 방향 추세 종료 청산 (x)", action="SELL_FULL")
        self.assertEqual(state["regime_reversal_exit_at"][:10], TODAY)
        engine._mark_exit_watch(state, reason="매도 체결 확인")
        self.assertEqual(state["regime_reversal_exit_at"][:10], TODAY)
        other = {}
        engine._mark_exit_watch(other, reason="방향 추세 손절 (평단 -1.5%)", action="SELL_STOP_LOSS")
        self.assertNotIn("regime_reversal_exit_at", other)

    def test_a_pending_sell_on_a_flat_slot_is_reconciled(self):
        trend = {"069500": _snap(100, 98.5, 99.3), "114800": _snap(1000, 1010, 1000)}
        state = _state("114800", 0, qty=0, strategy_id=STRATEGY, pending_sell_order_no="0006655500",
                       pending_sell_placed_at=f"{TODAY} 09:55:30", pending_sell_qty=4)
        engine = self._engine(trend, now=(12, 0), state=state)
        engine._sync_pending_sell = Mock(side_effect=lambda st, *a, **k: st.update(pending_sell_order_no="") or "filled")
        signal = self._signal(engine)
        engine._sync_pending_sell.assert_called_once()
        self.assertEqual(signal["action"], "BUY1")

    def test_a_stop_loss_blocks_the_rest_of_the_session(self):
        trend = {"069500": _snap(100, 98.5, 99.3), "114800": _snap(1000, 1010, 1000)}
        stopped = _state("114800", 0, qty=0, strategy_id=STRATEGY, last_exit_action="SELL_STOP_LOSS",
                         last_exit_watch_at=f"{TODAY} 09:35:00")
        signal = self._signal(self._engine(trend, now=(12, 0), state=stopped))
        self.assertEqual(signal["action"], "HOLD")
        self.assertIn("손절", signal["reason"])
        # An ordinary exit only waits the ten-minute cooldown.
        exited = dict(stopped, last_exit_action="SELL_FULL")
        self.assertEqual(self._signal(self._engine(trend, now=(12, 0), state=exited))["action"], "BUY1")

    def test_yesterdays_stop_does_not_block_today(self):
        trend = {"069500": _snap(100, 98.5, 99.3), "114800": _snap(1000, 1010, 1000)}
        stopped = _state("114800", 0, qty=0, strategy_id=STRATEGY, last_exit_action="SELL_STOP_LOSS",
                         last_exit_watch_at="2026-05-25 14:00:00")
        self.assertEqual(self._signal(self._engine(trend, state=stopped))["action"], "BUY1")

    def test_sides_config_limits_entries(self):
        trend = {"069500": _snap(100, 98.5, 99.3), "114800": _snap(1000, 1010, 1000)}
        engine = self._engine(trend)
        engine._config = lambda key, default=None: "BULL" if key == "daytrade_regime_trend_sides" else default
        signal = self._signal(engine)
        self.assertEqual(signal["action"], "HOLD")
        self.assertIn("롱", signal["reason"])
        self.assertNotIn("114800", [r["symbol"] for r in engine._with_regime_trend_candidates([], {}, market="KS")])

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
        engine._regime_trend_view = lambda symbol, **_k: view
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


class RegimeTrendOrderPathTests(unittest.TestCase):
    """Signal -> execute_live -> broker order, end to end. The KS strategy as
    first merged (#26) never set price_source, so execute_live's evidence gate
    refused every buy ("가격 출처: 없음") although the signal said BUY1."""

    def setUp(self):
        for patcher in (patch.object(daytrade_engine, "_PAPER_MODE", True),
                        patch.object(daytrade_engine, "_PAPER_CONTINUOUS", False),
                        patch.object(_StrategyStub, "_default_profile_for_market", create=True,
                                     new=lambda self, **_k: {}),
                        patch.object(_StrategyStub, "daytrade_entry_issue", create=True,
                                     new=lambda self, symbol: "")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _engine(self, snaps, now):
        engine, _ = _engine_with_state({}, [], configs={"daytrade_auto_enabled": "true"})
        engine._now = lambda: now
        engine._timestamp = lambda: now.strftime("%Y-%m-%d %H:%M:%S")
        engine._latest_snapshot = lambda symbol, market="KS": snaps[symbol]
        engine._hard_locked = lambda: False
        engine._daytrade_market_open = lambda market="KS": True
        engine._us_market_open = lambda: True
        engine._is_infinite_buy_symbol = lambda *a, **k: False
        engine._guardrails = lambda *a, **k: {"issues": [], "warnings": [], "risk_status": "SAFE"}
        engine._compact_runtime_meta = lambda *a, **k: {}
        engine._invalidate_kis_cache = lambda: None
        for name in ("_log_order_pending", "_log_order_failure", "_log_execution", "_append_runtime_log"):
            setattr(engine, name, Mock())
        engine._usd_krw_rate = lambda *a, **k: 1400.0
        engine._load_runtime_logs = lambda *a, **k: []
        engine._sync_broker_positions = lambda *a, **k: None
        broker = MagicMock()
        broker.buy_domestic_order.return_value = {"order_no": "0000123"}
        broker.buy_order.return_value = {"order_no": "0000456"}
        broker.get_domestic_fills_today.return_value = []
        broker.get_overseas_order_history.return_value = []
        broker.get_buying_power_info.return_value = {"ok": True, "executable_qty": 10_000, "executable_amount": 1_000_000,
                                                     "amount": 1_000_000, "qty": 10_000}
        engine._broker = lambda: broker
        engine._resolve_domestic_fill = lambda *a, **k: {"status": "UNKNOWN", "filled_qty": 0, "filled_price": 0}
        return engine, broker

    def test_ks_inverse_buy_reaches_the_broker(self):
        engine, broker = self._engine({"069500": _snap(100, 98.5, 99.3), "114800": _snap(1000, 1010, 1000)},
                                      datetime.datetime(2026, 5, 26, 10, 0))
        result = engine.execute_live("114800", market="KS", seed=10_000_000, strategy_id=STRATEGY, sync_broker=False)
        self.assertFalse(result.get("evidence_blocked"), result.get("message"))
        broker.buy_domestic_order.assert_called_once()

    def test_us_inverse_buy_reaches_the_broker_on_amex(self):
        # 23:30 KST = 10:30 ET (May, DST): the US session dated 05-26.
        us = lambda o, c, v: ({"date": TODAY, "bars": [{"open": o, "close": o}]},
                              {"close": c, "vwap": v, "price_source": "kis_overseas_quote"})
        engine, broker = self._engine({"SOXX": us(200, 196, 198), "SOXS": us(20, 20.6, 20.3)},
                                      datetime.datetime(2026, 5, 26, 23, 30))
        result = engine.execute_live("SOXS", market="US", seed=10_000_000, strategy_id=STRATEGY, sync_broker=False)
        self.assertFalse(result.get("evidence_blocked"), result.get("message"))
        broker.buy_order.assert_called_once()
        self.assertEqual(broker.buy_order.call_args.kwargs.get("exchange"), "AMEX")

    def test_us_waits_for_ten_am_eastern(self):
        us = lambda o, c, v: ({"date": TODAY, "bars": [{"open": o, "close": o}]},
                              {"close": c, "vwap": v, "price_source": "kis_overseas_quote"})
        engine, broker = self._engine({"SOXX": us(200, 196, 198), "SOXS": us(20, 20.6, 20.3)},
                                      datetime.datetime(2026, 5, 26, 22, 50))  # 09:50 ET
        signal = engine._signal_from_state("SOXS", market="US", seed=10_000_000, strategy_id=STRATEGY, sync_broker=False)["signal"]
        self.assertEqual(signal["action"], "HOLD")
        self.assertIn("ET", signal["reason"])

    def test_us_candidates_are_the_us_etfs(self):
        engine, _ = self._engine({}, datetime.datetime(2026, 5, 26, 23, 30))
        engine._risk_sized_entry_seed_krw = lambda *a, **k: 3_000_000
        rows = engine._with_regime_trend_candidates([{"symbol": "CRWD", "strategy_id": "us_premarket"}],
                                                    {"total_seed_krw": 1, "remaining_seed_krw": 1}, market="US")
        self.assertEqual([r["symbol"] for r in rows],
                         ["SQQQ", "PSQ", "SH", "SPXU", "SOXS", "QLD", "SSO", "USD", "CRWD"])
        self.assertTrue(all(r["market"] == "US" for r in rows[:-1]))


if __name__ == "__main__":
    unittest.main()
