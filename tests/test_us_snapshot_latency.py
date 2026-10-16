"""US day-trade page load (10-16).

A page load ran every KIS read in series behind the PAPER limiter: broker
fill history for the daily log, a live balance, a live portfolio valuation
and a broker-synced signal. It took 40 s while the page gave up after 8 s.
Page loads now read cached balances and local fills; the refresh button
(force_refresh) and the explicit verification keep the live reads.
"""
import ast
import unittest
from pathlib import Path

API = Path(__file__).resolve().parents[1] / "src/app/page.daytrade.us/api.py"
TREE = ast.parse(API.read_text(encoding="utf-8-sig"))


def _function(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == name)


def _calls(node, attr):
    return [c for c in ast.walk(node) if isinstance(c, ast.Call)
            and getattr(c.func, "attr", getattr(c.func, "id", "")) == attr]


def _kw(call, name):
    return next((ast.unparse(k.value) for k in call.keywords if k.arg == name), None)


class UsSnapshotLatencyTests(unittest.TestCase):
    def test_snapshot_reads_are_live_only_on_refresh(self):
        node = _function("_build_us_snapshot_payload")
        self.assertEqual(_kw(_calls(node, "_build_us_daily_payload")[0], "sync_broker"), "force_refresh")
        for call in _calls(node, "signal_status"):
            self.assertEqual(_kw(call, "sync_broker"), "force_refresh")

    def test_verify_uses_cached_budget_unless_forced(self):
        node = _function("_build_us_verify_payload")
        budget = _calls(node, "shared_budget_status")[0]
        self.assertEqual(_kw(budget, "use_cache_only"), "not force_refresh")
        self.assertEqual(_kw(_calls(node, "_enrich_budget_status")[0], "live"), "force_refresh")

    def test_explicit_verification_stays_live(self):
        node = _function("us_verify_runtime")
        self.assertEqual(_kw(_calls(node, "_build_us_verify_payload")[0], "force_refresh"), "True")


if __name__ == "__main__":
    unittest.main()
