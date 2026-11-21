"""11-21 LIVE SOXL: the cycle showed 112 shares @ $117.61 while the broker held
165 @ $84.82. The running FireGate portfolio still named a cycle ID from a
rebuilt DB, so

- the pull wrote that portfolio's numbers over the new cycle by symbol alone,
  and the 5-minute T sync turned a PENDING_EXTENSION back to ACTIVE;
- an incomplete ledger ([SELL 20, SELL 11, BUY 20]) closed cycle #1 at 0
  shares while the broker held 134, and the next fill opened cycle #2;
- the reverse MOC sold a tenth of FireGate's 112 although 165 were held;
- a FireGate read error fell back to the local v4 lines (11-18 sells).

Each guard does less when the two sides disagree; none sends, cancels or
re-sends an order."""
import datetime
import importlib.util
import json
import pathlib
import unittest

import test_infinitebuy_loc_schedule_regressions as base
import test_firegate_reverse_mode as rev

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "firegate_bridge_cycle_guards", ROOT / "src/portal/trading/model/struct/firegate_bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
Engine = base.engine_module.Engine
CONFIGURED = json.dumps({"enabled": True, "email": "user@example.test"})


class _Db:
    def __init__(self, rows=None):
        self.rows_data = [dict(row) for row in (rows or [])]

    def get(self, **kwargs):
        for row in self.rows_data:
            if all(row.get(key) == value for key, value in kwargs.items()):
                return row
        return None

    def rows(self, **kwargs):
        data = [dict(row) for row in self.rows_data]
        for key, value in kwargs.items():
            if key in ("orderby", "order", "dump", "page"):
                continue
            data = [row for row in data if row.get(key) == value]
        if kwargs.get("orderby"):
            data.sort(key=lambda row: row.get(kwargs["orderby"]),
                      reverse=str(kwargs.get("order", "ASC")).upper() == "DESC")
        if kwargs.get("dump"):
            data = data[:int(kwargs["dump"])]
        return data

    def update(self, data, id=None):
        for row in self.rows_data:
            if row.get("id") == id:
                row.update(dict(data))
                return
        raise AssertionError(f"missing row id={id}")

    def insert(self, data):
        payload = dict(data)
        payload.setdefault("id", f"new-{len(self.rows_data) + 1}")
        self.rows_data.append(payload)
        return payload

    def delete(self, id=None):
        self.rows_data = [row for row in self.rows_data if row.get("id") != id]


class _Engine:
    def __init__(self):
        self.events = []

    def _log_event(self, symbol, cycle_id, event_type, action="", message="", **_kw):
        self.events.append((symbol, cycle_id, event_type, message))


class _Struct:
    def __init__(self, cycles):
        self.dbs = {"etf_watchlist": _Db([{"id": "wl", "symbol": "SOXL"}]), "trading_cycle": _Db(cycles)}
        self.engine = _Engine()

    def db(self, name):
        return self.dbs[name]


# FireGate portfolio 1780022179464 on 11-21 (Cycle 1, linked to a pre-rebuild cycle ID)
PORTFOLIO = {"id": 1780022179464, "ticker": "SOXL", "source": "infinitystock", "sourceCycleId": "old-cycle",
             "portfolioGroup": "InfinityStock Auto", "category": "infinite_buy", "seed": 15000, "divisionDate": 20,
             "targetProfit": 20, "isRunning": True, "holdingQty": 112, "avgPrice": 117.61, "totalBuy": 13166.36,
             "totalSell": 0, "tValue": 19.62, "startDate": "2026-06-26", "endDate": "2026-10-27"}
CYCLE_2 = {"id": "cy-2", "symbol": "SOXL", "status": "ACTIVE", "cycle_number": 2, "current_round": 2, "t_value": 2,
           "total_qty": 165, "avg_price": 84.8162, "total_spent": 13994.67, "total_investment": 15000,
           "current_price": 33.37, "completed_at": None, "created": 2}


def _pull(cycles, portfolio):
    struct = _Struct(cycles)

    class _Remote:
        def list_portfolios(self):
            return [dict(portfolio)]

        def list_transactions(self, portfolio_id):
            return []

    original = bridge._bridge_call_from_config
    bridge._bridge_call_from_config = lambda _struct, fn: fn(_Remote(), {"enabled": True})
    try:
        result = bridge.sync_portfolios_to_local(struct)
    finally:
        bridge._bridge_call_from_config = original
    return struct, result


class FireGatePullGuardTests(unittest.TestCase):
    def test_link_mismatch_leaves_the_cycle_untouched(self):
        struct, result = _pull([CYCLE_2], PORTFOLIO)
        cycle = struct.db("trading_cycle").get(id="cy-2")
        for key in ("total_qty", "avg_price", "total_spent", "current_round", "t_value", "status", "completed_at"):
            self.assertEqual(cycle[key], CYCLE_2[key], key)
        self.assertEqual(result["cycles_updated"], 0)
        self.assertEqual(result["cycles_skipped"][0]["reason"], "link_mismatch")
        self.assertEqual([e[2] for e in struct.engine.events], ["FIREGATE_LINK_MISMATCH"])
        self.assertIn("old-cycle", struct.engine.events[0][3])

    def test_matching_or_empty_link_still_applies_firegate(self):
        for link in ("cy-2", ""):
            with self.subTest(link=link):
                struct, result = _pull([CYCLE_2], {**PORTFOLIO, "sourceCycleId": link})
                cycle = struct.db("trading_cycle").get(id="cy-2")
                self.assertEqual((cycle["total_qty"], cycle["avg_price"], cycle["current_round"]), (112, 117.61, 19))
                self.assertEqual(result["cycles_updated"], 1)
                self.assertEqual(struct.engine.events, [])

    def test_running_portfolio_does_not_undo_pause_or_holding(self):
        for status in ("PAUSED", "HOLDING"):
            with self.subTest(status=status):
                struct, _ = _pull([{**CYCLE_2, "status": status}], {**PORTFOLIO, "sourceCycleId": "cy-2"})
                cycle = struct.db("trading_cycle").get(id="cy-2")
                self.assertEqual(cycle["status"], status)
                self.assertEqual(cycle["total_qty"], 112)  # the values still follow FireGate

    def test_stopped_portfolio_still_pauses_an_active_cycle(self):
        struct, _ = _pull([CYCLE_2], {**PORTFOLIO, "sourceCycleId": "cy-2", "isRunning": False})
        self.assertEqual(struct.db("trading_cycle").get(id="cy-2")["status"], "PAUSED")

    def test_running_cycle_gets_no_end_date(self):
        struct, _ = _pull([CYCLE_2], {**PORTFOLIO, "sourceCycleId": "cy-2"})
        cycle = struct.db("trading_cycle").get(id="cy-2")
        self.assertEqual(cycle["status"], "ACTIVE")
        self.assertIsNone(cycle["completed_at"])

    def test_completed_cycle_is_not_reopened_or_duplicated(self):
        done = {"id": "cy-1", "symbol": "SOXL", "status": "COMPLETED", "cycle_number": 1, "total_qty": 0,
                "avg_price": 0.0, "total_spent": 977.64, "current_round": 19, "created": 1}
        for link in ("", "cy-1", "old-cycle"):
            with self.subTest(link=link):
                struct, result = _pull([done], {**PORTFOLIO, "sourceCycleId": link})
                rows = struct.db("trading_cycle").rows_data
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]["status"], rows[0]["total_qty"]), ("COMPLETED", 0))
                self.assertEqual(result["cycles_created"] + result["cycles_updated"], 0)

    def test_empty_symbol_history_still_creates_the_cycle(self):
        struct, result = _pull([], {**PORTFOLIO, "sourceCycleId": ""})
        self.assertEqual(result["cycles_created"], 1)
        self.assertEqual(struct.db("trading_cycle").rows_data[0]["total_qty"], 112)


def _engine(cycles, configs=None, holdings=None):
    engine, kis, logs = base.InfiniteBuyLocScheduleRegressionTests._engine(
        None,
        buying_power_info={"executable_amount": 100000, "executable_qty": 1000, "broker_amount": 100000,
                           "broker_qty": 1000, "orderable_amount": 100000},
        reservation_orders=[],
        watchlist_rows=[{"id": "w1", "symbol": "SOXL", "exchange": "AMEX", "is_active": True}],
        cycle_rows=cycles, configs=configs or {}, holdings=holdings)
    return engine, kis, logs


SOXL_LOCAL = {"id": "c1", "symbol": "SOXL", "status": "ACTIVE", "total_qty": 90, "avg_price": 124.94,
              "total_spent": 11244.6, "target_profit": 20.0, "total_commission": 0.0, "current_round": 15,
              "t_value": 15.98, "division_count": 20, "total_investment": 15000.0, "remaining_investment": 3755.4}


class StrategyMetadataGuardTests(unittest.TestCase):
    def test_link_mismatch_keeps_pending_extension(self):
        engine, _kis, logs = _engine([{**SOXL_LOCAL, "status": "PENDING_EXTENSION", "current_round": 20, "t_value": 20}],
                                     configs={"fire_gate_bridge": CONFIGURED})
        engine._load_firegate_authoritative_states = lambda symbol_filter="": {"states": {"SOXL": {
            "current_round": 19, "t_value": 19.62, "division_count": 20, "status": "ACTIVE",
            "_firegate_source_cycle_id": "old-cycle", "_firegate_portfolio_id": "1780022179464"}}, "error": ""}
        engine.sync_firegate_strategy_metadata()
        cycle = engine._cycle_db().get(id="c1")
        self.assertEqual((cycle["status"], cycle["current_round"], cycle["t_value"]), ("PENDING_EXTENSION", 20, 20))
        self.assertEqual([log["event_type"] for log in logs], ["FIREGATE_LINK_MISMATCH"])

    def test_matching_link_still_restores_t(self):
        engine, _kis, logs = _engine([{**SOXL_LOCAL, "status": "PENDING_EXTENSION"}], configs={"fire_gate_bridge": CONFIGURED})
        engine._load_firegate_authoritative_states = lambda symbol_filter="": {"states": {"SOXL": {
            "current_round": 15, "t_value": 15.98, "division_count": 20, "status": "ACTIVE",
            "_firegate_source_cycle_id": "c1"}}, "error": ""}
        engine.sync_firegate_strategy_metadata()
        self.assertEqual(engine._cycle_db().get(id="c1")["status"], "ACTIVE")
        self.assertEqual(logs, [])


class ReservationLinkGuardTests(unittest.TestCase):
    def test_link_mismatch_blocks_reverse_reservations(self):
        engine, kis, logs = _engine([SOXL_LOCAL])
        engine.calculate_buy_decision = Engine.calculate_buy_decision.__get__(engine, engine.__class__)
        engine._load_firegate_authoritative_states = lambda symbol_filter="": {"states": {"SOXL": {
            **rev.SOXL, "_firegate_reverse_state": "ACTIVE", "_firegate_source_cycle_id": "old-cycle"}}, "error": ""}
        sells = engine.schedule_loc_sells(symbol_filter="SOXL")
        engine.schedule_loc_buys(symbol_filter="SOXL")
        self.assertEqual(kis.sell_reservation_calls, [])
        self.assertEqual(kis.buy_calls, [])
        self.assertTrue(any("연결 대상" in str(item.get("reason", "")) for item in sells.get("errors", [])))
        self.assertIn("LOC_SELL_FIREGATE_AUTHORITY_BLOCKED", [log["event_type"] for log in logs])

    def test_link_mismatch_blocks_the_reverse_moc(self):
        kis = rev._Kis(datetime.datetime(2026, 10, 29, 10, 0))
        engine, struct = rev.ReverseMocTests.engine(None, kis)
        engine._load_firegate_authoritative_states = lambda symbol_filter="": {"states": {"SOXL": {
            **rev.SOXL, "_firegate_reverse_state": "NORMAL", "_firegate_source_cycle_id": "old-cycle"}}, "error": ""}
        engine.run_firegate_reverse_moc()
        self.assertEqual(kis.sells, [])
        self.assertNotIn("firegate_reverse_moc:SOXL", struct.configs)


class IncompleteLedgerTests(unittest.TestCase):
    def ledger(self, trades, cycle):
        engine, _kis, logs = _engine([cycle])
        engine.struct._db["cycle_trade"] = base._FakeDB(trades)
        return engine, logs

    def test_more_sold_than_bought_keeps_the_cycle(self):
        # cycle #1 on 11-17: the 112-share history was never in this ledger
        cycle = {**SOXL_LOCAL, "status": "PENDING_EXTENSION", "current_round": 20, "total_qty": 132,
                 "total_spent": 14149.96, "avg_price": 107.1967}
        trades = [
            {"id": "s1", "cycle_id": "c1", "action": "SELL", "status": "FILLED", "filled_qty": 20, "filled_price": 66.03,
             "trade_date": "2026-11-11", "created": "2026-11-11 23:23:28", "total_qty_after": 92},
            {"id": "s2", "cycle_id": "c1", "action": "SELL", "status": "FILLED", "filled_qty": 11, "filled_price": 65.53,
             "trade_date": "2026-11-12", "created": "2026-11-12 00:24:25", "total_qty_after": 101},
            {"id": "b1", "cycle_id": "c1", "action": "BUY", "status": "FILLED", "filled_qty": 20, "filled_price": 48.76,
             "commission": 2.44, "trade_date": "2026-11-16", "created": "2026-11-16 03:16:25", "total_qty_after": 132},
        ]
        engine, logs = self.ledger(trades, cycle)
        result = engine._recalculate_cycle_from_trades("c1")
        stored = engine._cycle_db().get(id="c1")
        self.assertEqual((stored["status"], stored["total_qty"], stored["total_spent"]), ("PENDING_EXTENSION", 132, 14149.96))
        self.assertEqual(result.get("reason"), "ledger_incomplete")
        self.assertEqual([row["total_qty_after"] for row in engine._trade_db().rows()], [92, 101, 132])
        self.assertEqual([log["event_type"] for log in logs], ["CYCLE_LEDGER_INCOMPLETE"])

    def test_fully_sold_cycle_still_completes(self):
        trades = [
            {"id": "b1", "cycle_id": "c1", "action": "BUY", "status": "FILLED", "filled_qty": 10, "filled_price": 100,
             "trade_date": "2026-11-16", "created": "1"},
            {"id": "s1", "cycle_id": "c1", "action": "SELL", "status": "FILLED", "filled_qty": 10, "filled_price": 120,
             "trade_date": "2026-11-17", "created": "2"},
        ]
        engine, logs = self.ledger(trades, dict(SOXL_LOCAL))
        result = engine._recalculate_cycle_from_trades("c1")
        self.assertTrue(result["recalculated"])
        self.assertEqual(engine._cycle_db().get(id="c1")["status"], "COMPLETED")
        self.assertEqual(engine._cycle_db().get(id="c1")["total_qty"], 0)
        self.assertEqual(logs, [])


class ReverseMocHoldingGuardTests(unittest.TestCase):
    def at(self):
        return datetime.datetime(2026, 10, 29, 10, 0)

    def test_more_held_than_firegate_holds_the_moc(self):
        kis = rev._Kis(self.at(), held=100)  # FireGate 90
        engine, struct = rev.ReverseMocTests.engine(None, kis)
        logs = []
        engine._log_event = lambda *a, **k: logs.append((a, k))
        engine.run_firegate_reverse_moc()
        self.assertEqual(kis.sells, [])
        self.assertNotIn("firegate_reverse_moc:SOXL", struct.configs)
        self.assertTrue(any(a[2] == "REVERSE_MOC_SKIPPED" for a, _k in logs))

    def test_balance_error_holds_the_moc_without_a_marker(self):
        kis = rev._Kis(self.at())

        def broken(exchange=None):
            raise RuntimeError("KIS 잔고 조회 실패")
        kis.get_balance = broken
        engine, struct = rev.ReverseMocTests.engine(None, kis)
        engine.run_firegate_reverse_moc()
        self.assertEqual(kis.sells, [])
        self.assertNotIn("firegate_reverse_moc:SOXL", struct.configs)

    def test_equal_holdings_still_send_once(self):
        kis = rev._Kis(self.at(), held=90)
        engine, _struct = rev.ReverseMocTests.engine(None, kis)
        engine.run_firegate_reverse_moc()
        self.assertEqual(kis.sells, [("SOXL", 9, "MOC")])


class FireGateLoadErrorTests(unittest.TestCase):
    def engine(self, configs):
        engine, kis, logs = _engine([SOXL_LOCAL], configs=configs)
        engine._load_firegate_authoritative_states = lambda symbol_filter="": {
            "states": {}, "error": "FireGate request failed: 503"}
        return engine, kis, logs

    def test_configured_bridge_read_error_blocks_the_symbol(self):
        engine, kis, logs = self.engine({"fire_gate_bridge": CONFIGURED})
        self.assertEqual(engine._firegate_reverse_states()["error"], "FireGate request failed: 503")
        buys = engine.schedule_loc_buys(symbol_filter="SOXL")
        sells = engine.schedule_loc_sells(symbol_filter="SOXL")
        self.assertEqual(kis.buy_calls, [])
        self.assertEqual(kis.sell_reservation_calls, [])
        self.assertEqual([e["label"] for e in buys["errors"]], ["FIREGATE"])
        self.assertEqual([e["label"] for e in sells["errors"]], ["FIREGATE"])
        events = [log["event_type"] for log in logs]
        self.assertIn("LOC_BUY_FIREGATE_AUTHORITY_BLOCKED", events)
        self.assertIn("LOC_SELL_FIREGATE_AUTHORITY_BLOCKED", events)

    def test_unused_bridge_keeps_the_local_plan(self):
        for configs in ({}, {"fire_gate_bridge": json.dumps({"enabled": False})}):
            with self.subTest(configs=configs):
                engine, kis, _logs = self.engine(configs)
                self.assertEqual(engine._firegate_reverse_states(), {"states": {}, "error": ""})
                engine.schedule_loc_buys(symbol_filter="SOXL")
                engine.schedule_loc_sells(symbol_filter="SOXL")
                self.assertTrue(kis.buy_calls)
                self.assertTrue(kis.sell_reservation_calls)



SOXL_SELL_RESERVATION = {"side": "SELL", "symbol": "SOXL", "exchange": "AMEX", "qty": 38, "filled_qty": 0, "price": 71.44,
                         "order_no": "0030439584", "cancel_yn": "N", "status_name": "접수", "trade_status_name": "정상",
                         "reject_reason": ""}
TQQQ_LOCAL = {**SOXL_LOCAL, "id": "c2", "symbol": "TQQQ", "total_qty": 30, "avg_price": 60.0, "total_spent": 1800.0,
              "current_round": 3, "t_value": 3, "total_investment": 10000.0, "remaining_investment": 8200.0}
MISMATCHED = {"states": {"SOXL": {**rev.SOXL, "_firegate_reverse_state": "NORMAL",
                                  "_firegate_source_cycle_id": "old-cycle"}}, "error": ""}


class RebuildFireGateGuardTests(unittest.TestCase):
    """The manual re-verify / per-symbol retry cancels first and schedules
    after; a FireGate-blocked symbol lost every reservation and got none."""

    def engine(self, state, configs=None):
        engine, kis, logs = _engine([SOXL_LOCAL], configs=configs)
        kis.reservation_orders = [dict(SOXL_SELL_RESERVATION)]
        engine._load_firegate_authoritative_states = lambda symbol_filter="": state
        return engine, kis, logs

    def rebuild(self, engine, symbols):
        from unittest.mock import patch
        with patch.object(base.engine_module.time, "sleep", lambda *_a: None):
            return engine.rebuild_loc_reservations(symbols)

    def test_link_mismatch_cancels_nothing(self):
        engine, kis, logs = self.engine(MISMATCHED)
        result = self.rebuild(engine, ["SOXL"])
        self.assertEqual(kis.cancel_reservation_calls, [])
        self.assertEqual(result["status"], "firegate_blocked")
        self.assertEqual([item["symbol"] for item in result["firegate_blocked"]], ["SOXL"])
        self.assertEqual((kis.buy_calls, kis.sell_reservation_calls), ([], []))
        self.assertIn("LOC_REBUILD_FIREGATE_BLOCKED", [log["event_type"] for log in logs])

    def test_configured_bridge_read_error_cancels_nothing(self):
        engine, kis, _logs = self.engine({"states": {}, "error": "FireGate request failed: 503"},
                                         configs={"fire_gate_bridge": CONFIGURED})
        result = self.rebuild(engine, ["SOXL"])
        self.assertEqual(kis.cancel_reservation_calls, [])
        self.assertEqual(result["status"], "firegate_blocked")

    def test_only_the_blocked_symbol_is_left_alone(self):
        engine, _kis, _logs = _engine([SOXL_LOCAL, TQQQ_LOCAL])
        engine._load_firegate_authoritative_states = lambda symbol_filter="": MISMATCHED
        cancelled_for = []

        def cancel(symbols=None, **_kw):
            cancelled_for.append(list(symbols or []))
            return {"status": "error", "cancelled_count": 0, "error_count": 1, "errors": [{"reason": "stop here"}]}
        engine.cancel_active_loc_reservations = cancel
        result = self.rebuild(engine, ["SOXL", "TQQQ"])
        self.assertEqual(cancelled_for, [["TQQQ"]])
        self.assertEqual([item["symbol"] for item in result["firegate_blocked"]], ["SOXL"])


class RunningLedgerTests(unittest.TestCase):
    """Later buys can bring an oversold ledger back to 0 or above; the
    history is still missing the buys that built the position."""

    def trades(self, last_buy):
        rows = [("s1", "SELL", 20, 66.03, "2026-11-11"), ("s2", "SELL", 11, 65.53, "2026-11-12"),
                ("b1", "BUY", 20, 48.76, "2026-11-16"), ("b2", "BUY", last_buy, 33.02, "2026-11-20")]
        return [{"id": rid, "cycle_id": "c1", "action": action, "status": "FILLED", "filled_qty": qty,
                 "filled_price": price, "trade_date": day, "created": f"{day} 01:00:00", "total_qty_after": -1}
                for rid, action, qty, price, day in rows]

    def check(self, last_buy):
        cycle = {**SOXL_LOCAL, "status": "ACTIVE", "total_qty": 165, "total_spent": 13994.67, "avg_price": 84.8162}
        engine, _kis, logs = _engine([cycle])
        engine.struct._db["cycle_trade"] = base._FakeDB(self.trades(last_buy))
        result = engine._recalculate_cycle_from_trades("c1")
        stored = engine._cycle_db().get(id="c1")
        self.assertEqual((stored["status"], stored["total_qty"], stored["total_spent"]), ("ACTIVE", 165, 13994.67))
        self.assertEqual(result.get("reason"), "ledger_incomplete")
        self.assertEqual(result.get("oversold_qty"), 31)
        self.assertEqual({row["total_qty_after"] for row in engine._trade_db().rows()}, {-1})
        self.assertEqual([log["event_type"] for log in logs], ["CYCLE_LEDGER_INCOMPLETE"])

    def test_sum_back_to_zero_does_not_complete(self):
        self.check(11)  # 20 + 11 sold, 20 + 11 bought

    def test_sum_above_zero_does_not_overwrite(self):
        self.check(12)  # would have written 1 share

    def test_verified_anchor_clears_the_earlier_oversell(self):
        cycle = {**SOXL_LOCAL, "status": "ACTIVE", "total_qty": 0}
        engine, _kis, logs = _engine([cycle], configs={
            "cycle_bookkeeping_anchor:c1": json.dumps({"verified": True, "trade_id": "b1", "qty_before": 134,
                                                       "avg_before": 100.0})})
        engine.struct._db["cycle_trade"] = base._FakeDB(self.trades(11))
        result = engine._recalculate_cycle_from_trades("c1")
        self.assertTrue(result["recalculated"])
        self.assertEqual(engine._cycle_db().get(id="c1")["total_qty"], 165)
        self.assertEqual(logs, [])


class ReverseMocMismatchLogTests(unittest.TestCase):
    def test_link_mismatch_says_why_the_moc_is_held(self):
        kis = rev._Kis(datetime.datetime(2026, 10, 29, 10, 0))
        engine, _struct = rev.ReverseMocTests.engine(None, kis)
        engine._load_firegate_authoritative_states = lambda symbol_filter="": MISMATCHED
        logs = []
        engine._log_event = lambda *a, **k: logs.append((a, k))
        result = engine.run_firegate_reverse_moc()
        self.assertEqual(kis.sells, [])
        self.assertEqual([a[2] for a, _k in logs], ["FIREGATE_LINK_MISMATCH"])
        self.assertIn("연결 대상", result["message"])
        engine.__dict__["_reverse_moc_state"]["checked_at"] = 0
        engine.run_firegate_reverse_moc()
        self.assertEqual(logs[0][1]["message"], logs[1][1]["message"])  # folds into one row a day


class LoadErrorMessageTests(unittest.TestCase):
    def test_error_text_is_short_and_stable(self):
        engine, _kis, _logs = _engine([SOXL_LOCAL], configs={"fire_gate_bridge": CONFIGURED})
        messages = []
        for code, ts in (("503", "1795141137"), ("502", "1795141437")):
            error = (f"FireGate request failed: {code} at https://firestore.example.test/v1/projects/x?t={ts} "
                     + "detail " * 60)
            _cycle, message = engine._cycle_with_firegate_authority(SOXL_LOCAL, {}, load_error=error)
            messages.append(message)
        self.assertEqual(messages[0], messages[1])
        self.assertNotIn("https://", messages[0])
        detail = messages[0].split("차단했습니다: ", 1)[1]
        self.assertNotRegex(detail, r"\d")
        self.assertLessEqual(len(detail), 120)


class LoadErrorScopeTests(unittest.TestCase):
    def engine(self, memos):
        engine, kis, _logs = _engine([SOXL_LOCAL, TQQQ_LOCAL], configs={"fire_gate_bridge": CONFIGURED})
        engine.struct._db["etf_watchlist"] = base._FakeDB([
            {"id": "w1", "symbol": "SOXL", "exchange": "AMEX", "is_active": True, "memo": memos[0]},
            {"id": "w2", "symbol": "TQQQ", "exchange": "NASD", "is_active": True, "memo": memos[1]}])
        engine._load_firegate_authoritative_states = lambda symbol_filter="": {
            "states": {}, "error": "FireGate request failed: 503"}
        return engine, kis

    def test_only_firegate_linked_symbols_are_blocked(self):
        engine, kis = self.engine(("FireGate portfolio 1780022179464", ""))
        engine.schedule_loc_buys()
        self.assertEqual([call["symbol"] for call in kis.buy_calls], ["TQQQ"])

    def test_unknown_linkage_blocks_everything(self):
        engine, kis = self.engine(("", ""))
        engine.schedule_loc_buys()
        self.assertEqual(kis.buy_calls, [])


class PullCompletedCycleTests(unittest.TestCase):
    DONE = {"id": "cy-1", "symbol": "SOXL", "status": "COMPLETED", "cycle_number": 1, "total_qty": 0,
            "avg_price": 0.0, "total_spent": 977.64, "current_round": 19, "created": 1}

    def test_running_portfolio_on_a_completed_cycle_is_reported(self):
        struct, result = _pull([self.DONE], {**PORTFOLIO, "sourceCycleId": ""})
        self.assertEqual([e[2] for e in struct.engine.events], ["FIREGATE_CYCLE_COMPLETED_LOCALLY"])
        self.assertEqual(result["cycles_skipped"][0]["reason"], "skipped_completed")
        self.assertNotIn("1건을 로컬 사이클/워치리스트에 반영했습니다", result["message"])
        self.assertIn("적용하지 않았습니다", result["message"])
        authoritative = bridge.sync_firegate_authoritative
        original = bridge.sync_portfolios_to_local
        bridge.sync_portfolios_to_local = lambda _s, symbol_filter="": result
        try:
            self.assertIn("사이클 미적용 1건", authoritative(None)["message"])
        finally:
            bridge.sync_portfolios_to_local = original

    def test_finished_on_both_sides_stays_quiet(self):
        struct, result = _pull([self.DONE], {**PORTFOLIO, "sourceCycleId": "", "isRunning": False,
                                             "holdingQty": 0, "totalSell": 14000})
        self.assertEqual(struct.engine.events, [])
        self.assertEqual(result["cycles_skipped"], [])
        self.assertEqual(struct.db("trading_cycle").rows_data[0]["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
