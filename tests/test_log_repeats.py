"""Repeated infinite-buy events collapse into one row (10-20: 925 identical rows a day)."""
import datetime
import unittest
from unittest.mock import MagicMock

from test_infinitebuy_loc_schedule_regressions import engine_module


def _engine():
    engine = engine_module.Engine.__new__(engine_module.Engine)
    db = MagicMock()
    db.insert.side_effect = ["row-1", "row-2", "row-3"]
    engine._log_db = lambda: db
    engine.struct = MagicMock()
    engine.struct._current_user_id.return_value = "u1"
    engine._now = lambda: datetime.datetime(2026, 10, 20, 10, 1)
    type(engine)._LOG_REPEATS.clear()
    return engine, db


class LogRepeatTests(unittest.TestCase):
    def test_same_event_updates_a_counter(self):
        engine, db = _engine()
        for _ in range(3):
            engine._log_event("SOXL", "cy", "LOC_BUY_PRICE_MISMATCH", message="수량 불일치 13/8")
        self.assertEqual(db.insert.call_count, 1)
        self.assertEqual(db.update.call_count, 2)
        self.assertIn('"repeat": 3', db.update.call_args.args[0]["raw_response"])
        self.assertEqual(db.update.call_args.kwargs["id"], "row-1")

    def test_a_different_message_or_day_inserts(self):
        engine, db = _engine()
        engine._log_event("SOXL", "cy", "LOC_BUY_PRICE_MISMATCH", message="13/8")
        engine._log_event("SOXL", "cy", "LOC_BUY_PRICE_MISMATCH", message="13/9")
        engine._now = lambda: datetime.datetime(2026, 10, 21, 10, 1)
        engine._log_event("SOXL", "cy", "LOC_BUY_PRICE_MISMATCH", message="13/9")
        self.assertEqual(db.insert.call_count, 3)


if __name__ == "__main__":
    unittest.main()
