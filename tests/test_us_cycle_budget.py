"""Exercise the production US loop with a broker-free execution stub."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class UsCycleBudgetTests(unittest.TestCase):
    def test_discovered_exchange_is_used_for_non_nasdaq_candidates(self):
        path = Path(__file__).resolve().parents[1] / 'src/portal/trading/model/struct/daytrade_engine.py'
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DomesticDaytradeEngine')
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_us_exchange')
        ns = {}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), ns)
        for exchange in ('NYSE', 'AMEX', 'NASD'):
            engine = SimpleNamespace(strategy=SimpleNamespace(us_candidate_universe=lambda: [{'symbol':'TEST','exchange':exchange}]))
            self.assertEqual(ns[fn.name](engine, 'TEST'), exchange)

    def test_entry_window_stays_open_during_regular_session(self):
        path = Path(__file__).resolve().parents[1] / 'src/portal/trading/model/struct/daytrade_engine.py'
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DomesticDaytradeEngine')
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_us_auto_buy_ready')
        ns = {}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), ns)
        for regular, premarket, expected in ((True, False, True), (False, True, True), (False, False, False)):
            engine = SimpleNamespace(_us_market_open=lambda: regular, _us_premarket_open=lambda: premarket)
            self.assertEqual(ns[fn.name](engine), expected)

    def test_ui_does_not_promote_legacy_soxl_or_domestic_state(self):
        path = Path(__file__).resolve().parents[1] / 'src/app/page.daytrade.us/api.py'
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_us_managed_positions')
        ns = {}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), ns)
        rows = [{'symbol':'SOXL','market':'US'}, {'symbol':'005930','market':'KS'},
                {'symbol':'TEST','market':'US'}]
        engine = SimpleNamespace(active_positions_from_state=lambda **kw: rows)
        self.assertEqual(ns[fn.name](engine), [rows[2]])
        self.assertEqual(len(rows), 3)  # Preserve historical records.

    def run_cycle(self, outcomes, seed=100000, slot=60000, positions=0, max_symbols=5):
        path = Path(__file__).resolve().parents[1] / 'src/portal/trading/model/struct/daytrade_engine.py'
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DomesticDaytradeEngine')
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'us_auto_cycle')
        ns = {}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), ns)
        rows = [dict(symbol=f'TEST{i}', market='US', entry_seed_krw=90000,
                     last_price=10, source='leaderboard') for i in range(len(outcomes))]
        engine = SimpleNamespace(
            _hard_locked=lambda: False, auto_enabled=lambda **kw: True,
            _us_market_open=lambda: True, _us_premarket_open=lambda: False,
            auto_candidates=lambda **kw: dict(effective_seed=seed, remaining_seed_krw=seed,
                candidates=rows, slot_seed_limit_krw=slot, position_count=positions),
            _append_runtime_log=Mock(), _safe_float=lambda v,d=0: float(v or d),
            _safe_int=lambda v,d=0: int(v or d), _auto_max_symbols=lambda **kw: max_symbols,
            _minimum_entry_seed=lambda *a,**kw: 1000,
            _minimum_entry_seed_krw=lambda *a,**kw: 1000,
            execute_live=Mock(side_effect=outcomes), daily_loss_status=lambda **kw: {},
            shared_budget_status=lambda **kw: {}, portfolio_usage=lambda **kw: {},
            _with_regime_trend_candidates=lambda rows, payload, market='US': rows)
        result = ns['us_auto_cycle'](engine, requested_seed=seed)
        return result, engine

    def test_pending_buys_reserve_krw_and_cap_next_allocation(self):
        buy = dict(submitted=True, executed=False, action='BUY1', order_value=40)
        result, engine = self.run_cycle([buy, buy, buy])
        self.assertEqual([c.kwargs['seed'] for c in engine.execute_live.call_args_list], [60000, 40000])
        self.assertEqual(result['results'][0]['remaining_seed_after'], 40000)
        self.assertTrue(result['results'][0]['submitted'])

    def test_pending_buy_consumes_slot(self):
        buy = dict(submitted=True, executed=False, action='BUY1', order_value=40)
        _, engine = self.run_cycle([buy, buy], max_symbols=1)
        self.assertEqual(engine.execute_live.call_count, 1)

    def test_partial_sell_does_not_recycle_cash_or_slot(self):
        sell = dict(executed=True, action='SELL_PARTIAL', order_value=500)
        result, _ = self.run_cycle([sell])
        self.assertEqual(result['results'][0]['remaining_seed_after'], 100000)

    def test_filled_buy_reserves_allocation_not_usd_notional(self):
        buy = dict(executed=True, action='BUY1', order_value=40)
        result, _ = self.run_cycle([buy])
        self.assertEqual(result['results'][0]['remaining_seed_after'], 40000)
