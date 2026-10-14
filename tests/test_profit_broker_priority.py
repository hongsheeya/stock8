import ast
from pathlib import Path
import unittest


class BrokerRealizedPriorityTests(unittest.TestCase):
    def test_period_ledger_is_not_overwritten_by_engine_state(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] /
            'src/app/page.dashboard/api.py').read_text(encoding='utf-8-sig'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == '_profit_summary_data')
        writes = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == 'daytrade_realized_profit'
                          for t in n.targets)]
        self.assertEqual(len(writes), 2)  # initialization, then period ledger
        ledger_write = next(n for n in writes if isinstance(n.value, ast.Call))
        for amount in (-3893, 0, 12000):
            scope = {'daytrade_summary': {'pnl_net': amount}}
            exec(compile(ast.Module(body=[ledger_write], type_ignores=[]), '<test>', 'exec'), scope)
            self.assertEqual(scope['daytrade_realized_profit'], amount)
        self.assertNotIn('_daytrade_state_realized_total', ast.unparse(fn))
