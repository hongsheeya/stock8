"""One-year KS minute-bar backfill (10-21)."""
import datetime
import unittest
from unittest.mock import MagicMock

from test_daytrade_engine_regressions import _engine_with_state
from test_kis_api_buying_power import kis_api, _StructStub
from test_ks_minute_archive import _Fs


class KisPastMinuteTests(unittest.TestCase):
    def test_walks_back_from_the_close_in_pages(self):
        api = kis_api.KisApi(_StructStub())
        cursors = []

        def request(method, path, tr_id, params=None, **_k):
            cursors.append(params["FID_INPUT_HOUR_1"])
            start = int(params["FID_INPUT_HOUR_1"][:2]) * 60 + int(params["FID_INPUT_HOUR_1"][2:4])
            rows = [{"stck_bsop_date": "20260715", "stck_cntg_hour": f"{(start - i) // 60:02d}{(start - i) % 60:02d}00",
                     "stck_prpr": "100", "cntg_vol": "1"} for i in range(120) if start - i >= 540]
            return {"rt_cd": "0", "output2": rows}

        api._request = request
        bars = api.get_domestic_minute_bars_for_day("069500", "2026-07-15")
        self.assertEqual(bars[0]["time"], "09:00")
        self.assertEqual(bars[-1]["time"], "15:30")
        self.assertEqual(len(bars), 391)
        self.assertEqual(cursors[0], "153000")
        self.assertEqual(len(cursors), 4)


class BackfillTests(unittest.TestCase):
    def test_fills_weekdays_and_resumes(self):
        engine, _ = _engine_with_state({}, [])
        engine._now = lambda: datetime.datetime(2026, 10, 21, 16, 30)
        fs = _Fs()
        engine._fs = lambda: fs
        api = MagicMock()
        api.get_domestic_minute_bars_for_day.side_effect = lambda sym, day: [{"date": day, "time": "15:30", "close": 1.0}]
        engine.struct.kis_api = api
        type(engine)._BACKFILL_STATE.clear()
        result = engine.backfill_ks_minute_archive(days_back=7, symbols=["069500", "229200"])
        self.assertEqual(result["done_days"], 5)  # 10-14..10-20, weekdays only
        calls = api.get_domestic_minute_bars_for_day.call_count
        result = engine.backfill_ks_minute_archive(days_back=7, symbols=["069500", "229200"])
        self.assertEqual((result["done_days"], result["skipped_days"]), (0, 5))
        self.assertEqual(api.get_domestic_minute_bars_for_day.call_count, calls)


if __name__ == "__main__":
    unittest.main()
