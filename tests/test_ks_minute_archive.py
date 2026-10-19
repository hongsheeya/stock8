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

        self.read = MagicMock()
        self.read.json.side_effect = lambda path, default=None: self.files.get(path, default)

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
        engine.struct.kis_api = broker
        engine._append_runtime_log = lambda *a, **k: None
        return engine, fs, broker

    def test_fills_the_archive_over_passes_and_then_stops(self):
        day = "2026-10-19"
        bars = lambda symbol, **_k: [{"date": day, "time": "15:30", "close": 1.0}]
        engine, fs, broker = self._engine(datetime.datetime(2026, 10, 19, 15, 45), bars)
        statuses = [engine.archive_ks_minute_bars()["status"] for _ in range(3)]
        self.assertEqual(statuses, ["partial", "partial", "saved"])
        self.assertEqual(len(fs.files[engine._ks_minute_archive_path(day)]["bars"]), 7)
        calls = broker.get_domestic_minute_bars.call_count
        self.assertEqual(calls, 7)
        self.assertEqual(engine.archive_ks_minute_bars()["status"], "done")
        self.assertEqual(broker.get_domestic_minute_bars.call_count, calls)

    def test_a_busy_gateway_keeps_what_it_got(self):
        day = "2026-10-19"
        def bars(symbol, **_k):
            if symbol == "229200":
                raise RuntimeError("KIS 프로세스 간 호출 대기 한도 초과")
            return [{"date": day, "close": 1.0}]
        engine, fs, _ = self._engine(datetime.datetime(2026, 10, 19, 17, 37), bars)
        result = engine.archive_ks_minute_bars()
        self.assertEqual(result["status"], "partial")
        self.assertIn("229200", result["missing"])
        self.assertEqual(sorted(fs.files[engine._ks_minute_archive_path(day)]["bars"]), ["069500", "122630"])

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
