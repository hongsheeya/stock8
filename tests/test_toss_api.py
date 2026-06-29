import builtins
import base64
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
        return datetime.datetime(2026, 6, 18, 17, 40, 0)


class _WizStub:
    @staticmethod
    def model(name):
        if name == "portal/trading/kst":
            return _TimeStub
        raise AssertionError(f"unexpected wiz.model({name})")

    @staticmethod
    def logger(*_args, **_kwargs):
        return None


class _StructStub:
    def __init__(self):
        self.configs = {
            "toss_client_id": "tsck_live_client",
            "toss_client_secret": "tssk_live_secret",
            "toss_account_seq": "1",
        }

    def get_config(self, key, default=""):
        return self.configs.get(key, default)

    def set_config(self, key, value, description="", is_secret=False):
        self.configs[key] = str(value)

    def _current_user_id(self):
        return self.configs.get("_user_id", "")


builtins.wiz = _WizStub()
toss_api_path = SRC / "portal" / "trading" / "model" / "struct" / "toss_api.py"
toss_api_spec = importlib.util.spec_from_file_location("toss_api_under_test", toss_api_path)
toss_api = importlib.util.module_from_spec(toss_api_spec)
toss_api_spec.loader.exec_module(toss_api)


class TossApiTests(unittest.TestCase):
    class _Response:
        def __init__(self, status_code=200, data=None, text="", headers=None):
            self.status_code = status_code
            self._data = data if data is not None else {}
            self.text = text
            self.headers = headers or {}

        def json(self):
            return self._data

    class _RequestsStub:
        def __init__(self, responses):
            self.responses = list(responses)
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append({"url": url, **kwargs})
            if not self.responses:
                raise AssertionError("unexpected post call")
            return self.responses.pop(0)

        def get(self, url, **kwargs):
            self.calls.append({"url": url, **kwargs})
            if not self.responses:
                raise AssertionError("unexpected get call")
            return self.responses.pop(0)

    def _with_requests_stub(self, responses):
        stub = self._RequestsStub(responses)
        original = toss_api.requests
        toss_api.requests = stub
        self.addCleanup(lambda: setattr(toss_api, "requests", original))
        return stub

    def test_loc_buy_uses_limit_cls_order(self):
        api = toss_api.TossApi(_StructStub())
        captured = {}

        def _fake_result(method, path, params=None, body=None, account_required=False, retries=1):
            captured.update({
                "method": method,
                "path": path,
                "body": dict(body or {}),
                "account_required": account_required,
            })
            return {"orderId": "toss-order-1"}

        api._result = _fake_result
        order = api.buy_reservation_order("SOXL", 1, price=267.57, order_type="LOC", exchange="NASD")

        self.assertEqual(order["order_no"], "toss-order-1")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["path"], "/api/v1/orders")
        self.assertTrue(captured["account_required"])
        self.assertEqual(captured["body"]["symbol"], "SOXL")
        self.assertEqual(captured["body"]["side"], "BUY")
        self.assertEqual(captured["body"]["orderType"], "LIMIT")
        self.assertEqual(captured["body"]["timeInForce"], "CLS")
        self.assertEqual(captured["body"]["quantity"], "1")
        self.assertEqual(captured["body"]["price"], "267.57")

    def test_buying_power_maps_cash_to_executable_qty(self):
        api = toss_api.TossApi(_StructStub())
        api._result = lambda *args, **kwargs: {"currency": "USD", "cashBuyingPower": "1000.00"}

        info = api.get_buying_power_info(symbol="TQQQ", price=240.0, exchange="NASD")

        self.assertEqual(info["source"], "toss_cashBuyingPower")
        self.assertEqual(info["executable_amount"], 1000.0)
        self.assertEqual(info["executable_qty"], 4)

    def test_price_uses_latest_completed_daily_candle_as_prev_close(self):
        api = toss_api.TossApi(_StructStub())
        captured_candle_params = {}

        def _fake_result(method, path, params=None, **kwargs):
            if path == "/api/v1/prices":
                return [{"symbol": "SOXL", "lastPrice": "240.00", "currency": "USD"}]
            if path == "/api/v1/candles":
                captured_candle_params.update(params or {})
                return {
                    "candles": [
                        {"timestamp": "2026-06-17T22:30:00+09:00", "closePrice": "226.76"},
                        {"timestamp": "2026-06-16T22:30:00+09:00", "closePrice": "220.00"},
                    ]
                }
            return {}

        api._result = _fake_result
        quote = api.get_current_price("SOXL", exchange="NAS")

        self.assertEqual(quote["price"], 240.0)
        self.assertEqual(quote["prev_close"], 226.76)
        self.assertEqual(captured_candle_params["symbol"], "SOXL")
        self.assertEqual(captured_candle_params["interval"], "1d")

    def test_error_decoder_handles_string_error_payload(self):
        api = toss_api.TossApi(_StructStub())

        class _Response:
            status_code = 400
            text = "bad request"

            def json(self):
                return {"error": "invalid_client"}

        with self.assertRaisesRegex(Exception, "invalid_client"):
            api._decode_response(_Response())

    def test_access_denied_error_explains_credentials_not_account_seq(self):
        api = toss_api.TossApi(_StructStub())

        class _Response:
            status_code = 403
            text = '{"error":"access_denied"}'

            def json(self):
                return {"error": "access_denied"}

        with self.assertRaisesRegex(Exception, "OpenAPI 이용 권한/약관/앱 활성화.*accountSeq"):
            api._decode_response(_Response())

    def test_token_request_uses_curl_equivalent_basic_auth(self):
        api = toss_api.TossApi(_StructStub())
        stub = self._with_requests_stub([
            self._Response(200, {"access_token": "token-1", "expires_in": 86400})
        ])

        self.assertEqual(api._issue_token(), "token-1")

        self.assertEqual(len(stub.calls), 1)
        call = stub.calls[0]
        self.assertEqual(call["url"], "https://openapi.tossinvest.com/oauth2/token")
        self.assertEqual(call["headers"]["Content-Type"], "application/x-www-form-urlencoded")
        expected_basic = base64.b64encode(b"tsck_live_client:tssk_live_secret").decode("ascii")
        self.assertEqual(call["headers"]["Authorization"], f"Basic {expected_basic}")
        self.assertEqual(call["data"], {"grant_type": "client_credentials"})
        self.assertNotIn("auth", call)
        self.assertNotIn("client_id", call["data"])
        self.assertNotIn("client_secret", call["data"])

    def test_token_request_does_not_fallback_or_use_account_seq(self):
        struct = _StructStub()
        struct.configs["toss_account_seq"] = "999999"
        api = toss_api.TossApi(struct)
        stub = self._with_requests_stub([
            self._Response(401, {"error": "invalid_client"}, headers={"WWW-Authenticate": 'Basic realm="openapi"'}),
        ])

        with self.assertRaisesRegex(Exception, "invalid_client"):
            api._issue_token()

        self.assertEqual(len(stub.calls), 1)
        call = stub.calls[0]
        self.assertEqual(call["data"], {"grant_type": "client_credentials"})
        self.assertNotIn("accountSeq", str(call))
        self.assertNotIn("999999", api._credential_scope())

    def test_token_success_uses_single_curl_equivalent_attempt(self):
        api = toss_api.TossApi(_StructStub())
        stub = self._with_requests_stub([
            self._Response(200, {"access_token": "token-2", "expires_in": 86400}),
        ])

        self.assertEqual(api._issue_token(), "token-2")

        self.assertEqual(len(stub.calls), 1)
        self.assertEqual(stub.calls[0]["data"], {"grant_type": "client_credentials"})

    def test_token_failure_reports_sanitized_diagnostics(self):
        struct = _StructStub()
        struct._toss_credential_source = "screen"
        api = toss_api.TossApi(struct)
        stub = self._with_requests_stub([
            self._Response(403, {"error": "access_denied"}),
        ])

        with self.assertRaisesRegex(Exception, "curl-equivalent"):
            api._issue_token()

        diagnostic_text = "\n".join(api.token_diagnostics())
        self.assertIn("source=screen", diagnostic_text)
        self.assertIn("authMode=basic", diagnostic_text)
        self.assertIn("endpoint=https://openapi.tossinvest.com/oauth2/token", diagnostic_text)
        self.assertIn("HTTP status=403", diagnostic_text)
        self.assertIn("error=access_denied", diagnostic_text)
        self.assertIn("prefix10=tsck_live_", diagnostic_text)
        self.assertIn("prefix10=tssk_live_", diagnostic_text)
        self.assertIn("length=", diagnostic_text)
        self.assertIn("분류=토스 OpenAPI 이용 권한/약관/앱 활성화 문제", diagnostic_text)
        self.assertNotIn("tsck_live_client", diagnostic_text)
        self.assertNotIn("tssk_live_secret", diagnostic_text)
        self.assertEqual(len(stub.calls), 1)

    def test_invalid_client_reports_key_set_problem(self):
        api = toss_api.TossApi(_StructStub())
        self._with_requests_stub([
            self._Response(401, {"error": "invalid_client"}),
        ])

        with self.assertRaisesRegex(Exception, "invalid_client"):
            api._issue_token()

        diagnostic_text = "\n".join(api.token_diagnostics())
        self.assertIn("HTTP status=401", diagnostic_text)
        self.assertIn("error=invalid_client", diagnostic_text)
        self.assertIn("분류=토스 키 세트/권한 문제", diagnostic_text)

    def test_token_2xx_without_access_token_is_app_implementation_problem(self):
        api = toss_api.TossApi(_StructStub())
        self._with_requests_stub([
            self._Response(200, {"unexpected": "shape"})
        ])

        with self.assertRaisesRegex(Exception, "token_missing"):
            api._issue_token()

        diagnostic_text = "\n".join(api.token_diagnostics())
        self.assertIn("HTTP status=200", diagnostic_text)
        self.assertIn("error=token_missing", diagnostic_text)
        self.assertIn("분류=앱 구현 문제", diagnostic_text)

    def test_connection_success_continues_to_accounts_and_reports_diagnostics(self):
        struct = _StructStub()
        struct._toss_credential_source = "screen"
        api = toss_api.TossApi(struct)
        stub = self._with_requests_stub([
            self._Response(200, {"access_token": "token-1", "expires_in": 86400}),
            self._Response(200, {"result": [{"accountSeq": "1", "accountNo": "masked-account"}]}),
        ])

        result = api.test_connection()

        self.assertTrue(result["success"])
        self.assertEqual(stub.calls[0]["url"], "https://openapi.tossinvest.com/oauth2/token")
        self.assertEqual(stub.calls[1]["url"], "https://openapi.tossinvest.com/api/v1/accounts")
        diagnostic_text = "\n".join(result["diagnostics"])
        self.assertIn("source=screen", diagnostic_text)
        self.assertIn("authMode=basic", diagnostic_text)
        self.assertIn("endpoint=https://openapi.tossinvest.com/oauth2/token", diagnostic_text)
        self.assertIn("HTTP status=200", diagnostic_text)
        self.assertIn("endpoint=https://openapi.tossinvest.com/api/v1/accounts", diagnostic_text)
        self.assertIn("분류=정상", diagnostic_text)

    def test_memory_token_is_scoped_by_user_and_credentials(self):
        struct = _StructStub()
        api = toss_api.TossApi(struct)
        issued = []

        def _issue():
            token = f"token-{len(issued) + 1}"
            issued.append(token)
            api._token = token
            api._token_expires = 9999999999
            api._token_scope = api._credential_scope()
            return token

        api._issue_token = _issue

        struct.configs["_user_id"] = "u1"
        self.assertEqual(api.get_token(), "token-1")
        self.assertEqual(api.get_token(), "token-1")
        struct.configs["_user_id"] = "u2"
        struct.configs["toss_access_token"] = ""
        struct.configs["toss_token_expires"] = "0"

        self.assertEqual(api.get_token(), "token-2")


if __name__ == "__main__":
    unittest.main()
