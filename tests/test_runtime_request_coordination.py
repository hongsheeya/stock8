import ast
import copy
from pathlib import Path
from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


class RuntimeCoordinationTests(unittest.TestCase):
    def test_manual_retry_outside_window_never_syncs_cancels_or_orders(self):
        self._assert_retry_blocked(window_open=False, pending='')

    def test_manual_retry_unknown_receipt_never_syncs_cancels_or_orders(self):
        self._assert_retry_blocked(window_open=True, pending='unknown')

    def _assert_retry_blocked(self, window_open, pending):
        tree = ast.parse((ROOT / 'src/app/page.dashboard/api.py').read_text(encoding='utf-8-sig'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'retry_loc_buy_reservation')
        trading = Mock()
        trading.get_config.return_value = pending
        response = Mock()
        scope = dict(wiz=SimpleNamespace(request=SimpleNamespace(query=lambda *a: 'SOXL'), response=response),
                     _normalize_symbol=lambda s: s, _require_trading=lambda: trading,
                     _TIME=SimpleNamespace(now=lambda: None),
                     _loc_reservation_window_open=lambda now: window_open,
                     _loc_reservation_window_label=lambda now: '10:00-22:20 KST')
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<retry>', 'exec'), scope)
        scope[node.name]()
        self.assertEqual(response.status.call_args.args[0], 409)
        trading.engine.rebuild_loc_reservations.assert_not_called()
        trading._loc_reservation_lock.assert_not_called()

    def test_dashboard_reloads_share_singleflight(self):
        tree = ast.parse((ROOT / 'src/app/page.dashboard/api.py').read_text(encoding='utf-8-sig'))
        names = {'_DASHBOARD_SHARED', '_CACHE_LOCK', '_SINGLEFLIGHT_EVENTS'}
        nodes = [n for n in tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id in names for t in n.targets)]
        nodes += [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_singleflight']
        shared_sys = SimpleNamespace()
        scopes = [dict(_sys=shared_sys, threading=threading) for _ in range(2)]
        for scope in scopes:
            exec(compile(ast.Module(body=nodes, type_ignores=[]), '<reload>', 'exec'), scope)
        entered, release = threading.Event(), threading.Event()
        calls = []
        def build():
            calls.append(1)
            entered.set()
            release.wait(2)
        leader = threading.Thread(target=lambda: scopes[0]['_singleflight']('account', build))
        leader.start()
        try:
            self.assertTrue(entered.wait(1))
            result = scopes[1]['_singleflight']('account', build, timeout_sec=.01)
            self.assertEqual(result, (None, False))
            self.assertEqual(len(calls), 1)
        finally:
            release.set()
            leader.join(2)

    def test_struct_reloads_share_reservation_lock(self):
        tree = ast.parse((ROOT / 'src/portal/trading/model/struct.py').read_text(encoding='utf-8-sig'))
        node = next(n for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == '_LOC_RESERVATION_PROCESS_LOCK' for t in n.targets))
        shared_sys = SimpleNamespace()
        scopes = [dict(_sys=shared_sys, threading=threading) for _ in range(2)]
        for scope in scopes:
            exec(compile(ast.Module(body=[node], type_ignores=[]), '<reload>', 'exec'), scope)
        self.assertIs(scopes[0]['_LOC_RESERVATION_PROCESS_LOCK'], scopes[1]['_LOC_RESERVATION_PROCESS_LOCK'])

    def test_live_dashboard_never_starts_history_reconciliation(self):
        tree = ast.parse((ROOT / 'src/app/page.dashboard/api.py').read_text(encoding='utf-8-sig'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_sync_external_cycle_trades_if_due')
        scope = {'_PAPER_MODE': False}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<read-only>', 'exec'), scope)
        self.assertEqual(scope[node.name](None, force=True)['status'], 'deferred')
