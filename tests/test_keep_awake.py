"""Keep the LIVE PC awake only while trading needs it (10-31)."""
import datetime
import importlib.util
import json
import os
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("keep_awake", ROOT / "src/portal/trading/model/keep_awake.py")
ka = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ka)

KST = datetime.timezone(datetime.timedelta(hours=9))


def kst(*args):
    return datetime.datetime(*args, tzinfo=KST).astimezone(datetime.timezone.utc)


class WindowTests(unittest.TestCase):
    def test_ks_session_on_weekdays_only(self):
        self.assertEqual(ka.needed(kst(2026, 10, 30, 11, 51)), (True, "국장 시간"))  # the 10-30 sleep
        self.assertFalse(ka.needed(kst(2026, 10, 31, 11, 51))[0])  # Saturday
        self.assertFalse(ka.needed(kst(2026, 10, 30, 8, 29))[0])
        self.assertTrue(ka.needed(kst(2026, 10, 30, 15, 39))[0])
        self.assertFalse(ka.needed(kst(2026, 10, 30, 15, 40))[0])

    def test_us_session_follows_eastern_time_and_dst(self):
        # summer: 09:00 ET = 22:00 KST, 16:30 ET = 05:30 KST next day
        self.assertEqual(ka.needed(kst(2026, 10, 29, 22, 0)), (True, "미장 시간"))
        self.assertFalse(ka.needed(kst(2026, 10, 29, 21, 59))[0])
        self.assertTrue(ka.needed(kst(2026, 10, 30, 5, 29))[0])
        self.assertFalse(ka.needed(kst(2026, 10, 30, 5, 30))[0])
        # winter (after 11-01): 09:00 ET = 23:00 KST
        self.assertFalse(ka.needed(kst(2026, 11, 2, 22, 30))[0])
        self.assertTrue(ka.needed(kst(2026, 11, 2, 23, 0))[0])
        # Friday ET session runs into Saturday morning KST; Saturday ET is off
        self.assertTrue(ka.needed(kst(2026, 10, 31, 4, 0))[0])
        self.assertFalse(ka.needed(kst(2026, 11, 1, 0, 0))[0])

    def test_coin_held_is_always_on_and_decision_bars_only_when_coin_on(self):
        sat_noon = kst(2026, 10, 31, 12, 30)
        self.assertEqual(ka.needed(sat_noon, coin_held=True), (True, "코인 보유/주문 중"))
        bar = kst(2026, 10, 31, 13, 0)  # 4h UTC bar end = 13:00 KST
        self.assertFalse(ka.needed(bar, coin_on=False)[0])
        self.assertEqual(ka.needed(bar - datetime.timedelta(minutes=2), coin_on=True), (True, "코인 4시간봉 판단"))
        self.assertTrue(ka.needed(bar + datetime.timedelta(minutes=19), coin_on=True)[0])
        self.assertFalse(ka.needed(bar + datetime.timedelta(minutes=20), coin_on=True)[0])
        self.assertFalse(ka.needed(bar - datetime.timedelta(minutes=3), coin_on=True)[0])


class LedgerTests(unittest.TestCase):
    def write(self, root, name, sleeves):
        os.makedirs(os.path.join(root, "owner"), exist_ok=True)
        with open(os.path.join(root, "owner", name), "w", encoding="utf-8") as handle:
            json.dump({"sleeves": sleeves}, handle)

    def test_long_or_pending_in_current_ledgers_only(self):
        root = tempfile.mkdtemp()
        self.write(root, "state_shadow.json", {"KRW-BTC": {"long": False, "pending": None}})
        self.assertFalse(ka.coin_held(root))
        self.write(root, "state_shadow.atr2-20261024.json", {"KRW-BTC": {"long": True}})
        self.assertFalse(ka.coin_held(root))
        self.write(root, "state_probe.json", {"KRW-TRX": {"long": False, "pending": {"side": "BUY"}}})
        self.assertTrue(ka.coin_held(root))


class ApplyTests(unittest.TestCase):
    def test_flags(self):
        calls = []
        ka.apply(True, setter=lambda f: calls.append(f) or 1)
        ka.apply(False, setter=lambda f: calls.append(f) or 1)
        self.assertEqual(calls, [0x80000001, 0x80000000])


if __name__ == "__main__":
    unittest.main()
