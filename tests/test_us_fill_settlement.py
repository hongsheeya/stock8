"""US day-trade fills and the overseas order-history pagination (PAPER 11-11..11-13).

- KIS filled SSO/ENGN/INGM/CLS/SM/WTI, but the US path only updated the state
  file: trade_log kept PENDING rows (verifier: "로컬 기록 0주") and realized
  P&L was never booked, so the daily loss limit could not see US losses.
- Page 2+ of the overseas order history went out without tr_cont "N"; KIS
  answered page 1 again and every strict lookup covering a US day with more
  than 20 orders failed ("주문/체결 연속조회 미완료"): 19 orders unverified.

Offline only: no broker connection, no orders.
"""
import contextlib
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_daytrade_engine_regressions import _engine_with_state
from test_kis_api_buying_power import kis_api, _StructStub as _KisStructStub


class _TradeLog:
    def __init__(self, rows=None):
        self.rows_ = list(rows or [])

    def insert(self, row):
        self.rows_.append(dict(row, created=row.get("created", "2026-11-12 05:40:00")))

    def rows(self, **query):
        return [copy.deepcopy(r) for r in self.rows_ if r.get("order_no") == query.get("order_no")]

    def fills(self, order_no):
        return [r for r in self.rows_ if r.get("order_no") == order_no and r.get("action") not in ("PENDING", "ERROR")]


def _engine(rows, log=None, state_map=None):
    engine, stored = _engine_with_state(state_map or {}, [])
    log = log if log is not None else _TradeLog()
    engine.struct.db = lambda _name: log
    engine._append_runtime_log = lambda *_a, **_k: None
    engine._us_exchange = lambda _symbol: "NASD"
    broker = Mock()
    broker.request_options = lambda **_k: contextlib.nullcontext()
    broker.get_overseas_order_history.return_value = rows
    engine._broker = lambda: broker
    return engine, stored, log, broker


def _sell_state(**extra):
    state = {"symbol": "WTI", "market": "US", "strategy_id": "us_premarket", "position_qty": 137, "avg_price": 2.10,
             "pending_sell_order_no": "0030549547", "pending_sell_qty": 137, "pending_sell_type": "SELL_FULL",
             "pending_sell_placed_at": "2026-11-13 05:40:25", "pending_sell_position_before": 137,
             "pending_sell_entry_avg": 2.10,
             "orders": [{"order_no": "0030549547", "action": "SELL_FULL", "qty": 137, "filled_qty": 0,
                         "timestamp": "2026-11-13 05:40:25"}]}
    state.update(extra)
    return state


SELL_ROW = {"order_no": "30549547", "symbol": "WTI", "side": "SELL", "status": "FILLED",
            "filled_qty": 137, "filled_price": 2.25}


class UsSellSettlementTests(unittest.TestCase):
    def test_filled_sell_writes_one_trade_log_row_and_books_pnl(self):
        engine, _stored, log, _broker = _engine([dict(SELL_ROW)])
        state = _sell_state()
        self.assertEqual(engine._sync_us_pending_order(state, "WTI", "SELL"), "filled")
        fills = log.fills("0030549547")
        self.assertEqual([(r["action"], r["filled_qty"], r["filled_price"]) for r in fills], [("SELL", 137, 2.25)])
        self.assertIn("$", fills[0]["message"])
        expected = (2.25 - 2.10) * 137
        self.assertAlmostEqual(state["realized_profit"], expected, places=4)
        self.assertAlmostEqual(state["daily_realized_profit"], expected, places=4)
        self.assertEqual((state["position_qty"], state["avg_price"]), (0, 0.0))
        self.assertEqual(state["orders"][0]["booked_qty"], 137)
        self.assertNotIn("pending_sell_entry_avg", state)
        # The same evidence again books nothing more and writes no second row.
        engine._mark_state_order_fill(state, "0030549547", dict(SELL_ROW, verification="kis"))
        self.assertAlmostEqual(state["realized_profit"], expected, places=4)

    def test_entry_average_survives_a_balance_sync_that_zeroed_the_position(self):
        engine, _stored, log, _broker = _engine([dict(SELL_ROW)])
        state = _sell_state(position_qty=0, avg_price=0.0)
        engine._sync_us_pending_order(state, "WTI", "SELL")
        self.assertAlmostEqual(state["realized_profit"], (2.25 - 2.10) * 137, places=4)
        self.assertEqual(len(log.fills("0030549547")), 1)

    def test_existing_row_of_this_order_is_not_written_again(self):
        log = _TradeLog([{"order_no": "0030549547", "symbol": "WTI", "action": "SELL", "event_type": "DT_US_SELL_FULL",
                          "filled_qty": 137, "created": "2026-11-13 05:41:00"}])
        engine, _stored, log, _broker = _engine([dict(SELL_ROW)], log=log)
        engine._sync_us_pending_order(_sell_state(), "WTI", "SELL")
        self.assertEqual(len(log.fills("0030549547")), 1)

    def test_same_number_on_another_symbol_or_earlier_day_is_another_order(self):
        """KIS numbers orders per day; a reused number is not a duplicate."""
        log = _TradeLog([
            {"order_no": "0030549547", "symbol": "SSO", "action": "SELL", "event_type": "DT_US_SELL_FULL",
             "filled_qty": 17, "created": "2026-11-13 03:51:00"},
            {"order_no": "0030549547", "symbol": "WTI", "action": "SELL", "event_type": "DT_US_SELL_FULL",
             "filled_qty": 10, "created": "2026-11-05 03:51:00"},
        ])
        engine, _stored, log, _broker = _engine([dict(SELL_ROW)], log=log)
        engine._sync_us_pending_order(_sell_state(), "WTI", "SELL")
        self.assertEqual(len(log.fills("0030549547")), 3)

    def test_open_or_failed_query_books_nothing(self):
        for rows in ([dict(SELL_ROW, status="OPEN", filled_qty=0)], RuntimeError("주문/체결 연속조회 미완료")):
            engine, _stored, log, broker = _engine([])
            if isinstance(rows, Exception):
                broker.get_overseas_order_history.side_effect = rows
            else:
                broker.get_overseas_order_history.return_value = rows
            state = _sell_state()
            self.assertEqual(engine._sync_us_pending_order(state, "WTI", "SELL"), "open")
            self.assertEqual(state["pending_sell_order_no"], "0030549547")
            self.assertEqual(state.get("realized_profit", 0), 0)
            self.assertEqual(log.fills("0030549547"), [])

    def test_cancelled_after_a_partial_fill_books_the_filled_part(self):
        engine, _stored, log, _broker = _engine([dict(SELL_ROW, status="CANCELLED", filled_qty=37)])
        state = _sell_state()
        self.assertEqual(engine._sync_us_pending_order(state, "WTI", "SELL"), "cancelled")
        self.assertEqual(state["position_qty"], 100)
        self.assertEqual([r["filled_qty"] for r in log.fills("0030549547")], [37])

    def test_fill_without_a_price_keeps_the_order_pending(self):
        engine, _stored, log, _broker = _engine([dict(SELL_ROW, filled_price=0)])
        state = _sell_state()
        self.assertEqual(engine._sync_us_pending_order(state, "WTI", "SELL"), "open")
        self.assertEqual(state["pending_sell_order_no"], "0030549547")
        self.assertEqual(log.fills("0030549547"), [])

    def test_latest_row_of_a_reused_order_number_is_used(self):
        older = dict(SELL_ROW, filled_qty=50, filled_price=1.50, order_date="20261105")
        engine, _stored, log, _broker = _engine([older, dict(SELL_ROW, order_date="20261112")])
        state = _sell_state()
        engine._sync_us_pending_order(state, "WTI", "SELL")
        self.assertEqual([(r["filled_qty"], r["filled_price"]) for r in log.fills("0030549547")], [(137, 2.25)])


class UsBuySettlementTests(unittest.TestCase):
    def test_filled_buy_writes_one_row_and_adds_to_a_position_once(self):
        row = {"order_no": "46841", "symbol": "SSO", "side": "BUY", "status": "FILLED",
               "filled_qty": 17, "filled_price": 68.3676}
        engine, _stored, log, _broker = _engine([row])
        state = {"symbol": "SSO", "market": "US", "strategy_id": "us_premarket", "position_qty": 0, "avg_price": 0,
                 "pending_buy_order_no": "0000046841", "pending_buy_action": "BUY1", "pending_buy_qty": 17,
                 "pending_buy_placed_at": "2026-11-13 01:08:14", "pending_buy_position_before": 0,
                 "pending_buy_avg_before": 0.0,
                 "orders": [{"order_no": "0000046841", "action": "BUY1", "qty": 17, "filled_qty": 0}]}
        self.assertEqual(engine._sync_us_pending_order(state, "SSO", "BUY"), "filled")
        self.assertEqual([(r["action"], r["filled_qty"]) for r in log.fills("0000046841")], [("BUY", 17)])
        self.assertEqual(state["position_qty"], 17)
        self.assertEqual(state["pending_buy_order_no"], "")
        synced = dict(state, position_qty=17)  # the balance already holds them
        engine._settle_us_pending_buy(dict(synced, pending_buy_position_before=0), "SSO", "0000046841", row)
        self.assertEqual(len(log.fills("0000046841")), 1)


class UsReconciliationTests(unittest.TestCase):
    def test_reconciliation_settles_on_the_current_state(self):
        state = _sell_state(position_qty=0, avg_price=0.0)
        engine, stored, log, broker = _engine([dict(SELL_ROW)], state_map={"WTI.US": state})
        engine._fs = lambda: SimpleNamespace(write=SimpleNamespace(json=Mock()))
        engine._data_root = lambda: "unused"
        engine.reconcile_order_history()
        after = stored()["WTI.US"]
        self.assertEqual(after["pending_sell_order_no"], "")
        self.assertNotIn("pending_sell_position_before", after)
        self.assertNotIn("pending_sell_entry_avg", after)
        self.assertAlmostEqual(after["realized_profit"], (2.25 - 2.10) * 137, places=4)
        self.assertEqual(after["last_exit_order_no"], "0030549547")
        self.assertEqual(len(log.fills("0030549547")), 1)
        engine.reconcile_order_history()
        broker.get_overseas_order_history.assert_called_once()
        self.assertEqual(len(log.fills("0030549547")), 1)

    def test_failed_query_keeps_the_order_pending(self):
        state = _sell_state()
        engine, stored, log, broker = _engine([], state_map={"WTI.US": state})
        broker.get_overseas_order_history.side_effect = RuntimeError("주문/체결 연속조회 미완료")
        engine._fs = lambda: SimpleNamespace(write=SimpleNamespace(json=Mock()))
        engine._data_root = lambda: "unused"
        engine._us_pending_session_over = lambda *_a: False
        engine.reconcile_order_history()
        self.assertEqual(stored()["WTI.US"]["pending_sell_order_no"], "0030549547")
        self.assertEqual(log.fills("0030549547"), [])


class UsMocSettlementTests(unittest.TestCase):
    def test_filled_moc_books_pnl_into_the_state(self):
        row = {"order_no": "777", "symbol": "WTI", "side": "SELL", "status": "FILLED",
               "filled_qty": 137, "filled_price": 2.25}
        engine, _stored, log, _broker = _engine([row])
        state = {"symbol": "WTI", "market": "US", "strategy_id": "us_premarket", "position_qty": 0, "avg_price": 0.0,
                 "moc_order_no": "777", "moc_qty": 137, "moc_placed_at": "2026-11-13 05:30:00",
                 "moc_entry_avg": 2.10, "orders": [{"order_no": "777", "action": "SELL_MOC", "qty": 137}]}
        self.assertEqual(engine._us_moc_reconcile(state, "WTI"), "filled")
        self.assertAlmostEqual(state["realized_profit"], (2.25 - 2.10) * 137, places=4)
        self.assertNotIn("moc_order_no", state)
        self.assertNotIn("moc_entry_avg", state)
        self.assertEqual([r["filled_qty"] for r in log.fills("777")], [137])


def _ccnl_row(order_no):
    return {"ODNO": order_no, "PDNO": "WTI", "SLL_BUY_DVSN_CD": "01", "ORD_DT": "20261111", "ORD_TMD": "220100",
            "FT_ORD_QTY": "1", "FT_ORD_UNPR3": "2.2", "FT_CCLD_QTY": "1", "FT_CCLD_UNPR3": "2.2",
            "FT_CCLD_AMT3": "2.2", "OVRS_EXCG_CD": "NASD"}


class OverseasHistoryPaginationTests(unittest.TestCase):
    def _api(self, pages):
        api = kis_api.KisApi(_KisStructStub())
        api.get_overseas_reservation_orders = lambda **_k: []
        calls = []

        def _request(_method, _path, _tr_id, params=None, **kwargs):
            calls.append(((params or {}).get("CTX_AREA_NK200", ""), kwargs.get("tr_cont", "")))
            return pages(params or {}, kwargs.get("tr_cont", ""))

        api._request = _request
        return api, calls

    def test_page_two_is_requested_with_tr_cont_n(self):
        def pages(params, tr_cont):
            if not params.get("CTX_AREA_NK200"):
                return {"rt_cd": "0", "tr_cont": "M", "ctx_area_nk200": "NK2", "ctx_area_fk200": "FK2",
                        "output1": [_ccnl_row(f"A{i:02d}") for i in range(20)]}
            self.assertEqual(tr_cont, "N")
            return {"rt_cd": "0", "tr_cont": "D", "output1": [_ccnl_row("A20")]}

        api, calls = self._api(pages)
        orders = api.get_overseas_order_history(start_date="20261111", end_date="20261113", exchanges=["NASD"],
                                                strict=True)
        self.assertEqual(len(orders), 21)
        self.assertEqual(calls[:2], [("", ""), ("NK2", "N")])

    def test_strict_lookup_fails_when_kis_repeats_the_cursor(self):
        def pages(params, tr_cont):
            return {"rt_cd": "0", "tr_cont": "M", "ctx_area_nk200": "NK2", "ctx_area_fk200": "FK2",
                    "output1": [_ccnl_row(f"A{i:02d}") for i in range(20)]}

        api, calls = self._api(pages)
        with self.assertRaisesRegex(RuntimeError, "연속조회 미완료"):
            api.get_overseas_order_history(start_date="20261111", exchanges=["NASD"], strict=True)
        self.assertLessEqual(len(calls), 3)

    def test_non_strict_lookup_returns_what_it_read_and_warns(self):
        def pages(params, tr_cont):
            return {"rt_cd": "0", "tr_cont": "M", "ctx_area_nk200": "NK2", "ctx_area_fk200": "FK2",
                    "output1": [_ccnl_row(f"A{i:02d}") for i in range(20)]}

        api, _calls = self._api(pages)
        api._log = Mock()
        orders = api.get_overseas_order_history(start_date="20261111", exchanges=["NASD"])
        self.assertEqual(len(orders), 20)
        self.assertTrue(any("연속조회 미완료" in str(c.args) for c in api._log.call_args_list))

    def test_reads_beyond_ten_pages(self):
        def pages(params, tr_cont):
            page = int((params.get("CTX_AREA_NK200") or "NK0")[2:])
            last = page == 11
            return {"rt_cd": "0", "tr_cont": "D" if last else "M",
                    "ctx_area_nk200": "" if last else f"NK{page + 1}", "ctx_area_fk200": "" if last else f"FK{page + 1}",
                    "output1": [_ccnl_row(f"P{page:02d}-{i:02d}") for i in range(20 if not last else 3)]}

        api, calls = self._api(pages)
        orders = api.get_overseas_order_history(start_date="20261111", exchanges=["NASD"], strict=True)
        self.assertEqual(len(calls), 12)
        self.assertEqual(len(orders), 11 * 20 + 3)


if __name__ == "__main__":
    unittest.main()
