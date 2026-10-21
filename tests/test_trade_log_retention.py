"""Order-log retention keeps order/fill events and archives what it trims (10-21)."""
import ast
import datetime
import gzip
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import peewee as pw

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "src/portal/trading/model/struct.py").read_text(encoding="utf-8-sig")
TREE = ast.parse(SRC)
STRUCT = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "Struct")
ATTRS = {}
for node in STRUCT.body:
    if isinstance(node, ast.Assign) and node.targets[0].id.startswith("_LOG_"):
        ATTRS[node.targets[0].id] = eval(compile(ast.Expression(node.value), "x", "eval"))
FN = next(n for n in STRUCT.body if isinstance(n, ast.FunctionDef) and n.name == "_trim_trade_logs")
ENV = {"_dt": datetime, "_os": os, "_json": json, "_kst_now": datetime.datetime.now}
exec(compile(ast.Module(body=[FN], type_ignores=[]), "struct.py", "exec"), ENV)
trim = ENV["_trim_trade_logs"]


class _Raw:
    def __init__(self, path):
        self.orm = SimpleNamespace(_meta=SimpleNamespace(database=pw.SqliteDatabase(path)))

    def _db_enter(self):
        pass

    def _close_connection(self):
        pass

    def _db_exit(self):
        pass


class TradeLogRetentionTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "trading.db")
        con = sqlite3.connect(self.path)
        con.execute("create table trade_log (id text, event_type text, message text, created text)")
        rows = [("1", "IB_LOC_AUTOMATION_RUN", "old noise", "2026-09-01 10:00:00"),
                ("2", "IB_LOC_BUY_PRICE_MISMATCH", "old noise", "2026-09-30 10:00:00"),
                ("3", "IB_LOC_AUTOMATION_RUN", "recent noise", "2026-10-20 10:00:00"),
                ("4", "IB_LOC_BUY_ERROR", "old error", "2026-08-01 10:00:00"),
                ("5", "IB_LOC_BUY_ERROR", "recent error", "2026-10-01 10:00:00"),
                ("6", "DT_KS_BUY1", "old fill", "2026-07-01 10:00:00"),
                ("7", "IB_LOC_BUY_SCHEDULED", "old order", "2026-07-01 10:00:00")]
        con.executemany("insert into trade_log values (?,?,?,?)", rows)
        con.commit()
        con.close()
        self.struct = SimpleNamespace(db=lambda name: SimpleNamespace(_db=_Raw(self.path)), **ATTRS)

    def test_trims_noise_and_old_errors_only_and_archives_them(self):
        now = datetime.datetime(2026, 10, 21, 12, 0)
        result = trim(self.struct, now=now)
        left = {r[0] for r in sqlite3.connect(self.path).execute("select id from trade_log")}
        self.assertEqual(left, {"3", "5", "6", "7"})
        self.assertEqual(result, {"removed": 3, "remaining": 4})
        archive = os.path.join(self.dir, "log-archive", "trade_log-20261021.jsonl.gz")
        with gzip.open(archive, "rt", encoding="utf-8") as fh:
            self.assertEqual(sorted(json.loads(line)["id"] for line in fh), ["1", "2", "4"])

    def test_soft_cap_trims_recent_noise(self):
        self.struct._LOG_SOFT_CAP = 3
        trim(self.struct, now=datetime.datetime(2026, 10, 25, 12, 0))
        left = {r[0] for r in sqlite3.connect(self.path).execute("select id from trade_log")}
        self.assertEqual(left, {"5", "6", "7"})


if __name__ == "__main__":
    unittest.main()
