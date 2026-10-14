"""Infinite-buy ledger/order regressions (broker double, no network orders)."""
import copy
import unittest

from test_infinitebuy_loc_schedule_regressions import _FakeDB, _KisApiStub, _StructStub, engine_module


class _OrderingKis(_KisApiStub):
    """Broker double that also accepts the direct (non-reservation) buy order."""

    def buy_order(self, symbol, qty, price=0, order_type="LOC", exchange="NASD"):
        order = {"order_no": f"BUY-{len(self.buy_calls) + 1}", "symbol": symbol, "qty": qty,
                 "price": price, "order_type": order_type, "exchange": exchange}
        self.buy_calls.append(copy.deepcopy(order))
        return order


def _cycle(**overrides):
    # Broker stub quotes 150.0 (prev close 149.0); avg 149.5 keeps the cycle
    # below its target so run_daily goes on to the buy decision.
    row = {"id": "c1", "symbol": "TQQQ", "status": "ACTIVE", "cycle_number": 1,
           "total_investment": 10000.0, "division_count": 20, "target_profit": 15.0,
           "current_round": 3, "total_qty": 6, "total_spent": 897.0, "avg_price": 149.5,
           "remaining_investment": 9103.0, "total_commission": 2.24}
    row.update(overrides)
    return row


def _engine(configs=None, cycle=None, trades=None):
    struct = _StructStub([{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True}],
                         [cycle or _cycle()], configs=configs or {})
    struct._db["cycle_trade"] = _FakeDB(trades or [])
    struct.kis_api = _OrderingKis({"ok": True, "executable_qty": 1000, "executable_amount": 100000.0,
                                   "amount": 100000.0, "qty": 1000})
    engine = engine_module.Engine(struct)
    engine._ensure_runtime_schema = lambda: None
    engine._sync_trade_to_firegate = lambda *_args, **_kwargs: None
    return engine, struct


def _daily_orders(struct):
    return [row for row in struct.db("trade_log").rows() if row["event_type"] == "IB_DAILY_ORDER_SUBMITTED"]


class DailyRunOrderTests(unittest.TestCase):
    def test_reservation_mode_daily_run_places_no_orders(self):
        engine, struct = _engine(configs={"auto_trade_enabled": "true"})

        result = engine.run_daily("TQQQ")

        self.assertEqual(result["action"], "RESERVATION_MODE")
        self.assertEqual(struct.kis_api.buy_calls, [])
        self.assertEqual(struct.kis_api.sell_calls, [])
        self.assertEqual(struct.db("cycle_trade").rows(), [])

    def test_firegate_authoritative_mode_places_no_local_orders(self):
        engine, struct = _engine(configs={"auto_trade_enabled": "false",
                                          "firegate_authoritative_reservations_only": "true"})

        self.assertEqual(engine.run_daily("TQQQ")["action"], "RESERVATION_MODE")
        self.assertEqual(struct.kis_api.buy_calls, [])

    def test_manual_buy_is_submitted_once_and_never_booked_as_a_fill(self):
        engine, struct = _engine()

        first = engine.run_daily("TQQQ")
        second = engine.run_daily("TQQQ")

        self.assertEqual(first["action"], "BUY_SUBMITTED")
        self.assertEqual(second["action"], "ALREADY_SUBMITTED")
        self.assertEqual(len(struct.kis_api.buy_calls), 1)
        self.assertEqual(struct.db("cycle_trade").rows(), [])
        cycle = struct.db("trading_cycle").get(id="c1")
        self.assertEqual(cycle["current_round"], 3)
        self.assertEqual(cycle["total_qty"], 6)
        logged = _daily_orders(struct)
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0]["order_no"], "BUY-1")
        self.assertEqual(logged[0]["action"], "BUY")

    def test_manual_sell_is_submitted_once_and_never_booked_as_a_fill(self):
        engine, struct = _engine(cycle=_cycle(total_spent=600.0, avg_price=100.0, remaining_investment=9400.0))

        first = engine.run_daily("TQQQ")
        second = engine.run_daily("TQQQ")

        self.assertIn(first["action"], ("SELL_SUBMITTED", "PARTIAL_SELL_SUBMITTED"))
        self.assertEqual(second["action"], "ALREADY_SUBMITTED")
        self.assertEqual(len(struct.kis_api.sell_calls), 1)
        cycle = struct.db("trading_cycle").get(id="c1")
        self.assertEqual(cycle["status"], "ACTIVE")
        self.assertEqual(cycle["total_qty"], 6)
        self.assertEqual(struct.db("cycle_trade").rows(), [])

    def test_unreadable_order_log_fails_closed(self):
        engine, struct = _engine()

        def broken(**_where):
            raise RuntimeError("log unavailable")

        struct.db("trade_log").rows = broken
        self.assertTrue(engine._daily_order_already_submitted("c1", "BUY"))


class LedgerMathTests(unittest.TestCase):
    def test_profit_rate_counts_buy_commission_once(self):
        engine, struct = _engine(cycle=_cycle(total_qty=10, total_spent=1000.0, avg_price=100.0,
                                              total_commission=2.5))
        rates = engine._get_commission_rates()
        expected = (1050.0 - 1000.0 - engine._calc_sell_commission(1050.0, rates)) / 1000.0 * 100

        decision = engine.calculate_sell_decision(struct.db("trading_cycle").get(id="c1"), 105.0)
        engine.update_cycle_price("c1", 105.0)

        self.assertAlmostEqual(decision["profit_rate"], expected, places=2)
        self.assertAlmostEqual(struct.db("trading_cycle").get(id="c1")["profit_rate"], round(expected, 2), places=2)

    def test_one_turn_never_exceeds_remaining_seed(self):
        engine, _struct = _engine()
        cycle = {"division_count": 20, "total_investment": 10000.0, "remaining_investment": 400.0}

        self.assertAlmostEqual(engine._firegate_v4_investment_per_turn({**cycle, "t_value": 19.5}), 400.0)
        self.assertAlmostEqual(engine._firegate_v4_investment_per_turn({**cycle, "t_value": 10}), 40.0)
        self.assertEqual(engine._firegate_v4_investment_per_turn({**cycle, "t_value": 20}), 0.0)

    def test_same_day_fills_consume_one_round(self):
        engine, struct = _engine()

        engine.execute_buy("c1", 150.0, 2, trade_date="2026-05-28", broker_order_no="A")
        engine.execute_buy("c1", 150.0, 1, trade_date="2026-05-28", broker_order_no="B")
        self.assertEqual(struct.db("trading_cycle").get(id="c1")["current_round"], 4)

        engine.execute_buy("c1", 148.0, 2, trade_date="2026-05-29", broker_order_no="C")
        self.assertEqual(struct.db("trading_cycle").get(id="c1")["current_round"], 5)

    def test_recalculation_counts_buy_days_and_skips_crash_buys(self):
        trades = [
            {"id": "t1", "cycle_id": "c1", "action": "BUY", "status": "FILLED", "trade_date": "2026-05-26",
             "filled_qty": 2, "filled_price": 100.0, "commission": 0.5, "created": "2026-05-26 09:00:00"},
            {"id": "t2", "cycle_id": "c1", "action": "BUY", "status": "FILLED", "trade_date": "2026-05-26",
             "filled_qty": 1, "filled_price": 99.0, "commission": 0.25, "created": "2026-05-26 09:00:01"},
            {"id": "t3", "cycle_id": "c1", "action": "BUY", "status": "FILLED", "trade_date": "2026-05-26",
             "strategy_type": "CRASH_BUY", "filled_qty": 1, "filled_price": 95.0, "commission": 0.24,
             "created": "2026-05-26 09:00:02"},
            {"id": "t4", "cycle_id": "c1", "action": "BUY", "status": "FILLED", "trade_date": "2026-05-27",
             "filled_qty": 2, "filled_price": 98.0, "commission": 0.49, "created": "2026-05-27 09:00:00"},
        ]
        engine, struct = _engine(cycle=_cycle(current_round=0, total_qty=0, total_spent=0.0), trades=trades)

        result = engine._recalculate_cycle_from_trades("c1")

        self.assertEqual(result["current_round"], 2)
        self.assertEqual(struct.db("trading_cycle").get(id="c1")["current_round"], 2)
        self.assertEqual(struct.db("trading_cycle").get(id="c1")["total_qty"], 6)


if __name__ == "__main__":
    unittest.main()
