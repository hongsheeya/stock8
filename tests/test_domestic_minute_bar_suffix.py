"""KOSDAQ minute bars live under ".KQ" even when the live state says "KS".

2026-10-14 PAPER: 079650 (KOSDAQ) was traded with market "KS"; Yahoo has no
079650.KS, so every live signal ran on the quote-only fallback bar
("079650 라이브 분봉 fallback: 079650.KS의 분봉 데이터를 찾을 수 없습니다").
"""
import sys
import types
import unittest
from unittest.mock import patch

from test_vrev_execution_timing import module


class _Frame:
    def __init__(self, rows):
        self._rows = rows
        self.empty = not rows

    def iterrows(self):
        return iter(self._rows)


class _Stamp:
    def __init__(self, text):
        self.text = text

    def strftime(self, fmt):
        return {"%Y-%m-%d %H:%M": self.text, "%Y-%m-%d": self.text[:10], "%H:%M": self.text[11:]}[fmt]


def _yfinance(listed):
    calls = []

    class Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **_kwargs):
            calls.append(self.symbol)
            if self.symbol not in listed:
                return _Frame([])
            return _Frame([(_Stamp(f"2026-10-14 09:{minute:02d}"),
                            {"Open": 9000, "High": 9010, "Low": 8990, "Close": 9000, "Volume": 100})
                           for minute in range(25)])

    return types.SimpleNamespace(Ticker=Ticker), calls


class DomesticSuffixTests(unittest.TestCase):
    def setUp(self):
        self.strategy = module.Daytrade.__new__(module.Daytrade)
        self.strategy._ensure_numpy_rec_alias = lambda: None
        patcher = patch.object(module.Daytrade, "_DOMESTIC_YF_SUFFIX", {})
        patcher.start()
        self.addCleanup(patcher.stop)
        cache = patch.object(module.Daytrade, "_DATASET_CACHE", {})
        cache.start()
        self.addCleanup(cache.stop)

    def test_kosdaq_code_stored_as_ks_reads_kq_bars_and_remembers_it(self):
        yf, calls = _yfinance({"079650.KQ"})
        with patch.dict(sys.modules, {"yfinance": yf}):
            sessions = self.strategy._prepare_dataset("079650", market="KS", period="5d", interval="1m")
            module.Daytrade._DATASET_CACHE.clear()
            self.strategy._prepare_dataset("079650", market="KS", period="5d", interval="1m")
        self.assertEqual(len(sessions[-1]["bars"]), 25)
        self.assertEqual(calls, ["079650.KS", "079650.KQ", "079650.KQ"])
        self.assertEqual(module.Daytrade._DOMESTIC_YF_SUFFIX["079650"], "KQ")

    def test_kospi_code_is_unchanged(self):
        yf, calls = _yfinance({"233740.KS"})
        with patch.dict(sys.modules, {"yfinance": yf}):
            self.strategy._prepare_dataset("233740", market="KS", period="5d", interval="1m")
        self.assertEqual(calls, ["233740.KS"])

    def test_us_symbols_are_not_suffixed(self):
        self.assertEqual(self.strategy._domestic_yf_candidates("TQQQ", "US", "TQQQ"), ["TQQQ"])

    def test_unlisted_code_still_fails(self):
        yf, _ = _yfinance(set())
        with patch.dict(sys.modules, {"yfinance": yf}):
            with self.assertRaises(Exception):
                self.strategy._prepare_dataset("999999", market="KS", period="5d", interval="1m")


if __name__ == "__main__":
    unittest.main()
