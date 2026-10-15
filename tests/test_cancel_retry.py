"""A rejected cancel of a resting sell is retried while the broker shows it open.

One rejected request (e.g. a rate limit) used to leave the reservation
resting and the stop-loss suspended for the session: the request was marked
as sent and never repeated.
"""
import datetime
import unittest
from unittest.mock import Mock

from test_daytrade_engine_regressions import _engine_with_state


class CancelRetryTests(unittest.TestCase):
    def setUp(self):
        self.engine, _ = _engine_with_state({}, [])
        self.clock = [datetime.datetime(2026, 5, 26, 10, 0, 0)]
        self.engine._now = lambda: self.clock[0]
        self.engine._timestamp = lambda: self.clock[0].strftime("%Y-%m-%d %H:%M:%S")
        self.broker = Mock()
        self.engine._broker = lambda: self.broker
        self.state = dict(pending_sell_order_no="000555", pending_sell_qty=10, pending_sell_price=10120)

    def _request(self, after_sec=0):
        self.clock[0] += datetime.timedelta(seconds=after_sec)
        self.engine._request_pending_sell_cancel(self.state, "069500")

    def test_rejected_request_is_retried_after_the_backoff(self):
        self.broker.cancel_domestic_order.side_effect = [Exception("초당 거래건수를 초과하였습니다"), {"rt_cd": "0"}]
        self._request()
        self._request(after_sec=15)  # next watch pass: too soon
        self.assertEqual(self.broker.cancel_domestic_order.call_count, 1)
        self._request(after_sec=20)
        self.assertEqual(self.broker.cancel_domestic_order.call_count, 2)
        self.assertEqual(self.state["pending_sell_cancel_error"], "")
        self._request(after_sec=60)  # accepted: never resent
        self.assertEqual(self.broker.cancel_domestic_order.call_count, 2)

    def test_retries_stop_at_the_cap(self):
        self.broker.cancel_domestic_order.side_effect = Exception("rejected")
        for _ in range(15):
            self._request(after_sec=31)
        self.assertEqual(self.broker.cancel_domestic_order.call_count, self.engine._CANCEL_MAX_ATTEMPTS)

    def test_a_confirmed_cancel_clears_the_retry_fields(self):
        self.broker.cancel_domestic_order.side_effect = Exception("rejected")
        self._request()
        self.engine._clear_pending_sell(self.state)
        self.assertFalse([key for key in self.state if key.startswith("pending_sell_cancel")])

    def test_a_new_order_starts_a_fresh_count(self):
        self.broker.cancel_domestic_order.side_effect = Exception("rejected")
        for _ in range(12):
            self._request(after_sec=31)
        self.state["pending_sell_order_no"] = "000777"
        self._request(after_sec=1)
        self.assertEqual(self.broker.cancel_domestic_order.call_args.args[0], "000777")
        self.assertEqual(self.state["pending_sell_cancel_attempts"], 1)


if __name__ == "__main__":
    unittest.main()
