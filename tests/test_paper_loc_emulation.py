"""PAPER close-time LOC emulation (broker double, no network orders)."""
import copy
import datetime
import os
import unittest
from unittest.mock import patch

from test_infinitebuy_loc_schedule_regressions import _FakeDB, _KisApiStub, _StructStub, engine_module

# 2026-05-28 is a Thursday: 15:56 EDT is 04:56 KST the next day.
DECIDE = datetime.datetime(2026, 5, 29, 4, 56, 0)
BEFORE = datetime.datetime(2026, 5, 29, 4, 40, 0)
NEXT_DAY = datetime.datetime(2026, 5, 30, 4, 56, 0)


class _UniqueDB(_FakeDB):
    def insert(self, data):
        if data.get("id") and self.get(id=data["id"]):
            raise RuntimeError("duplicate primary key")
        return super().insert(data)


class _PaperKis(_KisApiStub):
    def __init__(self, price=112.89, prev_close=115.0, holdings=None):
        super().__init__({"ok": True}, holdings=holdings)
        self.price, self.prev_close = price, prev_close

    def get_current_price(self, symbol, exchange="NAS"):
        return {"symbol": symbol, "price": self.price, "prev_close": self.prev_close, "order_exchange": "AMEX"}

    def get_balance(self, exchange="NASD"):
        return {"holdings": copy.deepcopy(self.holdings)}

    def buy_order(self, symbol, qty, price=0, order_type="LOC", exchange="NASD"):
        self.buy_calls.append((symbol, qty, price, order_type))
        return {"order_no": f"B{len(self.buy_calls)}"}

    def sell_order(self, symbol, qty, price=0, order_type="MARKET", exchange="NASD"):
        self.sell_calls.append((symbol, qty, price, order_type))
        return {"order_no": f"S{len(self.sell_calls)}"}


def _soxl(**overrides):
    # The PAPER SOXL cycle as aligned to the broker: 14 shares, T = 2.72.
    row = {"id": "c1", "symbol": "SOXL", "status": "ACTIVE", "cycle_number": 3, "total_investment": 15000.0,
           "division_count": 20, "target_profit": 20.0, "current_round": 9, "t_value": 0.0, "total_qty": 14,
           "total_spent": 2040.6, "avg_price": 145.757, "remaining_investment": 12959.4, "total_commission": 0.0}
    row.update(overrides)
    return row


def _engine(cycles, kis=None, configs=None, trades=None, symbols=("SOXL",)):
    watchlist = [{"id": f"w{index}", "symbol": symbol, "exchange": "AMEX" if symbol == "SOXL" else "NASD",
                  "is_active": True, "total_investment": 10000.0, "division_count": 20, "target_profit": 15.0,
                  "created": "2026-01-01 00:00:00"} for index, symbol in enumerate(symbols)]
    struct = _StructStub(watchlist, cycles, {"auto_trade_enabled": "true", **(configs or {})})
    struct._db["trade_log"] = _UniqueDB([])
    struct._db["cycle_trade"] = _FakeDB(trades or [])
    struct.kis_api = kis or _PaperKis()
    if not struct.kis_api.holdings:
        # The broker holds what the cycles say unless a test says otherwise.
        struct.kis_api.holdings = [{"symbol": row["symbol"], "qty": row["total_qty"]} for row in cycles if row.get("total_qty")]
    engine = engine_module.Engine(struct)
    engine._load_kis_api = lambda: struct.kis_api
    return engine, struct


def _events(struct, event_type):
    return [row for row in struct.db("trade_log").rows() if row["event_type"] == event_type]


class PaperLocEmulationTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, {"TRADING_MODE": "PAPER"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_waits_outside_the_decision_window_without_broker_calls(self):
        engine, struct = _engine([_soxl()])
        result = engine.run_paper_loc_emulation(now=BEFORE)
        self.assertEqual(result["status"], "waiting")
        self.assertEqual(struct.kis_api.buy_calls + struct.kis_api.sell_calls, [])
        self.assertEqual(struct.db("trade_log").rows(), [])

    def test_off_and_live_never_order(self):
        engine, struct = _engine([_soxl()], configs={"auto_trade_enabled": "false"})
        self.assertEqual(engine.run_paper_loc_emulation(now=DECIDE)["status"], "off")
        engine, struct = _engine([_soxl()])
        with patch.dict(os.environ, {"TRADING_MODE": "LIVE"}):
            self.assertEqual(engine.run_paper_loc_emulation(now=DECIDE)["status"], "unsupported")
        self.assertEqual(struct.kis_api.buy_calls + struct.kis_api.sell_calls, [])

    def test_sends_only_satisfied_v4_buy_lines_as_limits_once_a_day(self):
        engine, struct = _engine([_soxl()])

        first = engine.run_paper_loc_emulation(now=DECIDE)
        again = engine.run_paper_loc_emulation(now=DECIDE)

        self.assertEqual(first["status"], "completed")
        # T 2.72: avg LOC 3 @145.76, star(14.56%) LOC 2 @166.97, extra 1 @125.00;
        # the 107.14 extra is not reached at 112.89.
        self.assertEqual(struct.kis_api.buy_calls, [("SOXL", 3, 145.76, "LIMIT"), ("SOXL", 2, 166.97, "LIMIT"),
                                                    ("SOXL", 1, 125.0, "LIMIT")])
        self.assertEqual(struct.kis_api.sell_calls, [])
        self.assertEqual(again["results"][0]["status"], "already_decided")
        self.assertEqual(len(_events(struct, engine.PAPER_LOC_EVENT)), 3)
        # Submission is not a fill: the ledger waits for the broker fill sync.
        cycle = struct.db("trading_cycle").get(id="c1")
        self.assertEqual((cycle["total_qty"], cycle["current_round"]), (14, 9))

    def test_next_trading_day_decides_again(self):
        engine, struct = _engine([_soxl()])
        engine.run_paper_loc_emulation(now=DECIDE)
        engine.run_paper_loc_emulation(now=NEXT_DAY)
        self.assertEqual(len(struct.kis_api.buy_calls), 6)

    def test_star_and_target_sells_fill_above_their_prices(self):
        engine, struct = _engine([_soxl()], kis=_PaperKis(price=180.0, prev_close=170.0))
        engine.run_paper_loc_emulation(now=DECIDE)
        self.assertEqual(struct.kis_api.sell_calls, [("SOXL", 3, 166.98, "LIMIT"), ("SOXL", 11, 174.91, "LIMIT")])
        self.assertEqual(struct.kis_api.buy_calls, [])

    def test_stuck_pending_extension_cycle_is_recounted_by_buy_day(self):
        days = ["2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14", "2026-09-16",
                "2026-09-17", "2026-09-18", "2026-09-28", "2026-10-01"]
        trades = [{"id": f"t{index}{part}", "cycle_id": "c1", "action": "BUY", "status": "FILLED",
                   "trade_date": day, "filled_qty": 1, "filled_price": 120.0}
                  for index, day in enumerate(days) for part in ("a", "b")]
        engine, struct = _engine([_soxl(status="PENDING_EXTENSION", current_round=20)], trades=trades)

        engine.run_paper_loc_emulation(now=DECIDE)

        cycle = struct.db("trading_cycle").get(id="c1")
        self.assertEqual((cycle["status"], cycle["current_round"], cycle["total_qty"]), ("ACTIVE", 9, 14))
        self.assertEqual(len(_events(struct, "IB_PAPER_ROUND_REPAIRED")), 1)
        self.assertEqual(len(struct.kis_api.buy_calls), 3)

    def test_exhausted_cycle_stays_pending_and_only_sells(self):
        # T = 15000 * 20 / 15000 = 20: the seed is used up.
        engine, struct = _engine([_soxl(status="PENDING_EXTENSION", current_round=20, total_qty=100,
                                        total_spent=15000.0, avg_price=150.0, remaining_investment=0.0)],
                                 kis=_PaperKis(price=140.0, prev_close=141.0))
        engine.run_paper_loc_emulation(now=DECIDE)
        self.assertEqual(struct.db("trading_cycle").get(id="c1")["status"], "PENDING_EXTENSION")
        self.assertEqual(struct.kis_api.buy_calls, [])

    def test_missing_cycle_starts_one_with_a_first_limit_buy(self):
        kis = _PaperKis(price=70.0, prev_close=71.0)
        engine, struct = _engine([], kis=kis, symbols=("TQQQ",))

        engine.run_paper_loc_emulation(now=DECIDE)

        cycle = struct.db("trading_cycle").get(symbol="TQQQ", status="ACTIVE")
        self.assertEqual((cycle["total_investment"], cycle["division_count"]), (10000.0, 20))
        # First round: limit at prev close +12% (79.52) with 500/79.52 = 6 shares.
        self.assertEqual(kis.buy_calls[0], ("TQQQ", 6, 79.52, "LIMIT"))

    def test_shares_held_outside_a_cycle_block_the_auto_start(self):
        kis = _PaperKis(price=70.0, prev_close=71.0, holdings=[{"symbol": "TQQQ", "qty": 5}])
        engine, struct = _engine([], kis=kis, symbols=("TQQQ",))

        result = engine.run_paper_loc_emulation(now=DECIDE)

        self.assertEqual(result["results"][0]["status"], "held_outside_cycle")
        self.assertEqual(struct.db("trading_cycle").rows(), [])
        self.assertEqual(kis.buy_calls, [])

    def test_unbooked_fills_block_the_decision(self):
        # 20 at the broker, 14 in the cycle: yesterday's fills were not synced.
        kis = _PaperKis(holdings=[{"symbol": "SOXL", "qty": 20}])
        engine, struct = _engine([_soxl()], kis=kis)

        first = engine.run_paper_loc_emulation(now=DECIDE)
        engine.run_paper_loc_emulation(now=DECIDE)

        self.assertEqual(first["status"], "retry")
        self.assertEqual(first["results"][0]["status"], "ledger_mismatch")
        self.assertEqual(kis.buy_calls + kis.sell_calls, [])
        self.assertEqual(len(_events(struct, "IB_PAPER_LOC_ERROR")), 1)

    def test_ambiguous_order_response_is_never_resent(self):
        kis = _PaperKis()
        calls = []

        def lost(*args, **kwargs):
            calls.append(args)
            raise TimeoutError("accepted, response lost")

        kis.buy_order = lost
        engine, struct = _engine([_soxl()], kis=kis)
        engine.run_paper_loc_emulation(now=DECIDE)
        engine.run_paper_loc_emulation(now=DECIDE)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(_events(struct, "IB_PAPER_LOC_ORDER_ERROR")), 3)

    def test_quote_failure_retries_without_claiming_the_day(self):
        kis = _PaperKis()
        quote = kis.get_current_price
        kis.get_current_price = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("quote timeout"))
        engine, struct = _engine([_soxl()], kis=kis)

        self.assertEqual(engine.run_paper_loc_emulation(now=DECIDE)["status"], "retry")
        kis.get_current_price = quote
        self.assertEqual(engine.run_paper_loc_emulation(now=DECIDE)["status"], "completed")
        self.assertEqual(len(kis.buy_calls), 3)

    def test_ledger_t_tracks_invested_value(self):
        engine, _ = _engine([])
        self.assertAlmostEqual(engine._ledger_t_value(_soxl()), 2.7208, places=4)
        self.assertEqual(engine._ledger_t_value(_soxl(total_spent=0.0)), 0.0)


if __name__ == "__main__":
    unittest.main()
