"""Execute the production worker wrapper with real Flask thread contexts."""
import ast
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
import flask


class PaperWorkerOwnerTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'src/portal/trading/model/struct.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Struct')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_account_worker_target')
        self.app = flask.Flask(__name__)
        self.app.secret_key = 'test-only'
        self.env = dict(PAPER_MODE=True, wiz=SimpleNamespace(server=SimpleNamespace(app=SimpleNamespace(flask=self.app))))
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), self.env)
        self.exists = True
        self.obj = SimpleNamespace(_current_user_id=lambda: flask.session.get('id', ''),
                                   orm=SimpleNamespace(use=lambda _: SimpleNamespace(get=lambda **kw: self.exists)))

    def wrap(self, fn):
        return self.env['_account_worker_target'](self.obj, fn)

    def test_owner_survives_parent_request_and_nested_thread(self):
        seen = []
        def child():
            seen.append(flask.session['id'])
            nested = threading.Thread(target=self.wrap(lambda: seen.append(flask.session['id'])))
            nested.start(); nested.join()
        with self.app.test_request_context('/'):
            flask.session['id'] = 'paper-owner'
            target = self.wrap(child)
        thread = threading.Thread(target=target)
        thread.start(); thread.join()
        self.assertEqual(seen, ['paper-owner', 'paper-owner'])

    def test_anonymous_and_deleted_owner_fail_closed(self):
        with self.app.test_request_context('/'):
            anonymous = self.wrap(lambda: self.fail('must not execute'))
            flask.session['id'] = 'deleted'
            deleted = self.wrap(lambda: self.fail('must not execute'))
        with self.assertRaises(RuntimeError): anonymous()
        self.exists = False
        with self.assertRaises(RuntimeError): deleted()

    def test_live_callback_unchanged(self):
        self.env['PAPER_MODE'] = False
        fn = lambda: None
        self.assertIs(self.wrap(fn), fn)

    def test_paper_loc_does_not_start_unsupported_reservation_jobs(self):
        path = Path(__file__).resolve().parents[1] / 'src/portal/trading/model/struct.py'
        cls = next(n for n in ast.parse(path.read_text(encoding='utf-8-sig')).body
                   if isinstance(n, ast.ClassDef) and n.name == 'Struct')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_poll_or_start_loc_automation')
        env = {'PAPER_MODE': True}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), env)
        obj = SimpleNamespace(get_config=lambda key, default: 'true')
        state = {}
        for _ in range(3):
            result = env[method.name](obj, state, verify=True)
            self.assertEqual(result['status'], 'unsupported')
            self.assertFalse(result['verified'])
            self.assertFalse(result['submitted'])
            self.assertEqual(state, {})
        obj.get_config = lambda key, default: 'false'
        self.assertEqual(env[method.name](obj, state)['status'], 'off')

    def test_paper_forced_scheduler_uses_same_capability_gate(self):
        path = Path(__file__).resolve().parents[1] / 'src/portal/trading/model/struct.py'
        cls = next(n for n in ast.parse(path.read_text(encoding='utf-8-sig')).body
                   if isinstance(n, ast.ClassDef) and n.name == 'Struct')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'run_due_loc_automation')
        env = {'PAPER_MODE': True}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), env)
        calls = []
        obj = SimpleNamespace(_poll_or_start_loc_automation=lambda *args, **kwargs: calls.append(kwargs) or {'status': 'unsupported'})
        for force in (False, True):
            result = env[method.name](obj, force=force, verify=True, reason='scheduler')
            self.assertEqual(result['status'], 'unsupported')
        self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
