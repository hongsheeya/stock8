"""P0 exit-path regressions for the domestic day-trade engine (no network orders).

Held auto slots are managed only by kr_execute_exit_watch, so these tests run
that fast path with a broker double and capture the decision it hands to
execute_live.
"""
import datetime
import unittest
from unittest.mock import Mock, patch

from test_daytrade_engine_regressions import _StrategyStub, _engine_with_state


TODAY = "2026-05-26"  # Tuesday; matches the harness clock

# The subset of Daytrade.DEFAULT_PROFILE the KS signal path reads.
LIVE_PROFILE = {
    "buy_trigger_1_pct": 0.0, "buy_trigger_2_pct": -0.35, "jackpot_take_profit_pct": 1.2,
    "jackpot_soft_exit_guard_ratio": 0.995, "stop_loss_pct": 1.5, "min_exit_net_profit_krw": 300,
    "min_exit_fee_multiple": 1.5, "rsi_exit_overbought": 75, "recent_lot_take_profit_pct": 0.6,
    "rescue_take_profit_pct": 0.5, "carry_overnight_enabled": True, "carry_max_loss_pct": 0.8,
    "carry_min_vwap_ratio": 0.997, "carry_min_close_strength_pct": -1.2,
    "close_liquidity_take_profit_pct": 0.4, "stop_reentry_same_day_block": True,
}


def _at(hour, minute):
    return datetime.datetime(2026, 5, 26, hour, minute, 0)


def _state(symbol, avg_price, qty=10, strategy_id="vrev", **extra):
    row = dict(symbol=symbol, market="KS", strategy_id=strategy_id, position_qty=qty,
               avg_price=avg_price, session_date=TODAY, realized_profit=0, orders=[])
    row.update(extra)
    return row


def _watch_engine(states, prices, now=None, bars=None):
    """Engine whose exit watch sees `prices` and records each decision."""
    engine, saved = _engine_with_state({f"{row['symbol']}.KS": row for row in states}, [])
    if now is not None:
        engine._now = lambda: now
    engine.active_positions = lambda **_kwargs: [
        {"symbol": row["symbol"], "market": "KS", "position_qty": row["position_qty"],
         "avg_price": row["avg_price"], "current_price": prices[row["symbol"]],
         "strategy_id": row["strategy_id"]}
        for row in states
    ]
    engine.shared_budget_status = lambda **_kwargs: {"total_seed_krw": 10 ** 12}
    engine._append_runtime_log = lambda *_args, **_kwargs: None
    engine._log_execution = Mock()
    engine._domestic_fills_for_pending = Mock(return_value=[])
    broker = Mock()
    engine._broker = lambda: broker
    bars = bars or {}
    engine._latest_snapshot = lambda symbol, market="KS": ({}, dict(bars.get(symbol, {})))
    decisions = {}

    def capture(symbol, **kwargs):
        signal = dict(kwargs["precomputed_status"]["signal"])
        decisions[symbol] = signal
        return {"executed": False, "submitted": False, "message": signal["reason"],
                "status": {"signal": signal}}

    engine.execute_live = capture
    return engine, saved, broker, decisions


class PendingReservationStopTests(unittest.TestCase):
    def reservation(self, **extra):
        fields = dict(pending_sell_order_no="555", pending_sell_type="JACKPOT",
                      pending_sell_price=10120, pending_sell_qty=10,
                      pending_sell_placed_at=f"{TODAY} 09:50:00")
        fields.update(extra)
        return _state("AAA", 10000, **fields)

    def test_stop_cancels_reservation_then_sells_after_broker_confirms(self):
        engine, saved, broker, decisions = _watch_engine([self.reservation()], {"AAA": 9800})

        engine.kr_execute_exit_watch(requested_seed=1000000)

        self.assertEqual(decisions["AAA"]["action"], "HOLD")
        self.assertIn("취소", decisions["AAA"]["reason"])
        broker.cancel_domestic_order.assert_called_once_with("555", "AAA", 10)
        self.assertEqual(saved()["AAA.KS"]["pending_sell_order_no"], "555")

        engine._domestic_fills_for_pending.return_value = [dict(order_no="555", status="CANCELLED")]
        engine.kr_execute_exit_watch(requested_seed=1000000)

        self.assertEqual(decisions["AAA"]["action"], "SELL_STOP_LOSS")
        self.assertEqual(decisions["AAA"]["order_qty"], 10)
        self.assertEqual(saved()["AAA.KS"]["pending_sell_order_no"], "")
        broker.cancel_domestic_order.assert_called_once()

    def test_previous_session_cancel_confirmation_resumes_stop(self):
        stale = self.reservation(pending_sell_placed_at="2026-05-25 14:00:00")
        engine, saved, _broker, decisions = _watch_engine([stale], {"AAA": 9800})
        engine._domestic_fills_for_pending.return_value = [dict(order_no="555", status="CANCELLED")]

        engine.kr_execute_exit_watch(requested_seed=1000000)

        self.assertEqual(decisions["AAA"]["action"], "SELL_STOP_LOSS")
        self.assertEqual(saved()["AAA.KS"]["pending_sell_order_no"], "")

    def test_previous_day_query_failure_never_releases_order(self):
        stale = self.reservation(pending_sell_placed_at="2026-05-25 14:00:00")
        engine, saved, broker, decisions = _watch_engine([stale], {"AAA": 9800})
        engine._domestic_fills_for_pending.side_effect = TimeoutError('gateway')
        engine.kr_execute_exit_watch(requested_seed=1000000)
        self.assertEqual(saved()["AAA.KS"]["pending_sell_order_no"], "555")
        self.assertEqual(decisions['AAA']['action'], 'HOLD')

    def test_previous_day_market_exit_is_not_expired_or_resent(self):
        stale = self.reservation(pending_sell_placed_at="2026-05-25 14:00:00", pending_sell_type='SELL_STOP_LOSS')
        engine, saved, broker, decisions = _watch_engine([stale], {"AAA": 9500})
        for _ in range(3):
            engine.kr_execute_exit_watch(requested_seed=1000000)
        self.assertEqual(saved()["AAA.KS"]["pending_sell_order_no"], "555")
        self.assertEqual(decisions['AAA']['action'], 'HOLD')
        broker.cancel_domestic_order.assert_not_called()

    def test_repeated_watch_sends_only_one_cancel(self):
        engine, saved, broker, decisions = _watch_engine([self.reservation()], {'AAA': 9800})
        for _ in range(8):
            engine.kr_execute_exit_watch(requested_seed=1000000)
        broker.cancel_domestic_order.assert_called_once()

    def test_cancelled_reservation_backs_off_without_delaying_stop(self):
        engine, saved, broker, decisions = _watch_engine([self.reservation()], {'AAA': 10100})
        engine._domestic_fills_for_pending.return_value = [dict(order_no='555', status='CANCELLED')]
        engine.kr_execute_exit_watch(requested_seed=1000000)
        state = saved()['AAA.KS']
        self.assertEqual(decisions['AAA']['action'], 'HOLD')
        self.assertFalse(engine._reservation_rearm_ready(state))
        engine._now = lambda: _at(10, 5)
        self.assertTrue(engine._reservation_rearm_ready(state))

    def test_filled_reservation_closes_watch_without_new_order(self):
        engine, saved, _broker, decisions = _watch_engine([self.reservation()], {"AAA": 10130})
        engine._domestic_fills_for_pending.return_value = [
            dict(order_no="555", status="FILLED", filled_qty=10, filled_price=10120)]

        result = engine.kr_execute_exit_watch(requested_seed=1000000)

        self.assertNotIn("AAA", decisions)
        self.assertEqual(saved()["AAA.KS"]["position_qty"], 0)
        self.assertEqual(result["results"][0]["signal"], "HOLD")

    def test_pending_market_exit_is_never_cancelled_or_resent(self):
        working = _state("AAA", 10000, pending_sell_order_no="777", pending_sell_type="SELL_STOP_LOSS",
                         pending_sell_price=9840, pending_sell_qty=10,
                         pending_sell_placed_at=f"{TODAY} 09:58:00")
        engine, _saved, broker, decisions = _watch_engine([working], {"AAA": 9500})

        engine.kr_execute_exit_watch(requested_seed=1000000)

        self.assertEqual(decisions["AAA"]["action"], "HOLD")
        broker.cancel_domestic_order.assert_not_called()


class PendingFillLabelTests(unittest.TestCase):
    def test_jackpot_fill_starts_cooldown_and_profit_reentry_guard(self):
        engine, _ = _engine_with_state({}, [])
        engine._log_execution = Mock()
        engine._domestic_fills_for_pending = Mock(return_value=[
            dict(order_no="555", status="FILLED", filled_qty=10, filled_price=10120)])
        state = _state("AAA", 10000, pending_sell_order_no="555", pending_sell_type="JACKPOT",
                       pending_sell_price=10120, pending_sell_qty=10,
                       pending_sell_placed_at=f"{TODAY} 09:50:00")

        self.assertEqual(engine._sync_pending_sell(state, "AAA", "KS", 10120), "filled")

        self.assertEqual(state["last_exit_action"], "SELL_FULL")
        self.assertEqual(state["last_exit_price"], 10120)
        self.assertTrue(engine._reentry_cooldown_status(state, {}, market="KS")["active"])
        guard = engine._profit_reentry_guard(state, {}, current_price=10080, trigger_price=10100)
        self.assertTrue(guard["active"])
        self.assertEqual(engine._log_execution.call_args[0][1], "SELL_FULL")

    def test_confirmed_market_stop_keeps_same_day_stop_block(self):
        engine, _ = _engine_with_state({}, [])
        engine._log_execution = Mock()
        engine._domestic_fills_for_pending = Mock(return_value=[
            dict(order_no="777", status="FILLED", filled_qty=10, filled_price=9840)])
        state = _state("AAA", 10000, pending_sell_order_no="777", pending_sell_type="SELL_STOP_LOSS",
                       pending_sell_price=9840, pending_sell_qty=10,
                       pending_sell_placed_at=f"{TODAY} 09:58:00")

        self.assertEqual(engine._sync_pending_sell(state, "AAA", "KS", 9800), "filled")

        self.assertEqual(state["last_exit_action"], "SELL_STOP_LOSS")
        cooldown = engine._reentry_cooldown_status(state, {"stop_reentry_same_day_block": True}, market="KS")
        self.assertTrue(cooldown["active"])
        self.assertIn("당일 손절", cooldown["reason"])
        self.assertEqual(engine._log_execution.call_args[0][1], "SELL_STOP_LOSS")


class CloseWindowTests(unittest.TestCase):
    def test_close_window_runs_inside_the_auto_session(self):
        engine, _ = _engine_with_state({}, [])
        for (hour, minute), expected in {(15, 9): False, (15, 10): True, (15, 19): True,
                                         (15, 20): False, (15, 35): False}.items():
            engine._now = lambda hour=hour, minute=minute: _at(hour, minute)
            self.assertEqual(engine._is_market_close_approaching("KS"), expected, (hour, minute))
        engine._now = lambda: _at(15, 15)
        self.assertTrue(engine._daytrade_market_open("KS"))

    def test_close_window_start_is_configurable(self):
        engine, _ = _engine_with_state({}, [], configs={"daytrade_ks_close_window_start": "1500"})
        engine._now = lambda: _at(15, 5)
        self.assertTrue(engine._is_market_close_approaching("KS"))

    def test_exit_watch_applies_close_rule(self):
        states = [_state("WIN", 10000), _state("LOSE", 10000), _state("FLAT", 10000)]
        prices = {"WIN": 10050, "LOSE": 9900, "FLAT": 9990}
        bars = {"WIN": {"vwap": 10000}, "LOSE": {"vwap": 10000}, "FLAT": {"vwap": 9950}}
        engine, _saved, _broker, decisions = _watch_engine(states, prices, now=_at(15, 12), bars=bars)

        engine.kr_execute_exit_watch(requested_seed=1000000)

        self.assertEqual(decisions["WIN"]["action"], "SELL_FULL")
        self.assertFalse(decisions["WIN"]["risk_exit"])
        self.assertEqual(decisions["LOSE"]["action"], "SELL_FULL")
        self.assertTrue(decisions["LOSE"]["risk_exit"])
        self.assertIn("장마감 약세 정리", decisions["LOSE"]["reason"])
        self.assertEqual(decisions["FLAT"]["action"], "HOLD")
        self.assertIn("오버나잇", decisions["FLAT"]["reason"])

    def test_close_rule_is_not_blocked_by_profit_guards_in_signal_path(self):
        engine, _ = _engine_with_state({"LOSE.KS": _state("LOSE", 10000)}, [])
        engine._now = lambda: _at(15, 12)
        engine._append_runtime_log = lambda *_args, **_kwargs: None
        engine._profile_for = lambda *_args, **_kwargs: dict(LIVE_PROFILE)

        with patch.object(_StrategyStub, "_event_filter_snapshot", create=True,
                          new=lambda *_args, **_kwargs: {"blocked": False}):
            status = engine._signal_from_state("LOSE", market="KS", seed=1000000, strategy_id="vrev",
                                               sync_broker=False, allow_buy=False, current_price_override=9900)

        self.assertEqual(status["signal"]["action"], "SELL_FULL")
        self.assertTrue(status["signal"]["risk_exit"])


class VolumeBreakoutExitTests(unittest.TestCase):
    def test_exit_watch_takes_profit_and_cuts_failed_breakouts(self):
        states = [_state("TPB", 10000, strategy_id="volume_breakout"),
                  _state("DOWN", 10000, strategy_id="volume_breakout"),
                  _state("OK", 10000, strategy_id="volume_breakout")]
        prices = {"TPB": 10150, "DOWN": 9950, "OK": 10050}
        bars = {"TPB": {"vwap": 10000}, "DOWN": {"vwap": 10000, "breakout_low_20": 9900},
                "OK": {"vwap": 10000, "breakout_low_20": 9900}}
        engine, _saved, _broker, decisions = _watch_engine(states, prices, bars=bars)

        engine.kr_execute_exit_watch(requested_seed=1000000)

        self.assertEqual(decisions["TPB"]["action"], "SELL_FULL")
        self.assertFalse(decisions["TPB"]["risk_exit"])
        self.assertEqual(decisions["DOWN"]["action"], "SELL_FULL")
        self.assertTrue(decisions["DOWN"]["risk_exit"])
        self.assertEqual(decisions["OK"]["action"], "HOLD")

    def test_breakout_position_is_flattened_in_close_window(self):
        states = [_state("BRK", 10000, strategy_id="volume_breakout")]
        engine, _saved, _broker, decisions = _watch_engine(
            states, {"BRK": 10010}, now=_at(15, 12), bars={"BRK": {"vwap": 9990}})

        engine.kr_execute_exit_watch(requested_seed=1000000)

        self.assertEqual(decisions["BRK"]["action"], "SELL_FULL")
        self.assertTrue(decisions["BRK"]["risk_exit"])


if __name__ == "__main__":
    unittest.main()
