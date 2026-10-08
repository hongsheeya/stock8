import ast
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
import unittest
import time
from season.lib.exception import ResponseException


class ProfitResponseBoundary(unittest.TestCase):
    def test_completed_response_is_not_caught_as_connection_failure(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'src/app/page.dashboard/api.py').read_text(encoding='utf-8-sig'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'profit_summary')
        sent = []
        def status(code, **payload):
            sent.append(payload)
            raise ResponseException(code, payload)
        scope = {'json': json, 'time': time, 'wiz': NS(request=NS(query=lambda key, default: default), response=NS(status=status)),
                 '_truthy': lambda v: v == 'true', '_dashboard_cache_scope': lambda: 'test',
                 '_require_trading': lambda: object(), '_PAPER_MODE': False,
                 '_broker_setup_state': lambda *a, **kw: {'allowed': False, 'message': '잔고 조회 지연'},
                 '_empty_profit_summary_payload': lambda **kw: kw, '_dump_error': Mock()}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<response-test>', 'exec'), scope)
        with self.assertRaises(ResponseException): scope['profit_summary']()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['message'], '잔고 조회 지연')
        scope['_dump_error'].assert_not_called()
