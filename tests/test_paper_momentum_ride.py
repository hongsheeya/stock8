"""PAPER momentum ride (paper_momentum_ride) on today's movers, KS and US.

Rule fixed before testing: in play at +5% on the previous close, entry when a
closed bar sets a new 20-bar high above VWAP on 1.5x volume, exit on a 3%
trail, a VWAP break, -4% or the close.
"""
import datetime
import unittest
from unittest.mock import MagicMock, Mock, patch

from test_daytrade_engine_regressions import _StrategyStub, _engine_with_state, daytrade_engine
from test_daytrade_p0_exit_fixes import _state

TODAY = "2026-05-26"
STRATEGY = "paper_momentum_ride"


def _session(prev_close=95.0, signal_close=103.0, signal_volume=2000, vwap=101.0):
    bars = [{"timestamp": f"{TODAY} 10:{i:02d}", "open": 99, "high": 100, "low": 98, "close": 99.5,
             "volume": 1000, "vwap": 99.5} for i in range(21)]
    bars.append({"timestamp": f"{TODAY} 10:21", "open": 100, "high": 103.5, "low": 100, "close": signal_close,
                 "volume": signal_volume, "vwap": vwap})
    bars.append({"timestamp": f"{TODAY} 10:22", "open": 103, "high": 104, "low": 103, "close": 104,
                 "volume": 100, "vwap": vwap})  # still forming
    return {"date": TODAY, "prev_close": prev_close, "bars": bars}


def _snap(price=104.0, source="kis_domestic_quote", **kw):
    return _session(**kw), {"close": price, "vwap": kw.get("vwap", 101.0), "price_source": source}


class _Base(unittest.TestCase):
    def setUp(self):
        for patcher in (patch.object(daytrade_engine, "_PAPER_MODE", True),
                        patch.object(daytrade_engine, "_PAPER_CONTINUOUS", False),
                        patch.object(_StrategyStub, "_default_profile_for_market", create=True, new=lambda self, **_k: {}),
                        patch.object(_StrategyStub, "daytrade_entry_issue", create=True, new=lambda self, symbol: "")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _engine(self, snaps, now=(10, 30), states=None):
        engine, _ = _engine_with_state(states or {}, [], configs={"daytrade_auto_enabled": "true",
                                                                 "daytrade_momentum_min_turnover": "0",
                                                                 "daytrade_momentum_us_min_volume": "0",
                                                                 "daytrade_momentum_us_min_turnover": "0"})
        moment = datetime.datetime(2026, 5, 26, *now)
        engine._now = lambda: moment
        engine._timestamp = lambda: moment.strftime("%Y-%m-%d %H:%M:%S")
        engine._latest_snapshot = lambda symbol, market="KS": snaps[symbol]
        engine._append_runtime_log = lambda *a, **k: None
        engine._load_runtime_logs = lambda *a, **k: []
        engine._sync_broker_positions = lambda *a, **k: None
        return engine

    def _signal(self, engine, symbol="RUN1", market="KS"):
        return engine._signal_from_state(symbol, market=market, seed=10_000_000, strategy_id=STRATEGY,
                                         sync_broker=False)["signal"]


class MomentumSignalTests(_Base):
    def test_enters_a_mover_breaking_out_on_volume(self):
        signal = self._signal(self._engine({"RUN1": _snap()}))
        self.assertEqual(signal["action"], "BUY1")
        self.assertGreater(signal["order_qty"], 0)
        self.assertEqual(signal["price_source"], "kis_domestic_quote")

    def test_waits_when_not_in_play_without_volume_or_out_of_hours(self):
        self.assertEqual(self._signal(self._engine({"RUN1": _snap(prev_close=101.0)}))["action"], "HOLD")  # +3%
        self.assertEqual(self._signal(self._engine({"RUN1": _snap(signal_volume=1200)}))["action"], "HOLD")
        self.assertEqual(self._signal(self._engine({"RUN1": _snap()}, now=(9, 10)))["action"], "HOLD")
        self.assertEqual(self._signal(self._engine({"RUN1": _snap(prev_close=80.0)}))["action"], "HOLD")  # +30%: KS cap

    def test_three_entries_a_day_at_most(self):
        orders = [{"action": "BUY1", "strategy_id": STRATEGY, "timestamp": f"{TODAY} 10:0{i}:00"} for i in range(3)]
        state = _state("RUN1", 0, qty=0, strategy_id=STRATEGY, orders=orders)
        engine = self._engine({"RUN1": _snap()}, states={"RUN1.KS": state})
        self.assertIn("3회", self._signal(engine)["reason"])

    def test_trails_three_percent_under_the_peak(self):
        held = _state("RUN1", 100, qty=10, strategy_id=STRATEGY, momentum_peak=110)
        engine = self._engine({"RUN1": _snap(price=106.5, signal_close=106.0, vwap=101.0)}, states={"RUN1.KS": held})
        signal = self._signal(engine)
        self.assertEqual((signal["action"], signal["order_qty"]), ("SELL_FULL", 10))

    def test_exits_under_vwap_and_stops_at_minus_four(self):
        held = _state("RUN1", 100, qty=10, strategy_id=STRATEGY)
        engine = self._engine({"RUN1": _snap(price=102.0, signal_close=101.0, vwap=101.5)}, states={"RUN1.KS": held})
        self.assertEqual(self._signal(engine)["action"], "SELL_FULL")
        engine = self._engine({"RUN1": _snap(price=95.5)}, states={"RUN1.KS": dict(held)})
        self.assertEqual(self._signal(engine)["action"], "SELL_STOP_LOSS")

    def test_holds_a_running_winner(self):
        held = _state("RUN1", 100, qty=10, strategy_id=STRATEGY)
        signal = self._signal(self._engine({"RUN1": _snap(price=104.0)}, states={"RUN1.KS": held}))
        self.assertEqual(signal["action"], "HOLD")

    def test_flattens_in_the_close_window(self):
        held = _state("RUN1", 100, qty=10, strategy_id=STRATEGY)
        signal = self._signal(self._engine({"RUN1": _snap(price=104.0)}, now=(15, 12), states={"RUN1.KS": held}))
        self.assertEqual(signal["action"], "SELL_FULL")


class MomentumCandidateTests(_Base):
    def test_movers_follow_the_direction_etfs_and_skip_listed_symbols(self):
        engine = self._engine({})
        engine._risk_sized_entry_seed_krw = lambda *a, **k: 1_250_000
        engine._is_infinite_buy_symbol = lambda *a, **k: False
        universe = [{"symbol": "AAA", "change_pct": 9.0, "turnover_krw": 5e9},
                    {"symbol": "BBB", "change_pct": 12.0, "turnover_krw": 9e9},
                    {"symbol": "CCC", "change_pct": 2.0, "turnover_krw": 9e9},     # not in play
                    {"symbol": "LST", "change_pct": 9.0, "turnover_krw": 9e9}]     # already listed
        with patch.object(_StrategyStub, "candidate_universe", create=True, new=lambda self, market="KS": universe):
            rows = engine._with_momentum_candidates(
                [{"symbol": "114800", "source": "regime_trend"}, {"symbol": "LST", "source": "leaderboard"}],
                {"total_seed_krw": 1, "remaining_seed_krw": 1}, market="KS")
        self.assertEqual([(r["symbol"], r.get("strategy_id")) for r in rows],
                         [("114800", None), ("BBB", STRATEGY), ("AAA", STRATEGY), ("LST", None)])

    def test_live_never_runs_it(self):
        engine = self._engine({})
        with patch.object(daytrade_engine, "_PAPER_MODE", False):
            self.assertEqual(engine._with_momentum_candidates([{"symbol": "X"}], {}, market="US"), [{"symbol": "X"}])
            engine._is_infinite_buy_symbol = lambda *a, **k: False
            self.assertEqual(engine.execute_live("RUN1", market="KS", strategy_id=STRATEGY)["action"], "PAPER_ONLY")


class MomentumOrderPathTests(_Base):
    def _wire(self, engine):
        engine._hard_locked = lambda: False
        engine._daytrade_market_open = lambda market="KS": True
        engine._us_market_open = lambda: True
        engine._is_infinite_buy_symbol = lambda *a, **k: False
        engine._guardrails = lambda *a, **k: {"issues": [], "warnings": [], "risk_status": "SAFE"}
        engine._compact_runtime_meta = lambda *a, **k: {}
        engine._invalidate_kis_cache = lambda: None
        for name in ("_log_order_pending", "_log_order_failure", "_log_execution"):
            setattr(engine, name, Mock())
        engine._usd_krw_rate = lambda *a, **k: 1400.0
        broker = MagicMock()
        broker.buy_domestic_order.return_value = {"order_no": "0000123"}
        broker.buy_order.return_value = {"order_no": "0000456"}
        broker.get_domestic_fills_today.return_value = []
        broker.get_overseas_order_history.return_value = []
        broker.get_buying_power_info.return_value = {"ok": True, "executable_qty": 10_000, "executable_amount": 1_000_000,
                                                     "amount": 1_000_000, "qty": 10_000}
        engine._broker = lambda: broker
        engine._resolve_domestic_fill = lambda *a, **k: {"status": "UNKNOWN", "filled_qty": 0, "filled_price": 0}
        return broker

    def test_ks_mover_buy_reaches_the_broker(self):
        engine = self._engine({"RUN1": _snap()})
        broker = self._wire(engine)
        result = engine.execute_live("RUN1", market="KS", seed=10_000_000, strategy_id=STRATEGY, sync_broker=False)
        self.assertFalse(result.get("evidence_blocked"), result.get("message"))
        broker.buy_domestic_order.assert_called_once()

    def test_us_mover_buy_reaches_the_broker_on_its_booked_exchange(self):
        session, bar = _snap(source="kis_overseas_quote")
        bar["quote_prev_close"] = 95.0
        engine = self._engine({"RUNR": (session, bar)}, now=(23, 30))  # 10:30 ET
        broker = self._wire(engine)
        with patch.object(_StrategyStub, "us_candidate_universe", create=True, new=lambda self: []), \
                patch.dict(daytrade_engine.sys.__dict__, {"_stock8_us_exchange_book": {"RUNR": "NYSE"}}):
            result = engine.execute_live("RUNR", market="US", seed=10_000_000, strategy_id=STRATEGY, sync_broker=False)
        self.assertFalse(result.get("evidence_blocked"), result.get("message"))
        broker.buy_order.assert_called_once()
        self.assertEqual(broker.buy_order.call_args.kwargs.get("exchange"), "NYSE")


if __name__ == "__main__":
    unittest.main()
