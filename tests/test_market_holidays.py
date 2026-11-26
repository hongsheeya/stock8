"""Day-trade market-open checks know exchange holidays, not just weekends.

11-26 (Thanksgiving) PAPER kept sending RIVN buys every few minutes and KIS
answered "모의투자 영업일이 아닙니다": _us_market_open/_us_premarket_open only
knew weekends, and the KRX side (domestic_market.session and the engine's KS
check) had the same gap for 12-25 / 12-31 and other KRX closures.
"""
import builtins
import datetime
import importlib.util
import pathlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from test_daytrade_engine_regressions import _engine_with_state, daytrade_engine

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "domestic_market_holidays_under_test", ROOT / "src" / "portal" / "trading" / "model" / "domestic_market.py")
market = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(market)

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


def _kst(y, mo, d, h, mi=0):
    return datetime.datetime(y, mo, d, h, mi, tzinfo=market.KST)


class DomesticSessionHolidayTests(unittest.TestCase):
    def test_krx_and_nxt_are_closed_on_krx_holidays(self):
        for day in ((2026, 12, 25), (2026, 12, 31), (2027, 1, 1)):
            for exchange, hour in (("KRX", 10), ("KRX", 16), ("NXT", 8), ("NXT", 10), ("NXT", 16)):
                with self.subTest(day=day, exchange=exchange, hour=hour):
                    self.assertEqual(market.session(_kst(*day, hour), exchange), "CLOSED")

    def test_orders_are_refused_on_a_holiday(self):
        with self.assertRaises(ValueError):
            market.route(_kst(2026, 12, 25, 10), "KRX", "MARKET", 0, 1)

    def test_ordinary_weekday_is_unchanged(self):
        self.assertEqual(market.session(_kst(2026, 12, 24, 10), "KRX"), "REGULAR")
        self.assertEqual(market.route(_kst(2026, 12, 24, 10), "KRX", "MARKET", 0, 1)["ord_dvsn"], "01")

    def test_holiday_helper(self):
        self.assertTrue(market.is_krx_holiday(datetime.date(2026, 12, 31)))
        self.assertTrue(market.is_krx_holiday(datetime.datetime(2026, 12, 31, 9, 0)))
        self.assertFalse(market.is_krx_holiday(datetime.date(2026, 12, 30)))
        # Callers get the Model instance from wiz.model().
        self.assertTrue(market.Model.is_krx_holiday(datetime.date(2026, 12, 25)))

    def test_table_matches_the_dividend_calendar(self):
        # A trading day wrongly listed here would refuse every KS order,
        # exits included, so the two copies must agree.
        source = (ROOT / "src" / "portal" / "trading" / "model" / "dividend.py").read_text(encoding="utf-8")
        start = source.index("KR_HOLIDAYS = {")
        dividend_days = set(__import__("re").findall(r'"(\d{4}-\d{2}-\d{2})"', source[start:source.index("}", start)]))
        self.assertEqual(set(market.KRX_HOLIDAYS), dividend_days)

    def test_no_listed_holiday_is_a_weekend_or_duplicate_trading_day(self):
        for day in market.KRX_HOLIDAYS:
            self.assertLess(datetime.date.fromisoformat(day).weekday(), 5, day)


class _FixedDatetime(datetime.datetime):
    fixed = None

    @classmethod
    def now(cls, tz=None):
        value = cls.fixed
        return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)


@unittest.skipIf(ZoneInfo is None, "zoneinfo unavailable")
class UsDaytradeHolidayTests(unittest.TestCase):
    def _open_at(self, et_args, method):
        engine, _ = _engine_with_state({}, [])
        engine.struct.kis_api.US_MARKET_HOLIDAYS = {"2026-11-26": "Thanksgiving Day"}
        _FixedDatetime.fixed = datetime.datetime(*et_args, tzinfo=ZoneInfo("America/New_York"))
        fake = SimpleNamespace(datetime=_FixedDatetime, timedelta=datetime.timedelta,
                               date=datetime.date, timezone=datetime.timezone)
        with patch.object(daytrade_engine, "_PAPER_CONTINUOUS", False), patch.object(daytrade_engine, "datetime", fake):
            return getattr(engine, method)()

    def test_thanksgiving_regular_session_is_closed(self):
        self.assertFalse(self._open_at((2026, 11, 26, 11, 0), "_us_market_open"))

    def test_thanksgiving_premarket_is_closed(self):
        self.assertFalse(self._open_at((2026, 11, 26, 7, 0), "_us_premarket_open"))

    def test_next_day_is_open(self):
        self.assertTrue(self._open_at((2026, 11, 27, 10, 0), "_us_market_open"))
        self.assertTrue(self._open_at((2026, 11, 27, 7, 0), "_us_premarket_open"))

    def test_missing_table_falls_back_to_weekdays(self):
        engine, _ = _engine_with_state({}, [])
        engine.struct.kis_api = None
        self.assertEqual(engine._us_holiday_label(datetime.datetime(2026, 11, 26, 11, 0)), "")


class KsDaytradeHolidayTests(unittest.TestCase):
    def _engine_at(self, when):
        engine, _ = _engine_with_state({}, [])
        engine._now = lambda: when
        return engine

    def test_ks_is_closed_on_a_krx_holiday(self):
        original = builtins.wiz
        # Like the real wiz.model(): the module's Model instance, not the module.
        stub = SimpleNamespace(model=lambda name: market.Model if name == "portal/trading/domestic_market"
                               else original.model(name))
        engine = self._engine_at(datetime.datetime(2026, 12, 25, 10, 0))
        with patch.object(daytrade_engine, "_PAPER_CONTINUOUS", False), patch.object(builtins, "wiz", stub):
            self.assertFalse(engine._daytrade_market_open("KS"))
        engine = self._engine_at(datetime.datetime(2026, 12, 24, 10, 0))
        with patch.object(daytrade_engine, "_PAPER_CONTINUOUS", False), patch.object(builtins, "wiz", stub):
            self.assertTrue(engine._daytrade_market_open("KS"))

    def test_unavailable_calendar_keeps_the_weekday_rule(self):
        engine = self._engine_at(datetime.datetime(2026, 12, 24, 10, 0))
        with patch.object(daytrade_engine, "_PAPER_CONTINUOUS", False):
            self.assertTrue(engine._daytrade_market_open("KS"))


if __name__ == "__main__":
    unittest.main()
