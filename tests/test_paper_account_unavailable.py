"""11-16~ PAPER: KIS stopped taking orders from the mock account and then
answered every account call with "모의투자 신청내역을 확인하세요", while the
token kept working and the dashboard header kept saying 연결됨. kis_api now
records that answer and the dashboard shows it beside the connection state
(api_connected itself is unchanged)."""
import ast
import builtins
import datetime
import importlib.util
import pathlib
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
KIS_PATH = ROOT / "src" / "portal" / "trading" / "model" / "struct" / "kis_api.py"
DASHBOARD_PATH = ROOT / "src" / "app" / "page.dashboard" / "api.py"
ENGINE_PATH = ROOT / "src" / "portal" / "trading" / "model" / "struct" / "daytrade_engine.py"

UNREGISTERED = "모의투자 신청내역을 확인하세요.                                                 "
ORDER_REFUSED = "모의투자 주문이 불가한 계좌입니다."
AT_KEY = "kis_paper_account_unavailable_at"
REASON_KEY = "kis_paper_account_unavailable_reason"


class _TimeStub:
    current = datetime.datetime(2026, 11, 17, 9, 0, 0)

    @classmethod
    def now(cls):
        return cls.current


class _WizStub:
    @staticmethod
    def model(name):
        if name == "portal/trading/kst":
            return _TimeStub
        raise AssertionError(name)


class _StructStub:
    def __init__(self):
        self.values = {
            "kis_paper_app_key": "paper-key",
            "kis_paper_app_secret": "paper-secret",
            "kis_paper_account_no": "12345678-01",
            "kis_paper_access_token": "",
            "kis_paper_token_expires": "0",
            "kis_paper_readiness_scope": "verified-scope",
        }
        self.writes = []

    def get_config(self, key, default=""):
        return self.values.get(key, default)

    def set_config(self, key, value, description="", is_secret=False):
        self.writes.append(key)
        self.values[key] = str(value)


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.headers = {}
        self.status_code = 200

    def json(self):
        return dict(self._payload)


class KisApiAccountStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_wiz = getattr(builtins, "wiz", None)
        builtins.wiz = _WizStub()
        spec = importlib.util.spec_from_file_location("paper_account_kis_api_under_test", KIS_PATH)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        if cls.previous_wiz is None:
            delattr(builtins, "wiz")
        else:
            builtins.wiz = cls.previous_wiz

    def setUp(self):
        self.struct = _StructStub()
        self.api = self.module.KisApi(self.struct)
        self.api._log = Mock()

    def _note(self, path, payload, method="GET"):
        # path documents the call; the hook itself only needs the method.
        with patch.object(self.module, "PAPER_MODE", True):
            self.api._note_paper_account_state(method, payload)

    def test_unregistered_answer_marks_the_account(self):
        self._note("/uapi/overseas-stock/v1/trading/inquire-balance", {"rt_cd": "1", "msg1": UNREGISTERED})
        self.assertEqual(self.struct.values[AT_KEY], "2026-11-17 09:00:00")
        self.assertEqual(self.struct.values[REASON_KEY], "모의투자 신청내역을 확인하세요.")
        # Display only: the settings validation result is left alone.
        self.assertEqual(self.struct.values["kis_paper_readiness_scope"], "verified-scope")

    def test_order_refusal_alone_is_not_recorded(self):
        # 11-16 reads still worked; the next read would clear it and the chip
        # would flicker. Refused orders are the engine account halt's job.
        self._note("/uapi/domestic-stock/v1/trading/order-cash", {"rt_cd": "1", "msg1": ORDER_REFUSED})
        self.assertNotIn(AT_KEY, self.struct.values)

    def test_first_time_is_kept_and_repeats_do_not_write(self):
        self._note("/uapi/domestic-stock/v1/trading/inquire-balance", {"rt_cd": "1", "msg1": UNREGISTERED})
        writes = len(self.struct.writes)
        _TimeStub.current = datetime.datetime(2026, 11, 18, 9, 0, 0)
        try:
            for _ in range(5):
                self._note("/uapi/domestic-stock/v1/trading/inquire-balance", {"rt_cd": "1", "msg1": UNREGISTERED})
        finally:
            _TimeStub.current = datetime.datetime(2026, 11, 17, 9, 0, 0)
        self.assertEqual(self.struct.values[AT_KEY], "2026-11-17 09:00:00")
        self.assertEqual(len(self.struct.writes), writes)

    def test_other_errors_do_not_mark(self):
        for msg in ("초당 거래건수를 초과하였습니다.", "없는 서비스 코드 입니다", "모의투자 주문처리가 안되었습니다(매매불가 종목)",
                    ORDER_REFUSED, "ERROR : INPUT INVALID_CHECK_ACNO", "모의투자 영업일이 아닙니다."):
            self._note("/uapi/domestic-stock/v1/trading/order-cash", {"rt_cd": "1", "msg1": msg})
        self.assertNotIn(AT_KEY, self.struct.values)
        self.assertEqual(self.struct.values["kis_paper_readiness_scope"], "verified-scope")

    def test_a_later_successful_call_does_not_flip_it_back(self):
        # One exchange can fail while another answers; only a passing
        # connection test or new settings clear the record.
        self._note("/uapi/overseas-stock/v1/trading/inquire-balance", {"rt_cd": "1", "msg1": UNREGISTERED})
        self._note("/uapi/domestic-stock/v1/trading/inquire-balance", {"rt_cd": "0", "msg1": "정상처리 되었습니다."})
        self._note("/uapi/domestic-stock/v1/quotations/inquire-price", {"rt_cd": "0", "msg1": "정상처리 되었습니다."})
        self.assertTrue(self.struct.values[AT_KEY])

    def test_orders_never_touch_the_record(self):
        self._note("/uapi/domestic-stock/v1/trading/order-cash", {"rt_cd": "1", "msg1": UNREGISTERED}, method="POST")
        self.assertNotIn(AT_KEY, self.struct.values)

    def test_successful_and_unrelated_replies_do_no_config_io(self):
        reads = []
        original = self.struct.get_config
        self.struct.get_config = lambda key, default="": (reads.append(key), original(key, default))[1]
        self._note("/uapi/domestic-stock/v1/trading/inquire-balance", {"rt_cd": "0", "msg1": "정상처리 되었습니다."})
        self._note("/uapi/domestic-stock/v1/trading/inquire-balance", {"rt_cd": "1", "msg1": "초당 거래건수를 초과하였습니다."})
        self.assertEqual(reads, [])
        self.assertEqual(self.struct.writes, [])

    def test_live_never_records_anything(self):
        with patch.object(self.module, "PAPER_MODE", False):
            self.api._note_paper_account_state("/uapi/domestic-stock/v1/trading/inquire-balance", {"rt_cd": "1", "msg1": UNREGISTERED})
        self.assertNotIn(AT_KEY, self.struct.values)
        self.assertEqual(self.struct.values["kis_paper_readiness_scope"], "verified-scope")

    def test_bookkeeping_failure_never_escapes(self):
        def broken(*args, **kwargs):
            raise RuntimeError("db locked")
        self.struct.set_config = broken
        self._note("/uapi/domestic-stock/v1/trading/inquire-balance", {"rt_cd": "1", "msg1": UNREGISTERED})
        self._note("/uapi/domestic-stock/v1/trading/inquire-balance", None)

    def test_send_request_records_it_and_returns_the_reply_unchanged(self):
        reply = {"rt_cd": "1", "msg_cd": "40580000", "msg1": UNREGISTERED}
        client = Mock()
        client.get.return_value = _Response(reply)
        self.api._session = client
        self.api._headers = lambda tr_id: {}
        self.api._rate_limit_wait = lambda: None
        with patch.object(self.module, "PAPER_MODE", True):
            data = self.api._send_request("GET", "/uapi/domestic-stock/v1/trading/inquire-balance-test-only", "VTTC8434R",
                                          params={"probe": "account-state"}, retries=0)
        self.assertEqual(data["rt_cd"], "1")
        self.assertEqual(data["msg1"], UNREGISTERED)
        self.assertTrue(self.struct.values[AT_KEY])
        client.get.assert_called_once()

    def test_new_settings_clear_it(self):
        self.struct.values[AT_KEY] = "2026-11-17 09:00:00"
        self.struct.values[REASON_KEY] = "모의투자 신청내역을 확인하세요."
        with patch.object(self.module, "PAPER_MODE", True):
            self.api.save_settings("new-key", "new-secret", "87654321-01", is_real=False)
        self.assertEqual(self.struct.values[AT_KEY], "")
        self.assertEqual(self.struct.values[REASON_KEY], "")

    def test_passing_readiness_check_clears_it(self):
        self.struct.values[AT_KEY] = "2026-11-17 09:00:00"
        api = self.api
        with patch.object(self.module, "PAPER_MODE", True), \
                patch.object(api, "get_token", return_value="token"), \
                patch.object(api, "get_domestic_balance", return_value={"holdings": []}), \
                patch.object(api, "get_balance", return_value={"holdings": []}), \
                patch.object(api, "get_domestic_current_price", return_value={"price": 1}), \
                patch.object(api, "get_current_price", return_value={"price": 1}), \
                patch.object(api, "get_domestic_buying_power_info", return_value={"amount": 1}), \
                patch.object(api, "get_buying_power_info", return_value={"amount": 1}):
            self.assertTrue(api._validate_paper_readiness()["success"])
        self.assertEqual(self.struct.values[AT_KEY], "")


def _load_dashboard_function(name, paper_mode=True):
    tree = ast.parse(DASHBOARD_PATH.read_text(encoding="utf-8-sig"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = {"_PAPER_MODE": paper_mode}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<" + name + ">", "exec"), scope)
    return scope[name]


def _load_connection_status(paper_mode=True):
    tree = ast.parse(DASHBOARD_PATH.read_text(encoding="utf-8-sig"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_kis_connection_status")
    clock = [100.0]
    scope = {
        "time": SimpleNamespace(monotonic=lambda: clock[0]),
        "_dashboard_cache_scope": lambda: "account",
        "_KIS_STATUS_CACHE": {},
        "_PAPER_MODE": paper_mode,
        "_KIS_STATUS_SUCCESS_TTL_SEC": 20,
        "_KIS_STATUS_FAILURE_TTL_SEC": 3,
        "_KIS_STICKY_SUCCESS_GRACE_SEC": 180,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<connection-status>", "exec"), scope)
    return scope["_kis_connection_status"]


class DashboardConnectionTests(unittest.TestCase):
    def _trading(self, values):
        broker = SimpleNamespace(_readiness_scope=lambda: "verified-scope",
                                 app_key="k", app_secret="s", account_no="a",
                                 has_valid_cached_token=lambda ttl: True,
                                 test_connection=lambda: {"success": True, "message": "ok"})
        return SimpleNamespace(get_config=lambda key, default="": values.get(key, default), broker_api=broker)

    def test_issue_is_reported_beside_the_connection(self):
        issue = _load_dashboard_function("_paper_account_issue")(self._trading({
            AT_KEY: "2026-11-17 09:00:00",
            REASON_KEY: "모의투자 신청내역을 확인하세요.",
        }))
        self.assertEqual(issue, {"since": "2026-11-17 09:00", "reason": "모의투자 신청내역을 확인하세요."})

    def test_no_issue_without_a_record_or_in_live(self):
        self.assertEqual(_load_dashboard_function("_paper_account_issue")(self._trading({})), {})
        live = _load_dashboard_function("_paper_account_issue", paper_mode=False)
        self.assertEqual(live(self._trading({AT_KEY: "2026-11-17 09:00:00"})), {})

    def test_connection_state_itself_is_unchanged(self):
        # api_connected stays as before, so balance reads, their failure banner
        # and the profit totals are not affected by the record.
        status = _load_connection_status()(self._trading({
            "kis_paper_readiness_scope": "verified-scope",
            AT_KEY: "2026-11-17 09:00:00",
        }))
        self.assertTrue(status["success"])
        self.assertEqual(status["message"], "KIS READY")

    def test_overview_payload_carries_the_issue(self):
        source = DASHBOARD_PATH.read_text(encoding="utf-8-sig")
        self.assertIn('"paper_account_unavailable": _paper_account_issue(trading)', source)
        view = (DASHBOARD_PATH.parent / "view.pug").read_text(encoding="utf-8")
        self.assertIn("paperAccountIssue", view)
        self.assertNotIn("@", view.split("KIS 모의투자 계좌를 쓸 수 없습니다", 1)[1].split("\n", 3)[1])


class EngineAccountRejectionTests(unittest.TestCase):
    def test_unregistered_mock_account_halts_like_a_refused_account(self):
        tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8-sig"))
        engine = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "DomesticDaytradeEngine")
        markers = next(n for n in engine.body if isinstance(n, ast.Assign)
                       and any(getattr(t, "id", "") == "_ACCOUNT_REJECT_MARKERS" for t in n.targets))
        values = ast.literal_eval(markers.value)
        self.assertIn("주문이 불가한 계좌", values)
        self.assertIn("모의투자 신청내역", values)


if __name__ == "__main__":
    unittest.main()
