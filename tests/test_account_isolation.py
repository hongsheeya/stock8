import importlib.util
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class AccountIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = load('isolated_db', 'src/portal/season/model/dbbase/mysql.py')
        cls.ctx = load('account_context', 'src/portal/trading/model/account_context.py')

    def test_separate_physical_databases_never_import_paper_rows(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {}, clear=True):
            paths = []
            for mode in ('PAPER', 'LIVE'):
                os.environ['TRADING_MODE'] = mode
                path = self.db.trading_database_path(root)
                paths.append(path)
                Path(path).parent.mkdir(parents=True)
                with closing(sqlite3.connect(path)) as conn:
                    conn.execute('create table history (symbol text)')
                    if mode == 'PAPER':
                        conn.execute("insert into history values ('TQQQ')")
                    rows = conn.execute('select * from history').fetchall()
                    self.assertEqual(len(rows), 1 if mode == 'PAPER' else 0)
            self.assertNotEqual(paths[0], paths[1])

    def test_database_alias_is_rejected(self):
        with patch.dict(os.environ, {'TRADING_MODE': 'LIVE', 'STOCK8_LIVE_DB_PATH': 'shared.db', 'STOCK8_PAPER_DB_PATH': 'shared.db'}):
            with self.assertRaises(RuntimeError):
                self.db.trading_database_path(str(ROOT))

    def test_account_context_is_server_bound(self):
        for mode in ('LIVE', 'PAPER'):
            with patch.dict(os.environ, {'TRADING_MODE': mode}, clear=True):
                ctx = self.ctx.context()
                self.assertEqual(ctx['mode'], mode)
                self.assertEqual(ctx['is_mock'], mode == 'PAPER')
                self.assertNotEqual(ctx['live_url'], ctx['paper_url'])
                self.assertEqual(ctx['live_url'], 'http://127.0.0.1:3001/dashboard')

    def test_invalid_mode_fails_closed(self):
        with patch.dict(os.environ, {'TRADING_MODE': 'typo'}):
            for func in (self.ctx.context, lambda: self.db.trading_database_path(str(ROOT))):
                with self.assertRaises(RuntimeError): func()

    def test_origin_alias_and_url_paths_are_rejected(self):
        for paper in ('http://127.0.0.1:3001', 'https://host/path', 'javascript:alert(1)'):
            with patch.dict(os.environ, {'STOCK8_PAPER_ORIGIN': paper}, clear=True):
                with self.assertRaises(RuntimeError): self.ctx.context()
