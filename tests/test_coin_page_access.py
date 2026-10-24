"""Coin page (10-22): admin-only controller, keys never echoed, PAPER refuses edits."""
import json
import importlib.util
import os
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1] / "src"


class Status(Exception):
    def __init__(self, code, data):
        super().__init__(code)
        self.code, self.data = code, data


def _status(code=200, **data):
    raise Status(code, data)


class ControllerTests(unittest.TestCase):
    def run_controller(self, uid, user):
        class Base:
            def __init__(self):
                pass

        wiz = NS(controller=lambda name: Base, session=NS(get=lambda key: uid if key == "id" else None),
                 model=lambda name: NS(user=NS(get=lambda id=None: user)), response=NS(status=_status))
        env = {"wiz": wiz, "__name__": "coin_controller"}
        exec(compile((ROOT / "controller" / "coin.py").read_text(encoding="utf-8"), "coin.py", "exec"), env)
        env["Controller"]()

    def test_page_uses_the_coin_controller(self):
        app = json.loads((ROOT / "app" / "page.coin" / "app.json").read_text(encoding="utf-8"))
        self.assertEqual(app["controller"], "coin")
        self.assertEqual(app["layout"], "layout.trading")

    def test_non_admin_is_refused(self):
        for uid, user in (("u1", {"role": "user", "email": "a@b.c"}), ("u2", None), ("", None)):
            with self.subTest(uid=uid):
                with self.assertRaises(Status) as ctx:
                    self.run_controller(uid, user)
                self.assertEqual(ctx.exception.code, 403)

    def test_admin_passes(self):
        self.run_controller("a1", {"role": "admin", "email": "x@y.z"})
        self.run_controller("a2", {"role": "user", "email": "gigukbyun@gmail.com"})


class ApiTests(unittest.TestCase):
    def load_api(self, mode="LIVE", query=None):
        os.environ["TRADING_MODE"] = mode
        self.addCleanup(os.environ.pop, "TRADING_MODE", None)
        written = {}
        engine_cls = NS(ALL_MARKETS=("KRW-BTC", "KRW-ETH"), DEFAULT_MARKETS=("KRW-BTC",), SEED_MIN=50000, SEED_MAX=10000000,
                        STATUS={}, account_fingerprint=lambda k: "fp" if k else "")
        policy = {"mode": "off", "seed_krw": 1000000, "markets": ["KRW-BTC"], "max_order_krw": 0, "live_confirmed_at": "",
                  "updated_at": "", "owner_user_id": "a1", "account_fp": ""}
        trading = NS(coin_policy_read=lambda: dict(policy), coin_keys=lambda uid: ("A" * 40, "S" * 40),
                     coin_worker_status=lambda: {"alive": True, "status": "off"},
                     coin_data_dirs=lambda owner: ("/nonexistent", "/nonexistent", "/nonexistent"),
                     db=lambda name: NS(rows=lambda **kw: []),
                     coin_save_keys=lambda uid, a, s: written.update(uid=uid, a=a, s=s),
                     coin_policy_write=lambda upd: written.setdefault("policy", []).append(upd) or {**policy, **upd},
                     coin_alert_settings=lambda uid: dict(alerts),
                     coin_save_alert_settings=lambda uid, **kw: written.setdefault("alerts", []).append(kw))
        alerts = {"webhook": "", "hc_url": "", "notify_shadow": True}
        self.alerts = alerts
        spec = importlib.util.spec_from_file_location("t_notifier_page", ROOT / "portal" / "trading" / "model" / "notifier.py")
        notifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(notifier)
        models = {"struct": NS(trading=trading), "portal/trading/coin_engine": engine_cls,
                  "portal/trading/notifier": notifier.NotifierModel}
        q = dict(query or {})
        wiz = NS(model=lambda name: models[name], session=NS(get=lambda key: "a1"),
                 request=NS(query=lambda key, default=None: q.get(key, default)), response=NS(status=_status))
        env = {"wiz": wiz, "__name__": "coin_api"}
        exec(compile((ROOT / "app" / "page.coin" / "api.py").read_text(encoding="utf-8"), "api.py", "exec"), env)
        return env, written

    def call(self, env, name):
        with self.assertRaises(Status) as ctx:
            env[name]()
        return ctx.exception

    def test_alert_urls_are_validated_and_saved(self):
        env, written = self.load_api(query={"webhook": "https://evil.example/hook"})[:2]
        res = self.call(env, "save_alerts")
        self.assertEqual(res.code, 400)
        env, written = self.load_api(query={"webhook": "https://discord.com/api/webhooks/1/abc", "notify_shadow": "false"})[:2]
        res = self.call(env, "save_alerts")
        self.assertEqual(res.code, 200)
        self.assertEqual(written["alerts"][-1], {"webhook": "https://discord.com/api/webhooks/1/abc", "hc_url": None, "notify_shadow": False})
        env, _w = self.load_api(mode="PAPER", query={"webhook": "https://discord.com/api/webhooks/1/abc"})[:2]
        self.assertEqual(self.call(env, "save_alerts").code, 409)

    def test_status_never_contains_the_keys(self):
        env, _ = self.load_api()
        res = self.call(env, "status")
        self.assertEqual(res.code, 200)
        text = json.dumps(res.data, ensure_ascii=False)
        self.assertNotIn("A" * 8, text)
        self.assertNotIn("S" * 8, text)
        self.assertEqual(res.data["keys"], {"configured": True, "access_hint": "…AAAA"})

    def test_paper_server_refuses_every_edit(self):
        env, written = self.load_api("PAPER", {"access_key": "A" * 40, "secret_key": "S" * 40, "mode": "live"})
        for name in ("save_keys", "delete_keys", "test_connection", "save_settings", "set_mode", "resume"):
            with self.subTest(name=name):
                self.assertEqual(self.call(env, name).code, 409)
        self.assertEqual(written, {})

    def test_live_mode_needs_a_recent_connection_test_and_the_phrase(self):
        env, written = self.load_api("LIVE", {"mode": "live", "confirm": "실거래 시작"})
        res = self.call(env, "set_mode")
        self.assertEqual(res.code, 400)
        self.assertIn("연결 테스트", res.data["message"])
        self.assertNotIn("policy", written)

    def test_bad_keys_are_rejected(self):
        env, written = self.load_api("LIVE", {"access_key": "short", "secret_key": "S" * 40})
        self.assertEqual(self.call(env, "save_keys").code, 400)
        self.assertEqual(written, {})


if __name__ == "__main__":
    unittest.main()
