"""10-22: settled day orders stop being re-queried every minute (KIS budget)."""
import copy
import datetime
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

from test_daytrade_engine_regressions import _engine_with_state

NOW = datetime.datetime(2026, 10, 22, 10, 30)


class ReconcileExpiryTests(unittest.TestCase):
    def engine_with(self, stored):
        engine, _ = _engine_with_state({}, [])
        broker = Mock()
        broker.request_options.side_effect = lambda **kw: nullcontext()
        broker.get_overseas_order_history.return_value = []
        broker.get_domestic_fills_for_day.return_value = []
        engine._broker = lambda: broker
        engine._now = lambda: NOW
        engine._load_state_map = lambda: copy.deepcopy(stored)
        engine._save_state_map = lambda payload: (stored.clear(), stored.update(copy.deepcopy(payload)))
        engine._fs = lambda: SimpleNamespace(write=SimpleNamespace(json=Mock()))
        engine._data_root = lambda: "unused"
        engine._append_runtime_log = Mock()
        return engine, broker

    def us_state(self, placed_at):
        return {"symbol": "SPCX", "market": "US", "position_qty": 0, "pending_sell_order_no": "0000043756",
                "pending_sell_placed_at": placed_at, "pending_sell_qty": 5,
                "orders": [{"order_no": "0000043756", "timestamp": placed_at, "action": "SELL_FULL", "status": "ACCEPTED_UNVERIFIED"}]}

    def test_us_pending_from_a_finished_session_is_settled(self):
        stored = {"SPCX.US": self.us_state("2026-10-21 23:06:11")}   # 11.4 h ago: session may still be settling
        engine, broker = self.engine_with(stored)
        engine.reconcile_order_history()
        self.assertEqual(stored["SPCX.US"]["pending_sell_order_no"], "0000043756")
        stored["SPCX.US"] = self.us_state("2026-10-21 16:00:00")      # 18.5 h ago: definitely over
        engine.reconcile_order_history()
        self.assertEqual(stored["SPCX.US"]["pending_sell_order_no"], "")
        self.assertEqual(stored["SPCX.US"]["orders"][0]["status"], "EXPIRED_UNVERIFIED")
        calls = broker.get_overseas_order_history.call_count
        engine.reconcile_order_history()
        self.assertEqual(broker.get_overseas_order_history.call_count, calls)  # no more polling
        broker.sell_order.assert_not_called()

    def test_past_domestic_day_orders_become_final(self):
        stored = {
            "114800.KS": {"symbol": "114800", "market": "KS", "orders": [
                {"order_no": "0001", "timestamp": "2026-09-03 11:15:12", "action": "SELL_DELEVERAGE", "status": "ACCEPTED_UNVERIFIED"}]},
            "229200.KS": {"symbol": "229200", "market": "KS", "orders": [
                {"order_no": "0002", "timestamp": "2026-09-22 09:38:03", "action": "SELL_DELEVERAGE", "status": "ACCEPTED_UNVERIFIED"}]},
        }
        engine, broker = self.engine_with(stored)

        def fills(day):
            if day == "20260922":
                return [{"symbol": "229200", "order_no": "2", "status": "OPEN", "filled_qty": 3, "filled_price": 100}]
            return []

        broker.get_domestic_fills_for_day.side_effect = fills
        engine.reconcile_order_history(max_dates=2)
        self.assertEqual(stored["114800.KS"]["orders"][0]["status"], "EXPIRED_UNVERIFIED")  # absent from a final day
        self.assertEqual(stored["229200.KS"]["orders"][0]["status"], "FILLED")              # OPEN on a past day is final
        calls = broker.get_domestic_fills_for_day.call_count
        engine.reconcile_order_history(max_dates=2)
        self.assertEqual(broker.get_domestic_fills_for_day.call_count, calls)

    def test_today_unverified_domestic_order_keeps_waiting(self):
        stored = {"251340.KS": {"symbol": "251340", "market": "KS", "orders": [
            {"order_no": "0003", "timestamp": "2026-10-22 10:00:25", "action": "BUY1", "status": "ACCEPTED_UNVERIFIED"}]}}
        engine, broker = self.engine_with(stored)
        engine.reconcile_order_history()
        self.assertEqual(stored["251340.KS"]["orders"][0]["status"], "ACCEPTED_UNVERIFIED")


class UsQuietWindowTests(unittest.TestCase):
    def test_quiet_hours_follow_eastern_time(self):
        from test_kis_api_buying_power import kis_api
        api = kis_api.KisApi.__new__(kis_api.KisApi)
        kst = lambda *a: datetime.datetime(*a)
        self.assertTrue(api._us_market_quiet(kst(2026, 10, 22, 10, 30)))    # KS session: ET 21:30 the day before
        self.assertFalse(api._us_market_quiet(kst(2026, 10, 22, 17, 30)))   # ET 04:30 pre-market
        self.assertFalse(api._us_market_quiet(kst(2026, 10, 22, 23, 0)))    # regular session
        self.assertTrue(api._us_market_quiet(kst(2026, 10, 25, 1, 0)))      # Saturday ET
