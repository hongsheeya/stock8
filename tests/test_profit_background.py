import ast
import copy
import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

import flask


class MemoryStore:
    def __init__(self): self.entry = None
    def read(self, name): return copy.deepcopy(self.entry)
    def write(self, name, payload): self.entry = {'at': time.time(), 'payload': payload}


class ProfitBackgroundTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'src/app/page.dashboard/api.py').read_text(encoding='utf-8-sig'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_fast_profit_summary')
        self.store = MemoryStore()
        self.tasks = []
        self.scope = {'json':json, 'time':time, 'threading':threading,
            '_profit_store': lambda _: (self.store, 'account-a'),
            '_DASHBOARD_SHARED':{}, '_CACHE_LOCK':threading.Lock(),
            '_connection_message':str, '_profit_summary_data':lambda *a, **kw: {'aggregation_complete':True, 'realized_profit':123}}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<profit-background>', 'exec'), self.scope)
        self.app = flask.Flask(__name__)

    def call(self, **kwargs):
        with self.app.test_request_context('/'):
            with patch.object(threading.Thread, 'start', lambda thread: self.tasks.append(thread)):
                return self.scope['_fast_profit_summary'](object(), '1W', **kwargs)

    def test_cold_read_returns_without_running_broker_and_coalesces_requests(self):
        result = self.call()
        self.assertFalse(result['snapshot_available'])
        self.assertNotIn('realized_profit',result)
        self.call()
        self.assertEqual(len(self.tasks),1)
        self.tasks[0].run()
        self.assertEqual(self.call()['realized_profit'],123)

    def test_failed_refresh_preserves_last_confirmed_snapshot(self):
        self.store.entry = {'at':time.time()-60,'payload':{'realized_profit':789}}
        self.scope['_profit_summary_data'] = lambda *a, **kw: {'aggregation_complete':False,'realized_profit':0}
        self.assertEqual(self.call()['realized_profit'],789)
        self.tasks[0].run()
        result = self.call()
        self.assertEqual(result['realized_profit'],789)
        self.assertTrue(result['stale'])
        self.assertIn('미완료',result['message'])
