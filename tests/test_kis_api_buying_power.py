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
        return datetime.datetime(2026, 5, 29, 10, 0, 0)


class _WizStub:
    @staticmethod
    def model(name):
        if name == "portal/trading/kst":
            return _TimeStub
        raise AssertionError(f"unexpected wiz.model({name})")


class _StructStub:
    def __init__(self):
        self.configs = {
            "kis_is_real": "true",
            "kis_account_no": "12345678-01",
            "kis_app_key": "app",
            "kis_app_secret": "secret",
        }

    def get_config(self, key, default=""):
        return self.configs.get(key, default)

    def set_config(self, key, value, description="", is_secret=False):
        self.configs[key] = str(value)


builtins.wiz = _WizStub()
kis_api_path = SRC / "portal" / "trading" / "model" / "struct" / "kis_api.py"
kis_api_spec = importlib.util.spec_from_file_location("kis_api_under_test", kis_api_path)
kis_api = importlib.util.module_from_spec(kis_api_spec)
kis_api_spec.loader.exec_module(kis_api)


class KisBuyingPowerTests(unittest.TestCase):
    def test_frcr_amount_implies_executable_qty_when_kis_qty_fields_are_zero(self):
        api = kis_api.KisApi(_StructStub())
        api._request = lambda *args, **kwargs: {
            "rt_cd": "0",
            "msg1": "조회되었습니다",
            "output": {
                "ovrs_ord_psbl_amt": "0.00",
                "ord_psbl_frcr_amt": "0.00",
                "frcr_ord_psbl_amt1": "1560.584194",
                "echm_af_ord_psbl_amt": "0.00",
                "max_ord_psbl_qty": "0",
                "ord_psbl_qty": "0",
                "ovrs_max_ord_psbl_qty": "0",
                "echm_af_ord_psbl_qty": "0",
            },
        }
        api.get_balance = lambda: {"cash_balance": 0}
        api.get_present_balance = lambda: {"usd_krw": 1400, "withdrawable_krw": 0}
        api._us_auto_exchange_ready = lambda now=None: True

        info = api.get_buying_power_info(symbol="IONQ", price=70.10, exchange="NYSE")

        self.assertTrue(info["ok"])
        self.assertEqual(info["source"], "frcr_ord_psbl_amt1")
        self.assertEqual(info["broker_qty"], 0)
        self.assertEqual(info["executable_amount"], 1560.584194)
        self.assertEqual(info["executable_qty"], int(1560.584194 / 70.10))
        self.assertEqual(info["qty"], int(1560.584194 / 70.10))
        self.assertEqual(info["qty_source"], "frcr_ord_psbl_amt1:amount_implied_qty")


if __name__ == "__main__":
    unittest.main()
