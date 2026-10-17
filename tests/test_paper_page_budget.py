import ast
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

ROOT = Path(__file__).resolve().parents[1]

def method(path, name, env):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8-sig'))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), env)
    return env[name]

class PaperPageBudgetTests(unittest.TestCase):
    def test_asset_guard_compares_same_main_script(self):
        source = (ROOT / 'src/angular/app/app.component.ts').read_text(encoding='utf-8')
        latest = source.split('private latestAssetVersion', 1)[1].split('private installAssetVersionGuard', 1)[0]
        self.assertIn("includes('main.js')", latest)
        self.assertIn('DOMParser', latest)

    def test_single_symbol_ui_does_not_chain_full_training(self):
        source = (ROOT / 'src/app/page.daytrade/view.ts').read_text(encoding='utf-8')
        body = source.split('public async trainSymbol()', 1)[1].split('public async searchSymbols()', 1)[0]
        self.assertNotIn('refreshRecommendationIfMissing', body)
        self.assertNotIn('loadLiveStatus', body)
        self.assertIn('result.skipped || !summary', body)
        self.assertIn('summary.total_return', body)
        self.assertIn('validation.total_return', body)

    def test_cold_paper_page_fetches_real_budget_once(self):
        fn = method('src/app/page.daytrade/api.py', '_page_budget_status', {'_TRADING_MODE':'PAPER'})
        engine = SimpleNamespace(shared_budget_status=Mock(side_effect=[{'budget_status':'unavailable'}, {'budget_status':'ready','total_seed_krw':5000000}]),
                                 _broker=lambda: SimpleNamespace(request_options=lambda **kwargs: nullcontext()))
        self.assertEqual(fn(engine,5000000)['total_seed_krw'],5000000)
        self.assertEqual([c.kwargs['use_cache_only'] for c in engine.shared_budget_status.call_args_list],[True,False])

    def test_warm_page_does_not_add_gateway_calls(self):
        for mode in ('PAPER', 'LIVE'):
            fn = method('src/app/page.daytrade/api.py','_page_budget_status',{'_TRADING_MODE':mode})
            engine=SimpleNamespace(shared_budget_status=Mock(return_value={'budget_status':'ready','source':'cache_only:domestic_balance'}))
            fn(engine,5000000)
            engine.shared_budget_status.assert_called_once()

    def test_cold_live_page_reads_the_balance_once(self):
        # 10-18: with LIVE day trading OFF nothing warmed the cache and the
        # LIVE page showed a zero seed (source cache_miss, reserve_unavailable).
        fn = method('src/app/page.daytrade/api.py', '_page_budget_status', {'_TRADING_MODE':'LIVE'})
        engine = SimpleNamespace(shared_budget_status=Mock(side_effect=[{'budget_status':'reserve_unavailable','source':'cache_miss'},
                                                                        {'budget_status':'ready','total_seed_krw':1200000}]),
                                 _broker=lambda: SimpleNamespace(request_options=lambda **kwargs: nullcontext()))
        self.assertEqual(fn(engine,1000000)['total_seed_krw'],1200000)
        self.assertEqual([c.kwargs['use_cache_only'] for c in engine.shared_budget_status.call_args_list],[True,False])

    def test_dynamic_paper_allocation_respects_input_cap_live_unchanged(self):
        for paper,expected in [(True,5000000),(False,70000000)]:
            fn=method('src/portal/trading/model/struct/daytrade_engine.py','_dynamic_daytrade_allocation',{'_PAPER_MODE':paper})
            obj=SimpleNamespace(_config=lambda key,default: 'true' if key=='daytrade_dynamic_allocation_enabled' else default,
                                _safe_float=lambda value,default:float(value),
                                _recent_daytrade_allocation_performance=lambda:{'sell_count':0})
            result=fn(obj,total_asset_krw=100000000,requested_seed=5000000)
            self.assertEqual(result['target_seed_krw'],expected)

if __name__ == '__main__': unittest.main()
