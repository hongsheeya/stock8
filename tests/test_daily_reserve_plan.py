import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from test_daytrade_engine_regressions import _engine_with_state


class DailyReserveTests(unittest.TestCase):
    def test_production_firegate_plan_reserves_every_actual_leg(self):
        from test_infinitebuy_loc_schedule_regressions import engine_module
        engine, cycle, _ = self.engine()
        cycle.update(total_investment=15000, total_spent=5000)
        actual = engine_module.Engine.__new__(engine_module.Engine)
        engine.struct.engine.calculate_buy_decision = actual.calculate_buy_decision
        plan = actual.calculate_buy_decision(cycle, 150)
        expected = round(sum(row['loc_price'] * row['order_qty'] for row in plan['buy_orders']) * 1.01, 2)
        self.assertGreater(len(plan['buy_orders']), 2)
        self.assertEqual(engine.infinite_buy_daily_reserve()['reserve_usd'], expected)

    def engine(self):
        engine, _ = _engine_with_state({}, [])
        cycle = dict(symbol='SOXL', status='ACTIVE', current_round=7,
                     division_count=20, remaining_investment=10000,
                     total_qty=37, avg_price=150)
        planner = Mock(return_value=dict(should_buy=True, buy_orders=[
            dict(loc_price=150, order_qty=3), dict(loc_price=140, order_qty=2),
            dict(loc_price=100, order_qty=1)]))
        engine.struct.engine = SimpleNamespace(get_active_cycles=lambda: [cycle],
                                              calculate_buy_decision=planner)
        engine._fetch_kis_balance_raw = lambda: dict(withdrawable_krw=2000000,
            krw_balance=2000000, usd_krw=1000, source='broker', total_asset_krw=2000000)
        engine.portfolio_usage = lambda **kw: dict(active_entry_seed_krw=0, position_count=0)
        engine._dynamic_daytrade_allocation = lambda **kw: dict(target_seed_krw=kw['total_asset_krw'])
        return engine, cycle, planner

    def test_all_buy_legs_and_fee_buffer_not_lifetime_or_average(self):
        engine, cycle, planner = self.engine()
        reserve = engine.infinite_buy_daily_reserve()
        self.assertTrue(reserve['ready'])
        self.assertEqual(reserve['reserve_usd'], 838.30)
        planner.assert_called_once_with(cycle, 150)
        budget = engine.shared_budget_status(2000000)
        self.assertAlmostEqual(budget['remaining_seed_krw'], 1161700)

    def test_failed_cycle_read_blocks_new_budget(self):
        engine, _, _ = self.engine()
        engine.struct.engine.get_active_cycles = Mock(side_effect=TimeoutError('db'))
        budget = engine.shared_budget_status(2000000)
        self.assertEqual(budget['remaining_seed_krw'], 0)
        self.assertEqual(budget['budget_status'], 'reserve_unavailable')

    def test_unknown_plan_never_becomes_free_cash(self):
        engine, _, planner = self.engine()
        planner.side_effect = ValueError('bad plan')
        self.assertEqual(engine.shared_budget_status(2000000)['remaining_seed_krw'], 0)

    def test_first_entry_cache_only_never_fetches_quote(self):
        engine, cycle, planner = self.engine()
        cycle.update(current_round=0, total_qty=0, avg_price=0)
        engine._broker = Mock(side_effect=AssertionError('no network'))
        self.assertFalse(engine.infinite_buy_daily_reserve(use_cache_only=True)['ready'])
        planner.assert_not_called()

    def test_exhausted_cycle_does_not_reserve(self):
        engine, cycle, planner = self.engine()
        cycle['current_round'] = 20
        self.assertEqual(engine.infinite_buy_daily_reserve()['reserve_usd'], 0)
        planner.assert_not_called()

    def test_legacy_ignore_reserve_does_not_override_priority(self):
        engine, _, _ = self.engine()
        engine._config = lambda key, default='': 'true' if key == 'daytrade_ignore_reserve' else default
        budget = engine.shared_budget_status(2000000)
        self.assertFalse(budget['reserve_ignored'])
        self.assertAlmostEqual(budget['applied_reserve_krw'], 838300)

    def test_usd_cash_covers_the_reserve_before_krw(self):
        engine, _, _ = self.engine()
        raw = engine._fetch_kis_balance_raw()
        raw['usd_cash_balance_usd'] = 500
        engine._fetch_kis_balance_raw = lambda: raw
        budget = engine.shared_budget_status(2000000)
        self.assertEqual(budget['infinite_buy_reserve_covered_usd'], 500)
        self.assertAlmostEqual(budget['applied_reserve_krw'], 338300)
        self.assertAlmostEqual(budget['remaining_seed_krw'], 1661700)
        raw['usd_cash_balance_usd'] = 5000
        budget = engine.shared_budget_status(2000000)
        self.assertEqual(budget['infinite_buy_reserve_covered_usd'], 838.30)
        self.assertAlmostEqual(budget['remaining_seed_krw'], 2000000)

    def test_missing_fx_blocks_conversion(self):
        engine, _, _ = self.engine()
        raw = engine._fetch_kis_balance_raw()
        raw['usd_krw'] = 0
        engine._fetch_kis_balance_raw = lambda: raw
        self.assertEqual(engine.shared_budget_status(2000000)['remaining_seed_krw'], 0)
