"""Initial/automatic loads must execute essential broker account reads."""
import ast
from pathlib import Path
import unittest

class RequiredReads(unittest.TestCase):
    def test_account_reads_are_not_force_refresh_conditionals(self):
        source = Path(__file__).resolve().parents[1] / 'src/app/page.dashboard/api.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        method = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_build_overview_payload')
        expected = {'balance': 'get_balance', 'present': 'get_present_balance'}
        found = set()
        for node in ast.walk(method):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            call = node.value
            if not isinstance(call.func, ast.Name) or call.func.id != '_dashboard_kis_call':
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in expected:
                    self.assertEqual(call.args[0].value, expected[target.id])
                    found.add(target.id)
        self.assertEqual(found, set(expected))
