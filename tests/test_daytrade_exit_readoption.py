"""A stale balance read right after our own exit must not resurrect the position.

2026-10-14 PAPER: 233740 SELL_FULL filled at 09:39:02, then the exit watch
re-sent the 717-share sell four times until 09:40:50 ("모의투자 잔고내역이
없습니다"); 079650 did the same after its stop-loss. The cached balance still
listed the sold shares and broker adoption put them back.
"""
import time
import unittest

from test_daytrade_engine_regressions import _engine_with_state, daytrade_engine


SOLD = [{"symbol": "233740", "name": "test", "qty": 717, "avg_price": 6855.0, "current_price": 7020.0}]


def _flat_state(seconds_since_exit):
    return {"233740.KS": {"symbol": "233740", "market": "KS", "position_qty": 0, "avg_price": 0.0,
                          "strategy_id": "vrev", "last_exit_action": "SELL_FULL",
                          "flat_after_exit_at": time.time() - seconds_since_exit}}


class ExitReadoptionTests(unittest.TestCase):
    def test_stale_balance_right_after_exit_does_not_readopt(self):
        engine, store = _engine_with_state(_flat_state(10), SOLD)
        engine._sync_broker_positions(market_filter="KS")
        self.assertEqual(store()["233740.KS"]["position_qty"], 0)

    def test_position_still_held_after_the_grace_is_adopted(self):
        grace = daytrade_engine._READOPT_GRACE_SEC
        engine, store = _engine_with_state(_flat_state(grace + 20), SOLD)
        engine._sync_broker_positions(market_filter="KS")
        self.assertEqual(store()["233740.KS"]["position_qty"], 717)

    def test_only_a_flat_exit_starts_the_grace(self):
        engine, _ = _engine_with_state({}, [])
        flat = {"position_qty": 0}
        engine._mark_exit_watch(flat, reason="목표 달성", action="SELL_FULL", order_no="1")
        self.assertGreater(flat["flat_after_exit_at"], time.time() - 5)

        partial = {"position_qty": 300}
        engine._mark_exit_watch(partial, action="SELL_PARTIAL")
        settings = {"position_qty": 0}
        engine._mark_exit_watch(settings, reason="자동청산 감시 설정을 갱신했습니다.")
        self.assertNotIn("flat_after_exit_at", partial)
        self.assertNotIn("flat_after_exit_at", settings)


if __name__ == "__main__":
    unittest.main()
