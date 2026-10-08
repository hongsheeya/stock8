import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


class ConnectionGraceTests(unittest.TestCase):
    def test_overview_does_not_force_connection_probe_before_cache(self):
        source = Path(__file__).resolve().parents[1] / 'src/app/page.dashboard/api.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'overview')
        probes = [n for n in ast.walk(node) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Name) and n.func.id == '_broker_setup_state']
        self.assertEqual(len(probes), 1)
        setting = next(k.value for k in probes[0].keywords if k.arg == 'require_connection')
        self.assertIs(setting.value, False)

    def test_failed_checks_do_not_extend_last_success_indefinitely(self):
        source = Path(__file__).resolve().parents[1] / 'src/app/page.dashboard/api.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == '_kis_connection_status')
        clock = [100.0]
        cache = {'account': {'checked_at': 0, 'last_success_at': 90, 'result': None}}
        scope = {'time': SimpleNamespace(monotonic=lambda: clock[0]),
                 '_dashboard_cache_scope': lambda: 'account', '_KIS_STATUS_CACHE': cache,
                 '_PAPER_MODE': False, '_KIS_STATUS_SUCCESS_TTL_SEC': 20,
                 '_KIS_STATUS_FAILURE_TTL_SEC': 3, '_KIS_STICKY_SUCCESS_GRACE_SEC': 180}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<connection-test>', 'exec'), scope)
        trading = SimpleNamespace(get_config=lambda *args: 'kis',
                                  broker_api=SimpleNamespace(test_connection=lambda: {'success': False, 'message': 'timeout'}))
        fn = scope['_kis_connection_status']
        self.assertTrue(fn(trading, ttl_sec=0)['sticky'])
        self.assertEqual(cache['account']['last_success_at'], 90)
        clock[0] = 280
        self.assertFalse(fn(trading, ttl_sec=0)['success'])
