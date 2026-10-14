"""US day-trade order sizing and pricing (no broker traffic)."""
import contextlib
import datetime
import unittest
from unittest.mock import Mock, patch

from test_daytrade_engine_regressions import _engine_with_state, _StrategyStub, daytrade_engine
from test_vrev_execution_timing import module as daytrade_module

USD_KRW = 1390.0


def _engine():
    engine, store = _engine_with_state({}, [])
    daytrade_engine._USD_KRW_CACHE.clear()
    return engine, store


class UsEntrySizingTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(daytrade_engine._USD_KRW_CACHE.clear)

    def test_auto_entry_seed_buys_at_least_one_share(self):
        # Before: entry_seed_krw held the USD minimum (CRWD 418.65), which the
        # budget divided by USD/KRW again: $0.30 -> 0 shares on every US entry.
        engine, _ = _engine()
        engine._usd_krw_rate = lambda: USD_KRW
        prices = {"CRWD": 412.37, "PLTR": 25.10, "SERV": 4.20}
        rows = [dict(symbol=symbol, market="US", strategy_id="us_premarket", last_price=price,
                     source="leaderboard",
                     entry_seed_krw=round(engine._minimum_entry_seed_krw(price, market="US"), 2))
                for symbol, price in prices.items()]
        quantities = {}

        def execute_live(symbol, market="US", seed=0, name="", strategy_id=""):
            budget = engine._market_buy_budget(seed, prices[symbol], market="US")
            quantities[symbol] = engine._buy_qty(budget["buy_budget"], prices[symbol])
            return {"executed": False, "action": "HOLD", "status": {"signal": {"action": "HOLD"}}}

        engine._hard_locked = lambda: False
        engine.auto_enabled = lambda **kw: True
        engine._us_market_open = lambda: True
        engine._us_premarket_open = lambda: False
        engine.auto_candidates = lambda **kw: dict(effective_seed=3_000_000, remaining_seed_krw=3_000_000,
                                                   candidates=rows, slot_seed_limit_krw=1_000_000, position_count=0)
        engine._append_runtime_log = Mock()
        engine._auto_max_symbols = lambda **kw: 5
        engine.execute_live = execute_live
        engine.daily_loss_status = lambda **kw: {}
        engine.shared_budget_status = lambda **kw: {}
        engine.portfolio_usage = lambda **kw: {}

        engine.us_auto_cycle(requested_seed=3_000_000)

        self.assertEqual(set(quantities), set(prices))
        for symbol, qty in quantities.items():
            self.assertGreaterEqual(qty, 1, symbol)

    def test_unknown_rate_gives_no_seed_rather_than_a_wrong_one(self):
        engine, _ = _engine()
        engine._usd_krw_rate = lambda: 0.0
        self.assertEqual(engine._minimum_entry_seed_krw(412.37, market="US"), 0.0)

    def test_rate_falls_back_in_order_and_is_cached(self):
        engine, _ = _engine()
        broker = Mock()
        broker.get_present_balance.return_value = {"usd_krw": 0}
        broker._get_usd_krw_rate_fallback.return_value = {"rate": 1385.5}
        engine._broker = lambda: broker
        engine._fetch_kis_balance_raw = lambda: {"usd_krw": 0}

        self.assertEqual(engine._usd_krw_rate(), 1385.5)
        broker._get_usd_krw_rate_fallback.return_value = {"rate": 1500.0}
        self.assertEqual(engine._usd_krw_rate(), 1385.5)
        broker._get_usd_krw_rate_fallback.assert_called_once()

    def test_balance_rate_wins_when_present(self):
        engine, _ = _engine()
        broker = Mock()
        engine._broker = lambda: broker
        engine._fetch_kis_balance_raw = lambda: {"usd_krw": 1391.2}
        self.assertEqual(engine._usd_krw_rate(), 1391.2)
        broker._get_usd_krw_rate_fallback.assert_not_called()


def _us_state(avg_price, qty=7, strategy_id="us_premarket", **extra):
    row = dict(symbol="TEST", market="US", strategy_id=strategy_id, position_qty=qty, avg_price=avg_price,
               session_date="2026-05-26", realized_profit=0, orders=[], buy1_used=True)
    row.update(extra)
    return row


def _us_signal(state, price, now, **engine_overrides):
    engine, _ = _engine_with_state({"TEST.US": state}, [])
    daytrade_engine._USD_KRW_CACHE.clear()
    engine._usd_krw_rate = lambda: USD_KRW
    engine._now = lambda: now
    engine._append_runtime_log = lambda *_a, **_k: None
    engine._profile_for = lambda *_a, **_k: dict(daytrade_module.Daytrade.US_DEFAULT_PROFILE)
    for name, value in engine_overrides.items():
        setattr(engine, name, value)
    with patch.object(_StrategyStub, "_event_filter_snapshot", create=True,
                      new=lambda *_a, **_k: {"blocked": False}):
        return engine._signal_from_state("TEST", market="US", seed=1000000, strategy_id=state["strategy_id"],
                                         sync_broker=False, allow_buy=False, current_price_override=price)["signal"]


# 2026-05-26 is in US daylight time: 04:45 KST on 05-27 is 15:45 ET on 05-26.
CLOSE_WINDOW = datetime.datetime(2026, 5, 27, 4, 45)
MIDDAY = datetime.datetime(2026, 5, 27, 1, 0)


class UsExitTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(daytrade_engine._USD_KRW_CACHE.clear)

    def test_take_profit_is_not_held_back_by_the_won_floor(self):
        # +5%: 7 shares earn ~$31 net of US fees. The ₩500 floor was compared
        # with dollars, so every US take-profit became "미세 익절 보류".
        signal = _us_signal(_us_state(100.0), 105.0, MIDDAY)
        self.assertEqual(signal["action"], "SELL_FULL")

    def test_tiny_us_gain_is_still_held_for_fees(self):
        signal = _us_signal(_us_state(100.0, strategy_id="us_premarket", buy1_used=False),
                            100.2, MIDDAY, _profile_for=lambda *_a, **_k: {
                                **daytrade_module.Daytrade.US_DEFAULT_PROFILE, "jackpot_take_profit_pct": 0.1})
        self.assertEqual(signal["action"], "HOLD")
        self.assertIn("$", signal["reason"])

    def test_us_strategy_flattens_before_the_close(self):
        signal = _us_signal(_us_state(100.0), 101.0, CLOSE_WINDOW)
        self.assertEqual(signal["action"], "SELL_FULL")
        self.assertTrue(signal["risk_exit"])
        self.assertIn("장마감", signal["reason"])

    def test_us_holding_never_gets_a_domestic_pre_sell(self):
        signal = _us_signal(_us_state(100.0, strategy_id="vrev"), 102.6, MIDDAY,
                            _reservation_rearm_ready=lambda *_a, **_k: True)
        self.assertNotEqual(signal["action"], "PRE_SELL_JACKPOT")


class UsPricingTests(unittest.TestCase):
    def test_market_orders_are_marketable_limits(self):
        engine, _ = _engine()
        self.assertEqual(engine._us_marketable_price(100.0, "BUY"), 101.0)
        self.assertEqual(engine._us_marketable_price(100.0, "SELL"), 99.0)
        self.assertEqual(engine._us_marketable_price(0.5, "SELL"), 0.495)

    def test_us_auto_stop_keeps_cents_and_ks_keeps_won(self):
        engine, _ = _engine()
        self.assertEqual(engine._auto_stop_level(4.90, 8.0, "US"), 4.51)
        self.assertEqual(engine._auto_stop_level(12.34, 8.0, "US"), 11.35)
        self.assertEqual(engine._auto_stop_level(9010, 1.5, "KS"), 8875)
        self.assertEqual(engine._auto_stop_level(100.0, 0, "US"), 0)

    def test_us_close_window_follows_daylight_saving(self):
        engine, _ = _engine()
        for now, expected in ((datetime.datetime(2026, 5, 27, 4, 45), True),     # EDT 15:45
                              (datetime.datetime(2026, 11, 10, 5, 45), True),    # EST 15:45
                              (datetime.datetime(2026, 11, 10, 4, 45), False)):  # EST 14:45
            engine._now = lambda now=now: now
            self.assertEqual(engine._is_market_close_approaching("US"), expected, now)


class UsPremarketGapTests(unittest.TestCase):
    def test_gap_is_the_opening_gap_against_the_quote_prev_close(self):
        # Gap-up open 110 over a 100 close, now 104 after a pullback. The old
        # code read prev close = today's open and reported a -5.5% "gap".
        engine, _ = _engine_with_state({}, [])
        daytrade_engine._USD_KRW_CACHE.clear()
        self.addCleanup(daytrade_engine._USD_KRW_CACHE.clear)
        engine._now = lambda: MIDDAY
        engine._profile_for = lambda *_a, **_k: dict(daytrade_module.Daytrade.US_DEFAULT_PROFILE)
        engine._aggregate_ticks_to_candle = lambda *_a: None
        engine._market_buy_budget = lambda *_a, **_k: {"budget_total": 1000.0, "buy_budget": 1000.0}
        engine._append_runtime_log = lambda *_a, **_k: None
        engine._guardrails = lambda *_a, **_k: {"issues": [], "warnings": []}
        engine._latest_snapshot = lambda *_a, **_k: (
            {"date": "2026-05-26", "prev_close": 110.0, "prev_close_confirmed": True},
            {"close": 104.0, "open": 110.0, "high": 112.0, "low": 103.0, "volume": 50000,
             "quote_prev_close": 100.0, "indicator_bar_count": 60})
        with patch.object(_StrategyStub, "_event_filter_snapshot", create=True,
                          new=lambda *_a, **_k: {"blocked": False}):
            signal = engine._signal_from_state("TEST", market="US", seed=1000000,
                                               strategy_id="us_premarket", sync_broker=False)["signal"]
        self.assertAlmostEqual(signal["us_meta"]["gap_pct"], 10.0, places=2)


class UsSellFillTests(unittest.TestCase):
    def _state(self):
        return {"symbol": "TEST", "market": "US", "position_qty": 7, "avg_price": 100.0,
                "pending_sell_order_no": "S1", "pending_sell_qty": 7, "pending_sell_type": "SELL_STOP_LOSS",
                "pending_sell_placed_at": "2026-05-26 23:00:00",
                "orders": [{"order_no": "S1", "action": "SELL", "qty": 7, "filled_qty": 0}]}

    def _engine(self, rows):
        engine, _ = _engine()
        broker = Mock()
        broker.request_options = lambda **_k: contextlib.nullcontext()
        broker.get_overseas_order_history.return_value = rows
        engine._broker = lambda: broker
        engine._us_exchange = lambda _symbol: "NASD"
        return engine

    def test_filled_us_sell_takes_the_shares_off_the_books(self):
        state = self._state()
        engine = self._engine([{"order_no": "S1", "symbol": "TEST", "side": "SELL", "status": "FILLED",
                                "filled_qty": 7, "filled_price": 92.0}])
        self.assertEqual(engine._sync_us_pending_order(state, "TEST", "SELL"), "filled")
        self.assertEqual((state["position_qty"], state["avg_price"]), (0, 0.0))
        self.assertEqual(state["pending_sell_order_no"], "")
        self.assertEqual(state["last_exit_action"], "SELL_STOP_LOSS")

    def test_partly_filled_then_cancelled_keeps_the_rest(self):
        state = self._state()
        engine = self._engine([{"order_no": "S1", "symbol": "TEST", "side": "SELL", "status": "CANCELLED",
                                "filled_qty": 3, "filled_price": 92.0}])
        self.assertEqual(engine._sync_us_pending_order(state, "TEST", "SELL"), "cancelled")
        self.assertEqual((state["position_qty"], state["avg_price"]), (4, 100.0))

    def test_open_order_changes_nothing(self):
        state = self._state()
        engine = self._engine([])
        self.assertEqual(engine._sync_us_pending_order(state, "TEST", "SELL"), "open")
        self.assertEqual(state["position_qty"], 7)
        self.assertEqual(state["pending_sell_order_no"], "S1")


if __name__ == "__main__":
    unittest.main()
