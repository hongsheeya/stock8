"""Dashboard overview latency (10-16).

Measured: every overview request took 8.0 s, and after a manual refresh the
dashboard answered 503 for minutes. The refresh ran the PAPER external cycle
sync inline (7 days of overseas order history, three passes per symbol,
behind the KIS rate limiter) while every other request waited 8 s on the
singleflight and then failed.
"""
import ast
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "src/app/page.dashboard/api.py"


def _function(name):
    tree = ast.parse(API.read_text(encoding="utf-8-sig"))
    return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)


class _Stop(Exception):
    pass


class OverviewLatencyTests(unittest.TestCase):
    def test_overview_build_never_runs_the_external_cycle_sync(self):
        calls = {n.func.id for n in ast.walk(_function("_build_overview_payload"))
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertNotIn("_sync_external_cycle_trades_if_due", calls)

    def test_request_during_a_build_gets_the_last_payload_without_waiting(self):
        node = _function("overview")
        cache = {"scope": {"ts": 0.0, "payload": {"total_asset": 1}}}
        status = Mock(side_effect=_Stop)
        builder_started = Mock()

        def cache_get(store, key, ttl):
            entry = store.get(key)
            return (dict(entry["payload"]), 42.0) if entry and ttl >= 600 else (None, None)

        scope = {
            "wiz": SimpleNamespace(request=SimpleNamespace(query=lambda *a: "false"),
                                   response=SimpleNamespace(status=status)),
            "_truthy": lambda v: str(v).lower() == "true",
            "_dashboard_cache_scope": lambda: "scope",
            "_require_trading": lambda: None,
            "_broker_setup_state": lambda *a, **k: {"allowed": True},
            "_cache_get": cache_get, "_cache_set": Mock(), "_OVERVIEW_CACHE": cache, "_OVERVIEW_TTL_SEC": 30.0,
            "_CACHE_LOCK": threading.Lock(),
            "_SINGLEFLIGHT_EVENTS": {"dashboard:overview:scope": threading.Event()},
            "_singleflight": lambda *a, **k: builder_started() or (None, False),
            "_build_overview_payload": Mock(), "_dump_error": Mock(), "_empty_overview_payload": dict,
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<overview>", "exec"), scope)
        with self.assertRaises(_Stop):
            scope["overview"]()
        code, payload = status.call_args.args[0], status.call_args.kwargs
        self.assertEqual(code, 200)
        self.assertTrue(payload["refreshing"])
        self.assertEqual(payload["cache_age_sec"], 42.0)
        builder_started.assert_not_called()


if __name__ == "__main__":
    unittest.main()
