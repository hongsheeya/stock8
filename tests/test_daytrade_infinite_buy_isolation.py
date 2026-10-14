"""Day trading must not adopt or trade symbols owned by an open infinite-buy cycle.

The broker fill sync books every fill of those symbols into the cycle, so a
day-trade position on them corrupts the infinite-buy ledger.
"""
import unittest

from test_daytrade_engine_regressions import _engine_with_state


class _Cycles:
    def __init__(self, rows):
        self._rows = rows

    def rows(self, **where):
        return [row for row in self._rows
                if all(row.get(key) == value for key, value in where.items() if key not in ("dump", "orderby", "order"))]


def _engine(state_map, overseas_holdings, cycles):
    engine, store = _engine_with_state(state_map, [])
    engine.struct.kis_api.overseas_holdings = overseas_holdings
    engine.struct.db = lambda name: _Cycles(cycles)
    return engine, store


class InfiniteBuyIsolationTests(unittest.TestCase):
    def test_cycle_holdings_are_not_adopted_and_earlier_adoption_is_cleared(self):
        earlier = {"TQQQ.US": {"symbol": "TQQQ", "market": "US", "position_qty": 6, "avg_price": 70.0,
                               "strategy_id": "vrev"}}
        engine, store = _engine(earlier, [{"symbol": "TQQQ", "qty": 6, "avg_price": 70.0},
                                          {"symbol": "NVDA", "qty": 3, "avg_price": 180.0}],
                                [{"symbol": "TQQQ", "status": "ACTIVE"}])

        engine._sync_broker_positions(market_filter="US")

        states = store()
        self.assertEqual(states["TQQQ.US"]["position_qty"], 0)
        self.assertEqual(states["NVDA.US"]["position_qty"], 3)

    def test_orders_and_analysis_are_blocked_only_while_a_cycle_is_open(self):
        engine, _ = _engine({}, [], [{"symbol": "TQQQ", "status": "PENDING_EXTENSION"}])
        self.assertEqual(engine.execute_live("TQQQ", market="US")["action"], "INFINITE_BUY_ONLY")
        with self.assertRaises(RuntimeError):
            engine.manual_sell("TQQQ", market="US")
        self.assertFalse(engine.analysis_allowed("TQQQ"))

        engine, _ = _engine({}, [], [{"symbol": "TQQQ", "status": "COMPLETED"}])
        self.assertEqual(engine._infinite_buy_symbols(), {"SOXL"})

    def test_cycle_lookup_failure_keeps_the_last_known_reservations(self):
        engine, _ = _engine({}, [], [{"symbol": "TQQQ", "status": "ACTIVE"}])
        self.assertIn("TQQQ", engine._infinite_buy_symbols())
        engine._infinite_buy_symbols_cache = (0, engine._infinite_buy_symbols_cache[1])

        def broken(_name):
            raise RuntimeError("db locked")

        engine.struct.db = broken
        self.assertEqual(engine._infinite_buy_symbols(), {"SOXL", "TQQQ"})


if __name__ == "__main__":
    unittest.main()
