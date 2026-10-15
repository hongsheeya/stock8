"""Live KS minute bars: today from KIS (real time), earlier days from Yahoo.

Yahoo's Korean minute data ran about 20 minutes behind (10-15 11:15: last
bar 10:55 for 005930/069500/114800/036930), so live indicators lagged.
"""
import datetime
import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from test_kis_api_buying_power import _StructStub as _KisStruct, kis_api
from test_vrev_execution_timing import module as daytrade_module


def _kis_row(day, hhmm, close, volume=100):
    return {"stck_bsop_date": day, "stck_cntg_hour": hhmm + "00", "stck_prpr": str(close),
            "stck_oprc": str(close), "stck_hgpr": str(close + 1), "stck_lwpr": str(close - 1),
            "cntg_vol": str(volume)}


class KisMinuteBarTests(unittest.TestCase):
    def test_pages_walk_back_to_the_open_and_return_today_oldest_first(self):
        api = kis_api.KisApi(_KisStruct())
        cursors = []

        def request(method, path, tr_id, params=None, **_kwargs):
            cursors.append(params["FID_INPUT_HOUR_1"])
            start = datetime.datetime.strptime(params["FID_INPUT_HOUR_1"], "%H%M%S")
            rows = [_kis_row("20260529", (start - datetime.timedelta(minutes=i)).strftime("%H%M"), 1000 + i)
                    for i in range(30) if (start - datetime.timedelta(minutes=i)).strftime("%H%M") >= "0900"]
            rows.append(_kis_row("20260528", "1530", 999))  # yesterday's row is ignored
            return {"rt_cd": "0", "output2": rows}

        api._request = request
        bars = api.get_domestic_minute_bars("005930")
        self.assertEqual(cursors, ["100000", "093000", "090000"])
        self.assertEqual(len(bars), 61)
        self.assertEqual((bars[0]["time"], bars[-1]["time"]), ("09:00", "10:00"))
        self.assertTrue(all(bar["date"] == "2026-05-29" for bar in bars))

    def test_refresh_stops_at_the_last_cached_minute(self):
        api = kis_api.KisApi(_KisStruct())
        cursors = []
        api._request = lambda method, path, tr_id, params=None, **_k: cursors.append(params["FID_INPUT_HOUR_1"]) or {
            "rt_cd": "0", "output2": [_kis_row("20260529", f"09{m:02d}", 1000) for m in range(59, 29, -1)]}
        api.get_domestic_minute_bars("005930", since_hhmmss="095000")
        self.assertEqual(cursors, ["100000"])

    def test_error_is_raised_for_the_caller_to_fall_back(self):
        api = kis_api.KisApi(_KisStruct())
        api._request = lambda *_a, **_k: {"rt_cd": "1", "msg1": "없는 서비스 코드 입니다"}
        with self.assertRaises(Exception):
            api.get_domestic_minute_bars("005930")


def _rows(day, start_hhmm, count, base):
    start = datetime.datetime.strptime(f"{day} {start_hhmm}", "%Y-%m-%d %H:%M")
    return [{"timestamp": (start + datetime.timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M"),
             "date": day, "time": (start + datetime.timedelta(minutes=i)).strftime("%H:%M"),
             "open": base + i, "high": base + i + 1, "low": base + i - 1, "close": base + i, "volume": 100}
            for i in range(count)]


class LiveDatasetTests(unittest.TestCase):
    def setUp(self):
        self.svc = daytrade_module.Daytrade.__new__(daytrade_module.Daytrade)
        self.svc._now = lambda: datetime.datetime(2026, 5, 29, 10, 0)
        yesterday = _rows("2026-05-28", "09:00", 380, 5000)
        delayed_today = _rows("2026-05-29", "09:00", 40, 6000)  # Yahoo: 20 minutes behind
        self.yahoo = self.svc._rows_to_sessions(yesterday + delayed_today, market="KS")
        self.svc._prepare_dataset = lambda *_a, **_k: self.yahoo
        self.kis_calls = []
        live_today = [{**row, "close": row["close"] + 1} for row in _rows("2026-05-29", "09:00", 60, 6000)]

        def minute_bars(symbol, since_hhmmss="090000"):
            self.kis_calls.append(since_hhmmss)
            return [dict(row) for row in live_today]

        self.svc.struct = SimpleNamespace(get_config=lambda key, default=None: default,
                                          kis_api=SimpleNamespace(get_domestic_minute_bars=minute_bars))
        patcher = patch.object(daytrade_module.Daytrade, "_KS_LIVE_MINUTES", {})
        patcher.start()
        self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {"TRADING_MODE": "PAPER"})
        env.start()
        self.addCleanup(env.stop)

    def test_today_comes_from_kis_and_keeps_yesterdays_anchor(self):
        sessions = self.svc.prepare_live_dataset("005930", market="KS")
        today = sessions[-1]
        self.assertEqual((today["date"], len(today["bars"])), ("2026-05-29", 60))
        self.assertEqual(today["bars"][-1]["time"], "09:59")
        self.assertEqual(today["prev_close"], self.yahoo[0]["bars"][-1]["close"])
        self.assertEqual(today["bars"][-1]["bar_source"], "kis_minute")

    def test_second_refresh_asks_only_for_new_minutes(self):
        self.svc.prepare_live_dataset("005930", market="KS")
        self.svc.prepare_live_dataset("005930", market="KS")
        self.assertEqual(self.kis_calls, ["090000", "095900"])

    def test_kis_failure_keeps_the_yahoo_sessions(self):
        def broken(*_a, **_k):
            raise RuntimeError("없는 서비스 코드 입니다")
        self.svc.struct.kis_api.get_domestic_minute_bars = broken
        self.assertIs(self.svc.prepare_live_dataset("005930", market="KS"), self.yahoo)

    def test_us_and_a_disabled_setting_keep_yahoo(self):
        self.assertIs(self.svc.prepare_live_dataset("TQQQ", market="US"), self.yahoo)
        self.svc.struct.get_config = lambda key, default=None: "false" if key == "daytrade_ks_kis_minute_bars" else default
        self.assertIs(self.svc.prepare_live_dataset("005930", market="KS"), self.yahoo)
        self.assertEqual(self.kis_calls, [])

    def test_live_uses_the_same_real_time_bars(self):
        with patch.dict(os.environ, {"TRADING_MODE": "LIVE"}):
            self.assertEqual(self.svc.prepare_live_dataset("005930", market="KS")[-1]["bars"][-1]["bar_source"], "kis_minute")


class SuffixQualityTests(unittest.TestCase):
    def test_thin_answer_from_one_suffix_does_not_win(self):
        class Frame:
            def __init__(self, n):
                self.n, self.empty = n, n == 0

            def __len__(self):
                return self.n

            def iterrows(self):
                class Stamp:
                    def __init__(self, i):
                        self.i = i

                    def strftime(self, fmt):
                        text = f"2026-05-29 09:{self.i % 60:02d}"
                        return {"%Y-%m-%d %H:%M": text, "%Y-%m-%d": text[:10], "%H:%M": text[11:]}[fmt]
                return iter((Stamp(i), {"Open": 1, "High": 1, "Low": 1, "Close": 1, "Volume": 1}) for i in range(self.n))

        sizes = {"250030.KS": 4, "250030.KQ": 115}
        yf = types.SimpleNamespace(Ticker=lambda symbol: types.SimpleNamespace(
            history=lambda **_k: Frame(sizes.get(symbol, 0))))
        svc = daytrade_module.Daytrade.__new__(daytrade_module.Daytrade)
        svc._ensure_numpy_rec_alias = lambda: None
        with patch.dict(sys.modules, {"yfinance": yf}), \
                patch.object(daytrade_module.Daytrade, "_DOMESTIC_YF_SUFFIX", {}), \
                patch.object(daytrade_module.Daytrade, "_DATASET_CACHE", {}):
            svc._prepare_dataset("250030", market="KS", period="5d", interval="1m")
            self.assertEqual(daytrade_module.Daytrade._DOMESTIC_YF_SUFFIX["250030"], "KQ")


if __name__ == "__main__":
    unittest.main()
