"""US 13:00 ET early closes (11-27 day after Thanksgiving, 12-24, ...).

11-27 every US close check still said 16:00: the day-trade flatten (15:40 ET)
and MOC (15:30 ET) came after the 13:00 close, entries stayed open until
15:00, and the infinite-buy reverse MOC / PAPER LOC windows sat after the
close, so a PAPER day trade bought before 13:00 would have been held over the
weekend.
"""
import contextlib
import datetime
import importlib.util
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_daytrade_engine_regressions import _engine_with_state, daytrade_engine
from test_kis_api_buying_power import _StructStub as _KisStruct, kis_api
from test_firegate_reverse_mode import SOXL, _ConfigStruct, _Kis, Engine
from test_us_trend_hold import FakeBroker, E as UsTrendHold

try:
    from zoneinfo import ZoneInfo
    ZoneInfo("America/New_York")  # tz data present (the runtime venv has tzdata)
except Exception:  # pragma: no cover
    ZoneInfo = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("order_policy_early_close", ROOT / "src/portal/trading/model/order_policy.py")
order_policy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(order_policy)

EARLY = {"2026-11-27": "13:00", "2026-12-24": "13:00"}
# NYSE Group 2026-2028 holiday and early closings calendar (2025-12-23).
NYSE_EARLY_CLOSES = {"2026-11-27", "2026-12-24", "2027-11-26", "2028-07-03", "2028-11-24"}


def _kst_for_et(y, mo, d, h, mi=0):
    """Naive KST wall time for an ET wall time (how _now() reports time)."""
    et = datetime.datetime(y, mo, d, h, mi, tzinfo=ZoneInfo("America/New_York"))
    return et.astimezone(ZoneInfo("Asia/Seoul")).replace(tzinfo=None)


class EarlyCloseTableTests(unittest.TestCase):
    def test_table_is_the_nyse_calendar(self):
        self.assertEqual(set(kis_api.KisApi.US_EARLY_CLOSES), NYSE_EARLY_CLOSES)
        self.assertTrue(all(v == "13:00" for v in kis_api.KisApi.US_EARLY_CLOSES.values()))

    def test_early_closes_are_trading_weekdays(self):
        for day in kis_api.KisApi.US_EARLY_CLOSES:
            self.assertLess(datetime.date.fromisoformat(day).weekday(), 5, day)
            self.assertNotIn(day, kis_api.KisApi.US_MARKET_HOLIDAYS, day)

    def test_close_minutes(self):
        self.assertEqual(kis_api.KisApi.us_close_minutes_for(datetime.date(2026, 11, 27)), 13 * 60)
        self.assertEqual(kis_api.KisApi.us_close_minutes_for("2026-12-24"), 13 * 60)
        self.assertEqual(kis_api.KisApi.us_close_minutes_for(datetime.datetime(2026, 11, 27, 9, 0)), 13 * 60)
        self.assertEqual(kis_api.KisApi.us_close_minutes_for(datetime.date(2026, 11, 30)), 16 * 60)


@unittest.skipIf(ZoneInfo is None, "zoneinfo unavailable")
class KisSessionTests(unittest.TestCase):
    def test_regular_session_ends_at_the_early_close(self):
        api = kis_api.KisApi(_KisStruct())
        self.assertEqual(api._us_auto_exchange_session(_kst_for_et(2026, 11, 27, 12, 59))["session"], "regular")
        self.assertEqual(api._us_auto_exchange_session(_kst_for_et(2026, 11, 27, 13, 0))["session"], "closed")
        self.assertEqual(api._us_auto_exchange_session(_kst_for_et(2026, 11, 30, 15, 59))["session"], "regular")


class _FixedDatetime(datetime.datetime):
    fixed = None

    @classmethod
    def now(cls, tz=None):
        value = cls.fixed
        return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)


@unittest.skipIf(ZoneInfo is None, "zoneinfo unavailable")
class DaytradeEarlyCloseTests(unittest.TestCase):
    def _engine(self, *et_args):
        engine, _ = _engine_with_state({}, [])
        engine.struct.kis_api.US_EARLY_CLOSES = dict(EARLY)
        engine.struct.kis_api.US_MARKET_HOLIDAYS = {}
        engine._now = lambda: _kst_for_et(*et_args)
        return engine

    def _market_open(self, *et_args):
        engine = self._engine(*et_args)
        _FixedDatetime.fixed = datetime.datetime(*et_args, tzinfo=ZoneInfo("America/New_York"))
        fake = SimpleNamespace(datetime=_FixedDatetime, timedelta=datetime.timedelta,
                               date=datetime.date, timezone=datetime.timezone)
        with patch.object(daytrade_engine, "_PAPER_CONTINUOUS", False), patch.object(daytrade_engine, "datetime", fake):
            return engine._us_market_open()

    def test_regular_session_closes_at_13_on_an_early_close(self):
        self.assertTrue(self._market_open(2026, 11, 27, 12, 59))
        self.assertFalse(self._market_open(2026, 11, 27, 13, 0))
        self.assertFalse(self._market_open(2026, 11, 27, 15, 0))
        self.assertTrue(self._market_open(2026, 11, 30, 15, 59))

    def test_flatten_window_moves_to_12_40(self):
        approaching = lambda *a: self._engine(*a)._is_market_close_approaching("US")
        self.assertFalse(approaching(2026, 11, 27, 12, 39))
        self.assertTrue(approaching(2026, 11, 27, 12, 40))
        self.assertTrue(approaching(2026, 11, 27, 13, 5))
        self.assertFalse(approaching(2026, 11, 27, 15, 40))
        # An ordinary day keeps 15:40~16:05.
        self.assertFalse(approaching(2026, 11, 30, 12, 40))
        self.assertTrue(approaching(2026, 11, 30, 15, 40))
        self.assertTrue(approaching(2026, 11, 30, 16, 5))
        self.assertFalse(approaching(2026, 11, 30, 16, 6))

    def test_moc_last_place_moves_to_12_30(self):
        self.assertEqual(self._engine(2026, 11, 27, 10, 0)._us_moc_last_place_hhmm(), "12:30")
        self.assertEqual(self._engine(2026, 11, 30, 10, 0)._us_moc_last_place_hhmm(), "15:30")

    def test_us_entry_end_moves_three_hours_earlier(self):
        early = self._engine(2026, 11, 27, 10, 0)
        self.assertEqual(early._regime_trend_params("US")["end"], "12:00")
        self.assertEqual(early._momentum_params("US")["end"], "12:00")
        # KS is untouched by a US early close.
        self.assertEqual(early._regime_trend_params("KS")["end"], "14:30")
        normal = self._engine(2026, 11, 30, 10, 0)
        self.assertEqual(normal._regime_trend_params("US")["end"], "15:00")
        self.assertEqual(normal._momentum_params("US")["end"], "15:00")

    def _moc_guard_at(self, *et_args):
        engine = self._engine(*et_args)
        enabled = {"daytrade_us_moc_guard_enabled": "true"}
        engine._config = lambda key, default=None: enabled.get(key, default)
        engine._us_exchange = lambda _symbol: "NASD"
        engine._append_runtime_log = lambda *a, **k: None
        broker = Mock()
        broker.request_options = lambda **_k: contextlib.nullcontext()
        broker.get_overseas_order_history.return_value = []
        broker.sell_order.return_value = {"order_no": "M1", "order_type": "MOC"}
        engine._broker = lambda: broker
        state = dict(symbol="TEST", market="US", strategy_id="paper_regime_trend", position_qty=10,
                     avg_price=30.0, orders=[], last_price=30.0)
        _FixedDatetime.fixed = datetime.datetime(*et_args, tzinfo=ZoneInfo("America/New_York"))
        fake = SimpleNamespace(datetime=_FixedDatetime, timedelta=datetime.timedelta,
                               date=datetime.date, timezone=datetime.timezone)
        with patch.object(daytrade_engine, "_PAPER_CONTINUOUS", False), patch.object(daytrade_engine, "datetime", fake):
            return engine._us_moc_guard(state, "TEST"), broker

    def test_moc_guard_places_nothing_after_12_30_on_an_early_close(self):
        status, broker = self._moc_guard_at(2026, 11, 27, 12, 35)
        self.assertEqual(status, "idle")
        broker.sell_order.assert_not_called()
        status, broker = self._moc_guard_at(2026, 11, 27, 12, 25)
        self.assertEqual(status, "placed")
        broker.sell_order.assert_called_once_with("TEST", 10, price=0, order_type="MOC", exchange="NASD")
        # An ordinary day still places it at 12:35.
        status, _broker = self._moc_guard_at(2026, 11, 30, 12, 35)
        self.assertEqual(status, "placed")

    def test_configured_entry_end_is_capped_not_shifted(self):
        # An earlier configured end stays; a later one stops an hour before the close.
        early = self._engine(2026, 11, 27, 10, 0)
        early.struct.configs["daytrade_momentum_us_end"] = "11:00"
        early.struct.configs["daytrade_regime_trend_us_end"] = "15:45"
        self.assertEqual(early._momentum_params("US")["end"], "11:00")
        self.assertEqual(early._regime_trend_params("US")["end"], "12:00")
        normal = self._engine(2026, 11, 30, 10, 0)
        normal.struct.configs["daytrade_regime_trend_us_end"] = "15:45"
        self.assertEqual(normal._regime_trend_params("US")["end"], "15:45")

    def test_missing_table_keeps_the_16_close(self):
        engine = self._engine(2026, 11, 27, 15, 40)
        engine.struct.kis_api = None
        self.assertTrue(engine._is_market_close_approaching("US"))
        self.assertEqual(engine._us_moc_last_place_hhmm(), "15:30")

    def test_missing_tz_data_does_not_raise(self):
        # Without tz data ZoneInfo(...) raises; the stop/flatten checks must not.
        def no_tzdata(name):
            raise LookupError(f"No time zone found with key {name}")
        engine = self._engine(2026, 11, 30, 15, 40)
        with patch.object(daytrade_engine, "ZoneInfo", no_tzdata):
            self.assertTrue(engine._is_market_close_approaching("US"))
            self.assertEqual(engine._regime_trend_params("US")["end"], "15:00")
        engine = self._engine(2026, 11, 27, 12, 40)
        with patch.object(daytrade_engine, "ZoneInfo", no_tzdata):
            self.assertTrue(engine._is_market_close_approaching("US"))
            self.assertEqual(engine._momentum_params("US")["end"], "12:00")


class _EarlyKis(_Kis):
    US_EARLY_CLOSES = dict(EARLY)


class InfiniteBuyEarlyCloseTests(unittest.TestCase):
    def _engine(self, kis):
        struct = _ConfigStruct([], [{"id": "c1", "symbol": "SOXL", "status": "ACTIVE", "total_qty": 90}])
        engine = Engine(struct)
        engine._load_kis_api = lambda: kis
        engine._load_firegate_authoritative_states = lambda symbol_filter="": {
            "states": {"SOXL": {**SOXL, "_firegate_reverse_state": "NORMAL"}}, "error": ""}
        engine._log_event = lambda *a, **k: None
        return engine

    def test_reverse_moc_window_ends_at_12_40(self):
        kis = _EarlyKis(datetime.datetime(2026, 11, 27, 12, 40))
        result = self._engine(kis).run_firegate_reverse_moc()
        self.assertEqual(kis.sells, [])
        self.assertEqual(result["status"], "outside_window")
        self.assertIn("12:40", result["message"])
        kis = _EarlyKis(datetime.datetime(2026, 11, 27, 12, 39))
        self._engine(kis).run_firegate_reverse_moc()
        self.assertEqual(kis.sells, [("SOXL", 9, "MOC")])

    def test_ordinary_day_keeps_15_40(self):
        kis = _EarlyKis(datetime.datetime(2026, 11, 30, 15, 30))
        self._engine(kis).run_firegate_reverse_moc()
        self.assertEqual(kis.sells, [("SOXL", 9, "MOC")])

    def test_shift_reads_through_the_order_policy_wrapper(self):
        et = datetime.datetime(2026, 11, 27, 12, 0)
        bound = order_policy.BoundBroker(_EarlyKis(et), "infinite_buy")
        self.assertEqual(Engine._us_close_shift_minutes(bound, et), 180)
        self.assertEqual(Engine._us_close_shift_minutes(bound, datetime.datetime(2026, 11, 30, 12, 0)), 0)
        self.assertEqual(Engine._us_close_shift_minutes(None, et), 0)

    @unittest.skipIf(ZoneInfo is None, "zoneinfo unavailable")
    def test_paper_loc_window_moves_before_the_early_close(self):
        engine = self._engine(SimpleNamespace(US_EARLY_CLOSES=dict(EARLY)))
        window = engine.paper_loc_window(_kst_for_et(2026, 11, 27, 12, 56))
        self.assertEqual((window["window"], window["state"]), ("12:55-12:59 ET", "open"))
        window = engine.paper_loc_window(_kst_for_et(2026, 11, 30, 12, 56))
        self.assertEqual((window["window"], window["state"]), ("15:55-15:59 ET", "before"))

    @unittest.skipIf(ZoneInfo is None, "zoneinfo unavailable")
    def test_paper_loc_window_loads_the_broker_once_per_day(self):
        loads = []
        engine = self._engine(None)
        engine._load_kis_api = lambda: loads.append(1) or SimpleNamespace(US_EARLY_CLOSES=dict(EARLY))
        for minute in (50, 51, 52):
            engine.paper_loc_window(_kst_for_et(2026, 11, 27, 12, minute))
        self.assertEqual(len(loads), 1)
        engine.paper_loc_window(_kst_for_et(2026, 11, 30, 12, 50))
        self.assertEqual(len(loads), 2)


class UsTrendHoldEarlyCloseTests(unittest.TestCase):
    def test_trade_window_ends_at_12_30(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = UsTrendHold(FakeBroker(), tmp, {"enabled": False, "seed_usd": 1000}, lambda symbol: [],
                                 early_close_fn=lambda day: EARLY.get(day, ""))
            self.assertTrue(engine._trading_window(datetime.datetime(2026, 11, 27, 12, 29)))
            self.assertFalse(engine._trading_window(datetime.datetime(2026, 11, 27, 12, 30)))
            self.assertTrue(engine._trading_window(datetime.datetime(2026, 11, 30, 15, 29)))
            self.assertFalse(engine._trading_window(datetime.datetime(2026, 11, 30, 15, 30)))


if __name__ == "__main__":
    unittest.main()
