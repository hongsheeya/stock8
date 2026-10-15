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


class _TradeLog:
    def __init__(self, rows):
        self.data = [dict(row) for row in rows]
        self.inserted = []

    def rows(self, **_kwargs):
        return [dict(row) for row in self.data]

    def update(self, values, id=None):
        next(row for row in self.data if row["id"] == id).update(values)

    def insert(self, values):
        self.inserted.append(values)


def _row(row_id, action, raw):
    return {"id": row_id, "order_no": f"000{row_id}", "action": action, "filled_qty": 0,
            "filled_price": 0, "raw_response": json.dumps(raw, ensure_ascii=False)}


VERIFIED = {"action": "BUY1", "status": "FILLED", "filled_qty": 177, "filled_price": 277759.89,
            "verification": "kis", "reason": "1차 눌림 구간 진입 신호"}


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


if __name__ == "__main__":
    unittest.main()
