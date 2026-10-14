"""PAPER fill sync must stay recent-only so it cannot flood the paper gateway."""
import ast
import datetime
from pathlib import Path
from types import SimpleNamespace
import time
import unittest
from unittest.mock import Mock


def _load(paper_mode):
    source = Path(__file__).resolve().parents[1] / "src/portal/trading/model/struct.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    helpers = [n for n in tree.body if isinstance(n, ast.FunctionDef)
               and n.name in ("_external_cycle_sync_window_open", "_external_cycle_sync_verified")]
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Struct")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "run_due_external_cycle_sync")
    env = {"PAPER_MODE": paper_mode, "time": time,
           "_kst_now": lambda: datetime.datetime(2026, 10, 15, 8, 12, 0)}
    exec(compile(ast.Module(body=helpers + [method], type_ignores=[]), str(source), "exec"), env)
    return env["run_due_external_cycle_sync"]


def _struct(result):
    state = {}
    engine = SimpleNamespace(sync_external_cycle_trades=Mock(return_value=result), _log_event=Mock())
    return SimpleNamespace(_worker_state=lambda: state, engine=engine), state


class PaperExternalSyncTests(unittest.TestCase):
    def test_paper_sync_is_recent_only_and_marks_the_verified_day(self):
        run = _load(paper_mode=True)
        obj, state = _struct({"status": "completed", "verified": True})

        run(obj)

        obj.engine.sync_external_cycle_trades.assert_called_once_with(lookback_days=3, recent_only=True)
        self.assertEqual(state["last_external_cycle_sync_verified_day"], "2026-10-15")

    def test_failed_paper_sync_does_not_mark_the_day(self):
        run = _load(paper_mode=True)
        obj, state = _struct({"status": "error", "verified": False})
        run(obj)
        self.assertNotIn("last_external_cycle_sync_verified_day", state)

    def test_live_call_is_unchanged(self):
        run = _load(paper_mode=False)
        obj, _ = _struct({"status": "completed", "verified": True})
        run(obj)
        obj.engine.sync_external_cycle_trades.assert_called_once_with(lookback_days=7)


if __name__ == "__main__":
    unittest.main()
