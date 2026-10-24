"""Upbit trade stream (10-24): parsing, lowest-trade tracking, staleness, and
one connection per market set."""
import importlib.util
import json
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("t_upbit_ws", Path(__file__).resolve().parents[1] / "src/portal/trading/model/upbit_ws.py")
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)


class FakeConn:
    def __init__(self, stream, messages):
        self.stream, self.messages, self.sent = stream, list(messages), []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def send(self, data):
        self.sent.append(json.loads(data))

    def recv(self, timeout=None):
        if self.messages:
            return self.messages.pop(0)
        self.stream.changed.set()  # end of script: behave like a market-set change
        raise TimeoutError()


class TradeStreamTests(unittest.TestCase):
    def setUp(self):
        self.clock = [100.0]
        self.st = W.TradeStream(clock=lambda: self.clock[0])

    def test_parse_simple_and_default_formats(self):
        self.assertEqual(W.parse(b'{"ty":"trade","cd":"KRW-BTC","tp":108000000.0,"ttms":1}'), ("KRW-BTC", 108000000.0, 1))
        self.assertEqual(W.parse('{"type":"trade","code":"KRW-XRP","trade_price":1715}')[:2], ("KRW-XRP", 1715.0))
        self.assertIsNone(W.parse(b'{"error":{"name":"INVALID_AUTH"}}'))
        self.assertIsNone(W.parse(b"not json"))

    def test_read_returns_the_lowest_trade_since_the_last_read(self):
        self.st.want = frozenset({"KRW-BTC"})
        for p in (100.0, 97.0, 99.0):
            self.st.on_trade("KRW-BTC", p)
        self.st.on_trade("KRW-ETH", 1.0)  # not watched: ignored
        row = self.st.read(["KRW-BTC", "KRW-ETH"])
        self.assertEqual(row, {"KRW-BTC": {"price": 99.0, "low": 97.0, "age": 0.0}})
        self.assertEqual(self.st.read(["KRW-BTC"])["KRW-BTC"]["low"], 99.0)  # reset after a read

    def test_health_needs_a_connection_and_fresh_trades(self):
        self.st.want = frozenset({"KRW-BTC"})
        self.st.on_trade("KRW-BTC", 100.0)
        self.assertFalse(self.st.healthy(["KRW-BTC"]))
        self.st.connected = True
        self.assertTrue(self.st.healthy(["KRW-BTC"]))
        self.clock[0] += W.STALE_SEC + 1
        self.assertFalse(self.st.healthy(["KRW-BTC"]))

    def test_one_connection_subscribes_the_set_and_feeds_trades(self):
        msgs = [b'{"ty":"trade","cd":"KRW-BTC","tp":101.0}', b'{"ty":"trade","cd":"KRW-BTC","tp":99.5}']
        conn = FakeConn(self.st, msgs)
        self.st.connect = lambda url: conn
        self.st.want = frozenset({"KRW-BTC", "KRW-XRP"})
        self.st.run_once(self.st.want)
        self.assertEqual(conn.sent[0][1], {"type": "trade", "codes": ["KRW-BTC", "KRW-XRP"], "is_only_realtime": True})
        self.assertEqual(self.st.read(["KRW-BTC"])["KRW-BTC"]["low"], 99.5)

    def test_watching_nothing_drops_cached_prices(self):
        self.st.want = frozenset({"KRW-BTC"})
        self.st.on_trade("KRW-BTC", 100.0)
        self.st.watch([])
        self.assertEqual(self.st.read(["KRW-BTC"]), {})


if __name__ == "__main__":
    unittest.main()
