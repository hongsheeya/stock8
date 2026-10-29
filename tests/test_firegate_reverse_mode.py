"""FireGate v4 reverse mode (10-29): the app places what the FireGate
dashboard shows (getGuideV4Reverse), books trades like FireGate's
addTransaction, places the first-day MOC once per US session as a regular
order, and a definite KIS reservation rejection no longer blocks the LOC
automation."""
import datetime
import importlib.util
import json
import pathlib
import sys
import unittest

import test_infinitebuy_loc_schedule_regressions as base

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fg_bridge_rev", ROOT / "src/portal/trading/model/struct/firegate_bridge.py")
fg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fg)
Engine = base.engine_module.Engine

# the live SOXL portfolio on 10-29
SOXL = {"_firegate_authoritative": True, "symbol": "SOXL", "division_count": 20, "total_qty": 90, "avg_price": 124.94,
        "_firegate_raw_avg_price": 124.94, "_firegate_remaining_seed": 3761.61, "_firegate_reverse_mode": True,
        "_firegate_exhausted": False, "_firegate_reverse_star_price": 94.0, "_firegate_five_day_avg": 90.62,
        "current_round": 15, "total_investment": 15000, "total_spent": 11244.6, "remaining_investment": 3761.61}


class ReversePlanTests(unittest.TestCase):
    def test_first_day_is_a_moc_sell_of_a_tenth_and_nothing_else(self):
        plan = Engine.firegate_reverse_plan({**SOXL, "_firegate_reverse_state": "NORMAL"})
        self.assertEqual(plan["moc_qty"], 9)
        self.assertEqual((plan["sells"], plan["buys"]), ([], []))
        self.assertIn("첫날", plan["state_name"])

    def test_active_state_places_the_dashboard_loc_lines(self):
        plan = Engine.firegate_reverse_plan({**SOXL, "_firegate_reverse_state": "ACTIVE"})
        self.assertEqual(plan["moc_qty"], 0)
        self.assertEqual(plan["sells"], [{"label": "FireGate LOC 리버스★", "order_type": "LOC", "order_qty": 9, "price": 90.62,
                                          "source": "firegate_reverse"}])
        self.assertEqual(plan["buys"][0]["loc_price"], 90.61)
        self.assertEqual(plan["buys"][0]["order_qty"], 10)  # floor(3761.61 / 4 / 90.61)
        extra = [b["loc_price"] for b in plan["buys"][1:]]
        self.assertEqual(extra[0], round(3761.61 / 4 / 11, 2))
        self.assertEqual(len(extra), 7)
        self.assertTrue(all(p < 90.61 for p in extra))

    def test_re_exhausted_active_goes_back_to_moc(self):
        plan = Engine.firegate_reverse_plan({**SOXL, "_firegate_reverse_state": "ACTIVE", "_firegate_remaining_seed": 300})
        self.assertEqual(plan["moc_qty"], 9)
        self.assertIn("재소진", plan["state_name"])

    def test_normal_mode_keeps_the_regular_plan(self):
        self.assertIsNone(Engine.firegate_reverse_plan({**SOXL, "_firegate_reverse_mode": False}))
        self.assertIsNone(Engine.firegate_reverse_plan({**SOXL, "_firegate_authoritative": False}))

    def test_buy_decision_follows_the_reverse_plan(self):
        engine = Engine(base._StructStub([], []))
        decision = engine.calculate_buy_decision({**SOXL, "_firegate_reverse_state": "ACTIVE"}, 124.94)
        self.assertTrue(decision["should_buy"])
        self.assertEqual(decision["buy_orders"][0]["loc_price"], 90.61)
        moc_day = engine.calculate_buy_decision({**SOXL, "_firegate_reverse_state": "NORMAL"}, 124.94)
        self.assertFalse(moc_day["should_buy"])


class BridgeBookkeepingTests(unittest.TestCase):
    def portfolio(self, **kw):
        p = {"ticker": "SOXL", "version": "v4", "seed": 15000, "divisionDate": 20, "holdingQty": 100, "avgPrice": 122.41,
             "totalBuy": 18988.99, "totalSell": 6739.8, "tValue": 19.5, "reverseMode": True, "reverseState": "NORMAL",
             "reverseModeStarPrice": 0}
        p.update(kw)
        return p

    def test_a_reverse_sell_makes_the_state_active_and_sets_the_star(self):
        p = self.portfolio()
        tx = {"type": "sell", "price": 101.08, "size": 10, "commission": 2.53, "date": "2026. 10. 27"}
        tx.update(fg.firegate_operator(p, tx))
        self.assertEqual((tx["tOperator"], tx["tDelta"]), ("x", 0.9))
        out = fg.apply_v4_transaction(p, tx, recent_average=90.62)
        self.assertEqual(out["reverseState"], "ACTIVE")
        self.assertTrue(out["reverseMode"])
        self.assertEqual(out["reverseModeStarPrice"], 90.62)
        self.assertEqual(out["tValue"], round(19.5 * 0.9, 2))

    def test_normal_portfolio_that_becomes_exhausted_is_entered(self):
        p = self.portfolio(reverseMode=False, tValue=18.6, holdingQty=80, totalBuy=14000, totalSell=0)
        out = fg.apply_v4_transaction(p, {"type": "buy", "price": 100, "size": 5, "commission": 0, "tDelta": 1.0})
        self.assertEqual(out["reverseState"], "ENTERED")
        self.assertTrue(out["reverseMode"])

    def test_normal_sell_of_more_than_half_is_x025(self):
        p = self.portfolio(reverseMode=False, reverseState="NORMAL", tValue=8)
        self.assertEqual(fg.firegate_operator(p, {"type": "sell", "size": 60})["tDelta"], 0.25)
        self.assertEqual(fg.firegate_operator(p, {"type": "sell", "size": 25})["tDelta"], 0.75)

    def test_dashboard_auto_exit_above_80_percent_of_average(self):
        calls = []
        bridge = type("B", (), {"latest_price": lambda self, t: 101.0, "recent_prices": lambda self, t, n: [100.0, 99.0],
                                "update_portfolio": lambda self, pid, ch: calls.append((pid, ch))})()
        portfolio = {"id": 7, "ticker": "SOXL", "seed": 15000, "divisionDate": 20, "holdingQty": 90, "avgPrice": 124.94,
                     "totalBuy": 18988.99, "totalSell": 7750.6, "tValue": 15.98, "reverseMode": True, "reverseState": "ACTIVE"}
        state = fg._authoritative_cycle_state_from_portfolio(portfolio)
        _p, out = fg._reverse_market_view(bridge, portfolio, state)
        self.assertEqual(calls, [(7, {"reverseMode": False, "reverseState": "NORMAL"})])
        self.assertFalse(out["_firegate_reverse_mode"])
        calls.clear()
        _p, out = fg._reverse_market_view(bridge, {**portfolio, "reverseState": "ENTERED"},
                                          fg._authoritative_cycle_state_from_portfolio({**portfolio, "reverseState": "ENTERED"}))
        self.assertEqual(calls, [])
        self.assertEqual(out["_firegate_five_day_avg"], 99.5)


class _Kis:
    def __init__(self, et, held=90, history=()):
        self.et, self.held, self.history, self.sells = et, held, list(history), []

    def _us_eastern_now(self, now=None):
        return self.et

    def us_market_holiday_label(self, now=None):
        return ""

    def get_balance(self, exchange=None):
        return {"holdings": [{"symbol": "SOXL", "qty": self.held}]}

    def get_overseas_order_history(self, start_date=None, end_date=None, symbol=""):
        return {"orders": self.history}

    def sell_order(self, symbol, qty, price=0, order_type="MARKET", exchange="NASD"):
        self.sells.append((symbol, qty, order_type))
        return {"order_no": "0099"}


class _ConfigStruct(base._StructStub):
    def set_config(self, key, value, description=""):
        self.configs[key] = value


class ReverseMocTests(unittest.TestCase):
    def engine(self, kis, state="NORMAL"):
        struct = _ConfigStruct([], [{"id": "c1", "symbol": "SOXL", "status": "ACTIVE", "total_qty": 90}])
        engine = Engine(struct)
        engine._load_kis_api = lambda: kis
        engine._load_firegate_authoritative_states = lambda symbol_filter="": {
            "states": {"SOXL": {**SOXL, "_firegate_reverse_state": state}}, "error": ""}
        engine._log_event = lambda *a, **k: None
        return engine, struct

    def at(self, hh, mm):
        return datetime.datetime(2026, 10, 29, hh, mm)

    def test_moc_is_sent_once_per_session_inside_the_window(self):
        kis = _Kis(self.at(10, 0))
        engine, struct = self.engine(kis)
        engine.run_firegate_reverse_moc()
        self.assertEqual(kis.sells, [("SOXL", 9, "MOC")])
        engine.__dict__["_reverse_moc_state"]["checked_at"] = 0
        engine.run_firegate_reverse_moc()
        self.assertEqual(len(kis.sells), 1)
        self.assertEqual(json.loads(struct.configs["firegate_reverse_moc:SOXL"])["status"], "submitted")

    def test_no_moc_outside_the_window_or_in_active_state(self):
        for et in (self.at(9, 30), self.at(15, 45)):
            kis = _Kis(et)
            self.engine(kis)[0].run_firegate_reverse_moc()
            self.assertEqual(kis.sells, [])
        kis = _Kis(self.at(10, 0))
        self.engine(kis, state="ACTIVE")[0].run_firegate_reverse_moc()
        self.assertEqual(kis.sells, [])

    def test_unsynced_or_existing_sell_blocks_the_moc(self):
        kis = _Kis(self.at(10, 0), held=80)
        self.engine(kis)[0].run_firegate_reverse_moc()
        self.assertEqual(kis.sells, [])
        kis = _Kis(self.at(10, 0), history=[{"symbol": "SOXL", "side": "SELL", "status": "FILLED", "order_date": "20261029", "order_no": "1"}])
        self.engine(kis)[0].run_firegate_reverse_moc()
        self.assertEqual(kis.sells, [])


class LiveDefaultReservationTests(unittest.TestCase):
    """LIVE runs without firegate_authoritative_reservations_only; on 10-29
    it still placed the normal v4 lines for a reverse-mode SOXL."""

    def engine(self, state):
        engine, kis, _logs = base.InfiniteBuyLocScheduleRegressionTests._engine(
            None, buying_power_info={"orderable_amount": 5000.0}, reservation_orders=[],
            watchlist_rows=[{"id": "w1", "symbol": "SOXL", "exchange": "AMEX", "is_active": True}],
            cycle_rows=[{"id": "c1", "symbol": "SOXL", "status": "ACTIVE", "total_qty": 90, "avg_price": 124.94,
                         "total_spent": 11244.6, "target_profit": 20.0, "total_commission": 0.0, "current_round": 15,
                         "t_value": 15.98, "division_count": 20, "total_investment": 15000.0}],
            configs={})
        engine.calculate_buy_decision = Engine.calculate_buy_decision.__get__(engine, engine.__class__)
        engine._load_firegate_authoritative_states = lambda symbol_filter="": {
            "states": {"SOXL": {**SOXL, "_firegate_reverse_state": state}}, "error": ""}
        return engine, kis

    def test_moc_day_places_no_reservations(self):
        engine, kis = self.engine("NORMAL")
        engine.schedule_loc_sells(symbol_filter="SOXL")
        engine.schedule_loc_buys(symbol_filter="SOXL")
        self.assertEqual(kis.sell_reservation_calls, [])
        self.assertEqual(kis.buy_calls, [])

    def test_active_day_places_the_reverse_sell(self):
        engine, kis = self.engine("ACTIVE")
        engine.schedule_loc_sells(symbol_filter="SOXL")
        self.assertEqual([(c["price"], c["qty"]) for c in kis.sell_reservation_calls], [(90.62, 9)])

    def test_normal_firegate_state_keeps_the_local_cycle(self):
        engine, _ = self.engine("NORMAL")
        engine._load_firegate_authoritative_states = lambda symbol_filter="": {
            "states": {"SOXL": {**SOXL, "_firegate_reverse_mode": False, "total_qty": 1}}, "error": ""}
        self.assertEqual(engine._firegate_reverse_states()["states"], {})


class ReservationRejectionTests(unittest.TestCase):
    def setUp(self):
        from test_kis_api_buying_power import kis_api, _StructStub
        from unittest.mock import Mock
        self.config = _StructStub()
        self.api = kis_api.KisApi(self.config)
        self.api._kst_now = lambda: datetime.datetime(2026, 10, 29, 14, 0)
        self.Mock = Mock

    def test_definite_rejection_does_not_leave_the_barrier(self):
        self.api._request = self.Mock(return_value={"rt_cd": "7", "msg_cd": "APBK1574", "msg1": "예약주문접수는 10:00~22:20 에 가능합니다."})
        with self.assertRaisesRegex(RuntimeError, "거절"):
            self.api.buy_reservation_order("SOXL", 8, 103.73)
        self.assertFalse(self.config.get_config("kis_reservation_pending"))
        with self.assertRaises(RuntimeError):
            self.api.buy_reservation_order("SOXL", 8, 103.73)
        self.assertEqual(self.api._request.call_count, 2)  # the next attempt is allowed

    def test_stuck_record_with_a_definite_rejection_is_cleared(self):
        self.config.set_config("kis_reservation_pending", json.dumps({"at": "2026-10-23T22:20:05", "symbol": "SOXL", "qty": "8",
                                                                      "price": "103.73", "response": {"rt_cd": "7", "msg_cd": "APBK1574"}}))
        self.assertEqual(self.api.clear_definite_reservation_rejection()["symbol"], "SOXL")
        self.assertFalse(self.config.get_config("kis_reservation_pending"))
        self.config.set_config("kis_reservation_pending", json.dumps({"at": "2026-10-23T22:20:05", "symbol": "SOXL"}))
        self.assertIsNone(self.api.clear_definite_reservation_rejection())  # unknown outcome stays blocked

    def test_last_minute_before_the_cutoff_sends_nothing(self):
        self.api._kst_now = lambda: datetime.datetime(2026, 10, 29, 22, 19, 30)  # US summer time: cutoff 22:20
        self.api._request = self.Mock()
        with self.assertRaisesRegex(RuntimeError, "마감"):
            self.api.buy_reservation_order("SOXL", 8, 103.73)
        self.api._request.assert_not_called()
        self.assertFalse(self.config.get_config("kis_reservation_pending"))


if __name__ == "__main__":
    unittest.main()
