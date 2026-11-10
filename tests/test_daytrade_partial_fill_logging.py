"""11-09/11-10 PAPER: trade_log kept the partial fill seen right after a
domestic market order instead of the broker's final fill.

- 114800 SELL_FULL 1,262 shares: logged 1 share (-16 KRW), KIS filled 1,262.
- 251340 SELL_FULL 535 shares: logged 1 share, KIS filled 535.
- 122630 SELL_FULL 29 shares: logged 25, the "remaining" 4 were sold again
  and rejected ("잔고내역이 없습니다").
- 003490 BUY1 18 shares: logged 15, KIS filled 18.
- 251340 BUY1 535 shares: pending at submit, filled later, never logged.

Offline only: no broker connection, no orders.
"""
import copy
import datetime
import unittest
from unittest.mock import Mock, patch

from test_daytrade_engine_regressions import daytrade_engine as engine_module, _engine_with_state, _StrategyStub

ENTRY = 1300.0


class _TradeLog:
    def __init__(self):
        self.rows_ = []

    def insert(self, row):
        self.rows_.append(dict(row, id=f"row{len(self.rows_) + 1}"))

    def rows(self, **query):
        order_no = query.get("order_no")
        return [copy.deepcopy(r) for r in self.rows_ if order_no is None or r.get("order_no") == order_no]

    def fills(self, order_no):
        return [r for r in self.rows_ if r.get("order_no") == order_no and r.get("action") not in ("PENDING", "ERROR")]


class _RequestOptions:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _engine(state_map=None, strategy_id="paper_regime_trend"):
    engine, stored = _engine_with_state(state_map or {}, [], configs={"daytrade_auto_enabled": "true"})
    log = _TradeLog()
    engine.struct.db = lambda name: log
    engine.struct.kis_api.is_real = False
    engine.struct.kis_api.request_options = lambda **kw: _RequestOptions()
    engine._now = lambda: datetime.datetime(2026, 11, 10, 11, 20)
    engine._append_runtime_log = Mock()
    engine._invalidate_kis_cache = lambda: None
    engine._fs = lambda: Mock()
    return engine, stored, log


def _submit(engine, state, action, qty, fill, strategy_id="paper_regime_trend", price=1290):
    """Run execute_live with a canned signal and immediate fill result."""
    engine._hard_locked = lambda: False
    engine._feature_enabled = lambda: True
    engine._daytrade_market_open = lambda market: True
    engine.strategy.daytrade_entry_issue = lambda symbol: ""
    status = dict(state=state, signal=dict(action=action, order_qty=qty, current_price=price,
                                           reason="테스트용 거래량과 추세 조건 확인", price_source="kis_quote"),
                  runtime={"risk_status": "SAFE"})
    engine.signal_status = Mock(return_value=status)
    engine._state_for = lambda *a, **k: state
    engine._store_state = lambda s: None
    engine._compact_runtime_meta = lambda *args: {}
    broker = Mock()
    broker.buy_domestic_order.return_value = {"order_no": "0000012345"}
    broker.sell_domestic_order.return_value = {"order_no": "0000012345"}
    engine._broker = lambda: broker
    if isinstance(fill, Exception):
        engine.struct.kis_api.get_domestic_fills_today = Mock(side_effect=fill)
        engine._resolve_domestic_fill = engine_module.DomesticDaytradeEngine._resolve_domestic_fill.__get__(engine)
        broker.get_domestic_fills_today.side_effect = fill
    else:
        engine._resolve_domestic_fill = lambda *a, **kw: dict(fill)
    with patch.object(engine_module, "_PAPER_MODE", True), \
            patch.object(_StrategyStub, "daytrade_entry_issue", lambda self, symbol: "", create=True):
        result = engine.execute_live("114800", strategy_id=strategy_id, sync_broker=False)
    return result, broker


def _held(qty=1262, strategy_id="paper_regime_trend"):
    return dict(symbol="114800", market="KS", strategy_id=strategy_id, position_qty=qty,
                avg_price=ENTRY, buy1_used=True, orders=[])


class ImmediatePartialFillTests(unittest.TestCase):
    def test_partial_market_sell_stays_pending_for_every_strategy(self):
        for strategy_id in ("paper_regime_trend", "paper_momentum_ride", "vrev"):
            engine, _stored, log = _engine()
            state = _held(strategy_id=strategy_id)
            result, _broker = _submit(engine, state, "SELL_FULL", 1262,
                                      dict(status="PARTIAL", filled_qty=1, filled_price=1284),
                                      strategy_id=strategy_id)
            self.assertTrue(result.get("submitted"), result)
            self.assertFalse(result["executed"])
            self.assertEqual(state["pending_sell_order_no"], "0000012345")
            self.assertEqual(state["pending_sell_position_before"], 1262)
            self.assertEqual(state["pending_sell_entry_avg"], ENTRY)
            # Nothing is booked or removed from the position on a partial view.
            self.assertEqual(state["position_qty"], 1262)
            self.assertEqual(state.get("realized_profit", 0), 0)
            self.assertEqual(log.fills("0000012345"), [])
            pending = [r for r in log.rows_ if r["action"] == "PENDING"]
            self.assertEqual(len(pending), 1)
            self.assertIn("1/1262주", pending[0]["message"])

    def test_partial_market_buy_stays_pending_and_remembers_position(self):
        engine, _stored, log = _engine()
        state = dict(symbol="114800", market="KS", strategy_id="paper_regime_trend", position_qty=0,
                     avg_price=0, orders=[])
        engine._order_blocked_reason = lambda *a, **k: ""
        engine._buy_budget_snapshot = lambda *a, **k: {}
        result, broker = _submit(engine, state, "BUY1", 18,
                                 dict(status="PARTIAL", filled_qty=15, filled_price=32494))
        broker.buy_domestic_order.assert_called_once()
        self.assertTrue(result.get("submitted"), result)
        self.assertEqual(state["pending_buy_order_no"], "0000012345")
        self.assertEqual(state["pending_buy_position_before"], 0)
        self.assertEqual(state["position_qty"], 0)
        self.assertEqual(log.fills("0000012345"), [])

    def test_full_immediate_fill_is_still_logged_at_once(self):
        engine, _stored, log = _engine()
        state = _held()
        result, _broker = _submit(engine, state, "SELL_FULL", 1262,
                                  dict(status="FILLED", filled_qty=1262, filled_price=1284))
        self.assertTrue(result["executed"], result)
        fills = log.fills("0000012345")
        self.assertEqual([r["filled_qty"] for r in fills], [1262])
        self.assertEqual(state["position_qty"], 0)
        self.assertAlmostEqual(state["realized_profit"], (1284 - ENTRY) * 1262, places=2)

    def test_fill_query_failure_is_pending_not_zero_fill(self):
        engine, _stored, log = _engine()
        state = _held()
        result, _broker = _submit(engine, state, "SELL_FULL", 1262, RuntimeError("국내 체결 조회 실패"))
        self.assertTrue(result.get("submitted"), result)
        self.assertEqual(state["pending_sell_order_no"], "0000012345")
        self.assertEqual(state["position_qty"], 1262)
        self.assertEqual(log.fills("0000012345"), [])

    def test_pending_sell_blocks_a_second_sell(self):
        """122630 (11-09): the unconfirmed remainder must not be sold again."""
        engine, _stored, _log = _engine()
        state = _held(29)
        _submit(engine, state, "SELL_FULL", 29, dict(status="PARTIAL", filled_qty=25, filled_price=56499))
        result, broker = _submit(engine, state, "SELL_FULL", 29, dict(status="FILLED", filled_qty=29, filled_price=56499))
        self.assertEqual(result["action"], "PENDING_ORDER")
        broker.sell_domestic_order.assert_not_called()


def _pending_sell_state(position_qty=1262, avg_price=ENTRY):
    return dict(symbol="114800", market="KS", strategy_id="paper_regime_trend", name="KODEX 200선물인버스2X",
                position_qty=position_qty, avg_price=avg_price,
                pending_sell_order_no="0000012345", pending_sell_qty=1262, pending_sell_price=1290,
                pending_sell_type="SELL_FULL", pending_sell_placed_at="2026-11-10 11:15:10",
                pending_sell_position_before=1262, pending_sell_entry_avg=ENTRY,
                orders=[dict(timestamp="2026-11-10 11:15:10", action="SELL_FULL", qty=1262, price=1290,
                             order_no="0000012345", status="PARTIAL")])


KIS_SELL = dict(order_no="12345", symbol="114800", side="SELL", status="FILLED", filled_qty=1262, filled_price=1284.0)


class DelayedFillSettlementTests(unittest.TestCase):
    def test_confirmed_sell_logs_final_fill_after_balance_sync_zeroed_position(self):
        engine, _stored, log = _engine()
        engine.struct.kis_api.domestic_fills = [dict(KIS_SELL)]
        state = _pending_sell_state(position_qty=0, avg_price=0.0)  # balance sync already ran
        self.assertEqual(engine._sync_pending_sell(state, "114800", "KS"), "filled")
        fills = log.fills("0000012345")
        self.assertEqual([(r["filled_qty"], r["filled_price"]) for r in fills], [(1262, 1284.0)])
        expected = (1284.0 - ENTRY) * 1262
        self.assertAlmostEqual(state["realized_profit"], expected, places=2)
        self.assertEqual(state["position_qty"], 0)
        self.assertEqual(state["pending_sell_order_no"], "")
        self.assertNotIn("pending_sell_entry_avg", state)
        self.assertTrue(state.get("flat_after_exit_at"))
        self.assertEqual(state["orders"][0]["booked_qty"], 1262)
        # Later reconciliation of the same order books nothing more.
        engine._mark_state_order_fill(state, "0000012345", dict(KIS_SELL, verification="kis"))
        self.assertAlmostEqual(state["realized_profit"], expected, places=2)

    def test_confirmed_sell_does_not_subtract_twice(self):
        engine, _stored, _log = _engine()
        engine.struct.kis_api.domestic_fills = [dict(KIS_SELL, filled_qty=1000, status="FILLED")]
        state = _pending_sell_state(position_qty=262)  # balance sync applied the 1,000 sold
        engine._sync_pending_sell(state, "114800", "KS")
        self.assertEqual(state["position_qty"], 262)

    def test_partial_confirmation_keeps_waiting(self):
        engine, _stored, log = _engine()
        engine.struct.kis_api.domestic_fills = [dict(KIS_SELL, status="PARTIAL", filled_qty=1)]
        state = _pending_sell_state()
        self.assertEqual(engine._sync_pending_sell(state, "114800", "KS"), "open")
        self.assertEqual(state["pending_sell_order_no"], "0000012345")
        self.assertEqual(state["position_qty"], 1262)
        self.assertEqual(log.fills("0000012345"), [])

    def test_query_failure_keeps_waiting(self):
        engine, _stored, log = _engine()
        engine.struct.kis_api.get_domestic_fills_today = Mock(side_effect=RuntimeError("timeout"))
        state = _pending_sell_state()
        self.assertEqual(engine._sync_pending_sell(state, "114800", "KS"), "open")
        self.assertEqual(state["pending_sell_order_no"], "0000012345")
        self.assertEqual(log.fills("0000012345"), [])

    def test_existing_fill_row_is_not_written_twice(self):
        engine, _stored, log = _engine()
        log.insert(dict(order_no="0000012345", action="SELL", event_type="DT_KS_SELL_FULL", filled_qty=1262))
        engine.struct.kis_api.domestic_fills = [dict(KIS_SELL)]
        state = _pending_sell_state()
        engine._sync_pending_sell(state, "114800", "KS")
        self.assertEqual(len(log.fills("0000012345")), 1)

    def test_confirmed_buy_logs_final_fill(self):
        """003490 / 251340 (11-10): the delayed buy fill gets its own row."""
        engine, _stored, log = _engine()
        engine.struct.kis_api.domestic_fills = [dict(order_no="777", symbol="251340", side="BUY",
                                                     status="FILLED", filled_qty=535, filled_price=3070.0)]
        state = dict(symbol="251340", market="KS", strategy_id="paper_regime_trend", position_qty=0, avg_price=0,
                     pending_buy_order_no="0000000777", pending_buy_action="BUY1", pending_buy_qty=535,
                     pending_buy_price=3065, pending_buy_placed_at="2026-11-10 12:46:56",
                     pending_buy_position_before=0, pending_buy_avg_before=0.0,
                     orders=[dict(timestamp="2026-11-10 12:46:56", action="BUY1", qty=535,
                                  order_no="0000000777", status="ACCEPTED_UNVERIFIED")])
        self.assertEqual(engine._sync_pending_buy(state, "251340", "KS"), "filled")
        fills = log.fills("0000000777")
        self.assertEqual([(r["action"], r["filled_qty"], r["filled_price"]) for r in fills], [("BUY", 535, 3070.0)])
        self.assertEqual(state["position_qty"], 535)
        self.assertEqual(state["avg_price"], 3070.0)
        self.assertEqual(state["pending_buy_qty"], 0)
        self.assertNotIn("pending_buy_position_before", state)

    def test_confirmed_buy2_adds_to_position_once(self):
        engine, _stored, _log = _engine()
        engine.struct.kis_api.domestic_fills = [dict(order_no="778", symbol="003490", side="BUY",
                                                     status="FILLED", filled_qty=18, filled_price=32494.44)]
        base = dict(symbol="003490", market="KS", strategy_id="vrev", pending_buy_order_no="778",
                    pending_buy_action="BUY2", pending_buy_qty=18, pending_buy_placed_at="2026-11-10 11:48:58",
                    pending_buy_position_before=10, pending_buy_avg_before=30000.0, orders=[])
        state = dict(base, position_qty=10, avg_price=30000.0)
        engine._sync_pending_buy(state, "003490", "KS")
        self.assertEqual(state["position_qty"], 28)
        self.assertAlmostEqual(state["avg_price"], (30000 * 10 + 32494.44 * 18) / 28, places=3)
        synced = dict(base, position_qty=28, avg_price=31603.0)  # balance sync already added it
        engine._sync_pending_buy(synced, "003490", "KS")
        self.assertEqual(synced["position_qty"], 28)
        self.assertEqual(synced["avg_price"], 31603.0)


class ReconciliationSettlementTests(unittest.TestCase):
    def test_reconciliation_settles_pending_buy_and_sell_with_fill_rows(self):
        buy_state = dict(symbol="251340", market="KS", strategy_id="paper_regime_trend", position_qty=0, avg_price=0,
                         pending_buy_order_no="0000000777", pending_buy_action="BUY1", pending_buy_qty=535,
                         pending_buy_price=3065, pending_buy_placed_at="2026-11-10 12:46:56",
                         pending_buy_position_before=0, pending_buy_avg_before=0.0,
                         orders=[dict(timestamp="2026-11-10 12:46:56", action="BUY1", qty=535,
                                      order_no="0000000777", status="ACCEPTED_UNVERIFIED")])
        sell_state = _pending_sell_state(position_qty=0, avg_price=0.0)
        engine, stored, log = _engine({"251340.KS": buy_state, "114800.KS": sell_state})
        engine.struct.kis_api.domestic_fills = [
            dict(order_no="777", symbol="251340", side="BUY", status="FILLED", filled_qty=535, filled_price=3070.0),
            dict(KIS_SELL),
        ]
        engine.reconcile_order_history(max_dates=2)
        after = stored()
        self.assertEqual([r["filled_qty"] for r in log.fills("0000000777")], [535])
        self.assertEqual([r["filled_qty"] for r in log.fills("0000012345")], [1262])
        self.assertEqual(after["251340.KS"]["pending_buy_order_no"], "")
        self.assertEqual(after["251340.KS"]["pending_buy_qty"], 0)
        self.assertEqual(after["114800.KS"]["pending_sell_order_no"], "")
        self.assertAlmostEqual(after["114800.KS"]["realized_profit"], (1284.0 - ENTRY) * 1262, places=2)
        # A later signal-path sync of the same state finds nothing pending.
        state = after["114800.KS"]
        self.assertEqual(engine._sync_pending_sell(state, "114800", "KS"), "none")
        self.assertEqual(len(log.fills("0000012345")), 1)


class ExitWatchPendingTests(unittest.TestCase):
    """LIVE runs no reconciliation thread; the exit watch settles what it skips."""

    def _watch(self, state_map, fills):
        engine, stored, log = _engine(state_map)
        broker = Mock()
        broker.get_domestic_fills_today.side_effect = lambda symbol="": [
            dict(f) for f in fills if not symbol or f["symbol"] == symbol]
        engine._broker = lambda: broker
        engine._hard_locked = lambda: False
        engine._daytrade_market_open = lambda market: True
        engine.active_positions = lambda **kw: []
        engine.kr_execute_exit_watch(requested_seed=1000000)
        order_calls = [c[0] for c in broker.method_calls if c[0] != "get_domestic_fills_today"]
        self.assertEqual(order_calls, [], "the exit watch pre-pass must only query fills")
        return stored(), log, broker

    def test_pending_sell_on_flat_symbol_is_settled(self):
        after, log, _broker = self._watch({"114800.KS": _pending_sell_state(position_qty=0, avg_price=0.0)},
                                          [KIS_SELL])
        self.assertEqual([r["filled_qty"] for r in log.fills("0000012345")], [1262])
        self.assertEqual(after["114800.KS"]["pending_sell_order_no"], "")
        self.assertAlmostEqual(after["114800.KS"]["realized_profit"], (1284.0 - ENTRY) * 1262, places=2)

    def test_pending_buy_is_settled_so_the_stop_loss_is_not_blocked(self):
        state = dict(symbol="003490", market="KS", strategy_id="vrev", position_qty=10, avg_price=30000.0,
                     pending_buy_order_no="778", pending_buy_action="BUY2", pending_buy_qty=18,
                     pending_buy_placed_at="2026-11-10 11:48:58", pending_buy_position_before=10,
                     pending_buy_avg_before=30000.0, orders=[])
        fill = dict(order_no="778", symbol="003490", side="BUY", status="FILLED", filled_qty=18, filled_price=32494.44)
        after, log, _broker = self._watch({"003490.KS": state}, [fill])
        self.assertEqual(after["003490.KS"]["pending_buy_order_no"], "")
        self.assertEqual(after["003490.KS"]["position_qty"], 28)
        self.assertEqual([r["filled_qty"] for r in log.fills("778")], [18])

    def test_still_open_orders_stay_pending(self):
        state = dict(_pending_sell_state(position_qty=0, avg_price=0.0))
        after, log, _broker = self._watch({"114800.KS": state}, [dict(KIS_SELL, status="PARTIAL", filled_qty=1)])
        self.assertEqual(after["114800.KS"]["pending_sell_order_no"], "0000012345")
        self.assertEqual(log.fills("0000012345"), [])

    def test_held_pending_sell_is_left_to_the_positions_loop(self):
        _after, _log, broker = self._watch({"114800.KS": _pending_sell_state(position_qty=1262)}, [KIS_SELL])
        broker.get_domestic_fills_today.assert_not_called()

    def test_zero_quantity_fill_row_is_not_settled(self):
        engine, _stored, log = _engine()
        engine.struct.kis_api.domestic_fills = [dict(KIS_SELL, filled_qty=0, filled_price=0)]
        state = _pending_sell_state()
        self.assertEqual(engine._sync_pending_sell(state, "114800", "KS"), "open")
        self.assertEqual(state["pending_sell_order_no"], "0000012345")
        self.assertEqual(log.fills("0000012345"), [])


if __name__ == "__main__":
    unittest.main()
