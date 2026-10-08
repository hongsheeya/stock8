"""Run production worker bodies against fake engines, never a broker."""
import ast
import datetime
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
import unittest
import flask


class StopIterationTest(BaseException):
    pass


class WorkerPaths(unittest.TestCase):
    def run_job(self, job, enabled, init_failures=0, cycle_errors=None, rounds=1, policies=None, admin=True):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'src/portal/trading/model/struct.py').read_text(encoding='utf-8-sig'))
        outer = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_ensure_live_policy_workers')
        fn = next(n for n in ast.walk(outer) if isinstance(n, ast.FunctionDef) and n.name == 'account_job')
        engine = Mock()
        if cycle_errors is not None:
            engine.auto_cycle.side_effect = cycle_errors
        state = {}
        policy_read = Mock(side_effect=policies) if policies else lambda: enabled
        trading = NS(order_policy=NS(_key=lambda: 'test', read=policy_read, daytrade_allowed=lambda:admin),
                     get_config=lambda *a: '5000000', daytrade_engine=engine,
                     run_due_loc_automation=Mock())
        app = flask.Flask('worker-test'); app.secret_key = 'test-only'
        sleeps = []
        def stop(_):
            sleeps.append(dict(state))
            if len(sleeps) >= rounds: raise StopIterationTest()
        attempts = []
        def initialize():
            attempts.append(True)
            if len(attempts) <= init_failures: raise ConnectionError('temporary database outage')
            return trading
        scope = {'registry': {'jobs': {('test', job): state}},
                 'wiz': NS(server=NS(app=NS(flask=app))), 'Struct': initialize,
                 '_kst_now': lambda: datetime.datetime(2026, 10, 2, 10), 'time': NS(sleep=stop)}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<worker-test>', 'exec'), scope)
        with self.assertRaises(StopIterationTest): scope['account_job']('test', 'test-owner', job)
        state['observed_statuses'] = [row['status'] for row in sleeps]
        return trading, state

    def test_initialization_failure_recovers_without_losing_worker(self):
        trading, state = self.run_job('entry_ks', {'daytrade_ks': True}, init_failures=1, rounds=2)
        self.assertEqual(state['observed_statuses'], ['error', 'waiting'])
        trading.daytrade_engine.auto_cycle.assert_called_once()
        self.assertEqual(state['error'], '')

    def test_transport_failure_recovers_next_cycle(self):
        trading, state = self.run_job('entry_ks', {'daytrade_ks': True},
            cycle_errors=[TimeoutError('read timeout'), None], rounds=2)
        self.assertEqual(state['observed_statuses'], ['error', 'waiting'])
        self.assertEqual(trading.daytrade_engine.auto_cycle.call_count, 2)

    def test_switch_off_during_failure_does_not_retry_engine(self):
        trading, state = self.run_job('entry_ks', {}, cycle_errors=[TimeoutError('timeout')],
            rounds=2, policies=[{'daytrade_ks': True}, {'daytrade_ks': False}])
        self.assertEqual(state['observed_statuses'], ['error', 'off'])
        trading.daytrade_engine.auto_cycle.assert_called_once()

    def test_off_runs_no_entry_exit_or_loc(self):
        for job in ('entry_ks', 'exit_ks', 'entry_us', 'exit_us', 'loc'):
            with self.subTest(job=job):
                trading, state = self.run_job(job, {})
                self.assertEqual(trading.daytrade_engine.mock_calls, [])
                trading.run_due_loc_automation.assert_not_called()
                self.assertEqual(state['status'], 'off')

    def test_nonadmin_stale_on_never_runs_daytrade_but_loc_still_runs(self):
        for job in ('entry_ks','exit_ks','entry_us','exit_us','loc'):
            trading, state=self.run_job(job, {'daytrade_ks':True,'daytrade_us':True,'infinite_buy':True}, admin=False)
            self.assertEqual(trading.daytrade_engine.mock_calls, [])
            if job=='loc': trading.run_due_loc_automation.assert_called_once()
            else: self.assertEqual(state['status'],'off')

    def test_market_workers_execute_only_their_own_market(self):
        for suffix, market in (('ks', 'KS'), ('us', 'US')):
            for kind, method in (('entry', 'auto_cycle'), ('exit', 'execute_exit_watch')):
                with self.subTest(market=market, kind=kind):
                    trading, state = self.run_job(kind+'_'+suffix, {'daytrade_'+suffix: True})
                    getattr(trading.daytrade_engine, method).assert_called_once_with(requested_seed=5000000.0, market=market)
                    self.assertEqual(len(trading.daytrade_engine.mock_calls), 1)
                    self.assertEqual(state['status'], 'waiting')

    def test_other_market_on_cannot_start_off_market(self):
        for job in ('entry_us', 'exit_us'):
            trading, state = self.run_job(job, {'daytrade_ks': True})
            self.assertEqual(trading.daytrade_engine.mock_calls, [])
            self.assertEqual(state['status'], 'off')
