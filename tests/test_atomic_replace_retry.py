"""Atomic JSON saves retry a briefly locked target instead of failing.

On Windows os.replace() fails with WinError 5 while any reader holds the
target open: the daily report reading the other server's ledger, antivirus,
the search indexer. A failed trade-verification save silently drops a sent
order's verification record, so the ledger, coin and US trend-hold saves
retry for a moment before giving up.
"""
import importlib.util
import json
import os
import pathlib
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODEL = ROOT / "src" / "portal" / "trading" / "model"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tv = _load("trade_verifier_retry_under_test", MODEL / "trade_verifier.py")
coin = _load("coin_engine_retry_under_test", MODEL / "coin_engine.py")
trend = _load("us_trend_hold_retry_under_test", MODEL / "us_trend_hold.py")
HELPERS = (tv._replace_with_retry, coin._replace_with_retry, trend._replace_with_retry)


class ReplaceWithRetryTests(unittest.TestCase):
    def test_a_briefly_locked_target_is_retried(self):
        for helper in HELPERS:
            with self.subTest(helper=helper.__module__), tempfile.TemporaryDirectory() as tmp:
                src, dst = os.path.join(tmp, "a.tmp"), os.path.join(tmp, "a.json")
                for path, text in ((src, "new"), (dst, "old")):
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write(text)
                real = os.replace
                calls = []

                def flaky(a, b):
                    calls.append(1)
                    if len(calls) < 3:
                        raise PermissionError(5, "Access is denied")
                    return real(a, b)

                with patch.object(os, "replace", flaky), patch.object(time, "sleep", lambda _s: None):
                    helper(src, dst)
                self.assertEqual(len(calls), 3)
                with open(dst, encoding="utf-8") as handle:
                    self.assertEqual(handle.read(), "new")

    def test_a_target_that_stays_locked_still_raises(self):
        for helper in HELPERS:
            with self.subTest(helper=helper.__module__):
                def locked(_a, _b):
                    raise PermissionError(5, "Access is denied")

                with patch.object(os, "replace", locked), patch.object(time, "sleep", lambda _s: None):
                    with self.assertRaises(PermissionError):
                        helper("x.tmp", "x.json")

    def test_other_errors_are_not_retried(self):
        calls = []

        def missing(_a, _b):
            calls.append(1)
            raise FileNotFoundError(2, "missing")

        with patch.object(os, "replace", missing):
            with self.assertRaises(FileNotFoundError):
                tv._replace_with_retry("x.tmp", "x.json")
        self.assertEqual(len(calls), 1)


@unittest.skipUnless(os.name == "nt", "the reader lock only blocks os.replace on Windows")
class WindowsReaderLockTests(unittest.TestCase):
    def test_ledger_save_survives_a_reader_holding_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ledger.json")
            ledger = tv.Ledger(path)
            ledger.save({"records": [{"id": "old"}]})
            reader = open(path, "rb")  # another process's report, say
            released = threading.Timer(0.08, reader.close)
            released.start()
            try:
                ledger.save({"records": [{"id": "new"}]})
            finally:
                released.join()
                reader.close()
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["records"], [{"id": "new"}])


if __name__ == "__main__":
    unittest.main()
