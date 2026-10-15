"""The startup backfill keeps fills that carry evidence.

Every restart turned all history_backfill rows into PENDING with qty 0,
including the backfill's own verified fills (10-15 PAPER: 96 of 101 rows,
76 KIS-verified), and logged "과거 주문 86건을 ... 정정" each time.
"""
import json
import os
import sys
import unittest

from test_daytrade_engine_regressions import _engine_with_state, daytrade_engine

VERIFIED = {"action": "BUY1", "status": "FILLED", "filled_qty": 177, "filled_price": 277759.89,
            "verification": "kis", "reason": "1차 눌림 구간 진입 신호"}


class _TradeLog:
    """rows() is the current user's scope; _raw_rows() sees every user."""

    def __init__(self, rows, other_users=()):
        self.data = [dict(row) for row in rows]
        self.others = [dict(row) for row in other_users]
        self.inserted = []

    def rows(self, **_kwargs):
        return [dict(row) for row in self.data]

    def _raw_rows(self, **_kwargs):
        return [dict(row) for row in self.data + self.others]

    def update(self, values, id=None):
        next(row for row in self.data if row["id"] == id).update(values)

    def insert(self, values):
        self.inserted.append(values)


def _row(row_id, action, raw, order_no=None, created="2026-10-13 12:15:25"):
    return {"id": row_id, "order_no": order_no or f"000{row_id}", "action": action, "filled_qty": 0,
            "filled_price": 0, "created": created, "raw_response": json.dumps(raw, ensure_ascii=False)}


def _backfill(row_id, order_no, filled, created="2026-10-13 12:15:25"):
    raw = {"runtime": {"history_backfill": True, "reason": "1차 눌림 구간 진입 신호"}, "order": dict(VERIFIED),
           "execution_status": "FILLED" if filled else "ACCEPTED_UNVERIFIED", "action": "BUY1" if filled else "BUY1_PENDING"}
    row = _row(row_id, "BUY" if filled else "PENDING", raw, order_no=order_no, created=created)
    if filled:
        row.update(filled_qty=177, filled_price=277759.89)
    return row




class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.engine, _ = _engine_with_state({}, [])
        self.logs = []
        self.engine._append_runtime_log = lambda level, message, **_k: self.logs.append(message)
        self.log = _TradeLog([
            # A verified fill the old unconditional pass turned into PENDING.
            _row(1, "PENDING", {"runtime": {"history_backfill": True, "reason": "1차 눌림 구간 진입 신호"},
                                "execution_status": "ACCEPTED_UNVERIFIED", "action": "BUY1_PENDING",
                                "message": "기존 주문 접수 기록 · KIS 체결 미확인", "order": dict(VERIFIED)}),
            # No evidence, already corrected.
            _row(2, "PENDING", {"runtime": {"history_backfill": True}, "execution_status": "ACCEPTED_UNVERIFIED",
                                "action": "BUY1_PENDING", "order": {"action": "BUY1", "status": "ACCEPTED_UNVERIFIED"}}),
            # No evidence, still recorded as a fill by the old compatibility backfill.
            {**_row(3, "BUY", {"runtime": {"history_backfill": True}, "execution_status": "FILLED",
                               "action": "BUY1", "order": {"action": "BUY1", "order_no": "0003"}}),
             "filled_qty": 5, "filled_price": 1000},
        ])
        self.engine.struct.db = lambda name: self.log

    def _run(self):
        marker = f"_stock8_daytrade_history_backfilled_{os.getpid()}_{daytrade_engine._TRADING_MODE.lower()}"
        if hasattr(sys, marker):
            delattr(sys, marker)
        self.engine._backfill_state_history_once()

    def test_verified_fill_is_restored_and_unproven_fill_is_downgraded(self):
        self._run()
        restored, already, unproven = self.log.data
        self.assertEqual((restored["action"], restored["filled_qty"], restored["filled_price"]), ("BUY", 177, 277759.89))
        raw = json.loads(restored["raw_response"])
        self.assertEqual((raw["execution_status"], raw["action"]), ("FILLED", "BUY1"))
        self.assertEqual(already["action"], "PENDING")
        self.assertEqual((unproven["action"], unproven["filled_qty"]), ("PENDING", 0))
        self.assertEqual(self.logs, ["체결 근거가 없던 과거 주문 1건을 접수·확인대기로 정정했습니다.",
                                     "체결 근거가 있는 과거 주문 1건의 체결 기록을 복원했습니다."])

    def test_a_restart_changes_nothing(self):
        self._run()
        before, self.logs[:] = [dict(row) for row in self.log.data], []
        self._run()
        self.assertEqual(self.log.data, before)
        self.assertEqual(self.logs, [])

    def test_state_fills_with_evidence_are_still_inserted(self):
        self.engine._load_state_map = lambda: {"069500.KS": {"symbol": "069500", "market": "KS", "orders": [
            {**VERIFIED, "order_no": "0000099", "timestamp": "2026-09-03 10:09:38"},
            {"action": "SELL_FULL", "order_no": "0000100", "status": "ACCEPTED_UNVERIFIED", "filled_qty": 0},
        ]}}
        self._run()
        self.assertEqual([(row["order_no"], row["filled_qty"]) for row in self.log.inserted], [("0000099", 177)])



class OneFillPerOrderTests(unittest.TestCase):
    """10-15: 43 orders the engine had logged under user '' were backfilled
    twice more under the worker owner (the scoped view hid the engine row).
    Restoring those would count each fill three times."""

    def _engine(self, log):
        engine, _ = _engine_with_state({}, [])
        logs = []
        engine._append_runtime_log = lambda level, message, **_k: logs.append(message)
        engine.struct.db = lambda name: log
        marker = f"_stock8_daytrade_history_backfilled_{os.getpid()}_{daytrade_engine._TRADING_MODE.lower()}"
        return engine, logs, marker

    def _run(self, engine, marker):
        if hasattr(sys, marker):
            delattr(sys, marker)
        engine._backfill_state_history_once()

    def test_the_engines_own_fill_wins_over_backfill_copies(self):
        engine_fill = {"id": "live", "order_no": "0000023994", "action": "BUY", "filled_qty": 612,
                       "filled_price": 112541.03, "created": "2026-09-23 13:16:55", "raw_response": "{}"}
        log = _TradeLog([_backfill("a", "0000023994", True), _backfill("b", "0000023994", True)], other_users=[engine_fill])
        engine, logs, marker = self._engine(log)
        self._run(engine, marker)
        self.assertEqual([(row["action"], row["filled_qty"]) for row in log.data], [("PENDING", 0), ("PENDING", 0)])
        self.assertEqual(logs, ["같은 주문의 중복 체결 기록 2건을 접수 기록으로 정정했습니다."])
        before, logs[:] = [dict(row) for row in log.data], []
        self._run(engine, marker)
        self.assertEqual((log.data, logs), (before, []))

    def test_only_the_earliest_backfill_copy_is_restored(self):
        log = _TradeLog([_backfill("late", "0000011485", False, created="2026-09-22 21:53:15"),
                         _backfill("early", "0000011485", False, created="2026-08-31 17:45:19")])
        engine, logs, marker = self._engine(log)
        self._run(engine, marker)
        self.assertEqual({row["id"]: row["filled_qty"] for row in log.data}, {"late": 0, "early": 177})

    def test_insert_skips_orders_logged_under_another_user(self):
        log = _TradeLog([], other_users=[{"id": "live", "order_no": "0000099", "action": "BUY", "filled_qty": 177,
                                          "created": "2026-09-03 10:09:38", "raw_response": "{}"}])
        engine, _logs, marker = self._engine(log)
        engine._load_state_map = lambda: {"069500.KS": {"symbol": "069500", "market": "KS", "orders": [
            {**VERIFIED, "order_no": "0000099", "timestamp": "2026-09-03 10:09:38"}]}}
        self._run(engine, marker)
        self.assertEqual(log.inserted, [])


if __name__ == "__main__":
    unittest.main()
