"""The volume_breakout preflight's spread guard needs a real orderbook call.

It called KisApi.search_realtime_hoga, which never existed, so every
preflight logged "'KisApi' object has no attribute 'search_realtime_hoga'"
and the spread check never ran.
"""
import unittest

from test_kis_api_buying_power import _StructStub as _KisStruct, kis_api
from test_daytrade_engine_regressions import _engine_with_state


class OrderbookTests(unittest.TestCase):
    def test_best_ask_and_bid_come_from_output1(self):
        api = kis_api.KisApi(_KisStruct())
        calls = []

        def request(method, path, tr_id, params=None, **_kwargs):
            calls.append((tr_id, params["FID_INPUT_ISCD"]))
            return {"rt_cd": "0", "output1": {"askp1": "1247", "bidp1": "1246", "askp_rsqn1": "5000", "bidp_rsqn1": "7000"}}

        api._request = request
        hoga = api.search_realtime_hoga("114800", "KS")
        self.assertEqual(calls, [("FHKST01010200", "114800")])
        self.assertEqual((hoga["askp1"], hoga["bidp1"], hoga["bidp_rsqn1"]), (1247.0, 1246.0, 7000))

    def test_us_symbols_skip_the_domestic_call(self):
        api = kis_api.KisApi(_KisStruct())
        api._request = lambda *_a, **_k: self.fail("domestic orderbook called for a US symbol")
        self.assertEqual(api.search_realtime_hoga("TQQQ", "US"), {})

    def test_error_is_raised_for_the_preflight_to_log(self):
        api = kis_api.KisApi(_KisStruct())
        api._request = lambda *_a, **_k: {"rt_cd": "1", "msg1": "조회 실패"}
        with self.assertRaises(Exception):
            api.search_realtime_hoga("114800", "KS")


class PreflightSpreadTests(unittest.TestCase):
    def _issues(self, ask, bid):
        engine, _ = _engine_with_state({}, [])
        engine._broker = lambda: type("B", (), {"search_realtime_hoga": lambda self, s, m: {"askp1": ask, "bidp1": bid}})()
        engine._append_runtime_log = lambda *a, **k: self.fail("preflight logged an orderbook failure")
        bar = {"close": 1010, "vwap": 1005, "breakout_high_20": 1000}
        return engine._breakout_preflight_check("114800", "KS", bar, {"max_hoga_spread_pct": 0.3})

    def test_tight_spread_passes(self):
        self.assertEqual(self._issues(1011, 1010), [])

    def test_wide_spread_blocks_the_entry(self):
        issues = self._issues(1015, 1010)
        self.assertEqual(len(issues), 1)
        self.assertIn("호가 스프레드 과다", issues[0])


if __name__ == "__main__":
    unittest.main()
