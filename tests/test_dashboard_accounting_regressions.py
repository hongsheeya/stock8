
import builtins
import datetime
import importlib.util
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

    def test_attach_loc_buy_status_marks_existing_reservation(self):
        class _Db:
            @staticmethod
            def rows(**_kwargs):
                return [{"symbol": "TQQQ", "exchange": "NASD"}]

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

        class _Trading:
            kis_api = _Kis()

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
