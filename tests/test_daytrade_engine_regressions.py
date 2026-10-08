import builtins
import copy
import datetime
import importlib.util
import pathlib
import sys
import unittest
from unittest.mock import patch


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
        self.domestic_fills = []

    def get_balance(self):
        return {"holdings": copy.deepcopy(self.overseas_holdings)}

    def get_domestic_balance(self):
        return {"holdings": copy.deepcopy(self.domestic_holdings)}

    def get_domestic_fills_today(self, symbol=""):
        rows = copy.deepcopy(self.domestic_fills)
        return [row for row in rows if not symbol or row.get("symbol") == symbol]

    def get_domestic_fills_for_day(self, _date_str, symbol=""):
        return self.get_domestic_fills_today(symbol)

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
    def test_locked_signal_does_not_analyze_or_fetch_quotes(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        engine, _ = _engine_with_state({}, [])
        engine.struct.order_policy = SimpleNamespace(read=lambda: {'symbols': {'005930': True}})
        engine._signal_from_state = Mock(side_effect=AssertionError('locked symbol analyzed'))
        result = engine.signal_status('005930')
        self.assertTrue(result['analysis_excluded'])
        engine._signal_from_state.assert_not_called()
        self.assertFalse(engine.analysis_allowed('SOXL'))
    def test_budget_excludes_locked_positions_but_account_exposure_keeps_them(self):
        from types import SimpleNamespace
        engine, _ = _engine_with_state({}, [])
        permissions = {'symbols': {'005930': True, '069500': False, 'SOXL': False}}
        engine.struct.order_policy = SimpleNamespace(read=lambda: permissions)
        engine.active_positions = lambda **kwargs: [
            {'symbol': '005930', 'position_qty': 10, 'avg_price': 100, 'current_price': 110},
            {'symbol': '069500', 'position_qty': 2, 'avg_price': 50, 'current_price': 55},
            {'symbol': 'SOXL', 'position_qty': 5, 'avg_price': 100, 'current_price': 110}]
        budget = engine.portfolio_usage(use_live_price=False, budget_only=True)
        self.assertEqual(budget['active_cost_krw'], 100)
        self.assertEqual(budget['position_count'], 1)
        full = engine.portfolio_usage(use_live_price=False)
        self.assertEqual(full['active_cost_krw'], 1600)
        permissions['symbols']['005930'] = False
        self.assertEqual(engine.portfolio_usage(use_live_price=False, budget_only=True)['active_cost_krw'], 1100)

    def test_budget_policy_failure_does_not_release_private_holdings_as_cash(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        engine, _ = _engine_with_state({}, [])
        engine.active_positions = lambda **kwargs: []
        engine.struct.order_policy = SimpleNamespace(read=Mock(side_effect=RuntimeError('unavailable')))
        with self.assertRaises(RuntimeError):
            engine.portfolio_usage(use_live_price=False, budget_only=True)

    def test_domestic_budget_never_spends_locked_equity_or_double_counts_settlement(self):
        engine, _ = _engine_with_state({}, [])
        engine.infinite_buy_daily_reserve = lambda: {'reserve_usd': 0}
        engine._fetch_kis_balance_raw = lambda: {
            'withdrawable_krw': 100000, 'd1_deposit_krw': 100000,
            'krw_balance': 100000, 'usd_krw': 1350, 'source': 'test',
            'd2_deposit_krw': 100000, 'total_asset_krw': 10000000,
            'domestic_eval_krw': 9900000}
        engine.portfolio_usage = lambda **kwargs: {
            'active_entry_seed_krw': 50000, 'active_cost_krw': 50000, 'position_count': 1}
        budget = engine.shared_budget_status(requested_seed=5000000, market='KS')
        self.assertEqual(budget['cash_max_krw'], 100000)
        self.assertLessEqual(budget['total_seed_krw'], 150000)
        self.assertLessEqual(budget['remaining_seed_krw'], 100000)

    def test_closed_paper_session_blocks_even_forced_exit_before_quote_lookup(self):
        engine, _ = _engine_with_state({}, [])
        engine._daytrade_market_open = lambda market: False
        engine.signal_status = lambda *a, **k: self.fail("closed session must not fetch quotes or order")
        with patch.object(daytrade_engine, "_PAPER_MODE", True), patch.object(daytrade_engine, "_PAPER_CONTINUOUS", False):
            result = engine.execute_live("TQQQ", market="US", force=True, allow_buy=False)
        self.assertTrue(result["market_closed"])
        self.assertFalse(result["submitted"])

    def test_reserved_cash_is_subtracted_once_before_dynamic_allocation(self):
        engine, _ = _engine_with_state({}, [])
        engine.infinite_buy_daily_reserve = lambda: {'reserve_usd': 1000}
        engine._fetch_kis_balance_raw = lambda: {'withdrawable_krw': 1500000, 'krw_balance':1500000, 'usd_krw':1000, 'source':'test', 'total_asset_krw':10000000}
        engine.portfolio_usage = lambda **kwargs: {'active_entry_seed_krw':0, 'position_count':0}
        def allocate(**kwargs):
            self.assertEqual(kwargs['total_asset_krw'], 500000)
            self.assertEqual(kwargs['reserve_krw'], 0)
            return {'target_seed_krw': kwargs['total_asset_krw'] * .6}
        engine._dynamic_daytrade_allocation = allocate
        budget = engine.shared_budget_status(requested_seed=1000000, market='KS')
        self.assertEqual(budget['remaining_seed_krw'], 300000)
        self.assertEqual(budget['applied_reserve_krw'], 1000000)

    def test_exit_watch_does_not_submit_orders_after_domestic_market_close(self):
        engine, _state = _engine_with_state({
            "133690.KS": {"symbol": "133690", "market": "KS", "position_qty": 10, "avg_price": 100, "strategy_id": "vrev"},
        }, [], configs={"daytrade_auto_enabled": "true"})
        engine._daytrade_market_open = lambda market="KS": False
        engine._append_runtime_log = lambda *args, **kwargs: None
        engine.active_positions = lambda **kwargs: (_ for _ in ()).throw(AssertionError("closed market must not query positions"))
        engine.execute_live = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("closed market must not submit sell"))

        result = engine.kr_execute_exit_watch(requested_seed=5000000)

        self.assertTrue(result["market_closed"])
        self.assertFalse(result["submitted"])
        self.assertEqual(result["executed_count"], 0)

    def test_balance_snapshot_keeps_empty_domestic_holdings_when_kis_balance_fails(self):
        engine, _state = _engine_with_state({}, [])
        engine.struct.kis_api.get_domestic_balance = lambda: (_ for _ in ()).throw(RuntimeError("rate limited"))
        engine.struct.kis_api.get_balance = lambda: {"holdings": [], "cash_balance": 0, "total_eval": 0}
        engine.struct.kis_api.get_present_balance = lambda: {}
        engine.struct.kis_api.get_domestic_buying_power_info = lambda **_kwargs: {"ok": False}
        for key in ("_trading_kis_balance_cache_v2", "_trading_kis_balance_cache_ts"):
            if hasattr(sys, key):
                delattr(sys, key)

        raw = engine._fetch_kis_balance_raw()

        self.assertEqual(raw["holdings"], [])

    def test_paper_mode_exposes_daytrade_without_legacy_feature_flag(self):
        engine, _state = _engine_with_state({}, [], configs={})

        self.assertTrue(engine._feature_enabled())
        self.assertFalse(engine.auto_enabled())

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

    def test_pending_sell_matches_kis_order_number_without_leading_zeroes(self):
        engine, _state = _engine_with_state({}, [])
        engine.struct.kis_api.domestic_fills = [{
            "order_no": "37869",
            "symbol": "069500",
            "side": "SELL",
            "status": "FILLED",
            "filled_qty": 10,
            "filled_price": 106000,
            "rmn_qty": 0,
        }]
        engine._log_execution = lambda *_args, **_kwargs: None
        state = {
            "symbol": "069500",
            "market": "KS",
            "strategy_id": "vrev",
            "position_qty": 10,
            "avg_price": 105000,
            "realized_profit": 0,
            "pending_sell_order_no": "0000037869",
            "pending_sell_price": 106000,
            "pending_sell_qty": 10,
            "pending_sell_type": "JACKPOT",
            "pending_sell_placed_at": "2026-05-26 09:50:00",
        }

        status = engine._sync_pending_sell(state, "069500", "KS", current_price=106000)

        self.assertEqual(status, "filled")
        self.assertEqual(state["position_qty"], 0)
        self.assertEqual(state["realized_profit"], 10000)
        self.assertEqual(state["pending_sell_order_no"], "")

    def test_resolve_domestic_fill_matches_order_number_without_leading_zeroes(self):
        engine, _state = _engine_with_state({}, [])
        engine.struct.kis_api.domestic_fills = [{
            "order_no": "17001",
            "symbol": "069500",
            "side": "BUY",
            "status": "FILLED",
            "filled_qty": 3,
            "filled_price": 104900,
        }]

        fill = engine._resolve_domestic_fill(
            "069500",
            "BUY",
            {"order_no": "0000017001"},
            fallback_price=104860,
            fallback_qty=3,
        )

        self.assertEqual(fill["status"], "FILLED")
        self.assertEqual(fill["filled_qty"], 3)
        self.assertEqual(fill["filled_price"], 104900)

    def test_pending_buy_is_reconciled_from_kis_fill(self):
        engine, _state = _engine_with_state({}, [])
        engine.struct.kis_api.domestic_fills = [{
            "order_no": "6042",
            "symbol": "069500",
            "side": "BUY",
            "status": "FILLED",
            "filled_qty": 3,
            "filled_price": 104900,
        }]
        state = {
            "symbol": "069500",
            "market": "KS",
            "position_qty": 0,
            "avg_price": 0,
            "pending_buy_order_no": "0000006042",
            "pending_buy_action": "BUY1",
            "pending_buy_qty": 3,
            "pending_buy_price": 104860,
            "pending_buy_placed_at": "2026-05-25 15:10:00",
            "orders": [{
                "order_no": "0000006042",
                "action": "BUY1",
                "qty": 3,
                "price": 104860,
                "status": "ACCEPTED_UNVERIFIED",
            }],
        }

        status = engine._sync_pending_buy(state, "069500", "KS")

        self.assertEqual(status, "filled")
        self.assertEqual(state["pending_buy_order_no"], "")
        self.assertEqual(state["position_qty"], 3)
        self.assertEqual(state["avg_price"], 104900)
        self.assertEqual(state["orders"][0]["status"], "FILLED")

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

    def test_sync_uses_broker_quantity_and_average_for_managed_position(self):
        holdings = [{
            "symbol": "051910",
            "market": "KS",
            "name": "LG Chem",
            "qty": 177,
            "avg_price": 277000,
            "purchase_amount": 49163520,
            "current_price": 282500,
        }]
        engine, state = _engine_with_state({
            "051910.KS": {
                "symbol": "051910",
                "market": "KS",
                "name": "LG Chem",
                "position_qty": 180,
                "avg_price": 277000,
                "orders": [{"action": "BUY1", "qty": 180, "price": 277000}],
            },
        }, holdings)

        engine._sync_broker_positions()
        synced = state()["051910.KS"]

        self.assertEqual(synced["position_qty"], 177)
        self.assertEqual(synced["avg_price"], 277760)
        self.assertEqual(synced["broker_unmanaged_qty"], 0)

    def test_exit_watch_syncs_broker_once_then_uses_cached_position_state(self):
        holdings = [{
            "symbol": "051910",
            "market": "KS",
            "name": "LG Chem",
            "qty": 177,
            "avg_price": 277760,
            "current_price": 282500,
        }]
        engine, _state = _engine_with_state({
            "051910.KS": {
                "symbol": "051910",
                "market": "KS",
                "name": "LG Chem",
                "position_qty": 177,
                "avg_price": 277760,
                "strategy_id": "vrev",
            },
        }, holdings, configs={"daytrade_auto_enabled": "true"})
        calls = []
        engine.execute_live = lambda *args, **kwargs: calls.append(kwargs) or {
            "executed": False,
            "message": "hold",
            "status": {"signal": {"action": "HOLD"}},
        }
        engine._append_runtime_log = lambda *args, **kwargs: None
        engine.shared_budget_status = lambda **kwargs: {"total_seed_krw": 100000000}

        result = engine.kr_execute_exit_watch(requested_seed=5000000)

        self.assertEqual(result["watched_count"], 1)
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0]["sync_broker"])

    def test_exit_watch_forces_one_deleveraging_order_when_gross_exposure_exceeds_net_assets(self):
        engine, _state = _engine_with_state({
            "AAA.KS": {"symbol": "AAA", "market": "KS", "position_qty": 10, "avg_price": 9, "strategy_id": "vrev"},
            "BBB.KS": {"symbol": "BBB", "market": "KS", "position_qty": 10, "avg_price": 11, "strategy_id": "vrev"},
        }, [], configs={"daytrade_auto_enabled": "true"})
        engine.active_positions = lambda sync_broker=True, use_live_price=True, market_filter=None: [
            {"symbol": "AAA", "market": "KS", "position_qty": 10, "avg_price": 9, "current_price": 10, "pnl_pct": 11.1, "strategy_id": "vrev"},
            {"symbol": "BBB", "market": "KS", "position_qty": 10, "avg_price": 11, "current_price": 10, "pnl_pct": -9.1, "strategy_id": "vrev"},
        ]
        engine.shared_budget_status = lambda **kwargs: {"total_seed_krw": 100}
        engine._append_runtime_log = lambda *args, **kwargs: None
        calls = []

        def execute(*args, **kwargs):
            calls.append((args, kwargs))
            if kwargs.get("force"):
                return {"executed": False, "submitted": True, "action": "SELL_DELEVERAGE", "message": "submitted", "status": {"signal": {"action": "SELL_DELEVERAGE"}}}
            return {"executed": False, "message": "hold", "status": {"signal": {"action": "HOLD"}}}

        engine.execute_live = execute

        result = engine.kr_execute_exit_watch(requested_seed=100)

        forced = [item for item in calls if item[1].get("force")]
        self.assertEqual(len(forced), 1)
        self.assertEqual(forced[0][0][0], "AAA")
        self.assertEqual(forced[0][1]["forced_sell_qty"], 10)
        self.assertTrue(result["submitted"])
        self.assertEqual(result["submitted_count"], 1)

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

        with patch.object(daytrade_engine, "_PAPER_MODE", False):
            result = engine.auto_candidates(requested_seed=3000000, market="KS")

        self.assertEqual(result["candidates"], [])
        self.assertTrue(result["recommendation"]["live_quality_guard"]["block_new_entries"])
        self.assertEqual(result["recommendation"]["live_quality_guard"]["trade_ready_count"], 0)
        _StrategyStub.recommendation_payload = None

    def test_live_strategy_allowed_accepts_ks_volume_breakout_when_live_supported(self):
        engine, _state = _engine_with_state({}, [], configs={"daytrade_auto_max_symbols": "5"})
        with patch.object(daytrade_engine, "_PAPER_MODE", False):
            self.assertTrue(engine._live_strategy_allowed("volume_breakout", market="KS"))
            self.assertTrue(engine._live_strategy_allowed("vrev", market="KS"))
            self.assertFalse(engine._live_strategy_allowed("shadow_only", market="KS"))

    def test_paper_strategy_allows_shadow_research_strategy(self):
        engine, _state = _engine_with_state({}, [], configs={"daytrade_auto_max_symbols": "5"})
        with patch.object(daytrade_engine, "_PAPER_MODE", True):
            self.assertTrue(engine._live_strategy_allowed("shadow_only", market="KS"))

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

    def test_market_auto_max_symbols_respects_rate_limit_config(self):
        engine, _state = _engine_with_state({}, [], configs={"daytrade_auto_max_symbols": "8"})

        with patch.object(daytrade_engine, "_PAPER_MODE", False):
            self.assertEqual(engine._auto_max_symbols(market="KS"), 8)
        with patch.object(daytrade_engine, "_PAPER_MODE", True):
            self.assertEqual(engine._auto_max_symbols(market="KS"), 8)

    def test_risk_off_regime_prefers_inverse_and_blocks_kosdaq_longs(self):
        engine, _state = _engine_with_state({}, [])
        candidates = [
            {"symbol": "247540", "market": "KQ", "strategy_id": "vrev"},
            {"symbol": "122630", "market": "KS", "strategy_id": "vrev"},
            {"symbol": "114800", "market": "KS", "strategy_id": "vrev"},
            {"symbol": "005930", "market": "KS", "strategy_id": "vrev"},
        ]

        with patch.object(_StrategyStub, "market_regime_snapshot", lambda _self: {"regime": "RISK_OFF", "reason": "test breadth"}, create=True):
            allowed, excluded, snapshot = engine._apply_ks_market_regime_policy(candidates)

        self.assertEqual(snapshot["regime"], "RISK_OFF")
        self.assertEqual(allowed[0]["symbol"], "114800")
        self.assertEqual({row["symbol"] for row in excluded}, {"247540", "122630"})

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

    def test_paper_auto_candidates_forwards_bounded_untrained_fallback_to_live_signal_checks(self):
        engine, _state = _engine_with_state({}, [], configs={"daytrade_auto_max_symbols": "5"})

        class _FallbackStrategy(_StrategyStub):
            def candidate_universe(self, market="KS"):
                return [
                    {"symbol": "005930", "name": "Samsung", "market": "KS", "strategy_id": "vrev"},
                    {"symbol": "000660", "name": "SK Hynix", "market": "KS", "strategy_id": "vrev"},
                ]

        engine._Daytrade = _FallbackStrategy
        _FallbackStrategy.recommendation_payload = {
            "leaderboard": [],
            "quality_guard": {"block_new_entries": True, "issues": ["no training data"]},
        }
        engine.shared_budget_status = lambda **kwargs: {
            "effective_daytrade_seed": 3000000.0,
            "total_seed_krw": 3000000.0,
            "used_seed_krw": 0.0,
            "remaining_seed_krw": 3000000.0,
            "slot_target_count": 2,
            "available_slot_count": 2,
            "max_symbols": 5,
            "slot_seed_limit_krw": 1500000.0,
        }
        engine.portfolio_usage = lambda **kwargs: {"active_positions": [], "active_entry_seed_krw": 0.0, "active_cost_krw": 0.0}
        engine._append_runtime_log = lambda *args, **kwargs: None
        engine.auto_enabled = lambda market="KS": True

        with patch.object(daytrade_engine, "_PAPER_MODE", True):
            result = engine.auto_candidates(requested_seed=3000000, market="KS")

        self.assertEqual([row["symbol"] for row in result["candidates"]], ["005930", "000660"])
        self.assertTrue(all(row["paper_exploration"] for row in result["candidates"]))
        self.assertTrue(result["recommendation"]["fast_universe_expanded"])
        self.assertFalse(result["recommendation"]["live_quality_guard"]["block_new_entries"])
        self.assertTrue(result["recommendation"]["live_quality_guard"]["paper_exploration"])

    def test_us_exit_watch_skips_slow_broker_checks_while_market_is_closed(self):
        engine, _state = _engine_with_state({}, [], configs={"daytrade_us_auto_enabled": "true"})
        engine._us_market_open = lambda: False
        engine._us_premarket_open = lambda: False
        engine._append_runtime_log = lambda *args, **kwargs: None
        engine.active_positions = lambda **kwargs: (_ for _ in ()).throw(AssertionError("closed US market must not query holdings"))

        result = engine.us_execute_exit_watch(requested_seed=5000000)

        self.assertTrue(result["market_closed"])
        self.assertEqual(result["watched_count"], 0)

    def test_execute_live_blocks_buy_without_reliable_price_evidence(self):
        engine, _state = _engine_with_state({}, [], configs={})
        engine._append_runtime_log = lambda *args, **kwargs: None
        status = {
            "state": {"symbol": "005930", "market": "KS", "position_qty": 0, "avg_price": 0},
            "signal": {
                "action": "BUY1",
                "reason": "1차 눌림 구간 진입 신호",
                "order_qty": 1,
                "current_price": 70000,
                "price_source": "error_fallback",
                "strategy_id": "vrev",
            },
            "runtime": {"risk_status": "SAFE", "issues": [], "warnings": []},
        }

        result = engine.execute_live(
            "005930",
            market="KS",
            seed=1000000,
            allow_buy=True,
            sync_broker=False,
            precomputed_status=status,
        )

        self.assertFalse(result["executed"])
        self.assertTrue(result["evidence_blocked"])
        self.assertIn("가격 출처", result["message"])

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

    def test_shared_budget_cache_only_never_refetches_fresh_kis_balance(self):
        import time
        from unittest.mock import Mock
        engine, _state = _engine_with_state({}, [])
        engine.infinite_buy_daily_reserve = lambda: {"reserve_usd": 0, "cycles": [], "cycle_count": 0}
        engine.portfolio_usage = Mock(return_value={"active_entry_seed_krw": 0, "active_cost_krw": 0, "position_count": 0})
        engine._fetch_kis_balance_raw = lambda: self.fail("cache-only UI path made a network balance request")
        cached = {
            "withdrawable_krw": 1000000, "krw_balance": 1000000, "usd_krw": 1350,
            "same_day_sell_krw": 0, "same_day_buy_krw": 0, "source": "test",
        }
        setattr(sys, "_trading_kis_balance_cache_v2", cached)
        setattr(sys, "_trading_kis_balance_cache_ts", time.time())
        try:
            budget = engine.shared_budget_status(requested_seed=500000, use_cache_only=True)
            self.assertEqual(budget["withdrawable_krw"], 1000000)
            self.assertTrue(str(budget["source"]).startswith("cache_only:"))
            for call in engine.portfolio_usage.call_args_list:
                self.assertFalse(call.kwargs['sync_broker'])
                self.assertFalse(call.kwargs['use_live_price'])
        finally:
            for key in ("_trading_kis_balance_cache_v2", "_trading_kis_balance_cache_ts"):
                if hasattr(sys, key):
                    delattr(sys, key)

if __name__ == "__main__":
    unittest.main()
