import ast
from contextlib import contextmanager
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import uuid


def gateway():
    source = Path(__file__).resolve().parents[1] / 'src/portal/trading/model/struct/kis_api.py'
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_shared_paper_gateway')
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'KisApi')
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in ('_rate_limit_wait', '_apply_rate_limit_cooldown')]
    ns = dict(os=os, tempfile=tempfile, hashlib=hashlib, json=json, time=time,
              contextmanager=contextmanager, PAPER_MODE=True, _REQUEST_OPTIONS=threading.local())
    exec(compile(ast.Module(body=[helper] + methods, type_ignores=[]), str(source), 'exec'), ns)
    return ns


def run_worker(key, queue):
    ns = gateway()
    api = SimpleNamespace(app_key=key, base_url='test-paper', _min_request_interval=1.1)
    for _ in range(2):
        ns['_rate_limit_wait'](api)
        queue.put(time.time())


class CrossProcessLimitTests(unittest.TestCase):
    def test_two_processes_share_one_request_budget(self):
        ctx = multiprocessing.get_context('spawn')
        queue = ctx.Queue()
        key = uuid.uuid4().hex
        workers = [ctx.Process(target=run_worker, args=(key, queue)) for _ in range(2)]
        for worker in workers: worker.start()
        try:
            stamps = sorted(queue.get(timeout=20) for _ in range(4))
            for a, b in zip(stamps, stamps[1:]): self.assertGreaterEqual(b-a, 1.07)
        finally:
            for worker in workers:
                worker.join(timeout=5)
                if worker.is_alive(): worker.terminate(); worker.join()
        self.assertTrue(all(w.exitcode == 0 for w in workers))

    def test_shared_cooldown_honors_deadline_without_sending(self):
        ns = gateway()
        api = SimpleNamespace(app_key=uuid.uuid4().hex, base_url='test-paper', _min_request_interval=1.1)
        ns['_apply_rate_limit_cooldown'](api, 2)
        ns['_REQUEST_OPTIONS'].deadline = time.monotonic() + 0.05
        with self.assertRaises(TimeoutError): ns['_rate_limit_wait'](api)
