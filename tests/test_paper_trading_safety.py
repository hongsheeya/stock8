import builtins
import datetime
import importlib.util
import pathlib
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "portal" / "trading" / "model" / "struct" / "kis_api.py"


class _TimeStub:
    @staticmethod
    def now():
        return datetime.datetime(2026, 8, 14, 9, 0, 0)


class _WizStub:
    @staticmethod
    def model(name):
        if name == "portal/trading/kst":
            return _TimeStub
        raise AssertionError(name)


class _StructStub:
    def __init__(self):
        self.values = {
            "kis_app_key": "legacy-live-key-must-not-be-read",
            "kis_paper_app_key": "paper-key",
            "kis_paper_app_secret": "paper-secret",
            "kis_paper_account_no": "12345678-01",
            "kis_paper_access_token": "",
            "kis_paper_token_expires": "0",
        }

    def get_config(self, key, default=""):
        return self.values.get(key, default)

    def set_config(self, key, value, description="", is_secret=False):
        self.values[key] = str(value)


class PaperTradingSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_wiz = getattr(builtins, "wiz", None)
        builtins.wiz = _WizStub()
        spec = importlib.util.spec_from_file_location("paper_kis_api_under_test", MODULE_PATH)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        if cls.previous_wiz is None:
            delattr(builtins, "wiz")
        else:
            builtins.wiz = cls.previous_wiz

    def setUp(self):
        self.api = self.module.KisApi(_StructStub())

    def test_validation_deadline_is_restored(self):
        with patch.object(self.api, '_validate_paper_readiness', return_value={'success': True}):
            self.assertTrue(self.api.validate_paper_readiness()['success'])
        self.assertIsNone(getattr(self.module._REQUEST_OPTIONS, 'deadline', None))

    def test_live_token_success_is_not_account_connection_success(self):
        with patch.object(self.module, 'PAPER_MODE', False), patch.object(self.api, 'get_token', return_value='test-token'), patch.object(self.api, 'get_present_balance', side_effect=RuntimeError('mock key rejected')):
            result = self.api.test_connection()
        self.assertFalse(result['success'])
        self.assertIn('mock key rejected', result['message'])

    def test_validation_expired_deadline_does_not_wait(self):
        self.module._REQUEST_OPTIONS.deadline = 0
        try:
            with self.assertRaises(TimeoutError):
                self.api._rate_limit_wait()
        finally:
            self.module._REQUEST_OPTIONS.deadline = None

    def test_paper_mode_uses_only_paper_credentials_and_mock_url(self):
        self.assertEqual(self.api.app_key, "paper-key")
        self.assertEqual(self.api.base_url, self.module.MOCK_BASE_URL)
        self.assertFalse(self.api.is_real)

    def test_real_endpoint_is_blocked(self):
        with self.assertRaises(RuntimeError):
            self.api._assert_safe_request(
                "GET", "/uapi/domestic-stock/v1/quotations/inquire-price", "FHKST01010100",
                url=f"{self.module.REAL_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price",
            )

    def test_live_order_tr_id_is_blocked_in_paper(self):
        with self.assertRaises(RuntimeError):
            self.api._assert_safe_request(
                "POST", "/uapi/domestic-stock/v1/trading/order-cash", "TTTC0802U",
                body={"ORD_QTY": "1"},
            )

    def test_zero_quantity_is_blocked(self):
        with self.assertRaises(ValueError):
            self.api._assert_safe_request(
                "POST", "/uapi/domestic-stock/v1/trading/order-cash", "VTTC0802U",
                body={"ORD_QTY": "0"},
            )

    def test_mock_order_with_positive_quantity_passes_guard(self):
        self.api._assert_safe_request(
            "POST", "/uapi/domestic-stock/v1/trading/order-cash", "VTTC0802U",
            body={"ORD_QTY": "1"},
        )

    def test_oauth_403_is_actionable_and_redacts_credentials(self):
        class Response:
            status_code = 403

            @staticmethod
            def json():
                return {
                    "error_code": "EGW00123",
                    "error_description": "paper-secret was rejected for paper-key",
                }

        message = self.api._safe_oauth_error(Response())
        self.assertIn("HTTP 403", message)
        self.assertIn("모의투자 전용", message)
        self.assertNotIn("paper-secret", message)
        self.assertNotIn("paper-key", message)

    def test_token_issue_reuses_database_cache_inside_lock(self):
        self.api.struct.values["kis_paper_access_token"] = "cached-token"
        self.api.struct.values["kis_paper_token_expires"] = "9999999999"
        self.assertEqual(self.api._issue_token(), "cached-token")

    def test_live_orders_stay_blocked_even_with_legacy_unlock_flag(self):
        with patch.object(self.module, "PAPER_MODE", False), patch.object(self.module, "LIVE_UNLOCKED", True):
            with self.assertRaises(RuntimeError):
                self.api._assert_safe_request("POST", "/uapi/domestic-stock/v1/trading/order-cash", "TTTC0802U", body={"ORD_QTY": "1"})

    def test_live_read_only_connection_does_not_enable_trading(self):
        with patch.object(self.module, "PAPER_MODE", False), patch.object(self.module, "LIVE_UNLOCKED", False):
            self.assertEqual(self.api.base_url, self.module.REAL_BASE_URL)
            self.api._assert_safe_request('POST', '/oauth2/tokenP', 'OAUTH')
            self.api._assert_safe_request('GET', '/uapi/domestic-stock/v1/trading/inquire-balance', 'TTTC8434R')
            for path in ('order-cash', 'order-rvsecncl'):
                with self.assertRaises(RuntimeError):
                    self.api._assert_safe_request('POST', '/uapi/domestic-stock/v1/trading/' + path, 'TTTC0802U', body={'ORD_QTY': '1'})

    def test_live_credentials_never_fallback_to_paper(self):
        with patch.object(self.module, 'PAPER_MODE', False):
            self.assertEqual(self.api.app_key, '')
            self.assertEqual(self.api.app_secret, '')
            self.assertEqual(self.api.account_no, '')
            self.assertEqual(self.api.token_config_keys, ('kis_live_access_token', 'kis_live_token_expires'))

    def test_live_order_consent_is_rechecked_for_each_submission(self):
        from types import SimpleNamespace
        consent = {"value": "true"}
        def authorize(symbol):
            if consent['value'] != 'true':
                raise RuntimeError('Strategy OFF or symbol locked')
        self.api.struct.order_policy = SimpleNamespace(assert_order=authorize)
        with patch.object(self.module, "PAPER_MODE", False), patch.object(self.module, "LIVE_UNLOCKED", True):
            self.api._assert_safe_request("POST", "/uapi/domestic-stock/v1/trading/order-cash", "TTTC0802U", body={"ORD_QTY": "1"})
            consent["value"] = "false"
            with self.assertRaises(RuntimeError):
                self.api._assert_safe_request("POST", "/uapi/domestic-stock/v1/trading/order-cash", "TTTC0802U", body={"ORD_QTY": "1"})

    def test_lock_changed_during_rate_wait_blocks_network_post(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        locked = {'value': False}
        def authorize(symbol):
            if locked['value']:
                raise RuntimeError('Symbol locked')
        self.api.struct.order_policy = SimpleNamespace(assert_order=authorize)
        self.api._headers = lambda tr_id: {}
        self.api._rate_limit_wait = lambda: locked.update(value=True)
        client = Mock()
        self.api._session = client
        with patch.object(self.module, 'PAPER_MODE', False):
            with self.assertRaises(RuntimeError):
                self.api._request('POST', '/uapi/domestic-stock/v1/trading/order-cash', 'TTTC0802U', body={'PDNO': '005930', 'ORD_QTY': '1'})
        client.post.assert_not_called()

    def test_fill_query_uses_current_tr_and_does_not_hide_broker_error(self):
        calls = []
        def request(method, path, tr_id, **kwargs):
            calls.append(tr_id)
            return {"rt_cd": "1", "msg1": "없는 서비스 코드"}
        self.api._request = request
        with self.assertRaisesRegex(RuntimeError, "체결 조회 실패"):
            self.api.get_domestic_fills_for_day("20260904")
        self.assertEqual(calls, ["VTTC0081R"])

    def test_empty_stock_balance_does_not_count_cash_as_stock_exposure(self):
        self.api._request = lambda *a, **k: {"rt_cd": "0", "output1": [], "output2": [{
            "evlu_amt_smtl_amt": "0", "scts_evlu_amt": "100000000", "tot_evlu_amt": "100000000", "dnca_tot_amt": "100000000"}]}
        result = self.api.get_domestic_balance()
        self.assertEqual(result["portfolio_eval_krw"], 0)
        self.assertEqual(result["total_asset_krw"], 100000000)

    def test_gateway_budget_survives_model_reload(self):
        spec = importlib.util.spec_from_file_location("reloaded_paper_kis", MODULE_PATH)
        other = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(other)
        self.assertIs(other._GATEWAY_STATE, self.module._GATEWAY_STATE)
        self.assertIs(other.KisApi._token_issue_lock, self.module.KisApi._token_issue_lock)
        with patch.dict(self.module._GATEWAY_STATE, {"last": 99.8, "blocked_until": 0}), patch.object(other.time, "monotonic", return_value=100), patch.object(other.time, "sleep") as sleep:
            other.KisApi(_StructStub())._rate_limit_wait()
            self.assertAlmostEqual(sleep.call_args.args[0], 0.9)

    def test_reset_account_cannot_sell_stale_local_holdings(self):
        self.api.get_balance = lambda **kwargs: {"holdings": []}
        self.api._request = lambda *a, **k: self.fail("must not submit a stale position")
        with self.assertRaisesRegex(RuntimeError, "보유수량 불일치"):
            self.api.sell_order("TQQQ", 98, price=80)

    def test_broker_balance_failure_is_not_an_empty_account(self):
        self.api._request = lambda *a, **k: {"rt_cd": "1", "msg1": "gateway unavailable"}
        with self.assertRaisesRegex(RuntimeError, "잔고 조회 불완전"):
            self.api.get_balance(exchange="NASD")


if __name__ == "__main__":
    unittest.main()
