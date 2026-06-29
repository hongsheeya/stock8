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
        return datetime.datetime(2026, 6, 25, 12, 0, 0)


class _ResponseStatus(Exception):
    def __init__(self, code, data):
        super().__init__(data.get("message", ""))
        self.code = code
        self.data = data


class _RequestStub:
    values = {}

    @classmethod
    def query(cls, key, default=None):
        return cls.values[key] if key in cls.values else default


class _ResponseStub:
    @staticmethod
    def status(code, **data):
        raise _ResponseStatus(code, data)


class _TradingStub:
    def __init__(self):
        self.configs = {
            "broker_provider": "toss",
            "toss_client_id": "tsck_saved_should_not_win",
            "toss_client_secret": "tssk_saved_should_not_win",
            "toss_account_seq": "7",
            "kis_is_real": "true",
        }

    def get_config(self, key, default=""):
        return self.configs.get(key, default)


class _StructStub:
    def __init__(self):
        self.trading = _TradingStub()


class _WizStub:
    request = _RequestStub
    response = _ResponseStub
    struct = _StructStub()

    @classmethod
    def model(cls, name):
        if name == "portal/trading/kst":
            return _TimeStub
        if name == "struct":
            return cls.struct
        raise AssertionError(f"unexpected wiz.model({name})")


_PREVIOUS_WIZ = getattr(builtins, "wiz", None)
builtins.wiz = _WizStub
settings_api_path = SRC / "app" / "page.settings" / "api.py"
settings_api_spec = importlib.util.spec_from_file_location("settings_api_under_test", settings_api_path)
settings_api = importlib.util.module_from_spec(settings_api_spec)
settings_api_spec.loader.exec_module(settings_api)
if _PREVIOUS_WIZ is None:
    try:
        delattr(builtins, "wiz")
    except AttributeError:
        pass
else:
    builtins.wiz = _PREVIOUS_WIZ


class SettingsApiPayloadTests(unittest.TestCase):
    def setUp(self):
        self._previous_wiz = getattr(builtins, "wiz", None)
        builtins.wiz = _WizStub
        _RequestStub.values = {}
        _WizStub.struct = _StructStub()
        settings_api._STRUCT_CACHE["obj"] = None
        settings_api._STRUCT_CACHE["error"] = None
        settings_api._STRUCT_CACHE["error_at"] = 0.0

    def tearDown(self):
        if self._previous_wiz is None:
            try:
                delattr(builtins, "wiz")
            except AttributeError:
                pass
        else:
            builtins.wiz = self._previous_wiz

    def test_screen_input_wins_over_saved_toss_credentials(self):
        _RequestStub.values = {
            "broker_provider": "toss",
            "toss_client_id": "tsck_screen_value",
            "toss_client_secret": "tssk_screen_value",
            "toss_account_seq": "",
            "is_mock": "false",
        }

        payload = settings_api._api_settings_payload_from_request()

        self.assertEqual(payload["toss_client_id"], "tsck_screen_value")
        self.assertEqual(payload["toss_client_secret"], "tssk_screen_value")
        self.assertEqual(payload["toss_account_seq"], "")
        self.assertEqual(payload["_input_source"], "screen")

    def test_blank_screen_secret_is_not_backfilled_from_saved_secret(self):
        _RequestStub.values = {
            "broker_provider": "toss",
            "toss_client_id": "tsck_screen_value",
            "toss_client_secret": "",
            "toss_account_seq": "",
            "is_mock": "false",
        }

        payload = settings_api._api_settings_payload_from_request()

        self.assertEqual(payload["toss_client_secret"], "")
        with self.assertRaises(_ResponseStatus) as ctx:
            settings_api._validate_api_settings_payload(payload)
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("비밀키", ctx.exception.data.get("message", ""))


if __name__ == "__main__":
    unittest.main()
