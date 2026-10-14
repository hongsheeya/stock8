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

    def _paper_loc_methods(self):
        path = Path(__file__).resolve().parents[1] / 'src/portal/trading/model/struct.py'
        cls = next(n for n in ast.parse(path.read_text(encoding='utf-8-sig')).body
                   if isinstance(n, ast.ClassDef) and n.name == 'Struct')
        names = ('_poll_or_start_loc_automation', '_poll_or_start_paper_loc_emulation')
        methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
        env = {'PAPER_MODE': True, 'threading': threading}
        exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), 'exec'), env)
        return env

    def _paper_loc_obj(self, env, window_state, config='true'):
        runs = []
        engine = SimpleNamespace(
            paper_loc_window=lambda: {'state': window_state, 'et_date': '2026-10-14', 'window': '15:55-15:59 ET'},
            run_paper_loc_emulation=lambda: runs.append(1) or {'status': 'completed', 'et_date': '2026-10-14',
                                                               'message': '주문 3건', 'executed': True})
        obj = SimpleNamespace(get_config=lambda key, default: config, engine=engine,
                              _account_worker_target=lambda fn: fn)
        obj._poll_or_start_paper_loc_emulation = lambda state: env['_poll_or_start_paper_loc_emulation'](obj, state)
        return obj, runs

    def test_paper_loc_waits_outside_the_window_and_off_is_a_noop(self):
        env = self._paper_loc_methods()
        poll = env['_poll_or_start_loc_automation']
        obj, runs = self._paper_loc_obj(env, 'before')
        state = {}
        for _ in range(3):
            result = poll(obj, state, verify=True)
            self.assertEqual(result['status'], 'waiting')
            self.assertFalse(result['submitted'])
        self.assertEqual((state, runs), ({}, []))
        obj, runs = self._paper_loc_obj(env, 'open', config='false')
        self.assertEqual(poll(obj, state)['status'], 'off')
        self.assertEqual((state, runs), ({}, []))

    def test_paper_loc_decides_off_the_loop_once_a_day(self):
        env = self._paper_loc_methods()
        poll = env['_poll_or_start_loc_automation']
        obj, runs = self._paper_loc_obj(env, 'open')
        state = {}
        self.assertEqual(poll(obj, state)['status'], 'running')
        state['paper_loc_thread'].join(5)
        self.assertEqual(poll(obj, state)['status'], 'completed')
        later = poll(obj, state)
        self.assertEqual(later['status'], 'waiting')
        self.assertIn('오늘 판정 완료', later['message'])
        self.assertEqual(runs, [1])

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



class PaperWorkerResumeTests(unittest.TestCase):
    """Restart resume: the server bootstrap has no browser session."""

    METHODS = ('_account_worker_target', '_ensure_background_worker', 'resume_paper_worker',
               '_remembered_paper_worker_owner', '_remember_paper_worker_owner')

    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'src/portal/trading/model/struct.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Struct')
        methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in self.METHODS]
        self.assertEqual(sorted(m.name for m in methods), sorted(self.METHODS))
        self.app = flask.Flask(__name__)
        self.app.secret_key = 'test-only'
        self.users = {'admin', 'member', 'admin2'}
        self.admins = {'admin', 'admin2'}
        self.subscribed = {'admin', 'member', 'admin2'}
        self.config = {}
        self.ran_as = []
        self.done = threading.Event()
        test = self

        class Subscription:
            def __init__(self, _root):
                pass

            def enabled(self, uid):
                return uid in test.subscribed

        wiz = SimpleNamespace(server=SimpleNamespace(app=SimpleNamespace(flask=self.app),
                                                     path=SimpleNamespace(root='.')),
                              model=lambda name: Subscription)
        import os, sys
        self.env = dict(PAPER_MODE=True, wiz=wiz, threading=threading, _os=os, _sys=SimpleNamespace(argv=[]),
                        _PAPER_WORKER_OWNER_KEY='paper_worker_owner_user_id',
                        Struct=SimpleNamespace(_worker_lock=threading.Lock()))
        exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), 'exec'), self.env)
        self.state = {}
        self.live_calls = []

        def loop(_self, generation):
            test.ran_as.append(flask.session.get('id'))
            test.done.set()

        attrs = {name: self.env[name] for name in self.METHODS}
        attrs.update(
            _current_user_id=lambda _self: flask.session.get('id', '') if flask.has_request_context() else '',
            _current_user_is_admin=lambda _self, uid=None: uid in test.admins,
            _lookup_config_value=lambda _self, key, missing=None: test.config.get(key, missing),
            _write_config_value=lambda _self, key, value, *a, **k: test.config.__setitem__(key, str(value)),
            _worker_state=lambda _self: test.state,
            _daytrade_engine_model=lambda _self: object(),
            _daytrade_model=lambda _self: object(),
            _background_worker_loop=loop,
            _ensure_live_policy_workers=lambda _self: test.live_calls.append(True),
            orm=SimpleNamespace(use=lambda _name: SimpleNamespace(get=lambda **kw: kw.get('id') in test.users)),
        )
        self.obj = type('StructDouble', (), attrs)()

    def _finish_worker(self):
        self.assertTrue(self.done.wait(5))
        self.state['thread'].join(5)
        self.done.clear()

    def test_restart_resumes_remembered_owner_without_session(self):
        self.config['paper_worker_owner_user_id'] = 'admin'
        with self.app.test_request_context('/stock8-paper-bootstrap'):
            self.assertEqual(self.obj.resume_paper_worker(), 'admin')
        self._finish_worker()
        self.assertEqual(self.ran_as, ['admin'])

    def test_resume_waits_for_login_when_owner_is_gone_or_unsubscribed(self):
        for remembered, users, subscribed in (('', self.users, self.subscribed),
                                              ('ghost', self.users, self.subscribed | {'ghost'}),
                                              ('member', self.users, {'admin'})):
            self.config['paper_worker_owner_user_id'] = remembered
            self.users, self.subscribed = users, subscribed
            with self.app.test_request_context('/stock8-paper-bootstrap'):
                self.assertEqual(self.obj.resume_paper_worker(), '')
            self.assertNotIn('thread', self.state)

    def test_session_less_loads_never_start_a_worker(self):
        # Scripts load Struct without a session; only the bootstrap may resume.
        self.config['paper_worker_owner_user_id'] = 'admin'
        with self.app.test_request_context('/'):
            self.obj._ensure_background_worker()
        self.assertNotIn('thread', self.state)

    def test_live_never_resumes_paper_owner(self):
        self.env['PAPER_MODE'] = False
        self.config['paper_worker_owner_user_id'] = 'admin'
        with self.app.test_request_context('/stock8-paper-bootstrap'):
            self.assertEqual(self.obj.resume_paper_worker(), '')
        self.assertNotIn('thread', self.state)
        self.assertEqual(self.live_calls, [])

    def test_login_start_remembers_owner_but_member_does_not_displace_admin(self):
        for user, remembered in (('admin', 'admin'), ('member', 'admin'), ('admin2', 'admin2')):
            with self.app.test_request_context('/'):
                flask.session['id'] = user
                self.obj._ensure_background_worker()
            self._finish_worker()
            self.assertEqual(self.config['paper_worker_owner_user_id'], remembered)
        self.assertEqual(self.ran_as, ['admin', 'member', 'admin2'])

    def test_member_is_remembered_when_no_valid_owner_exists(self):
        self.config['paper_worker_owner_user_id'] = 'ghost'
        with self.app.test_request_context('/'):
            flask.session['id'] = 'member'
            self.obj._ensure_background_worker()
        self._finish_worker()
        self.assertEqual(self.config['paper_worker_owner_user_id'], 'member')

    def test_alive_worker_is_not_restarted_or_reassigned(self):
        with self.app.test_request_context('/'):
            flask.session['id'] = 'admin'
            self.obj._ensure_background_worker()
        self._finish_worker()
        alive = threading.Event()
        keeper = threading.Thread(target=alive.wait)
        keeper.start()
        self.state['thread'] = keeper
        try:
            with self.app.test_request_context('/'):
                flask.session['id'] = 'admin2'
                self.obj._ensure_background_worker()
            self.assertIs(self.state['thread'], keeper)
            self.assertEqual(self.config['paper_worker_owner_user_id'], 'admin')
        finally:
            alive.set()
            keeper.join(5)


if __name__ == '__main__':
    unittest.main()
