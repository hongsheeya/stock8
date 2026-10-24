"""Coin alerts (10-24): Discord messages and healthchecks.io heartbeat never
break the caller; the worker watchdog sends each notice once."""
import ast
import importlib.util
import time as _time
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("t_notifier", ROOT / "src/portal/trading/model/notifier.py")
N = importlib.util.module_from_spec(spec)
spec.loader.exec_module(N)

HOOK = "https://discord.com/api/webhooks/123/abcDEF"
HC = "https://hc-ping.com/0f0e0d0c-aaaa-bbbb-cccc-000000000000"


def _struct_methods(*names):
    tree = ast.parse((ROOT / "src/portal/trading/model/struct.py").read_text(encoding="utf-8-sig"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Struct")
    defs = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    consts = [n for n in tree.body if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id.startswith(("_COIN_ALERT", "_COIN_HEARTBEAT", "_COIN_ERROR_ALERT")) for t in n.targets)]
    scope = {"time": _time}
    exec(compile(ast.Module(body=consts + defs, type_ignores=[]), "<struct>", "exec"), scope)
    return scope


class NotifierTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.clock = [1000.0]
        self.n = N.Notifier(post=lambda url, payload: self.sent.append((url, payload)), clock=lambda: self.clock[0])

    def test_only_official_hosts_are_accepted(self):
        self.assertTrue(N.valid_discord(HOOK))
        self.assertFalse(N.valid_discord("http://discord.com/api/webhooks/1/x"))
        self.assertFalse(N.valid_discord("https://evil.example/api/webhooks/1/x"))
        self.assertTrue(N.valid_hc(HC))
        self.assertFalse(N.valid_hc("https://example.com/ping"))
        self.assertFalse(self.n.discord("https://evil.example/x", "hi"))

    def test_duplicates_within_a_minute_are_dropped(self):
        self.n._ensure_thread = lambda: None
        self.assertTrue(self.n.discord(HOOK, "same"))
        self.assertFalse(self.n.discord(HOOK, "same"))
        self.clock[0] += 61
        self.assertTrue(self.n.discord(HOOK, "same"))

    def test_delivery_and_failures_are_recorded(self):
        self.assertTrue(self.n.deliver("discord", HOOK, "hello"))
        self.assertEqual(self.sent[-1], (HOOK, {"content": "hello"}))
        self.assertTrue(self.n.deliver("ping", HC + "/fail", None))

        def refuse(url, payload):
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        bad = N.Notifier(post=refuse)
        self.assertFalse(bad.deliver("discord", HOOK, "x"))
        self.assertEqual(N.STATE["last_error"], "HTTP 404")
        ok, msg = bad.send_now(HOOK, "x")
        self.assertFalse(ok)
        self.assertIn("404", msg)


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        scope = _struct_methods("_coin_watchdog", "_coin_alert", "_coin_notify")
        self.msgs, self.pings = [], []
        sender = NS(discord=lambda url, text: self.msgs.append(text), ping=lambda url, fail=False: self.pings.append(fail))
        self.settings = {"webhook": HOOK, "hc_url": HC, "notify_shadow": True}
        self.self = NS(coin_alert_settings=lambda owner: dict(self.settings),
                       coin_policy_read=lambda: {"owner_user_id": "admin-1"},
                       model=lambda name: NS(shared=lambda: sender))
        for name in ("_coin_watchdog", "_coin_alert", "_coin_notify"):
            setattr(self.self, name, scope[name].__get__(self.self))

    def policy(self, mode):
        return {"mode": mode, "owner_user_id": "admin-1"}

    def test_start_mode_change_errors_and_recovery_are_announced_once(self):
        watch, reg = {}, {"status": "shadow"}
        eng = NS(state={"last_decision_bar_end": int(_time.time()) // 14400 * 14400})
        self.self._coin_watchdog(reg, watch, self.policy("shadow"), eng)
        self.self._coin_watchdog(reg, watch, self.policy("shadow"), eng)
        self.assertEqual(len(self.msgs), 1)
        self.assertIn("코인 작업 시작", self.msgs[0])
        self.assertEqual(self.pings, [False])  # one heartbeat per 5 minutes
        reg.update(status="error", error="boom")
        for _ in range(4):
            self.self._coin_watchdog(reg, watch, self.policy("shadow"), None)
        self.assertEqual(sum("오류가 반복" in m for m in self.msgs), 1)
        reg.update(status="shadow", error="")
        self.self._coin_watchdog(reg, watch, self.policy("live"), eng)
        self.assertTrue(any("다시 정상" in m for m in self.msgs))
        self.assertTrue(any("모드 변경" in m for m in self.msgs))

    def test_off_at_start_is_quiet_but_still_sends_the_heartbeat(self):
        self.self._coin_watchdog({"status": "off"}, {}, self.policy("off"), None)
        self.assertEqual(self.msgs, [])
        self.assertEqual(self.pings, [False])

    def test_trade_events_follow_the_shadow_switch(self):
        self.self._coin_alert("COIN_SHADOW_BUY", "[모의] KRW-BTC 매수")
        self.self._coin_alert("COIN_BUY_SKIPPED", "noise")
        self.self._coin_alert("COIN_SHADOW_BUY", "[점검] KRW-ADA 매수")  # probe: never alerted
        self.assertEqual(len(self.msgs), 1)
        self.assertNotIn("[모의] KRW", self.msgs[0])
        self.settings["notify_shadow"] = False
        self.self._coin_alert("COIN_SHADOW_SELL", "x")
        self.self._coin_alert("COIN_SELL", "KRW-BTC SELL")
        self.assertEqual(len(self.msgs), 2)
        self.assertIn("🔴 매도", self.msgs[-1])


if __name__ == "__main__":
    unittest.main()
