"""LOC reservation automation checks the US holiday of the session it books.

A reservation made between 10:00 KST and the cutoff books the US session
dated with the same KST date. Converting that KST time to ET first reads the
previous US date during KST 10:00-13:59 (12:59 in summer time): on 11/26 10:00
KST LIVE tried to book the Thanksgiving session, and on 11/27 10:00 KST it
waited for "Thanksgiving" although 11/27 trades.
"""
import builtins
import datetime
import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class _Clock:
    current = datetime.datetime(2026, 11, 26, 10, 0, 0)

    @classmethod
    def now(cls):
        return cls.current


class _SessionStub:
    @classmethod
    def use(cls):
        return {}


class _WizStub:
    @staticmethod
    def model(name):
        if name == "portal/trading/kst":
            return _Clock
        if name == "portal/season/session":
            return _SessionStub
        raise AssertionError(f"unexpected wiz.model({name})")


class _ConfigDb:
    def __init__(self, store):
        self.store = store
        self.next_id = 1

    def rows(self, dump=1000):
        return [dict(row) for row in self.store.values()]

    def get(self, key=None, id=None):
        if key is not None:
            row = self.store.get(key)
            return dict(row) if row else None
        for row in self.store.values():
            if row.get("id") == id:
                return dict(row)
        return None

    def insert(self, row):
        row = dict(row)
        row.setdefault("id", f"cfg-{self.next_id}")
        self.next_id += 1
        self.store[row["key"]] = row
        return row["id"]

    def update(self, fields, id=None):
        for key, row in self.store.items():
            if row.get("id") == id:
                row.update(fields)
                self.store[key] = row
                return


class _OrmStub:
    def __init__(self, config_store):
        self.config_db = _ConfigDb(config_store)

    def use(self, name, module=None):
        if name == "trading_config":
            return self.config_db
        raise AssertionError(f"unexpected orm.use({name})")


class _KisStructStub:
    def get_config(self, key, default=""):
        return default

    def set_config(self, key, value, description="", is_secret=False):
        raise AssertionError("the holiday lookup must not write config")


class _EngineSpy:
    """Records every reservation call; none may happen on a holiday session."""

    def __init__(self):
        self.calls = []

    def _load_kis_api(self):
        self.calls.append("_load_kis_api")
        return object()

    def schedule_loc_buys(self, *args, **kwargs):
        self.calls.append("schedule_loc_buys")
        return {"status": "completed", "scheduled_count": 0, "expected_count": 0, "expected": []}

    def schedule_loc_sells(self, *args, **kwargs):
        self.calls.append("schedule_loc_sells")
        return {"status": "completed", "scheduled_count": 0, "expected_count": 0, "expected": []}

    def rebuild_loc_reservations(self, *args, **kwargs):
        self.calls.append("rebuild_loc_reservations")
        return {"status": "completed"}

    def _log_event(self, *args, **kwargs):
        return None


builtins.wiz = _WizStub()
kis_api_path = SRC / "portal" / "trading" / "model" / "struct" / "kis_api.py"
kis_api_spec = importlib.util.spec_from_file_location("kis_api_session_holiday_under_test", kis_api_path)
kis_api = importlib.util.module_from_spec(kis_api_spec)
kis_api_spec.loader.exec_module(kis_api)

struct_path = SRC / "portal" / "trading" / "model" / "struct.py"
trading_struct = types.ModuleType("trading_struct_session_holiday_under_test")
trading_struct.__dict__["wiz"] = _WizStub()
source = struct_path.read_text(encoding="utf-8").replace("\nModel = Struct()\n", "\nModel = None\n")
exec(compile(source, str(struct_path), "exec"), trading_struct.__dict__)


def _kst(*args):
    return datetime.datetime(*args)


class KisCurrentSessionHolidayLabelTests(unittest.TestCase):
    def setUp(self):
        self.api = kis_api.KisApi(_KisStructStub())

    def test_current_session_label_keeps_its_eastern_time_meaning(self):
        # 11/26 10:00 KST is 11/25 20:00 ET: the session in progress then is
        # 11/25. Callers asking about "now" (reverse MOC, day trading) rely on it.
        self.assertEqual(self.api.us_market_holiday_label(_kst(2026, 11, 26, 10, 0)), "")
        self.assertEqual(self.api.us_market_holiday_label(_kst(2026, 11, 26, 23, 30)), "Thanksgiving Day")
        self.assertEqual(self.api.us_market_holiday_label(_kst(2026, 11, 27, 3, 0)), "Thanksgiving Day")  # 11/26 13:00 ET
        self.assertEqual(self.api.us_market_holiday_label(_kst(2026, 11, 27, 14, 0)), "")  # 11/27 00:00 ET


@patch.object(trading_struct, "PAPER_MODE", False)
class LocAutomationUsSessionHolidayTests(unittest.TestCase):
    def setUp(self):
        self._build()

    def _build(self):
        """A fresh struct, config and engine spy, so no case sees another's
        "already scheduled today" marks."""
        trading_struct.Struct._cfg = {}
        trading_struct.Struct._cfg_ready = False
        self.struct = object.__new__(trading_struct.Struct)
        self.struct.orm = _OrmStub({})
        self.struct._kis_api_obj = kis_api.KisApi(_KisStructStub())
        self.struct._toss_api_obj = object()
        self.engine = _EngineSpy()
        self.struct._engine_obj = self.engine
        self.struct.run_due_external_cycle_sync = lambda *args, **kwargs: {"executed": False}
        self.struct.run_due_firegate_sync = lambda *args, **kwargs: {"executed": False}
        self.struct.set_config("auto_trade_enabled", "true")
        self._clear_worker_state()

    def tearDown(self):
        self._clear_worker_state()
        _Clock.current = datetime.datetime(2026, 11, 26, 10, 0, 0)

    def _clear_worker_state(self):
        state = self.struct._worker_state()
        for key in list(state.keys()):
            if key.startswith("loc_reservation_verified") or key.startswith("pending_inspect"):
                state.pop(key, None)

    def _run_worker_at(self, now):
        _Clock.current = now
        return self.struct.run_due_loc_automation(reason="worker")

    # Every entry point: the worker, the scheduler's forced loc-buy/loc-sell
    # (cancel and rebook) and the 10-minute verify that may lead to a rebuild.
    _MODES = (
        {"reason": "worker"},
        {"force": True, "reason": "scheduler_loc-buy"},
        {"verify": True, "reason": "10min_reservation_verify"},
    )

    def test_holiday_session_is_never_booked_in_the_morning(self):
        cases = [
            (_kst(2026, 11, 26, 10, 0), "Thanksgiving Day"),   # the 11/26 LIVE attempt
            (_kst(2026, 11, 26, 13, 59), "Thanksgiving Day"),  # last shifted minute (EST)
            (_kst(2026, 11, 26, 14, 0), "Thanksgiving Day"),
            (_kst(2026, 12, 25, 10, 0), "Christmas Day"),
            (_kst(2027, 1, 1, 10, 0), "New Year's Day"),
            (_kst(2027, 6, 18, 10, 0), "Juneteenth observed"),  # EDT: 10:00-12:59 shifted
            (_kst(2027, 6, 18, 12, 59), "Juneteenth observed"),
        ]
        for now, label in cases:
            for mode in self._MODES:
                with self.subTest(now=now, mode=mode):
                    self._build()
                    _Clock.current = now
                    result = self.struct.run_due_loc_automation(**mode)
                    self.assertEqual(result.get("holiday"), label, result)
                    self.assertTrue(result.get("waiting"))
                    self.assertFalse(result.get("executed"))
                    self.assertEqual(self.engine.calls, [])

    def test_holiday_check_does_not_depend_on_broker_methods(self):
        # A KisApi object built before a code reload, or the Toss broker,
        # still sees the class holiday table.
        table = dict(kis_api.KisApi.US_MARKET_HOLIDAYS)

        def toss_broker():
            # set_config(broker_provider) drops both API objects; put them back
            # as the runtime would rebuild them.
            self.struct.set_config("broker_provider", "toss")
            self.struct._kis_api_obj = kis_api.KisApi(_KisStructStub())
            self.struct._toss_api_obj = object()

        setups = {
            "stale_kis_object": lambda: setattr(self.struct, "_kis_api_obj", types.SimpleNamespace(US_MARKET_HOLIDAYS=table)),
            "toss_broker": toss_broker,
        }
        for name, setup in setups.items():
            with self.subTest(setup=name):
                self._build()
                setup()
                result = self._run_worker_at(_kst(2026, 12, 25, 10, 0))
                self.assertEqual(result.get("holiday"), "Christmas Day", result)
                self.assertEqual(self.engine.calls, [])

    def test_trading_day_after_a_holiday_is_not_held_as_a_holiday(self):
        # Stop right after the holiday/window checks: a fresh rebuild cooldown
        # makes the verify path return without touching the engine.
        for now in (_kst(2026, 11, 27, 10, 0), _kst(2027, 1, 19, 10, 0)):
            with self.subTest(now=now):
                self._build()
                _Clock.current = now
                self.struct._set_loc_reservation_rebuild_cooldown("test_session_holiday")
                result = self.struct.run_due_loc_automation(verify=True, reason="10min_reservation_verify")
                self.assertNotIn("holiday", result, result)
                self.assertEqual(result.get("status"), "cooldown_wait", result)
                self.assertEqual(self.engine.calls, [])

    def test_off_still_does_nothing_on_a_holiday(self):
        self.struct.set_config("auto_trade_enabled", "false")
        result = self._run_worker_at(_kst(2026, 11, 26, 10, 0))
        self.assertFalse(result.get("enabled"))
        self.assertNotIn("holiday", result)
        self.assertEqual(self.engine.calls, [])


if __name__ == "__main__":
    unittest.main()
