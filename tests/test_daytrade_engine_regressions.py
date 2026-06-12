import builtins
import copy
import datetime
import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class _TimeStub:
    @staticmethod
    def now():
        return datetime.datetime(2026, 5, 26, 10, 0, 0)

    @staticmethod
    def normalize(value):
        return str(value or "")

    @staticmethod
    def to_kst(value):
        if isinstance(value, datetime.datetime):
            return value
        try:
            return datetime.datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None


class _StrategyStub:
    recommendation_payload = None
    strategy_specs = {
        "vrev": {"name": "vrev", "live_supported": True, "market": "KS"},
        "volume_breakout": {"name": "volume_breakout", "live_supported": True, "market": "KS"},
        "us_premarket": {"name": "us_premarket", "live_supported": True, "market": "US"},
        "us_opening_reclaim": {"name": "us_opening_reclaim", "live_supported": False, "market": "US"},
        "shadow_only": {"name": "shadow_only", "live_supported": False, "market": "KS"},
    }

    def __init__(self, _struct):
        pass

    def defaults(self):
        return {"strategy": "vrev"}

    def us_defaults(self):
        return {"symbol": "TQQQ", "strategy": "us_premarket"}

    def us_candidate_universe(self):
        return [{"symbol": "TQQQ", "market": "US", "name": "TQQQ", "exchange": "NASD"}]

    def _normalize_strategy(self, strategy_id):
        return strategy_id or "vrev"

    def symbol_name(self, symbol):
        return str(symbol)

    def strategy_spec(self, strategy_id):
        strategy_id = strategy_id or "vrev"
        return copy.deepcopy(self.strategy_specs.get(strategy_id, {"name": strategy_id, "live_supported": False, "market": "KS"}))

    def vrev_entry_issues(self, bar, profile=None):
        return []

    def recommendation_training_defaults(self):
        return {
            "period": "10d",
            "interval": "5m",
            "min_session_count": 6,
            "min_validation_sessions": 3,
        }

    def _build_quality_guard(self, leaderboard, _training_defaults, market="KS"):
        trade_ready_count = len([row for row in leaderboard if row.get("trade_ready")])
        issues = []
        if trade_ready_count <= 0:
            issues.append("실주문 가능한 후보가 없습니다.")
        return {
            "block_new_entries": trade_ready_count <= 0,
            "issues": issues,
            "trade_ready_count": trade_ready_count,
        }

    def recommend(self, **kwargs):
        return copy.deepcopy(self.recommendation_payload or {})

    def latest_recommendation(self, **kwargs):
        return copy.deepcopy(self.recommendation_payload or {})


class _WizStub:
    @staticmethod
    def model(name):
        if name == "portal/trading/kst":
            return _TimeStub
        if name == "portal/trading/struct/daytrade":
            return _StrategyStub
        raise AssertionError(f"unexpected wiz.model({name})")


builtins.wiz = _WizStub()
daytrade_engine_path = SRC / "portal" / "trading" / "model" / "struct" / "daytrade_engine.py"
daytrade_engine_spec = importlib.util.spec_from_file_location("daytrade_engine_under_test", daytrade_engine_path)
daytrade_engine = importlib.util.module_from_spec(daytrade_engine_spec)
daytrade_engine_spec.loader.exec_module(daytrade_engine)


class _KisApiStub:
    def __init__(self, domestic_holdings=None, overseas_holdings=None):
        self.domestic_holdings = list(domestic_holdings or [])
        self.overseas_holdings = list(overseas_holdings or [])
        self.buying_power_info = {
            "ok": True,
            "amount": 0,
            "qty": 0,
            "executable_amount": 0,
            "executable_qty": 0,
            "estimated_amount": 0,
            "estimated_qty": 0,
        }
        self.buy_orders = []

    def get_balance(self):
        return {"holdings": copy.deepcopy(self.overseas_holdings)}

    def get_domestic_balance(self):
        return {"holdings": copy.deepcopy(self.domestic_holdings)}

    def get_buying_power_info(self, symbol="TQQQ", price=0, exchange="NASD"):
        payload = copy.deepcopy(self.buying_power_info)
        payload.setdefault("symbol", symbol)
        payload.setdefault("price", price)
        payload.setdefault("exchange", exchange)
        return payload

    def buy_order(self, symbol, qty, price=0, order_type="MARKET", exchange="NASD"):
        order = {
            "order_no": f"ORDER-{len(self.buy_orders) + 1}",
            "symbol": symbol,
            "qty": qty,
            "price": price,
            "order_type": order_type,
            "exchange": exchange,
            "market": "US",
        }
        self.buy_orders.append(copy.deepcopy(order))
        return order


class _StructStub:
    def __init__(self, configs=None, domestic_holdings=None, overseas_holdings=None):
        self.configs = dict(configs or {})
        self.kis_api = _KisApiStub(domestic_holdings, overseas_holdings)

    def get_config(self, key, default=""):
        return self.configs.get(key, default)


def _engine_with_state(state_map, holdings, configs=None):
    builtins.wiz = _WizStub()
    struct = _StructStub(configs=configs, domestic_holdings=holdings)
    engine = daytrade_engine.DomesticDaytradeEngine(struct)
    store = copy.deepcopy(state_map)

    def load_state_map():
        return copy.deepcopy(store)

    def save_state_map(payload):
        store.clear()
        store.update(copy.deepcopy(payload))

    engine._load_state_map = load_state_map
    engine._save_state_map = save_state_map
    engine._timestamp = lambda: "2026-05-26 10:00:00"
    engine._fetch_kis_balance_raw = lambda use_cache_only=False: {"holdings": copy.deepcopy(holdings)}
    engine._latest_snapshot = lambda symbol, market="KS": ({}, {"close": next(
        (
            item.get("current_price") or item.get("avg_price") or 0
            for item in holdings
            if str(item.get("symbol")) == str(symbol)
        ),
        0,
    )})
    return engine, lambda: copy.deepcopy(store)


class DaytradeEngineRegressionTests(unittest.TestCase):
    def test_execute_exit_watch_skips_domestic_when_auto_disabled(self):
        engine, _state = _engine_with_state({}, [], configs={
            "daytrade_auto_enabled": "false",
            "daytrade_exit_watch_enabled": "true",
        })

        def _should_not_run(**_kwargs):
            raise AssertionError("kr_execute_exit_watch should not run when domestic auto is disabled")

        engine.kr_execute_exit_watch = _should_not_run

        result = engine.execute_exit_watch(requested_seed=1000000, market="KS")

        self.assertFalse(result["executed"])
        self.assertEqual(result["executed_count"], 0)
        self.assertIn("비활성", result["message"])

    def test_execute_exit_watch_skips_us_when_auto_disabled(self):
        engine, _state = _engine_with_state({}, [], configs={
            "daytrade_us_auto_enabled": "false",
            "daytrade_us_exit_watch_enabled": "true",
        })

        def _should_not_run(**_kwargs):
            raise AssertionError("us_execute_exit_watch should not run when US auto is disabled")

        engine.us_execute_exit_watch = _should_not_run

        result = engine.execute_exit_watch(requested_seed=1000000, market="US")

        self.assertFalse(result["executed"])
        self.assertEqual(result["executed_count"], 0)
        self.assertIn("비활성", result["message"])

    def test_cancel_pending_auto_sells_clears_domestic_pending_state(self):
        engine, state = _engine_with_state({
            "122630.KS": {
                "symbol": "122630",
                "market": "KS",
                "pending_sell_order_no": "ORDER-1",
                "pending_sell_price": 12345,
                "pending_sell_qty": 7,
                "pending_sell_type": "JACKPOT",
                "pending_sell_placed_at": "2026-05-26 09:50:00",
            },
        }, [])
        engine._cancel_open_sell_orders = lambda _symbol: []

        result = engine.cancel_pending_auto_sells(market="KS", reason="국장 단타 자동매매 OFF")
        saved = state()

        self.assertTrue(result["executed"])
        self.assertEqual(result["cleared_symbol_count"], 1)
        self.assertEqual(saved["122630.KS"]["pending_sell_order_no"], "")
        self.assertEqual(saved["122630.KS"]["pending_sell_qty"], 0)
        self.assertEqual(saved["122630.KS"]["last_exit_reason"], "국장 단타 자동매매 OFF")

    def test_daily_loss_limit_is_soft_warning_by_default(self):
        engine, _state = _engine_with_state({
            "000001.KS": {
                "symbol": "000001",
                "market": "KS",
                "session_date": "2026-05-26",
                "position_qty": 0,
                "avg_price": 0,
                "realized_profit": -60000,
            },
        }, [], configs={"daytrade_daily_loss_limit_krw": "50000"})

        status = engine.daily_loss_status(requested_seed=1000000, use_live_price=False, use_cache_only=True)

        self.assertTrue(status["soft_limit_reached"])
        self.assertFalse(status["halt_enabled"])
        self.assertFalse(status["halt_new_buys"])

    def test_stop_loss_reentry_uses_cooldown_not_same_day_block_by_default(self):
        engine, _state = _engine_with_state({}, [], configs={"daytrade_stop_reentry_cooldown_sec": "900"})

        status = engine._reentry_cooldown_status({
            "position_qty": 0,
            "last_exit_action": "SELL_STOP_LOSS",
            "last_exit_watch_at": "2026-05-26 09:50:00",
        }, {}, market="KS")

        self.assertTrue(status["active"])
        self.assertGreater(status["cooldown_sec"], 0)
        self.assertNotEqual(status["reason"], "당일 손절 종목은 같은 거래일 재진입을 차단합니다.")

    def test_state_order_open_position_rebuilds_open_lots(self):
        engine, _state = _engine_with_state({}, [])
        position = engine._state_order_open_position({
            "orders": [
                {"action": "BUY1", "qty": 18, "price": 111000},
                {"action": "SELL_STOP_LOSS", "qty": 18, "price": 109000},
                {"action": "BUY1", "qty": 2, "price": 110000},
                {"action": "BUY1", "qty": 2, "price": 110500},
            ],
        })

        self.assertEqual(position["qty"], 4)
        self.assertEqual(position["avg_price"], 110250)

    def test_sync_adopts_broker_position_when_local_orders_prove_open_lot(self):
        holdings = [{
            "symbol": "138040",
            "market": "KS",
            "name": "Meritz",
            "qty": 4,
            "avg_price": 110250,
            "current_price": 107000,
        }]
        engine, state = _engine_with_state({
            "138040.KS": {
                "symbol": "138040",
                "market": "KS",
                "name": "Meritz",
                "position_qty": 0,
                "avg_price": 0,
                "orders": [
                    {"action": "BUY1", "qty": 18, "price": 111000},
                    {"action": "SELL_STOP_LOSS", "qty": 18, "price": 109000},
                    {"action": "BUY1", "qty": 2, "price": 110000},
                    {"action": "BUY1", "qty": 2, "price": 110500},
                ],
            },
        }, holdings, configs={"daytrade_adopt_broker_positions": "false"})

        engine._sync_broker_positions()
        synced = state()["138040.KS"]

        self.assertEqual(synced["position_qty"], 4)
        self.assertEqual(synced["avg_price"], 110250)
        self.assertFalse(synced["broker_unmanaged_position"])
        self.assertEqual(synced["broker_unmanaged_qty"], 0)
        self.assertTrue(synced["buy1_used"])

    def test_sync_keeps_broker_only_holding_unmanaged_when_adoption_disabled(self):
        holdings = [{
            "symbol": "005930",
            "market": "KS",
            "name": "Samsung",
            "qty": 3,
            "avg_price": 70000,
            "current_price": 70100,
        }]
        engine, state = _engine_with_state({
            "005930.KS": {
                "symbol": "005930",
                "market": "KS",
                "name": "Samsung",
                "position_qty": 0,
                "avg_price": 0,
                "orders": [],
            },
        }, holdings, configs={"daytrade_adopt_broker_positions": "false"})

        engine._sync_broker_positions()
        synced = state()["005930.KS"]

        self.assertEqual(synced["position_qty"], 0)
        self.assertTrue(synced["broker_unmanaged_position"])
        self.assertEqual(synced["broker_unmanaged_qty"], 3)

    def test_auto_candidates_block_when_only_non_live_strategy_is_trade_ready(self):
        engine, _state = _engine_with_state({}, [], configs={"daytrade_auto_max_symbols": "5"})
        _StrategyStub.recommendation_payload = {
            "leaderboard": [
                {
                    "symbol": "009150",
                    "market": "KS",
                    "name": "Samsung Electro",
                    "strategy_id": "shadow_only",
                    "strategy_name": "shadow_only",
                    "trade_ready": True,
                    "score": 25.0,
                    "rank_score": 25.0,
                    "validation_return": 4.0,
                    "validation_win_rate": 60.0,
                    "validation_robustness": 10.0,
                    "avg_day_range_pct": 9.0,
                    "liquidity_score": 5.0,
                    "last_price": 150000.0,
                },
                {
                    "symbol": "004170",
                    "market": "KS",
                    "name": "Shinsegae",
                    "strategy_id": "vrev",
                    "strategy_name": "vrev",
                    "trade_ready": False,
                    "score": 5.0,
                    "rank_score": 5.0,
                    "validation_return": -1.0,
                    "validation_win_rate": 35.0,
                    "validation_robustness": -2.0,
                    "avg_day_range_pct": 4.0,
                    "liquidity_score": 2.0,
                    "last_price": 200000.0,
                    "quality_issues": ["검증 수익률 -1.00%"],
                },
            ],
            "quality_guard": {"block_new_entries": False, "issues": [], "trade_ready_count": 1},
        }
        engine.shared_budget_status = lambda **kwargs: {
            "effective_daytrade_seed": 3000000.0,
            "total_seed_krw": 3000000.0,
            "used_seed_krw": 0.0,
            "remaining_seed_krw": 3000000.0,
            "capacity_daytrade_seed_krw": 3000000.0,
            "available_for_daytrade": 3000000.0,
        }
        engine.portfolio_usage = lambda: {"active_positions": [], "active_entry_seed_krw": 0.0, "active_cost_krw": 0.0}
        engine._append_runtime_log = lambda *args, **kwargs: None
        engine.auto_enabled = lambda market="KS": True

        result = engine.auto_candidates(requested_seed=3000000, market="KS")

        self.assertEqual(result["candidates"], [])
        self.assertTrue(result["recommendation"]["live_quality_guard"]["block_new_entries"])
        self.assertEqual(result["recommendation"]["live_quality_guard"]["trade_ready_count"], 0)
        _StrategyStub.recommendation_payload = None

    def test_live_strategy_allowed_accepts_ks_volume_breakout_when_live_supported(self):
        engine, _state = _engine_with_state({}, [], configs={"daytrade_auto_max_symbols": "5"})
        self.assertTrue(engine._live_strategy_allowed("volume_breakout", market="KS"))
        self.assertTrue(engine._live_strategy_allowed("vrev", market="KS"))
        self.assertFalse(engine._live_strategy_allowed("shadow_only", market="KS"))

    def test_active_positions_marks_synced_local_order_position_auto_managed(self):
        holdings = [{
            "symbol": "138040",
            "market": "KS",
            "name": "Meritz",
            "qty": 4,
            "avg_price": 110250,
            "current_price": 107000,
        }]
        engine, _state = _engine_with_state({
            "138040.KS": {
                "symbol": "138040",
                "market": "KS",
                "name": "Meritz",
                "position_qty": 0,
                "avg_price": 0,
                "orders": [
                    {"action": "BUY1", "qty": 2, "price": 110000},
                    {"action": "BUY1", "qty": 2, "price": 110500},
                ],
            },
        }, holdings, configs={"daytrade_adopt_broker_positions": "false"})

        rows = engine.active_positions()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "138040")
        self.assertEqual(rows[0]["position_qty"], 4)
        self.assertTrue(rows[0]["auto_managed"])

    def test_minimum_entry_seed_keeps_one_share_buyable_after_buffer(self):
        engine, _state = _engine_with_state({}, [], configs={"daytrade_buy_buffer_ratio": "0.985"})

        required_seed = engine._minimum_entry_seed(918000, market="KS")

        self.assertGreater(required_seed, 918000)
        self.assertGreaterEqual(engine._buy_qty(required_seed, 918000), 1)

    def test_ks_auto_max_symbols_has_larger_floor_even_with_old_config(self):
        engine, _state = _engine_with_state({}, [], configs={"daytrade_auto_max_symbols": "8"})

        self.assertEqual(engine._auto_max_symbols(market="KS"), 16)

    def test_legacy_narrow_cache_refreshes_before_filtered_limit_masks_it(self):
        engine, _state = _engine_with_state({}, [])
        legacy_cache = {
            "leaderboard": [{"symbol": f"{idx:06d}"} for idx in range(12)],
        }
        filtered = {
            "leaderboard": [{"symbol": f"{idx:06d}"} for idx in range(12)],
            "leaderboard_limit": 48,
        }

        should_refresh, meta = engine._cached_recommendation_narrow_for_auto(legacy_cache, filtered, 16)

        self.assertTrue(should_refresh)
        self.assertEqual(meta["cached_leaderboard_count"], 12)
        self.assertEqual(meta["cached_leaderboard_limit"], 0)
        self.assertEqual(meta["filtered_leaderboard_limit"], 48)

    def test_expanded_cache_is_not_refreshed_only_because_price_filter_is_short(self):
        engine, _state = _engine_with_state({}, [])
        expanded_cache = {
            "leaderboard": [{"symbol": f"{idx:06d}"} for idx in range(48)],
            "leaderboard_limit": 48,
        }
        filtered = {
            "leaderboard": [{"symbol": f"{idx:06d}"} for idx in range(4)],
            "leaderboard_limit": 48,
        }

        should_refresh, meta = engine._cached_recommendation_narrow_for_auto(expanded_cache, filtered, 16)

        self.assertFalse(should_refresh)
        self.assertEqual(meta["cached_leaderboard_count"], 48)
        self.assertEqual(meta["filtered_leaderboard_count"], 4)

    def test_fast_universe_expansion_fills_narrow_auto_leaderboard(self):
        engine, _state = _engine_with_state({}, [])
        class _ExpandedStrategy(_StrategyStub):
            def candidate_universe(self, market="KS"):
                return [
                    {"symbol": f"{idx:06d}", "name": f"Stock {idx}", "market": "KS"}
                    for idx in range(20)
                ]

        engine._Daytrade = _ExpandedStrategy
        recommendation = {
            "leaderboard": [{"symbol": f"{idx:06d}", "market": "KS", "strategy_id": "vrev"} for idx in range(12)],
        }

        expanded = engine._expand_recommendation_with_candidate_universe(
            recommendation,
            market="KS",
            target_count=16,
            max_count=16,
        )

        self.assertEqual(len(expanded["leaderboard"]), 16)
        self.assertEqual(expanded["fast_universe_added_count"], 4)
        self.assertTrue(expanded["fast_universe_expanded"])
        self.assertEqual(expanded["candidate_universe_count"], 20)

    def test_guardrails_use_allocated_seed_as_symbol_limit_floor(self):
        engine, _state = _engine_with_state({}, [], configs={
            "daytrade_buy_buffer_ratio": "0.985",
            "daytrade_opening_guard_minutes": "0",
            "daytrade_opening_stop_halt_minutes": "0",
        })
        engine.check_kis_connection = lambda: {"connected": True, "is_real": True}
        engine.portfolio_usage = lambda *args, **kwargs: {"active_entry_seed_krw": 0, "active_cost_krw": 0}
        engine.shared_budget_status = lambda **kwargs: {
            "slot_seed_limit_krw": 50000,
            "capacity_daytrade_seed_krw": 2610291,
            "total_seed_krw": 2610291,
        }
        engine.daily_loss_status = lambda **kwargs: {"halt_new_buys": False}
        engine._today_trade_log_stats = lambda market="KS": {"stop_loss_count": 0, "buy_count": 0}
        engine._market_daily_stop_loss_halt_count = lambda market: 0
        engine._minutes_since_market_open = lambda market="KS": 90
        engine._recent_symbol_quality_gate = lambda symbol, market="KS": {"allow": True, "reason": "", "stats": {}}
        engine._openai_entry_gate = lambda *args, **kwargs: {"enabled": False, "allow": True, "reason": "disabled"}

        guardrails = engine._guardrails(
            "036570",
            "KS",
            413017.03,
            {"position_qty": 0, "avg_price": 0, "orders": []},
            {
                "action": "BUY1",
                "strategy_id": "vrev",
                "current_price": 271500,
                "order_qty": 1,
                "price_source": "kis_domestic_quote",
            },
            {},
            {"intraday_range_pct": 1.2, "gap_from_open_pct": 0.4},
            {"budget_ratio": 1.0, "max_order_cooldown_sec": 0, "max_live_day_range_pct": 8.5, "max_live_gap_pct": 5.5},
        )

        self.assertNotEqual(guardrails["risk_status"], "HALT")
        self.assertFalse(any("종목당 동적 한도" in issue for issue in guardrails["issues"]))

    def test_auto_cycle_wait_summary_classifies_quality_exclusions(self):
        engine, _state = _engine_with_state({}, [])

        summary = engine._auto_cycle_wait_summary(
            results=[],
            excluded_by_price=[{"reason": "실전 후보 품질 미달: 검증PF 1.18 < 1.50"}],
            daily_loss={"halt_new_buys": False},
            market="KS",
        )

        self.assertEqual(summary["reason_summary"][0]["reason"], "품질 게이트 대기")

    def test_shared_budget_status_uses_combined_us_orderable_amount(self):
        engine, _state = _engine_with_state({}, [])
        engine.infinite_buy_daily_reserve = lambda: {"reserve_usd": 0, "cycles": [], "cycle_count": 0}
        engine._fetch_kis_balance_raw = lambda use_cache_only=False: {
            "withdrawable_krw": 1500000,
            "krw_balance": 1500000,
            "deposit_krw": 1500000,
            "usd_krw": 1350,
            "same_day_sell_krw": 0,
            "same_day_buy_krw": 0,
            "domestic_eval_krw": 0,
            "foreign_eval_krw": 0,
            "usd_cash_balance_usd": 0,
            "usd_cash_balance_krw": 0,
            "subscription_deposit_krw": 0,
            "d1_deposit_krw": 0,
            "d2_deposit_krw": 0,
            "present_total_asset_krw": 1500000,
            "direct_total_asset_krw": 1500000,
            "fallback_total_asset_krw": 1500000,
            "summary_total_asset_krw": 1500000,
            "total_asset_krw": 1500000,
            "source": "stub",
            "total_asset_source": "stub",
        }
        engine.portfolio_usage = lambda **kwargs: {"active_entry_seed_krw": 0, "active_cost_krw": 0, "position_count": 0}
        engine.struct.kis_api.buying_power_info = {
            "ok": True,
            "amount": 0,
            "qty": 0,
            "estimated_amount": 1000,
            "estimated_qty": 5,
            "krw_auto_exchange_estimate_usd": 1000,
            "source": "ovrs_ord_psbl_amt",
        }

        budget = engine.shared_budget_status(requested_seed=1000000, market="US")

        self.assertEqual(budget["us_combined_orderable_amount_usd"], 1000.0)
        self.assertEqual(budget["us_estimated_orderable_qty"], 5)
        self.assertEqual(budget["actual_orderable_seed_krw"], 1500000.0)

if __name__ == "__main__":
    unittest.main()
