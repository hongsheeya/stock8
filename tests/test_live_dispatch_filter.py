"""Exercise the actual dispatcher predicate without starting trading workers."""
import ast
from pathlib import Path
import unittest
import peewee as pw

ROOT = Path(__file__).resolve().parents[1]


class DispatchFilterTests(unittest.TestCase):
    def test_dispatch_reads_only_policy_rows(self):
        tree = ast.parse((ROOT / 'src/portal/trading/model/struct.py').read_text(encoding='utf-8'))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                      and n.name == '_ensure_live_policy_workers')
        call = next(n for n in ast.walk(method) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and n.func.attr == 'rows')
        self.assertNotIn('key__startswith', [kw.arg for kw in call.keywords])
        expression = next(kw.value for kw in call.keywords if kw.arg == 'key')
        predicate = eval(compile(ast.Expression(expression), '<dispatch-filter>', 'eval'))
        db = pw.SqliteDatabase(':memory:')

        class Config(pw.Model):
            key = pw.TextField()
            value = pw.TextField()
            class Meta:
                database = db

        with db:
            db.create_tables([Config])
            Config.insert_many([
                {'key': 'ordinary_setting', 'value': 'not-json'},
                {'key': 'user:abc:order_policy_v1:other', 'value': '{}'},
                {'key': 'order_policy_v1:account', 'value': '{}'},
            ]).execute()
            rows = list(Config.select().where(predicate(Config.key)).dicts())
            self.assertEqual([row['key'] for row in rows], ['order_policy_v1:account'])
