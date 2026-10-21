"""UpbitApi (10-22): signing, fail-closed order guard, volume truncation."""
import base64
import hashlib
import hmac
import importlib.util
import json
import unittest
from pathlib import Path
from urllib.parse import urlencode

spec = importlib.util.spec_from_file_location("upbit_api_t", Path(__file__).resolve().parents[1] / "src" / "portal" / "trading" / "model" / "upbit_api.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, status=200, payload=None):
        self.calls = []
        self.status, self.payload = status, payload if payload is not None else {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse(self.status, self.payload)


def _decode(token):
    head, body, sig = token.split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)
    return json.loads(base64.urlsafe_b64decode(pad(body))), head, body, sig


class UpbitApiTests(unittest.TestCase):
    def test_orders_without_a_guard_are_refused(self):
        session = FakeSession(payload={"uuid": "x"})
        api = mod.UpbitApi("ak", "sk", session=session)
        with self.assertRaises(mod.UpbitError) as ctx:
            api.buy_market_krw("KRW-BTC", 10000)
        self.assertEqual(ctx.exception.name, "order_guard")
        self.assertEqual(session.calls, [])

    def test_guard_sees_the_order_and_can_block_it(self):
        seen = []
        session = FakeSession(payload={"uuid": "x"})

        def guard(method, path, params, info):
            seen.append((method, path, params, info))
            if info.get("krw", 0) > 50000:
                raise RuntimeError("1회 한도 초과")

        api = mod.UpbitApi("ak", "sk", session=session, order_guard=guard)
        api.buy_market_krw("KRW-BTC", 10000, identifier="s8c-BTC-1-b")
        self.assertEqual(len(session.calls), 1)
        with self.assertRaises(mod.UpbitError):
            api.buy_market_krw("KRW-BTC", 60000)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(seen[0][2]["identifier"], "s8c-BTC-1-b")

    def test_jwt_carries_a_query_hash_of_the_parameters(self):
        session = FakeSession(payload={"uuid": "x"})
        api = mod.UpbitApi("ak", "sk", session=session, order_guard=lambda *a: None)
        api.sell_market("KRW-BTC", 0.123456789)
        method, url, kwargs = session.calls[0]
        self.assertEqual(kwargs["json"]["volume"], "0.12345678")  # truncated, never rounded up
        token = kwargs["headers"]["Authorization"].split(" ", 1)[1]
        payload, head, body, sig = _decode(token)
        expected = hashlib.sha512(urlencode(kwargs["json"]).encode()).hexdigest()
        self.assertEqual(payload["query_hash"], expected)
        self.assertEqual(payload["access_key"], "ak")
        want = base64.urlsafe_b64encode(hmac.new(b"sk", f"{head}.{body}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        self.assertEqual(sig, want)

    def test_minimum_order_and_errors(self):
        api = mod.UpbitApi("ak", "sk", session=FakeSession(), order_guard=lambda *a: None)
        with self.assertRaises(mod.UpbitError):
            api.buy_market_krw("KRW-BTC", 4999)
        bad = mod.UpbitApi("ak", "sk", session=FakeSession(401, {"error": {"name": "no_authorization_ip", "message": "This is not a verified IP."}}))
        with self.assertRaises(mod.UpbitError) as ctx:
            bad.accounts()
        self.assertTrue(ctx.exception.fatal)
        self.assertEqual(mod.format_volume(1e-9), "0")
        self.assertEqual(mod.format_volume(2.5), "2.5")

    def test_candles_are_oldest_first_with_utc_epochs(self):
        rows = [{"candle_date_time_utc": "2026-10-21T01:00:00", "opening_price": 2, "high_price": 2, "low_price": 2, "trade_price": 2},
                {"candle_date_time_utc": "2026-10-21T00:00:00", "opening_price": 1, "high_price": 1, "low_price": 1, "trade_price": 1}]
        api = mod.UpbitApi(session=FakeSession(payload=rows))
        out = api.minute_candles("KRW-BTC", 60, 2)
        import calendar
        start = calendar.timegm((2026, 10, 21, 0, 0, 0))
        self.assertEqual([r["t"] for r in out], [start, start + 3600])
        self.assertEqual(out[0]["c"], 1.0)


if __name__ == "__main__":
    unittest.main()
