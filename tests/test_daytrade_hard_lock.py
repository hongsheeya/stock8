import builtins
import datetime
import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class _TimeStub:
    @staticmethod
    def now():
        return datetime.datetime(2026, 6, 18, 10, 0, 0)


class _DaytradeStub:
    def __init__(self, _struct):
        pass


class _WizStub:
    @staticmethod
    def model(name):
        if name == "portal/trading/kst":
            return _TimeStub
        if name == "portal/trading/struct/daytrade":
            return _DaytradeStub
        raise AssertionError(f"unexpected wiz.model({name})")


class _StructStub:
    daytrade_hard_locked = True
    daytrade_lock_message = "단타 기능은 현재 운영 안정화를 위해 완전히 봉인되어 있습니다."

    def get_config(self, _key, default=""):
        return default


builtins.wiz = _WizStub()
engine_path = SRC / "portal" / "trading" / "model" / "struct" / "daytrade_engine.py"
engine_spec = importlib.util.spec_from_file_location("daytrade_engine_hard_lock_under_test", engine_path)
engine_module = importlib.util.module_from_spec(engine_spec)
engine_spec.loader.exec_module(engine_module)


class DaytradeHardLockTests(unittest.TestCase):
    def setUp(self):
        builtins.wiz = _WizStub()

    def test_auto_cycle_is_blocked_by_hard_lock(self):
        engine = engine_module.DomesticDaytradeEngine(_StructStub())

        self.assertFalse(engine.auto_enabled())
        result = engine.auto_cycle(requested_seed=5000000)

        self.assertFalse(result["executed"])
        self.assertTrue(result["hard_locked"])
        self.assertIn("봉인", result["message"])

    def test_manual_sell_is_blocked_before_state_or_order(self):
        engine = engine_module.DomesticDaytradeEngine(_StructStub())

        with self.assertRaisesRegex(Exception, "봉인"):
            engine.manual_sell("005930", market="KS")


if __name__ == "__main__":
    unittest.main()
