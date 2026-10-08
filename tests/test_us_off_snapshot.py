"""OFF page rendering must not evaluate signals or fetch broker data."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock


class UsOffSnapshotTests(unittest.TestCase):
    def test_off_snapshot_reads_only_local_state_and_cached_budget(self):
        source = Path(__file__).resolve().parents[1] / 'src/app/page.daytrade.us/api.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_build_us_off_snapshot')
        scope = {}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), scope)
        engine = Mock()
        engine._state_for.return_value = {'position_qty': 3, 'last_price': 10}
        engine.shared_budget_status.return_value = {'source': 'cache_miss'}
        result = scope[fn.name](engine, 'TEST', 'vrev', 5000000, {'us_auto_enabled': False})
        self.assertTrue(result['deferred'])
        self.assertFalse(result['verify']['ok'])
        self.assertEqual(result['status']['signal']['action'], 'HOLD')
        self.assertEqual(result['status']['state']['position_qty'], 3)
        engine.shared_budget_status.assert_called_once_with(requested_seed=5000000, market='US', use_cache_only=True)
        self.assertEqual([call[0] for call in engine.mock_calls], ['_state_for', 'shared_budget_status'])
