"""Daily KS minute-bar archive (10-19: Yahoo stops at 15:00)."""
import contextlib
import datetime
import unittest
from unittest.mock import MagicMock

from test_daytrade_engine_regressions import _engine_with_state


class _Fs:
    def __init__(self):
        self.files, self.write = {}, MagicMock()
        self.write.json.side_effect = lambda path, payload: self.files.__setitem__(path, payload)

    def exists(self, path):
        return path in self.files

    def makedirs(self, _path):
        pass


class KsMinuteArchiveTests(unittest.TestCase):
    def _engine(self, now, bars):
        engine, _ = _engine_with_state({}, [])
        engine._now = lambda: now
        fs = _Fs()
        engine._fs = lambda: fs
        broker = MagicMock()
        broker.request_options.side_effect = lambda **_k: contextlib.nullcontext()
        broker.get_domestic_minute_bars.side_effect = bars
        engine._broker = lambda: broker
        return engine, fs, broker

    def test_saves_once_after_the_close(self):
        day = "2026-10-19"
        bars = lambda symbol, **_k: [{"date": day, "time": "15:30", "close": 1.0}] if symbol != "251340" else []
        engine, fs, broker = self._engine(datetime.datetime(2026, 10, 19, 15, 45), bars)
        result = engine.archive_ks_minute_bars()
        self.assertEqual(result["status"], "saved")
        saved = fs.files[engine._ks_minute_archive_path(day)]
        self.assertEqual(len(saved["bars"]), 6)
        self.assertIn("251340", saved["errors"])
        calls = broker.get_domestic_minute_bars.call_count
        self.assertEqual(engine.archive_ks_minute_bars()["status"], "done")
        self.assertEqual(broker.get_domestic_minute_bars.call_count, calls)

    def test_waits_before_the_close_and_on_weekends(self):
        bars = lambda symbol, **_k: [{"date": "x", "close": 1.0}]
        for now in (datetime.datetime(2026, 10, 19, 15, 20), datetime.datetime(2026, 10, 18, 16, 0)):
            engine, fs, broker = self._engine(now, bars)
            self.assertEqual(engine.archive_ks_minute_bars()["status"], "waiting")
            broker.get_domestic_minute_bars.assert_not_called()

    def test_holiday_without_bars_saves_nothing(self):
        engine, fs, _ = self._engine(datetime.datetime(2026, 10, 19, 16, 0), lambda symbol, **_k: [])
        self.assertEqual(engine.archive_ks_minute_bars()["status"], "empty")
        self.assertEqual(fs.files, {})


if __name__ == "__main__":
    unittest.main()
