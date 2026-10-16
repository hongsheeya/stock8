"""History page (10-16): fast reads, complete fills and closed-trade P&L.

Measured on PAPER: symbols 21.5 s, daytrade_trades 32.6 s. The ORM dropped
the `event_type__startswith` filter and ignored `dump` without `page`, so each
call read all 25k trade_log rows; sqlite3 then gave up the GIL once per row
while the trading workers were busy. The page also showed only the newest 900
log rows, so September's trades were missing from the totals.
"""
import ast
import builtins
import datetime
import json
import os
import re
import tempfile
import types
import unittest
from pathlib import Path

import peewee as pw

ROOT = Path(__file__).resolve().parents[1]


def _functions(path, extra=None):
    tree = ast.parse(Path(path).read_text(encoding="utf-8-sig"))
    # Module-level constants and functions; never the wiz.model(...) loaders.
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef)
            or (isinstance(n, ast.Assign) and "wiz" not in ast.unparse(n.value))]
    ns = {"re": re, "json": json, "datetime": datetime, "copy": __import__("copy"), "math": __import__("math"),
          "time": __import__("time"), "KST": datetime.timezone(datetime.timedelta(hours=9))}
    ns.update(extra or {})
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), ns)
    return ns


class _Time:
    @staticmethod
    def to_kst(value, **_kwargs):
        if value in (None, ""):
            return None
        return datetime.datetime.fromisoformat(str(value)[:19])


class _Wiz:
    def model(self, name):
        if name == "portal/trading/kst":
            return _Time()
        if name == "struct":
            return types.SimpleNamespace(trading=None)
        if name == "portal/season/config":
            return types.SimpleNamespace(orm_base="db/")
        raise RuntimeError(name)


builtins.wiz = getattr(builtins, "wiz", None) or _Wiz()
api = _functions(ROOT / "src/app/page.history/api.py", extra={"_TIME": _Time(), "_HISTORY_CACHE": {},
                                                               "_HISTORY_CACHE_TTL_SEC": 20, "_READ_STATE": {"fallback": ""}})
api["_history_cache_scope"] = lambda: "test"

# A file, not :memory:: the ORM closes the connection after every query.
_DB_PATH = os.path.join(tempfile.mkdtemp(prefix="stock8-history-"), "trading.db")
_DB = pw.SqliteDatabase(_DB_PATH)


class _Log(pw.Model):
    id = pw.CharField(primary_key=True)
    user_id = pw.CharField(default="")
    symbol = pw.CharField(default="")
    event_type = pw.CharField(default="")
    message = pw.TextField(default="")
    created = pw.DateTimeField()

    class Meta:
        database = _DB
        table_name = "trade_log"


_DB.create_tables([_Log])
for i, (uid, event) in enumerate([("u", "DT_KS_BUY1"), ("", "DT_KS_SELL_FULL"), ("", "IB_LOC_AUTOMATION_RUN"),
                                  ("u", "DT_KS_SELL_FULL_ERROR"), ("other", "DT_KS_BUY1"), ("", "DT_US_BUY")]):
    _Log.create(id=f"r{i}", user_id=uid, symbol=f"S{i}", event_type=event, message=f"m{i}",
                created=datetime.datetime(2026, 10, 16, 9, i))


class OrmStartswithTests(unittest.TestCase):
    def setUp(self):
        orm_src = (ROOT / "src/portal/season/model/orm.py").read_text(encoding="utf-8")
        ns = {"wiz": _Wiz(), "__name__": "orm_under_test"}
        exec(compile(orm_src, "orm.py", "exec"), ns)
        self.model = object.__new__(ns["Model"])
        self.model.orm = _Log

    def test_prefix_filter_is_applied(self):
        rows = self.model.rows(event_type__startswith="DT_", orderby="created", order="DESC")
        self.assertEqual([r["id"] for r in rows], ["r5", "r4", "r3", "r1", "r0"])

    def test_underscore_in_prefix_is_literal(self):
        _Log.create(id="rx", user_id="", symbol="X", event_type="DTX_OTHER", created=datetime.datetime(2026, 1, 1))
        try:
            rows = self.model.rows(event_type__startswith="DT_")
            self.assertNotIn("rx", [r["id"] for r in rows])
        finally:
            _Log.delete_by_id("rx")


class ScopedLimitTests(unittest.TestCase):
    """_UserScopedDb: SQL LIMIT per query, then a correct page of the merge."""

    def setUp(self):
        src = (ROOT / "src/portal/trading/model/struct.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "_UserScopedDb")
        ns = {}
        exec(compile(ast.Module(body=[cls], type_ignores=[]), "struct.py", "exec"), ns)
        self.calls = []
        rows = [{"id": f"a{i}", "user_id": "u", "created": f"2026-10-16 09:{i:02d}"} for i in range(0, 10, 2)] + \
               [{"id": f"b{i}", "user_id": "", "created": f"2026-10-16 09:{i:02d}"} for i in range(1, 10, 2)]

        calls = self.calls

        class Raw:
            def rows(self, page=None, dump=10, orderby=None, order="ASC", **where):
                calls.append({"page": page, "dump": dump})
                data = sorted([r for r in rows if r["user_id"] == where.get("user_id")],
                              key=lambda r: r[orderby], reverse=order == "DESC")
                return data[(page - 1) * dump:page * dump] if page else data

        struct = types.SimpleNamespace(_current_user_id=lambda: "u", _current_user_is_admin=lambda uid: True)
        self.db = ns["_UserScopedDb"](Raw(), struct, "trade_log")

    def test_each_query_is_limited_and_the_page_is_exact(self):
        page2 = self.db.rows(orderby="created", order="DESC", dump=3, page=2)
        self.assertEqual([r["id"] for r in page2], ["a6", "b5", "a4"])
        self.assertTrue(all(c == {"page": 1, "dump": 6} for c in self.calls))

    def test_dump_without_page_limits_in_sql(self):
        top = self.db.rows(orderby="created", order="DESC", dump=2)
        self.assertEqual([r["id"] for r in top], ["b9", "a8"])
        self.assertTrue(all(c == {"page": 1, "dump": 2} for c in self.calls))

    def test_without_orderby_nothing_changes(self):
        self.db.rows(dump=2)
        self.assertTrue(all(c["page"] is None for c in self.calls))


class JsonRowsTests(unittest.TestCase):
    class _Raw:
        def __init__(self):
            self.orm = _Log

        def _db_enter(self):
            pass

        def _db_exit(self):
            pass

        def _close_connection(self):
            pass

    def _trading(self, uid, admin):
        raw = self._Raw()
        scoped = types.SimpleNamespace(_db=raw, _uid=lambda: uid, _is_admin=lambda _u: admin)
        return types.SimpleNamespace(db=lambda _name: scoped)

    def test_admin_reads_own_and_legacy_rows_in_one_json_row(self):
        rows = api["_json_rows"](self._trading("u", True), "trade_log", ("id", "event_type"),
                                 where=api["_DT_FILL_WHERE"])
        self.assertEqual(sorted(r["id"] for r in rows), ["r0", "r1", "r5"])

    def test_regular_user_reads_only_own_rows(self):
        rows = api["_json_rows"](self._trading("u", False), "trade_log", ("id",))
        self.assertEqual(sorted(r["id"] for r in rows), ["r0", "r3"])

    def test_count_and_paging(self):
        trading = self._trading("u", True)
        self.assertEqual(api["_json_count"](trading, "trade_log"), 5)
        page = api["_json_rows"](trading, "trade_log", ("id",), limit=2, offset=2)
        self.assertEqual([r["id"] for r in page], ["r2", "r1"])


def _fill(ts, action, qty, price, **extra):
    record = {"id": f"{ts}-{action}", "timestamp": ts, "_sort": ts, "market": "KS", "symbol": "069500",
              "name": "KODEX 200", "action": action, "action_detail": extra.pop("detail", action), "qty": qty,
              "price": price, "amount": qty * price, "source": "trade_log", "strategy_id": "vrev", "message": ""}
    record.update(extra)
    return record


class ClosedTradeTests(unittest.TestCase):
    def test_average_cost_book_and_partial_exit(self):
        trips = api["_closed_trades"]([
            _fill("2026-10-16 09:00:00", "BUY", 10, 100.0),
            _fill("2026-10-16 09:10:00", "BUY", 10, 110.0),
            _fill("2026-10-16 09:30:00", "SELL", 5, 120.0, detail="SELL_DELEVERAGE"),
            _fill("2026-10-16 10:00:00", "SELL", 15, 90.0, detail="SELL_STOP_LOSS"),
        ])
        last, first = trips
        self.assertTrue(first["partial"])
        self.assertEqual(first["entry_price"], 105.0)
        self.assertEqual(first["exit_label"], "노출 축소")
        self.assertFalse(last["partial"])
        self.assertEqual(last["hold_min"], 60)
        self.assertEqual(last["exit_kind"], "stop")
        self.assertAlmostEqual(last["net"], 15 * (90 - 105) - api["_estimated_fee"]("KS", 1575, 1350), places=2)

    def test_engine_net_from_the_log_line_wins(self):
        trips = api["_closed_trades"]([
            _fill("2026-10-16 10:13:18", "BUY", 434, 71834.34),
            _fill("2026-10-16 10:28:22", "SELL", 434, 70765.0, net_realized=-528509.0, fee=64564.0),
        ])
        self.assertEqual(trips[0]["net"], -528509.0)
        self.assertEqual(trips[0]["fee"], 64564.0)
        self.assertEqual(trips[0]["return_pct"], round(-528509.0 / (71834.34 * 434) * 100, 2))

    def test_sale_beyond_recorded_buys_counts_only_known_shares(self):
        trips = api["_closed_trades"]([
            _fill("2026-09-04 09:07:03", "BUY", 629, 105000.0),
            _fill("2026-09-18 12:14:01", "SELL", 793, 109000.0, realized=999.0, fee=18_000_000.0),
        ])
        trip = trips[0]
        self.assertEqual(trip["unmatched_qty"], 164)
        self.assertEqual(trip["cost"], 629 * 105000.0)
        self.assertLess(trip["fee"], 200_000)

    def test_engine_gross_covers_missing_buys(self):
        trips = api["_closed_trades"]([
            _fill("2026-09-04 09:07:03", "BUY", 629, 105000.0),
            _fill("2026-09-18 12:14:01", "SELL", 793, 109000.0, engine_gross=2_000_000.0),
        ])
        self.assertEqual(trips[0]["unmatched_qty"], 0)
        self.assertEqual(trips[0]["cost"], 793 * 109000.0 - 2_000_000.0)

    def test_unknown_cost_is_listed_but_not_counted(self):
        trips = api["_closed_trades"]([_fill("2026-09-08 22:30:08", "SELL", 14, 126.67)])
        self.assertFalse(trips[0]["cost_known"])
        self.assertEqual(api["_trade_stats"](trips)["closed"], 0)

    def test_infinite_buy_sales_use_the_cycle_book(self):
        trips = api["_closed_trades"]([
            _fill("2026-09-01 05:00:00", "BUY", 10, 100.0, source="cycle_trade", market="US", symbol="SOXL"),
            _fill("2026-09-08 22:30:04", "SELL", 10, 120.0, source="cycle_trade", market="US", symbol="SOXL",
                  detail="INFINITE_SELL", fee=1.0, cycle_id="c1"),
        ], {"c1": {"started_at": "2026-08-31 22:00:00"}})
        self.assertEqual(trips[0]["strategy_id"], "infinite_buy")
        self.assertEqual(trips[0]["net"], 199.0)


class MergeTests(unittest.TestCase):
    def test_state_fill_replaces_a_pending_trade_log_row(self):
        pending = _fill("2026-09-30 10:40:46", "PENDING", 214, 271255.84, status="ACCEPTED_UNVERIFIED",
                        detail="SELL_STOP_LOSS_PENDING")
        fill = _fill("2026-09-30 10:40:46", "SELL", 214, 271255.84, status="FILLED", source="live_state",
                     detail="SELL_STOP_LOSS")
        merged = api["_merge_daytrade_record"](dict(pending), fill)
        self.assertEqual(merged["action"], "SELL")
        self.assertTrue(api["_is_executable_daytrade_record"](merged))


class LabelTests(unittest.TestCase):
    def test_event_labels(self):
        self.assertEqual(api["_event_label"]("DT_KS_SELL_STOP_LOSS_ERROR")[:2], ("손절 매도 거절", "error"))
        self.assertEqual(api["_event_label"]("DT_US_BUY_PENDING"), ("매수 접수", "pending", "미장 단타"))
        self.assertEqual(api["_event_label"]("IB_BUY_FILLED")[1:], ("buy", "무한매수"))
        self.assertEqual(api["_event_label"]("IB_LOC_RESERVATION_CANCELLED")[:2], ("LOC 예약 취소", "error"))

    def test_reservations_stay_visible_and_repeats_do_not(self):
        self.assertNotIn("IB_LOC_BUY_SCHEDULED", api["_SYSTEM_EVENT_TYPES"])
        self.assertIn("IB_LOC_BUY_ALREADY_SCHEDULED", api["_SYSTEM_EVENT_TYPES"])

    def test_log_line_money(self):
        text = "122630 SELL_STOP_LOSS 실행 | 손익 ₩-463,945 | 수수료 ₩64,564 | 순손익 ₩-528,509"
        self.assertEqual(api["_labeled_money"](text, "순손익"), -528509.0)
        self.assertEqual(api["_labeled_money"](text, "수수료"), 64564.0)
        self.assertEqual(api["_labeled_money"]("손익 $+1.20 | 순손익 $+0.95", "순손익"), 0.95)


if __name__ == "__main__":
    unittest.main()
