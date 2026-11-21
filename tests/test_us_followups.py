"""Follow-ups of the US fill settlement (PR #40).

- The trade verifier summed every trade_log/cycle_trade row of an order
  number; KIS numbers orders per day, so a row of another symbol, side or
  day inflated the local quantity (FAIL, buys held).
- A LIVE US market-on-close sell counted the position from moc_qty alone, so
  shares bought after the MOC was placed were booked as 0.

Offline only: no broker connection, no orders.
"""
import contextlib
import unittest
from unittest.mock import Mock

from test_daytrade_engine_regressions import _engine_with_state
from test_trade_verifier import tv


class _Rows:
    def __init__(self, rows, key):
        self.rows_, self.key = rows, key

    def rows(self, **query):
        return [dict(r) for r in self.rows_ if r.get(self.key) == query.get(self.key)]


TRADE_LOG = [
    {"id": "t1", "order_no": "0030549547", "symbol": "WTI", "action": "SELL", "event_type": "DT_US_SELL_FULL",
     "filled_qty": 137, "created": "2026-11-13 05:41:00"},
    {"id": "t2", "order_no": "0030549547", "symbol": "SSO", "action": "SELL", "event_type": "DT_US_SELL_FULL",
     "filled_qty": 17, "created": "2026-11-13 03:51:00"},
    {"id": "t3", "order_no": "0030549547", "symbol": "WTI", "action": "SELL", "event_type": "DT_US_SELL_FULL",
     "filled_qty": 10, "created": "2026-11-05 03:51:00"},
    {"id": "t4", "order_no": "0030549547", "symbol": "WTI", "action": "BUY", "event_type": "DT_US_BUY1",
     "filled_qty": 5, "created": "2026-11-13 04:04:00"},
    {"id": "t5", "order_no": "0030549547", "symbol": "WTI", "action": "PENDING", "event_type": "DT_US_SELL_FULL_PENDING",
     "filled_qty": 0, "created": "2026-11-13 05:40:25"},
]


class VerifierLocalScopeTests(unittest.TestCase):
    def test_only_this_orders_symbol_side_and_day_are_counted(self):
        read = tv.local_filled_reader(_Rows(TRADE_LOG, "order_no"), _Rows([], "broker_order_no"))
        self.assertEqual(read("0030549547", symbol="WTI", side="SELL", since="2026-11-13"), 137)

    def test_unscoped_call_keeps_the_old_sum(self):
        read = tv.local_filled_reader(_Rows(TRADE_LOG, "order_no"), _Rows([], "broker_order_no"))
        self.assertEqual(read("0030549547"), 137 + 17 + 10 + 5)

    def test_cycle_trade_dates_are_us_session_dates(self):
        cycle = [
            {"id": "c1", "broker_order_no": "777", "symbol": "SOXL", "action": "SELL", "filled_qty": 11,
             "trade_date": "2026-11-12"},  # KST 11-13 order, US 11-12 session
            {"id": "c2", "broker_order_no": "777", "symbol": "SOXL", "action": "SELL", "filled_qty": 9,
             "trade_date": "2026-11-03"},
        ]
        read = tv.local_filled_reader(_Rows([], "order_no"), _Rows(cycle, "broker_order_no"))
        self.assertEqual(read("777", symbol="SOXL", side="SELL", since="2026-11-13"), 11)

    def test_rows_without_symbol_or_date_still_count(self):
        rows = [{"id": "x", "order_no": "9", "action": "SELL", "event_type": "DT_KS_SELL_FULL", "filled_qty": 4}]
        read = tv.local_filled_reader(_Rows(rows, "order_no"), None)
        self.assertEqual(read("9", symbol="114800", side="SELL", since="2026-11-13"), 4)

    def test_verifier_passes_the_order_scope(self):
        local = Mock(return_value=137)
        verifier = tv.Verifier.__new__(tv.Verifier)
        verifier.local = local
        verifier.broker = Mock(orders=lambda *_a: [])
        record = {"order_no": "0030549547", "symbol": "WTI", "side": "SELL", "market": "US",
                  "at": "2026-11-13 05:40:25", "ts": 0}
        result = verifier._lookup(record, {}, {})
        local.assert_called_with("0030549547", symbol="WTI", side="SELL", since="2026-11-13")
        self.assertEqual(result["local"], 137)


class UsMocLaterBuyTests(unittest.TestCase):
    def test_shares_bought_after_the_moc_stay_on_the_books(self):
        engine, _ = _engine_with_state({}, [])
        logged = []
        engine.struct.db = lambda _name: Mock(rows=lambda **_q: [], insert=logged.append)
        engine._append_runtime_log = lambda *_a, **_k: None
        engine._us_exchange = lambda _symbol: "NASD"
        broker = Mock()
        broker.request_options = lambda **_k: contextlib.nullcontext()
        broker.get_overseas_order_history.return_value = [
            {"order_no": "777", "symbol": "WTI", "side": "SELL", "status": "FILLED", "filled_qty": 137,
             "filled_price": 2.25}]
        engine._broker = lambda: broker
        state = {"symbol": "WTI", "market": "US", "strategy_id": "us_premarket", "position_qty": 157,
                 "avg_price": 2.12, "buy1_used": True, "buy2_used": True,
                 "moc_order_no": "777", "moc_qty": 137, "moc_placed_at": "2026-11-13 05:30:00", "moc_entry_avg": 2.10,
                 "orders": [{"order_no": "777", "action": "SELL_MOC", "qty": 137, "timestamp": "2026-11-13 05:30:00"},
                            {"order_no": "778", "action": "BUY2", "qty": 20, "filled_qty": 20,
                             "timestamp": "2026-11-13 05:35:00"}]}
        self.assertEqual(engine._us_moc_reconcile(state, "WTI"), "filled")
        self.assertEqual(state["position_qty"], 20)
        self.assertTrue(state["buy2_used"])
        self.assertAlmostEqual(state["realized_profit"], (2.25 - 2.10) * 137, places=4)
        self.assertEqual([r["filled_qty"] for r in logged], [137])

    def test_a_repeated_buy_record_counts_once(self):
        engine, _ = _engine_with_state({}, [])
        engine.struct.db = lambda _name: Mock(rows=lambda **_q: [], insert=lambda _row: None)
        engine._append_runtime_log = lambda *_a, **_k: None
        engine._us_exchange = lambda _symbol: "NASD"
        broker = Mock()
        broker.request_options = lambda **_k: contextlib.nullcontext()
        broker.get_overseas_order_history.return_value = [
            {"order_no": "777", "symbol": "WTI", "side": "SELL", "status": "FILLED", "filled_qty": 137,
             "filled_price": 2.25}]
        engine._broker = lambda: broker
        buy = {"order_no": "778", "action": "BUY2", "qty": 20, "filled_qty": 20, "timestamp": "2026-11-13 05:35:00"}
        state = {"symbol": "WTI", "market": "US", "position_qty": 177, "avg_price": 2.12,
                 "moc_order_no": "777", "moc_qty": 137, "moc_placed_at": "2026-11-13 05:30:00", "moc_entry_avg": 2.10,
                 "orders": [{"order_no": "777", "action": "SELL_MOC", "qty": 137}, dict(buy), dict(buy)]}
        engine._us_moc_reconcile(state, "WTI")
        self.assertEqual(state["position_qty"], 20)


if __name__ == "__main__":
    unittest.main()
