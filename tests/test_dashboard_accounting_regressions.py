
import builtins
import datetime
import importlib.util
import json
import os
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class _TimeStub:
    @staticmethod
    def now():
        return datetime.datetime(2026, 5, 26, 10, 0, 0)

    @staticmethod
    def aware_now():
        return datetime.datetime(2026, 5, 26, 10, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=9)))

    @staticmethod
    def isoformat(with_offset=False):
        return "2026-05-26T10:00:00+09:00" if with_offset else "2026-05-26T10:00:00"


class _SessionStub:
    current_user_id = ""

    @classmethod
    def use(cls):
        if cls.current_user_id:
            return {"id": cls.current_user_id}
        return {}


class _LoggerStub:
    def info(self, _message):
        pass

    def warning(self, _message):
        pass

    def error(self, _message):
        pass


class _WizStub:
    @staticmethod
    def model(name):
        if name == "portal/season/session":
            return _SessionStub
        if name == "portal/trading/kst":
            return _TimeStub
        if name == "struct":
            return object()
        raise AssertionError(f"unexpected wiz.model({name})")

    @staticmethod
    def logger(*_args):
        return _LoggerStub()


builtins.wiz = _WizStub()
dashboard_api_path = SRC / "app" / "page.dashboard" / "api.py"
dashboard_api_spec = importlib.util.spec_from_file_location("dashboard_api_under_test", dashboard_api_path)
dashboard_api = importlib.util.module_from_spec(dashboard_api_spec)
dashboard_api_spec.loader.exec_module(dashboard_api)

daytrade_api_path = SRC / "app" / "page.daytrade" / "api.py"
daytrade_api_spec = importlib.util.spec_from_file_location("daytrade_api_under_test", daytrade_api_path)
daytrade_api = importlib.util.module_from_spec(daytrade_api_spec)
daytrade_api_spec.loader.exec_module(daytrade_api)

history_api_path = SRC / "app" / "page.history" / "api.py"
history_api_spec = importlib.util.spec_from_file_location("history_api_under_test", history_api_path)
history_api = importlib.util.module_from_spec(history_api_spec)
history_api_spec.loader.exec_module(history_api)


class DashboardAccountingRegressionTests(unittest.TestCase):
    def setUp(self):
        _SessionStub.current_user_id = ""

    def test_broker_setup_blocks_missing_session(self):
        class _Trading:
            @staticmethod
            def get_config(key, default=""):
                if key == "broker_provider":
                    return "kis"
                return "configured"

        state = dashboard_api._broker_setup_state(_Trading(), require_connection=False)

        self.assertFalse(state["allowed"])
        self.assertFalse(state["configured"])
        self.assertEqual(state["user_id"], "")

    def test_broker_setup_blocks_missing_user_credentials(self):
        _SessionStub.current_user_id = "new-user"

        class _Trading:
            @staticmethod
            def get_config(key, default=""):
                if key == "broker_provider":
                    return "kis"
                return ""

        state = dashboard_api._broker_setup_state(_Trading(), require_connection=False)

        self.assertFalse(state["allowed"])
        self.assertFalse(state["configured"])
        self.assertIn("한국투자증권 App Key", state["message"])

    def test_broker_setup_rejects_sticky_connection_success(self):
        _SessionStub.current_user_id = "user-with-old-success"
        original = dashboard_api._kis_connection_status
        dashboard_api._kis_connection_status = lambda _trading, ttl_sec=None: {
            "success": True,
            "raw_success": False,
            "sticky": True,
            "message": "최근 성공 캐시",
        }

        class _Trading:
            @staticmethod
            def get_config(key, default=""):
                values = {
                    "broker_provider": "kis",
                    "kis_app_key": "app-key",
                    "kis_app_secret": "app-secret",
                    "kis_account_no": "12345678-01",
                }
                return values.get(key, default)

        try:
            state = dashboard_api._broker_setup_state(_Trading(), require_connection=True)
        finally:
            dashboard_api._kis_connection_status = original

        self.assertFalse(state["allowed"])
        self.assertTrue(state["configured"])
        self.assertFalse(state["connected"])

    def test_extract_firegate_authoritative_symbols_ignores_manual_portfolios(self):
        symbols = dashboard_api._extract_firegate_authoritative_symbols([
            {"ticker": "TQQQ", "source": "infinitystock"},
            {"ticker": "SOXL", "portfolioGroup": "InfinityStock Auto"},
            {"ticker": "FNGU", "category": "infinite_buy"},
            {"ticker": "UPRO", "nickname": "Manual UPRO"},
            {"ticker": "tqqq", "source": "infinitystock"},
        ])

        self.assertEqual(symbols, ["TQQQ", "SOXL", "FNGU"])

    def test_scoped_engine_status_counts_only_visible_cycles(self):
        status = dashboard_api._scoped_engine_status({
            "active_cycles": 9,
            "holding_cycles": 9,
            "paused_cycles": 9,
            "pending_extension_cycles": 9,
            "completed_cycles": 12,
            "auto_trade": True,
        }, [
            {"symbol": "TQQQ", "status": "ACTIVE"},
            {"symbol": "SOXL", "status": "HOLDING"},
            {"symbol": "FNGU", "status": "PAUSED"},
            {"symbol": "TECL", "status": "PENDING_EXTENSION"},
        ])

        self.assertEqual(status["active_cycles"], 1)
        self.assertEqual(status["holding_cycles"], 1)
        self.assertEqual(status["paused_cycles"], 1)
        self.assertEqual(status["pending_extension_cycles"], 1)
        self.assertEqual(status["completed_cycles"], 12)
        self.assertTrue(status["auto_trade"])

    def test_holding_eval_sum_ignores_cash_like_summary_rows_without_quantity(self):
        total, count = dashboard_api._holding_eval_sum([
            {"symbol": "", "qty": 0, "eval_amount": 3_000_000},
            {"symbol": "005930", "qty": 0, "current_price": 70_000},
        ])

        self.assertEqual(count, 0)
        self.assertEqual(total, 0)

    def test_holding_eval_sum_uses_only_positive_quantity_holdings(self):
        total, count = dashboard_api._holding_eval_sum([
            {"symbol": "005930", "qty": 2, "current_price": 70_000},
            {"symbol": "000660", "qty": 1, "eval_amount": 180_500},
            {"symbol": "CASH", "qty": 0, "eval_amount": 1_000_000},
        ])

        self.assertEqual(count, 2)
        self.assertEqual(total, 320_500)

    def test_holding_eval_sum_dedupes_same_us_symbol_across_exchanges(self):
        total, count = dashboard_api._holding_eval_sum([
            {"symbol": "SOXL", "qty": 3, "eval_amount": 678.57, "exchange": "NASD"},
            {"symbol": "SOXL", "qty": 3, "eval_amount": 678.57, "exchange": "AMEX"},
            {"symbol": "TQQQ", "qty": 1, "eval_amount": 50.25, "exchange": "NASD"},
        ])

        self.assertEqual(count, 2)
        self.assertEqual(total, 728.82)

    def test_live_us_price_refresh_updates_cycle_unrealized_fields(self):
        original = dashboard_api._display_us_price
        dashboard_api._display_us_price = lambda _trading, symbol, exchange="NAS", refresh=False: {
            "price": 228.0002,
            "source": "yahoo_chart:1m_prepost",
            "timestamp": "2026-06-16T23:59:00+00:00",
            "timestamp_kst": "2026-06-17 08:59:00 KST",
        }

        class _Engine:
            def __init__(self):
                self.calls = []

            def update_cycle_price(self, cycle_id, price):
                self.calls.append((cycle_id, price))

        class _Trading:
            engine = _Engine()

        try:
            rows = dashboard_api._refresh_cycle_prices_for_display(_Trading(), [{
                "id": "cycle-soxl",
                "symbol": "SOXL",
                "total_qty": 3,
                "total_spent": 678.57,
                "current_price": 226.19,
            }])
        finally:
            dashboard_api._display_us_price = original

        self.assertEqual(_Trading.engine.calls, [("cycle-soxl", 228.0002)])
        self.assertEqual(rows[0]["current_price"], 228.0002)
        self.assertEqual(rows[0]["current_eval"], 684.0)
        self.assertEqual(rows[0]["price_source"], "yahoo_chart:1m_prepost")
        self.assertEqual(rows[0]["price_timestamp_kst"], "2026-06-17 08:59:00 KST")
        self.assertAlmostEqual(rows[0]["profit_rate"], 0.8)

    def test_alpaca_overnight_price_uses_quote_midpoint_and_metadata(self):
        original_urlopen = dashboard_api.urllib.request.urlopen
        original_time = dashboard_api.time.time
        dashboard_api._US_LIVE_PRICE_CACHE.clear()
        requested_urls = []

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "quotes": {
                        "SOXL": {
                            "bp": 239.8,
                            "ap": 240.2,
                            "t": "2026-06-17T06:45:02.123456789Z",
                        }
                    }
                }).encode("utf-8")

        env_backup = {key: os.environ.get(key) for key in [
            "ALPACA_API_KEY",
            "ALPACA_API_SECRET",
            "ALPACA_DATA_FEED",
            "ALPACA_OVERNIGHT_MAX_AGE_SEC",
        ]}

        def _fake_urlopen(req, timeout=0):
            requested_urls.append(req.full_url)
            return _Response()

        try:
            os.environ["ALPACA_API_KEY"] = "test-key"
            os.environ["ALPACA_API_SECRET"] = "test-secret"
            os.environ["ALPACA_DATA_FEED"] = "overnight"
            os.environ["ALPACA_OVERNIGHT_MAX_AGE_SEC"] = "7200"
            dashboard_api.urllib.request.urlopen = _fake_urlopen
            dashboard_api.time.time = lambda: datetime.datetime(2026, 6, 17, 6, 50, 2, tzinfo=datetime.timezone.utc).timestamp()
            result = dashboard_api._alpaca_overnight_price(object(), "SOXL", refresh=True)
        finally:
            for key, value in env_backup.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            dashboard_api.urllib.request.urlopen = original_urlopen
            dashboard_api.time.time = original_time
            dashboard_api._US_LIVE_PRICE_CACHE.clear()

        self.assertEqual(result["price"], 240.0)
        self.assertEqual(result["source"], "alpaca:overnight_quote")
        self.assertEqual(result["timestamp_kst"], "2026-06-17 15:45:02 KST")
        self.assertEqual(result["age_sec"], 300.0)
        self.assertEqual(result["bid_price"], 239.8)
        self.assertEqual(result["ask_price"], 240.2)
        self.assertIn("symbols=SOXL", requested_urls[0])
        self.assertIn("feed=overnight", requested_urls[0])

    def test_display_us_price_prefers_fresh_alpaca_overnight_quote(self):
        original_alpaca = dashboard_api._alpaca_overnight_price
        original_yahoo = dashboard_api._yahoo_chart_extended_price
        dashboard_api._alpaca_overnight_price = lambda _trading, symbol, refresh=False: {
            "price": 240.0,
            "source": "alpaca:overnight_quote",
            "timestamp_kst": "2026-06-17 15:45:02 KST",
        }
        dashboard_api._yahoo_chart_extended_price = lambda symbol, refresh=False: {
            "price": 228.0,
            "source": "yahoo_chart:1m_prepost",
        }

        class _Kis:
            def get_current_price(self, symbol, exchange="NAS"):
                return {"price": 226.19, "exchange": exchange}

        class _Trading:
            kis_api = _Kis()

        try:
            result = dashboard_api._display_us_price(_Trading(), "SOXL", exchange="AMS", refresh=True)
        finally:
            dashboard_api._alpaca_overnight_price = original_alpaca
            dashboard_api._yahoo_chart_extended_price = original_yahoo

        self.assertEqual(result["price"], 240.0)
        self.assertEqual(result["source"], "alpaca:overnight_quote")

    def test_live_us_price_refresh_dedupes_holdings_before_portfolio_sum(self):
        original = dashboard_api._display_us_price
        dashboard_api._display_us_price = lambda _trading, symbol, exchange="NAS", refresh=False: {
            "price": 228.0002,
            "source": "yahoo_chart:1m_prepost",
            "timestamp": "2026-06-16T23:59:00+00:00",
            "timestamp_kst": "2026-06-17 08:59:00 KST",
        }

        try:
            holdings = dashboard_api._apply_live_us_prices_to_holdings(None, [
                {"symbol": "SOXL", "qty": 3, "avg_price": 226.19, "current_price": 226.19, "eval_amount": 678.57, "exchange": "NASD"},
                {"symbol": "SOXL", "qty": 3, "avg_price": 226.19, "current_price": 226.19, "eval_amount": 678.57, "exchange": "AMEX"},
            ])
        finally:
            dashboard_api._display_us_price = original

        total, count = dashboard_api._holding_eval_sum(holdings)
        self.assertEqual(len(holdings), 1)
        self.assertEqual(count, 1)
        self.assertEqual(total, 684.0)

    def test_total_asset_prefers_summary_field_over_direct_sum(self):
        total, source = dashboard_api._select_total_asset_krw(
            summary_total_asset_krw=2_679_663,
            present_total_asset_krw=1_618_863,
            direct_total_asset_krw=3_323_663,
            fallback_total_asset_krw=3_323_663,
        )

        self.assertEqual(total, 2_679_663)
        self.assertEqual(source, "summary_total_asset")

    def test_total_asset_uses_present_only_when_summary_missing(self):
        total, source = dashboard_api._select_total_asset_krw(
            summary_total_asset_krw=0,
            present_total_asset_krw=1_618_863,
            direct_total_asset_krw=3_323_663,
            fallback_total_asset_krw=3_323_663,
        )

        self.assertEqual(total, 1_618_863)
        self.assertEqual(source, "present_total_asset")

    def test_total_asset_uses_direct_sum_only_when_summary_and_present_missing(self):
        total, source = dashboard_api._select_total_asset_krw(
            summary_total_asset_krw=0,
            present_total_asset_krw=0,
            direct_total_asset_krw=3_323_663,
            fallback_total_asset_krw=1_000_000,
        )

        self.assertEqual(total, 3_323_663)
        self.assertEqual(source, "direct(cash+portfolio)")

    def test_daytrade_budget_normalization_prefers_summary_over_larger_direct_sum(self):
        budget = daytrade_api._normalize_budget_total_asset({
            "summary_total_asset_krw": 2_679_663,
            "summary_total_asset_key": "tot_evlu_amt",
            "total_asset_krw": 3_323_663,
            "total_asset_source": "direct(cash_krw+domestic_eval+usd_cash+usd_eval)",
            "direct_total_asset_krw": 3_323_663,
            "fallback_total_asset_krw": 3_323_663,
        })

        self.assertEqual(budget["total_asset_krw"], 2_679_663)
        self.assertEqual(budget["total_asset_source"], "summary_total_asset:tot_evlu_amt")

    def test_profit_component_totals_preserve_realized_breakdown(self):
        totals = dashboard_api._combine_profit_components(
            cycle_realized_profit=125000,
            cycle_unrealized_profit=33000,
            daytrade_realized_profit=-7000,
            daytrade_unrealized_profit=11000,
        )

        self.assertEqual(totals["realized_profit"], 118000)
        self.assertEqual(totals["unrealized_profit"], 44000)
        self.assertEqual(totals["total_profit"], 162000)

    def test_infinite_buy_realized_1d_window_includes_previous_us_trade_date(self):
        now = datetime.datetime(2026, 6, 30, 10, 0, 0, tzinfo=dashboard_api.KST)

        date_from, date_to = dashboard_api._infinite_buy_realized_date_window(
            "1D",
            filter_from="2026-06-30",
            filter_to="2026-06-30",
            now=now,
        )

        self.assertEqual(date_from, "2026-06-29")
        self.assertEqual(date_to, "2026-06-30")

    def test_infinite_buy_realized_window_keeps_explicit_dates(self):
        now = datetime.datetime(2026, 6, 30, 10, 0, 0, tzinfo=dashboard_api.KST)

        date_from, date_to = dashboard_api._infinite_buy_realized_date_window(
            "1D",
            filter_from="2026-06-30",
            filter_to="2026-06-30",
            now=now,
            explicit_dates=True,
        )

        self.assertEqual(date_from, "2026-06-30")
        self.assertEqual(date_to, "2026-06-30")

    def test_cycle_partial_sell_realized_summary_includes_active_partial_sells(self):
        class _TradeDb:
            @staticmethod
            def rows(**_kwargs):
                return [
                    {
                        "trade_date": "2026-06-29",
                        "action": "SELL",
                        "status": "FILLED",
                        "filled_price": 77.19,
                        "filled_qty": 12,
                        "filled_amount": 926.28,
                        "commission": 2.32,
                        "avg_buy_price": 75.9814,
                        "total_qty_after": 36,
                        "strategy_type": "PARTIAL_SELL",
                    },
                    {
                        "trade_date": "2026-06-29",
                        "action": "SELL",
                        "status": "FILLED",
                        "filled_price": 77.19,
                        "filled_qty": 36,
                        "filled_amount": 2778.84,
                        "commission": 6.95,
                        "avg_buy_price": 75.9814,
                        "total_qty_after": 0,
                        "strategy_type": "FULL_SELL",
                    },
                    {
                        "trade_date": "2026-06-29",
                        "action": "BUY",
                        "status": "FILLED",
                        "filled_price": 76.0,
                        "filled_qty": 1,
                    },
                ]

        summary = dashboard_api._cycle_partial_sell_realized_summary(
            _TradeDb(),
            date_from="2026-06-29",
            date_to="2026-06-29",
        )

        self.assertEqual(summary["count"], 1)
        self.assertAlmostEqual(summary["cost"], 911.7768, places=4)
        self.assertAlmostEqual(summary["realized"], 12.1832, places=4)
        self.assertAlmostEqual(summary["by_date"]["2026-06-29"], 12.1832, places=4)

    def test_cycle_partial_sell_realized_summary_applies_date_filter(self):
        class _TradeDb:
            @staticmethod
            def rows(**_kwargs):
                return [
                    {
                        "trade_date": "2026-06-28",
                        "action": "SELL",
                        "status": "FILLED",
                        "filled_price": 100,
                        "filled_qty": 1,
                        "filled_amount": 100,
                        "commission": 1,
                        "avg_buy_price": 90,
                        "total_qty_after": 2,
                    },
                    {
                        "trade_date": "2026-06-29",
                        "action": "SELL",
                        "status": "FILLED",
                        "filled_price": 110,
                        "filled_qty": 1,
                        "filled_amount": 110,
                        "commission": 1,
                        "avg_buy_price": 100,
                        "total_qty_after": 2,
                    },
                ]

        summary = dashboard_api._cycle_partial_sell_realized_summary(
            _TradeDb(),
            date_from="2026-06-29",
            date_to="2026-06-29",
        )

        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["realized"], 9)
        self.assertEqual(summary["by_date"], {"2026-06-29": 9.0})

    def test_daytrade_history_excludes_pre_sell_reservations(self):
        self.assertFalse(history_api._is_executable_daytrade_record({
            "action": "SELL",
            "action_detail": "PRE_SELL_JACKPOT",
            "qty": 1,
            "price": 284500,
            "amount": 284500,
        }))

    def test_daytrade_history_excludes_zero_fill_rows(self):
        self.assertFalse(history_api._is_executable_daytrade_record({
            "action": "BUY",
            "action_detail": "BUY1",
            "qty": 0,
            "price": 0,
            "amount": 0,
        }))

    def test_daytrade_history_keeps_real_fills(self):
        self.assertTrue(history_api._is_executable_daytrade_record({
            "action": "SELL",
            "action_detail": "SELL_STOP_LOSS",
            "qty": 2,
            "price": 13785,
            "amount": 27570,
        }))

    def test_cycle_trade_row_is_visible_as_infinite_buy_history(self):
        record = history_api._cycle_trade_record_from_row({
            "id": "trade-soxl-buy",
            "cycle_id": "cycle-soxl",
            "symbol": "SOXL",
            "trade_date": "2026-06-23",
            "action": "BUY",
            "order_type": "LOC",
            "order_price": 226.76,
            "order_qty": 2,
            "filled_price": 226.76,
            "filled_qty": 2,
            "filled_amount": 453.52,
            "commission": 0.15,
            "avg_buy_price": 226.76,
            "total_qty_after": 3,
            "broker_order_no": "0031033779",
            "memo": "FireGate 반영",
        })

        self.assertIsNotNone(record)
        self.assertEqual(record["strategy"], "무한매수")
        self.assertEqual(record["source"], "cycle_trade")
        self.assertEqual(record["market"], "US")
        self.assertEqual(record["symbol"], "SOXL")
        self.assertEqual(record["action"], "BUY")
        self.assertEqual(record["action_detail"], "INFINITE_BUY")
        self.assertEqual(record["qty"], 2)
        self.assertEqual(record["amount"], 453.52)

    def test_cycle_trade_history_hides_synthetic_reconciliation_rows(self):
        record = history_api._cycle_trade_record_from_row({
            "id": "recon-tqqq",
            "cycle_id": "cycle-tqqq",
            "symbol": "TQQQ",
            "trade_date": "2026-06-25",
            "action": "BUY",
            "order_type": "RECON",
            "filled_price": 78.0,
            "filled_qty": 19,
            "filled_amount": 1482.0,
            "broker_order_no": "RECONCILE-TQQQ-20260625-41",
        })

        self.assertIsNone(record)

    def test_trade_history_collects_cycle_trades_without_daytrade_logs(self):
        history_api._HISTORY_CACHE.clear()

        class _CycleTradeDb:
            @staticmethod
            def rows(**_kwargs):
                return [{
                    "id": "trade-tqqq-buy",
                    "cycle_id": "cycle-tqqq",
                    "symbol": "TQQQ",
                    "trade_date": "2026-06-23",
                    "action": "BUY",
                    "order_type": "LOC",
                    "filled_price": 86.84,
                    "filled_qty": 6,
                    "filled_amount": 521.04,
                    "total_qty_after": 14,
                    "broker_order_no": "0031033780",
                }]

        class _Trading:
            @staticmethod
            def db(name):
                if name == "cycle_trade":
                    return _CycleTradeDb()
                raise RuntimeError(name)

        try:
            records = history_api._collect_trade_history_records(_Trading(), max_log_rows=100)
        finally:
            history_api._HISTORY_CACHE.clear()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["symbol"], "TQQQ")
        self.assertEqual(records[0]["strategy"], "무한매수")
        self.assertEqual(records[0]["source"], "cycle_trade")
        self.assertEqual(records[0]["action_detail"], "INFINITE_BUY")

    def test_history_active_daytrade_positions_include_unrealized_profit(self):
        class _Engine:
            @staticmethod
            def _load_state_map():
                return {
                    "AAA.KS": {
                        "symbol": "AAA",
                        "market": "KS",
                        "name": "테스트",
                        "position_qty": 3,
                        "avg_price": 10000,
                        "last_price": 11000,
                    },
                    "SOXL.US": {
                        "symbol": "SOXL",
                        "market": "US",
                        "position_qty": 2,
                        "avg_price": 200,
                        "last_price": 220,
                    },
                }

        class _Trading:
            daytrade_engine = _Engine()

        positions = history_api._active_daytrade_positions(_Trading())

        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["symbol"], "AAA")
        self.assertEqual(positions[0]["current_price"], 11000)
        self.assertEqual(positions[0]["eval_amount"], 33000)
        self.assertEqual(positions[0]["unrealized"], 3000)

    def test_history_active_daytrade_positions_prefer_broker_domestic_holding_qty(self):
        history_api._HISTORY_CACHE.clear()

        class _Engine:
            @staticmethod
            def _load_state_map():
                return {
                    "000660.KS": {
                        "symbol": "000660",
                        "market": "KS",
                        "name": "SK하이닉스",
                        "strategy_id": "vrev",
                        "position_qty": 1,
                        "avg_price": 2_050_000,
                        "last_price": 2_312_000,
                    }
                }

        class _Kis:
            @staticmethod
            def get_domestic_balance():
                return {
                    "holdings": [{
                        "symbol": "000660",
                        "market": "KS",
                        "name": "SK하이닉스",
                        "qty": 2,
                        "avg_price": 2_050_000,
                        "current_price": 2_312_000,
                        "profit_loss": 524_000,
                    }]
                }

        class _Trading:
            daytrade_engine = _Engine()
            kis_api = _Kis()

        try:
            positions = history_api._active_daytrade_positions(_Trading(), force_broker=True)
        finally:
            history_api._HISTORY_CACHE.clear()

        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["symbol"], "000660")
        self.assertEqual(positions[0]["source"], "broker")
        self.assertEqual(positions[0]["position_qty"], 2)
        self.assertEqual(positions[0]["current_price"], 2_312_000)
        self.assertEqual(positions[0]["eval_amount"], 4_624_000)
        self.assertEqual(positions[0]["cost_amount"], 4_100_000)
        self.assertEqual(positions[0]["unrealized"], 524_000)

    def test_history_active_cycle_positions_include_unrealized_profit(self):
        class _Engine:
            @staticmethod
            def get_active_cycles():
                return [{
                    "id": "cycle-tqqq",
                    "symbol": "TQQQ",
                    "total_qty": 10,
                    "total_spent": 750,
                    "current_price": 80,
                    "current_eval": 800,
                }]

        class _Trading:
            engine = _Engine()

        positions = history_api._active_cycle_positions(_Trading())

        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["strategy"], "무한매수")
        self.assertEqual(positions[0]["market"], "US")
        self.assertEqual(positions[0]["cost_amount"], 750)
        self.assertEqual(positions[0]["eval_amount"], 800)
        self.assertEqual(positions[0]["unrealized"], 50)

    def test_attach_loc_buy_status_marks_existing_reservation(self):
        class _Db:
            @staticmethod
            def rows(**_kwargs):
                return [{"symbol": "TQQQ", "exchange": "NASD"}]

            @staticmethod
            def get(**_kwargs):
                return {"symbol": "TQQQ", "exchange": "NASD"}

        class _Kis:
            @staticmethod
            def get_overseas_reservation_orders(start_date=None):
                return [{
                    "symbol": "TQQQ",
                    "exchange": "NASD",
                    "side": "BUY",
                    "qty": 3,
                    "price": 54.25,
                    "order_no": "0031033779",
                    "status_name": "접수",
                }]

            @staticmethod
            def get_current_price(symbol, exchange="NAS"):
                return {"price": 54.25, "prev_close": 50.0}

        class _Engine:
            @staticmethod
            def _reservation_order_symbol_key(symbol="", exchange=""):
                return f"{str(symbol or '').upper()}:{str(exchange or 'NASD').upper()}"

            @staticmethod
            def _reservation_order_line_key(symbol="", exchange="", price=0):
                return f"{str(symbol or '').upper()}:{str(exchange or 'NASD').upper()}:{float(price or 0):.4f}"

            @staticmethod
            def _reservation_order_is_active(order):
                return True

            @staticmethod
            def _reservation_order_remaining_qty(order):
                return int(float((order or {}).get("qty", 0) or 0)) - int(float((order or {}).get("filled_qty", 0) or 0))

            @staticmethod
            def _price_exchange(exchange):
                return "NAS"

            @staticmethod
            def calculate_buy_decision(cycle, prev_close):
                return {
                    "should_buy": True,
                    "order_type": "LOC",
                    "buy_orders": [{"label": "LOC", "loc_price": 54.25, "order_qty": 3}],
                }

        class _Trading:
            kis_api = _Kis()
            engine = _Engine()

            @staticmethod
            def get_config(key, default=""):
                return "true"

            @staticmethod
            def db(name):
                return _Db()

        rows = dashboard_api._attach_loc_buy_status(_Trading(), [{
            "symbol": "TQQQ",
            "status": "ACTIVE",
            "current_round": 4,
        }])

        self.assertEqual(rows[0]["loc_buy_status"], "scheduled")
        self.assertEqual(rows[0]["loc_buy_order_no"], "0031033779")
        self.assertEqual(rows[0]["loc_buy_qty"], 3)

    def test_attach_loc_buy_status_resolves_soxl_stale_watchlist_exchange(self):
        class _Db:
            @staticmethod
            def get(**_kwargs):
                return {"symbol": "SOXL", "exchange": "NASD"}

        class _Kis:
            @staticmethod
            def get_overseas_reservation_orders(start_date=None):
                return [{
                    "symbol": "SOXL",
                    "exchange": "AMEX",
                    "side": "BUY",
                    "qty": 1,
                    "price": 193.22,
                    "order_no": "0031595580",
                    "status_name": "접수",
                }]

            @staticmethod
            def get_current_price(symbol, exchange="NAS"):
                return {"price": 229.4, "prev_close": 229.4, "exchange": exchange}

        class _Engine:
            @staticmethod
            def _resolve_order_exchange(symbol, exchange=""):
                if str(symbol or "").upper() == "SOXL" and str(exchange or "").upper() in ("", "NASD"):
                    return "AMEX"
                return str(exchange or "NASD").upper()

            @staticmethod
            def _reservation_order_symbol_key(symbol="", exchange=""):
                return f"{str(symbol or '').upper()}:{str(exchange or 'NASD').upper()}"

            @staticmethod
            def _reservation_order_line_key(symbol="", exchange="", price=0):
                return f"{str(symbol or '').upper()}:{str(exchange or 'NASD').upper()}:{float(price or 0):.4f}"

            @staticmethod
            def _reservation_order_is_active(order):
                return True

            @staticmethod
            def _reservation_order_remaining_qty(order):
                return int(float((order or {}).get("qty", 0) or 0)) - int(float((order or {}).get("filled_qty", 0) or 0))

            @staticmethod
            def _price_exchange(exchange):
                return {"AMEX": "AMS", "NASD": "NAS"}.get(exchange, "NAS")

            @staticmethod
            def calculate_buy_decision(cycle, prev_close):
                return {
                    "should_buy": True,
                    "order_type": "LOC",
                    "buy_orders": [{"label": "LOC", "loc_price": 193.22, "order_qty": 1}],
                }

        class _Trading:
            kis_api = _Kis()
            engine = _Engine()

            @staticmethod
            def get_config(key, default=""):
                return "true"

            @staticmethod
            def db(name):
                return _Db()

        rows = dashboard_api._attach_loc_buy_status(_Trading(), [{
            "symbol": "SOXL",
            "status": "ACTIVE",
            "current_round": 1,
            "division_count": 10,
        }])

        self.assertEqual(rows[0]["loc_buy_status"], "scheduled")
        self.assertEqual(rows[0]["loc_buy_order_no"], "0031595580")

    def test_completed_cycle_without_liquidation_is_excluded_from_realized(self):
        self.assertFalse(dashboard_api._include_completed_cycle_in_realized({
            "status": "COMPLETED",
            "total_qty": 7,
            "current_eval": 0,
        }))

    def test_completed_cycle_with_real_proceeds_is_included_in_realized(self):
        self.assertTrue(dashboard_api._include_completed_cycle_in_realized({
            "status": "COMPLETED",
            "total_qty": 0,
            "current_eval": 12345,
        }))

    def test_completed_cycle_without_local_sell_trade_is_excluded_from_realized_when_trade_db_available(self):
        class _TradeDb:
            @staticmethod
            def rows(**_kwargs):
                return []

        self.assertFalse(dashboard_api._include_completed_cycle_in_realized({
            "id": "cycle-1",
            "status": "COMPLETED",
            "total_qty": 0,
            "current_eval": 12345,
        }, trade_db=_TradeDb()))

    def test_completed_cycle_with_local_sell_trade_is_included_when_trade_db_available(self):
        class _TradeDb:
            @staticmethod
            def rows(**_kwargs):
                return [{
                    "action": "SELL",
                    "status": "FILLED",
                    "filled_qty": 2,
                    "filled_amount": 250,
                }]

        self.assertTrue(dashboard_api._include_completed_cycle_in_realized({
            "id": "cycle-1",
            "status": "COMPLETED",
            "total_qty": 0,
            "current_eval": 250,
        }, trade_db=_TradeDb()))

    def test_active_cycle_without_local_trade_is_excluded_from_unrealized_when_it_has_position(self):
        class _TradeDb:
            @staticmethod
            def rows(**_kwargs):
                return []

        self.assertFalse(dashboard_api._include_active_cycle_in_unrealized({
            "id": "cycle-1",
            "status": "ACTIVE",
            "total_qty": 3,
            "total_spent": 300,
        }, trade_db=_TradeDb()))

    def test_daytrade_state_realized_total_can_filter_session_date(self):
        class _Engine:
            @staticmethod
            def _load_state_map():
                return {
                    "AAA.KS": {"session_date": "2026-05-28", "realized_profit": -100000},
                    "BBB.KS": {"session_date": "2026-05-28", "realized_profit": 25000},
                    "CCC.US": {"session_date": "2026-05-27", "realized_profit": 990000},
                }

        class _Trading:
            daytrade_engine = _Engine()

        self.assertEqual(dashboard_api._daytrade_state_realized_total(_Trading(), session_date="2026-05-28"), -75000)
        self.assertEqual(dashboard_api._daytrade_state_realized_total(_Trading()), 915000)

    def test_daytrade_state_realized_total_prefers_session_order_calculation_when_available(self):
        class _Engine:
            @staticmethod
            def _load_state_map():
                return {
                    "AAA.KS": {"session_date": "2026-05-28", "realized_profit": -100000},
                    "BBB.KS": {"session_date": "2026-05-28", "realized_profit": -7500},
                }

            @staticmethod
            def _session_realized_value(state, session_date):
                if state.get("realized_profit") == -7500:
                    return -450
                return 0

        class _Trading:
            daytrade_engine = _Engine()

        self.assertEqual(dashboard_api._daytrade_state_realized_total(_Trading(), session_date="2026-05-28"), -450)


if __name__ == "__main__":
    unittest.main()
