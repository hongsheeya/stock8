"""KRW amounts of the overseas present balance come from output3 only (11-28).

output2 rows are per currency; their foreign fields (frcr_dncl_amt_2,
frcr_evlu_amt2) used to fill KRW cash/withdrawable when output3 had no KRW
cash, and the USD deposit was then counted again as a KRW auto-exchange.
"""
import builtins
import datetime
import importlib.util
import pathlib
import sys
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class _TimeStub:
    @staticmethod
    def now():
        return datetime.datetime(2026, 11, 28, 10, 0, 0)


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
_spec = importlib.util.spec_from_file_location(
    "kis_api_present_krw_under_test", SRC / "portal" / "trading" / "model" / "struct" / "kis_api.py")
kis_api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kis_api)

USD_ROW = {"crcy_cd": "USD", "frst_bltn_exrt": "1342.70", "frcr_dncl_amt_2": "1305204",
           "frcr_evlu_amt2": "1305204", "frcr_drwg_psbl_amt_1": "972.08"}


def _api(output3, output2=None, psamount=None):
    api = kis_api.KisApi(_StructStub())

    def request(method, path, tr_id, **kwargs):
        if path.endswith("inquire-present-balance"):
            return {"rt_cd": "0", "output2": [USD_ROW] if output2 is None else output2, "output3": output3}
        if path.endswith("inquire-psamount"):
            return {"rt_cd": "0", "output": psamount or {
                "ovrs_ord_psbl_amt": "972.08", "max_ord_psbl_qty": "27", "echm_af_ord_psbl_amt": "0"}}
        raise AssertionError(f"unexpected request {path}")

    api._request = request
    api._get_usd_krw_rate_fallback = lambda: {"rate": 0, "source": ""}
    return api


class PresentBalanceKrwFromSummaryTests(unittest.TestCase):
    def setUp(self):
        self._paper = patch.object(kis_api, "PAPER_MODE", False)
        self._paper.start()
        self.addCleanup(self._paper.stop)

    def test_zero_krw_cash_in_output3_is_not_filled_with_the_usd_deposit(self):
        info = _api({"tot_dncl_amt": "0", "dncl_amt": "0", "wdrw_psbl_tot_amt": "0",
                     "tot_asst_amt": "1305204"}).get_present_balance()
        self.assertEqual(info["krw_balance"], 0)
        self.assertEqual(info["withdrawable_krw"], 0)
        self.assertEqual(info["meta"]["krw_key"], "tot_dncl_amt")
        self.assertEqual(info["meta"]["withdrawable_key"], "wdrw_psbl_tot_amt")
        self.assertTrue(info["meta"]["withdrawable_present"])
        # The USD side is still read from the USD row.
        self.assertEqual(info["usd_krw"], 1342.7)
        self.assertEqual(info["usd_cash_usd"], 972.08)

    def test_missing_krw_fields_stay_unknown_instead_of_taking_currency_row_fields(self):
        info = _api({"tot_asst_amt": "1305204"}).get_present_balance()
        self.assertEqual(info["krw_balance"], 0)
        self.assertEqual(info["withdrawable_krw"], 0)
        self.assertFalse(info["meta"]["krw_present"])
        self.assertFalse(info["meta"]["withdrawable_present"])
        self.assertIsNone(info["meta"]["krw_key"])
        self.assertIsNone(info["meta"]["withdrawable_key"])

    def test_krw_amounts_in_output3_are_read_as_before(self):
        info = _api({"tot_dncl_amt": "1219202", "wdrw_psbl_tot_amt": "1100000"}).get_present_balance()
        self.assertEqual(info["krw_balance"], 1219202)
        self.assertEqual(info["withdrawable_krw"], 1100000)
        self.assertEqual(info["meta"]["krw_key"], "tot_dncl_amt")
        self.assertEqual(info["meta"]["withdrawable_key"], "wdrw_psbl_tot_amt")

        # Order of output3 keys is unchanged: zero withdrawable falls to the deposit total.
        info = _api({"tot_dncl_amt": "50000", "wdrw_psbl_tot_amt": "0"}).get_present_balance()
        self.assertEqual(info["withdrawable_krw"], 50000)
        self.assertEqual(info["meta"]["withdrawable_key"], "tot_dncl_amt")

    def test_usd_cash_is_not_counted_twice_as_a_krw_auto_exchange(self):
        api = _api({"tot_dncl_amt": "0", "wdrw_psbl_tot_amt": "0"})
        api.get_balance = lambda: {"cash_balance": 972.08}
        api._us_auto_exchange_ready = lambda now=None: False
        info = api.get_buying_power_info("SOXL", 35.85, "AMEX")
        self.assertEqual(info["krw_auto_exchange_estimate_usd"], 0.0)
        self.assertEqual(info["estimated_amount"], 972.08)
        self.assertEqual(info["estimated_qty"], 27)

        # Real KRW cash still shows as a KRW auto-exchange estimate.
        api = _api({"tot_dncl_amt": "134270", "wdrw_psbl_tot_amt": "134270"})
        api.get_balance = lambda: {"cash_balance": 972.08}
        api._us_auto_exchange_ready = lambda now=None: False
        info = api.get_buying_power_info("SOXL", 35.85, "AMEX")
        self.assertAlmostEqual(info["krw_auto_exchange_estimate_usd"], 100.0, places=2)
        self.assertAlmostEqual(info["estimated_amount"], 1072.08, places=2)


if __name__ == "__main__":
    unittest.main()
