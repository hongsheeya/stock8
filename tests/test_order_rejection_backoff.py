"""11-16 PAPER: KIS rejected every order of the mock account ("40910000
모의투자 주문이 불가한 계좌입니다") and the engine kept re-sending: 114800 SELL
34x in 20-30 s steps (the exit watch fast path skipped the failure cooldown),
251340 BUY 35x, AVEX/HUBS SELL ~50x. 252670 BUY was re-sent for three days
although KIS answered "40070000 매매불가 종목".

Offline only: no broker connection, no orders.
"""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_daytrade_engine_regressions import daytrade_engine as engine_module, _StrategyStub
from test_daytrade_partial_fill_logging import _engine

ACCOUNT_ERROR = "국내주식 SELL 주문 실패 [114800]: 모의투자 주문이 불가한 계좌입니다. (qty=1317, price=0)"
SYMBOL_ERROR = "국내주식 BUY 주문 실패 [252670]: 모의투자 주문처리가 안되었습니다(매매불가 종목) (qty=15200)"
RATE_ERROR = "국내주식 SELL 주문 실패 [114800]: 초당 거래건수를 초과하였습니다. (qty=1317)"


class _Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def time(self):
        return self.now


def _state(symbol="114800", qty=1317, **extra):
    return dict(symbol=symbol, market="KS", strategy_id="paper_regime_trend", position_qty=qty,
                avg_price=1247.0 if qty else 0.0, buy1_used=bool(qty), orders=[], **extra)


def _run(engine, state, action, qty, error=None, precomputed=False, symbol="114800", clock=None):
    """execute_live with a canned signal; the broker raises `error` if given."""
    engine._hard_locked = lambda: False
    engine._feature_enabled = lambda: True
    engine._daytrade_market_open = lambda market: True
    status = dict(state=state, signal=dict(action=action, order_qty=qty, current_price=1250,
                                           reason="테스트용 거래량과 추세 조건 확인", price_source="kis_quote"),
                  runtime={"risk_status": "SAFE", "issues": []})
    engine.signal_status = Mock(return_value=status)
    engine._state_for = lambda *a, **k: state
    engine._store_state = lambda s: None
    engine._compact_runtime_meta = lambda *args: {}
    engine._resolve_domestic_fill = lambda *a, **kw: dict(status="FILLED", filled_qty=qty, filled_price=1250)
    broker = Mock()
    for name in ("buy_domestic_order", "sell_domestic_order"):
        method = getattr(broker, name)
        if error:
            method.side_effect = RuntimeError(error)
        else:
            method.return_value = {"order_no": "0000012345"}
    engine._broker = lambda: broker
    with patch.object(engine_module, "_PAPER_MODE", True), \
            patch.object(engine_module, "_clock", clock or _Clock()), \
            patch.object(_StrategyStub, "daytrade_entry_issue", lambda self, symbol: "", create=True):
        result = engine.execute_live(symbol, strategy_id="paper_regime_trend", sync_broker=False,
                                     allow_buy=action.startswith("BUY"),
                                     precomputed_status=status if precomputed else None)
    return result, broker


def _sent(broker):
    return broker.buy_domestic_order.call_count + broker.sell_domestic_order.call_count


class RejectionKindTests(unittest.TestCase):
    def test_kinds(self):
        kind = engine_module.DomesticDaytradeEngine._order_rejection_kind
        self.assertEqual(kind(ACCOUNT_ERROR), "account")
        self.assertEqual(kind("모의투자 주문이 불가한 계좌입니다."), "account")
        self.assertEqual(kind(SYMBOL_ERROR), "symbol")
        # Digits alone never classify: overseas errors carry CANO, qty and price.
        self.assertEqual(kind("매도 주문 실패 [AVEX]: 주문 오류 (rt_cd=1, CANO=40910000, qty=40070000)"), "other")
        self.assertEqual(kind(RATE_ERROR), "rate")
        self.assertEqual(kind("잔고내역이 없습니다"), "other")
        self.assertEqual(kind(""), "other")


class AccountHaltTests(unittest.TestCase):
    def setUp(self):
        sys._trading_daytrade_account_halt = {}
        self.clock = _Clock()

    def tearDown(self):
        sys._trading_daytrade_account_halt = {}

    def _halted_engine(self):
        engine, _stored, _log = _engine()
        _run(engine, _state(), "SELL_FULL", 1317, error=ACCOUNT_ERROR, clock=self.clock)
        self.assertTrue(engine._account_halt_status("KS"))
        return engine

    def test_account_rejection_stops_other_symbols_and_sides(self):
        engine = self._halted_engine()
        self.clock.now += 30
        for symbol, action, qty in (("251340", "BUY1", 567), ("233740", "SELL_STOP_LOSS", 350)):
            state = _state(symbol, 0) if action.startswith("BUY") else _state(symbol, qty)
            result, broker = _run(engine, state, action, qty, symbol=symbol, clock=self.clock)
            self.assertEqual(result["action"], "ORDER_BACKOFF", result)
            self.assertIn("계좌 주문을 거부", result["message"])
            self.assertEqual(_sent(broker), 0)

    def test_sell_probe_every_two_minutes_and_success_lifts_the_halt(self):
        engine = self._halted_engine()
        self.clock.now += engine._account_sell_probe_sec() + 1
        _result, broker = _run(engine, _state("233740", 350), "SELL_STOP_LOSS", 350, error=ACCOUNT_ERROR,
                               symbol="233740", clock=self.clock)
        self.assertEqual(_sent(broker), 1)  # the probe went out and was rejected again
        result, broker = _run(engine, _state("233740", 350), "SELL_STOP_LOSS", 350, symbol="233740", clock=self.clock)
        self.assertEqual(result["action"], "ORDER_BACKOFF")
        self.clock.now += engine._account_sell_probe_sec() + 1
        _result, broker = _run(engine, _state("233740", 350), "SELL_STOP_LOSS", 350, symbol="233740", clock=self.clock)
        self.assertEqual(_sent(broker), 1)
        self.assertIsNone(engine._account_halt_status("KS"))

    def test_buy_probe_is_rare_and_never_delays_the_sell_probe(self):
        engine = self._halted_engine()
        self.clock.now += engine._account_sell_probe_sec() + 1
        result, broker = _run(engine, _state("251340", 0), "BUY1", 567, symbol="251340", clock=self.clock)
        self.assertEqual(_sent(broker), 0, "buys wait for the long buy interval")
        self.clock.now += engine._account_buy_probe_sec()
        _result, broker = _run(engine, _state("251340", 0), "BUY1", 567, error=ACCOUNT_ERROR,
                               symbol="251340", clock=self.clock)
        self.assertEqual(_sent(broker), 1)
        halt = engine._account_halt_status("KS")
        # The rejected buy probe re-armed the sell slot only by the short interval.
        self.assertLessEqual(halt["next_sell_probe"] - self.clock.now, engine._account_sell_probe_sec())
        self.assertGreater(halt["next_buy_probe"] - self.clock.now, engine._account_sell_probe_sec())

    def test_paths_that_stop_before_sending_keep_the_probe_slot(self):
        engine = self._halted_engine()
        self.clock.now += engine._account_sell_probe_sec() + 1
        before = engine._account_halt_status("KS")["next_sell_probe"]
        engine._order_blocked_reason = lambda *a, **k: "신호가 오래되어 주문하지 않습니다."
        result, broker = _run(engine, _state(), "SELL_FULL", 1317, clock=self.clock)
        self.assertEqual(_sent(broker), 0)
        self.assertEqual(engine._account_halt_status("KS")["next_sell_probe"], before)
        with patch.object(engine_module, "_clock", self.clock):
            self.assertEqual(engine._account_halt_issue("SELL_FULL", "KS"), "")

    def test_concurrent_lanes_share_one_probe(self):
        engine = self._halted_engine()
        self.clock.now += engine._account_sell_probe_sec() + 1
        send = Mock(side_effect=RuntimeError(ACCOUNT_ERROR))
        with patch.object(engine_module, "_clock", self.clock):
            with self.assertRaises(RuntimeError):
                engine._submit_order(send, market="KS", side="SELL")
            with self.assertRaises(engine.OrderBackoff):
                engine._submit_order(send, market="KS", side="SELL")
        self.assertEqual(send.call_count, 1)

    def test_shadow_order_does_not_lift_the_halt(self):
        engine = self._halted_engine()
        self.clock.now += engine._account_sell_probe_sec() + 1
        with patch.object(engine_module, "_clock", self.clock):
            engine._submit_order(lambda: {"order_no": "shadow_1", "shadow": True}, market="KS", side="SELL")
        self.assertTrue(engine._account_halt_status("KS"))

    def test_halt_is_per_lane_and_per_account(self):
        engine = self._halted_engine()
        self.assertIsNone(engine._account_halt_status("US"))
        other, _stored, _log = _engine()
        other.struct.live_data_scope = "other-account"
        with patch.object(engine_module, "_PAPER_MODE", True):
            self.assertIsNone(other._account_halt_status("KS"))
        result, broker = _run(other, _state(), "SELL_FULL", 1317, clock=self.clock)
        self.assertEqual(_sent(broker), 1)

    def test_rate_limit_and_other_errors_do_not_halt_the_account(self):
        for error in (RATE_ERROR, "국내주식 SELL 주문 실패 [114800]: 잔고내역이 없습니다."):
            sys._trading_daytrade_account_halt = {}
            engine, _stored, _log = _engine()
            _run(engine, _state(), "SELL_FULL", 1317, error=error, clock=self.clock)
            self.assertIsNone(engine._account_halt_status("KS"))


class SymbolBlockTests(unittest.TestCase):
    def setUp(self):
        sys._trading_daytrade_account_halt = {}

    def test_unbuyable_symbol_is_skipped_for_the_rest_of_the_day(self):
        engine, _stored, _log = _engine()
        state = _state("252670", 0)
        _run(engine, state, "BUY1", 15200, error=SYMBOL_ERROR, symbol="252670")
        self.assertEqual(state["buy_blocked_date"], "2026-11-10")
        state.pop("last_order_failure_at")  # past the normal cooldown
        result, broker = _run(engine, state, "BUY1", 15200, symbol="252670")
        self.assertEqual(result["action"], "ORDER_BACKOFF")
        self.assertIn("매매불가", result["message"])
        self.assertEqual(_sent(broker), 0)
        self.assertIsNone(engine._account_halt_status("KS"))
        # The next day it may be tried again.
        engine._now = lambda: engine_module.datetime.datetime(2026, 11, 11, 10, 0)
        _result, broker = _run(engine, state, "BUY1", 15200, symbol="252670")
        self.assertEqual(_sent(broker), 1)

    def test_symbol_block_never_stops_a_sell(self):
        engine, _stored, _log = _engine()
        state = _state("252670", 10, buy_blocked_date="2026-11-10", buy_blocked_reason=SYMBOL_ERROR)
        _result, broker = _run(engine, state, "SELL_FULL", 10, symbol="252670")
        self.assertEqual(broker.sell_domestic_order.call_count, 1)


class FastPathCooldownTests(unittest.TestCase):
    def setUp(self):
        sys._trading_daytrade_account_halt = {}

    def test_exit_watch_fast_path_waits_after_a_rejected_sell(self):
        engine, _stored, _log = _engine()  # _now is 2026-11-10 11:20:00
        state = _state(last_order_failure_at="2026-11-10 11:19:50", last_order_failure_action="SELL_FULL")
        result, broker = _run(engine, state, "SELL_FULL", 1317, precomputed=True)
        self.assertEqual(result["action"], "ORDER_BACKOFF", result)
        self.assertIn("재시도 대기", result["message"])
        self.assertEqual(_sent(broker), 0)

    def test_fast_path_sells_again_after_30_seconds(self):
        engine, _stored, _log = _engine()
        state = _state(last_order_failure_at="2026-11-10 11:19:20", last_order_failure_action="SELL_FULL")
        _result, broker = _run(engine, state, "SELL_FULL", 1317, precomputed=True)
        self.assertEqual(broker.sell_domestic_order.call_count, 1)

    def test_a_failed_buy_does_not_hold_back_an_exit(self):
        engine, _stored, _log = _engine()
        state = _state(last_order_failure_at="2026-11-10 11:19:50", last_order_failure_action="BUY1")
        _result, broker = _run(engine, state, "SELL_STOP_LOSS", 1317, precomputed=True)
        self.assertEqual(broker.sell_domestic_order.call_count, 1)

    def test_all_sell_exits_share_one_cooldown(self):
        engine, _stored, _log = _engine()
        state = _state(last_order_failure_at="2026-11-10 11:19:50", last_order_failure_action="SELL_FULL")
        result, broker = _run(engine, state, "SELL_STOP_LOSS", 1317, precomputed=True)
        self.assertEqual(result["action"], "ORDER_BACKOFF")
        self.assertEqual(_sent(broker), 0)

    def test_jackpot_reservation_keeps_its_failure_cooldown(self):
        engine, _stored, _log = _engine()
        state = _state(last_order_failure_at="2026-11-10 11:18:00", last_order_failure_action="PRE_SELL_JACKPOT")
        self.assertIn("재시도 대기", engine._order_failure_cooldown_issue(state, "PRE_SELL_JACKPOT"))
        self.assertEqual(engine._order_failure_cooldown_issue(state, "SELL_FULL"), "")


if __name__ == "__main__":
    unittest.main()
