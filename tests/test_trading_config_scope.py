import builtins
import datetime
import pathlib
import sys
import time
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class _TimeStub:
    @staticmethod
    def now():
        return datetime.datetime(2026, 6, 18, 12, 0, 0)


class _SessionStub:
    current_user_id = ""

    @classmethod
    def use(cls):
        return {"id": cls.current_user_id} if cls.current_user_id else {}


class _WizStub:
    @staticmethod
    def model(name):
        if name == "portal/trading/kst":
            return _TimeStub
        if name == "portal/season/session":
            return _SessionStub
        raise AssertionError(f"unexpected wiz.model({name})")


class _ConfigDb:
    def __init__(self, store):
        self.store = store
        self.next_id = 1

    def rows(self, dump=1000):
        return [dict(row) for row in self.store.values()]

    def get(self, key=None, id=None):
        if key is not None:
            row = self.store.get(key)
            return dict(row) if row else None
        for row in self.store.values():
            if row.get("id") == id:
                return dict(row)
        return None

    def insert(self, row):
        row = dict(row)
        row.setdefault("id", f"cfg-{self.next_id}")
        self.next_id += 1
        self.store[row["key"]] = row
        return row["id"]

    def update(self, fields, id=None):
        for key, row in self.store.items():
            if row.get("id") == id:
                row.update(fields)
                self.store[key] = row
                return


class _UserDb:
    def __init__(self, users):
        self.users = users

    def get(self, id=None):
        user = self.users.get(id)
        return dict(user) if user else None


class _RowsDb:
    def __init__(self, rows=None):
        self.rows_data = [dict(row) for row in (rows or [])]

    def rows(self, **kwargs):
        controls = {"orderby", "order", "page", "dump"}
        data = []
        for row in self.rows_data:
            matched = True
            for key, value in kwargs.items():
                if key in controls:
                    continue
                if row.get(key) != value:
                    matched = False
                    break
            if matched:
                data.append(dict(row))
        orderby = kwargs.get("orderby")
        if orderby:
            data.sort(key=lambda row: row.get(orderby), reverse=str(kwargs.get("order", "ASC")).upper() == "DESC")
        dump = int(kwargs.get("dump", 0) or 0)
        return data[:dump] if dump else data

    def get(self, **kwargs):
        rows = self.rows(**kwargs)
        return rows[0] if rows else None

    def insert(self, row):
        row = dict(row)
        row.setdefault("id", f"row-{len(self.rows_data) + 1}")
        self.rows_data.append(row)
        return row["id"]

    def update(self, data, id=None, **kwargs):
        for row in self.rows_data:
            if id is not None and row.get("id") != id:
                continue
            if all(row.get(key) == value for key, value in kwargs.items()):
                row.update(dict(data))

    def delete(self, id=None, **kwargs):
        kept = []
        for row in self.rows_data:
            if id is not None and row.get("id") != id:
                kept.append(row)
                continue
            if kwargs and not all(row.get(key) == value for key, value in kwargs.items()):
                kept.append(row)
        self.rows_data = kept


class _OrmStub:
    def __init__(self, config_store, users):
        self.config_db = _ConfigDb(config_store)
        self.user_db = _UserDb(users)

    def use(self, name, module=None):
        if name == "trading_config":
            return self.config_db
        if name == "user":
            return self.user_db
        raise AssertionError(f"unexpected orm.use({name})")


builtins.wiz = _WizStub()
struct_path = SRC / "portal" / "trading" / "model" / "struct.py"
trading_struct = types.ModuleType("trading_struct_under_test")
trading_struct.__dict__["wiz"] = _WizStub()
source = struct_path.read_text(encoding="utf-8").replace("\nModel = Struct()\n", "\nModel = None\n")
exec(compile(source, str(struct_path), "exec"), trading_struct.__dict__)


class TradingConfigScopeTests(unittest.TestCase):
    def setUp(self):
        _SessionStub.current_user_id = ""
        trading_struct.Struct._cfg = {}
        trading_struct.Struct._cfg_ready = False
        self.config_store = {
            "kis_app_key": {"id": "legacy-kis", "key": "kis_app_key", "value": "legacy-key"},
        }
        self.users = {
            "admin": {"id": "admin", "email": "admin@example.com", "role": "admin"},
            "user": {"id": "user", "email": "user@example.com", "role": "user"},
        }
        self.struct = object.__new__(trading_struct.Struct)
        self.struct.orm = _OrmStub(self.config_store, self.users)
        self.struct._kis_api_obj = object()
        self.struct._toss_api_obj = object()
        state = self.struct._worker_state()
        for key in list(state.keys()):
            if key.startswith("loc_reservation_verified"):
                state.pop(key, None)

    def test_regular_user_does_not_read_legacy_api_key(self):
        _SessionStub.current_user_id = "user"

        self.assertEqual(self.struct.get_config("kis_app_key", ""), "")
        self.assertNotIn("user:user:kis_app_key", self.config_store)

    def test_admin_adopts_legacy_api_key_into_user_scope(self):
        _SessionStub.current_user_id = "admin"

        self.assertEqual(self.struct.get_config("kis_app_key", ""), "legacy-key")
        self.assertEqual(self.config_store["user:admin:kis_app_key"]["value"], "legacy-key")

    def test_regular_user_writes_only_user_scoped_api_key(self):
        _SessionStub.current_user_id = "user"

        self.struct.set_config("kis_app_key", "user-key", "KIS App Key", True)

        self.assertEqual(self.config_store["user:user:kis_app_key"]["value"], "user-key")
        self.assertEqual(self.config_store["kis_app_key"]["value"], "legacy-key")

    def test_background_without_session_reads_legacy_key(self):
        _SessionStub.current_user_id = ""

        self.assertEqual(self.struct.get_config("kis_app_key", ""), "legacy-key")

    def test_regular_user_cannot_read_legacy_portfolio_rows(self):
        _SessionStub.current_user_id = "user"
        db = trading_struct._UserScopedDb(_RowsDb([
            {"id": "legacy", "symbol": "SOXL", "user_id": ""},
            {"id": "mine", "symbol": "TQQQ", "user_id": "user"},
            {"id": "other", "symbol": "TQQQ", "user_id": "other"},
        ]), self.struct, "etf_watchlist")

        self.assertEqual([row["id"] for row in db.rows(orderby="id")], ["mine"])
        self.assertIsNone(db.get(id="legacy"))
        self.assertEqual(db.get(symbol="TQQQ")["id"], "mine")

    def test_admin_can_read_legacy_and_own_portfolio_rows(self):
        _SessionStub.current_user_id = "admin"
        db = trading_struct._UserScopedDb(_RowsDb([
            {"id": "legacy", "symbol": "SOXL", "user_id": ""},
            {"id": "mine", "symbol": "TQQQ", "user_id": "admin"},
            {"id": "other", "symbol": "TQQQ", "user_id": "other"},
        ]), self.struct, "etf_watchlist")

        self.assertEqual([row["id"] for row in db.rows(orderby="id")], ["legacy", "mine"])

    def test_scoped_insert_and_cross_user_update_guard(self):
        _SessionStub.current_user_id = "user"
        raw = _RowsDb([{"id": "other", "symbol": "SOXL", "user_id": "other"}])
        db = trading_struct._UserScopedDb(raw, self.struct, "etf_watchlist")

        row_id = db.insert({"symbol": "TQQQ"})

        self.assertEqual(raw.get(id=row_id)["user_id"], "user")
        with self.assertRaises(Exception):
            db.update({"symbol": "SOXL2"}, id="other")

    def test_kis_loc_reservation_window_opens_at_10_and_uses_summer_cutoff(self):
        self.assertFalse(trading_struct._loc_reservation_window_open(datetime.datetime(2026, 6, 25, 9, 59)))
        self.assertTrue(trading_struct._loc_reservation_window_open(datetime.datetime(2026, 6, 25, 10, 0)))
        self.assertEqual(trading_struct._loc_reservation_cutoff_hhmm(datetime.datetime(2026, 6, 25, 12, 0)), 2220)
        self.assertTrue(trading_struct._loc_reservation_window_open(datetime.datetime(2026, 6, 25, 22, 20)))
        self.assertFalse(trading_struct._loc_reservation_window_open(datetime.datetime(2026, 6, 25, 22, 21)))
        self.assertEqual(trading_struct._loc_reservation_window_label(datetime.datetime(2026, 6, 25, 12, 0)), "10:00-22:20 KST")

    def test_kis_loc_reservation_window_uses_standard_cutoff_outside_summer_time(self):
        self.assertEqual(trading_struct._loc_reservation_cutoff_hhmm(datetime.datetime(2026, 12, 1, 12, 0)), 2320)
        self.assertTrue(trading_struct._loc_reservation_window_open(datetime.datetime(2026, 12, 1, 23, 20)))
        self.assertFalse(trading_struct._loc_reservation_window_open(datetime.datetime(2026, 12, 1, 23, 21)))
        self.assertEqual(trading_struct._loc_reservation_window_label(datetime.datetime(2026, 12, 1, 12, 0)), "10:00-23:20 KST")

    def test_loc_reservation_verification_requires_three_identical_broker_echoes(self):
        state = self.struct._worker_state()
        for key in list(state.keys()):
            if key.startswith("loc_reservation_verified"):
                state.pop(key, None)

        buy = {
            "status": "completed",
            "scheduled_count": 0,
            "already_scheduled_count": 1,
            "skipped_count": 0,
            "error_count": 0,
            "expected_count": 1,
            "satisfied_count": 1,
            "missing_count": 0,
            "force_rebuild_count": 0,
            "expected": [{
                "symbol": "TQQQ",
                "exchange": "NASD",
                "order_type": "LOC",
                "order_qty": 4,
                "price": 79.61,
            }],
        }
        sell = {
            "status": "completed",
            "scheduled_count": 0,
            "already_scheduled_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "expected_count": 0,
            "satisfied_count": 0,
            "missing_count": 0,
            "force_rebuild_count": 0,
            "expected": [],
        }

        first = self.struct._record_loc_reservation_verification("2026-06-25", buy, sell, {}, verify_only=True)
        for key in list(state.keys()):
            if key.startswith("loc_reservation_verified"):
                state.pop(key, None)
        second = self.struct._record_loc_reservation_verification("2026-06-25", buy, sell, {}, verify_only=True)
        for key in list(state.keys()):
            if key.startswith("loc_reservation_verified"):
                state.pop(key, None)
        third = self.struct._record_loc_reservation_verification("2026-06-25", buy, sell, {}, verify_only=True)

        self.assertEqual(first["streak"], 1)
        self.assertFalse(first["complete"])
        self.assertEqual(second["streak"], 2)
        self.assertFalse(second["complete"])
        self.assertEqual(third["streak"], 3)
        self.assertTrue(third["complete"])
        self.assertTrue(self.struct._loc_reservation_verified_done("2026-06-25"))

    def test_loc_reservation_verification_resets_when_new_order_was_submitted(self):
        state = self.struct._worker_state()
        for key in list(state.keys()):
            if key.startswith("loc_reservation_verified"):
                state.pop(key, None)

        buy = {
            "status": "completed",
            "scheduled_count": 1,
            "already_scheduled_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "expected_count": 1,
            "satisfied_count": 1,
            "missing_count": 0,
            "force_rebuild_count": 0,
            "expected": [{
                "symbol": "SOXL",
                "exchange": "NASD",
                "order_type": "LIMIT",
                "order_qty": 1,
                "price": 229.78,
            }],
        }
        sell = {
            "status": "completed",
            "scheduled_count": 0,
            "already_scheduled_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "expected_count": 0,
            "satisfied_count": 0,
            "missing_count": 0,
            "force_rebuild_count": 0,
            "expected": [],
        }

        result = self.struct._record_loc_reservation_verification("2026-06-25", buy, sell, {}, verify_only=True)

        self.assertFalse(result["passed"])
        self.assertFalse(result["complete"])
        self.assertIn("scheduled_count=1", result["reason"])

    def test_recent_reservation_rebuild_cooldown_blocks_immediate_rebuild_loop(self):
        class _Engine:
            def __init__(self):
                self.rebuild_calls = []
                self.buy_schedule_calls = 0
                self.sell_schedule_calls = 0

            def _load_kis_api(self):
                return object()

            def schedule_loc_buys(self):
                self.buy_schedule_calls += 1
                return {
                    "status": "partial_pending",
                    "scheduled_count": 0,
                    "already_scheduled_count": 0,
                    "skipped_count": 0,
                    "error_count": 0,
                    "expected_count": 1,
                    "satisfied_count": 0,
                    "missing_count": 1,
                    "force_rebuild_count": 0,
                    "missing": [{"symbol": "TQQQ"}],
                    "expected": [{"symbol": "TQQQ", "exchange": "NASD", "order_type": "LOC", "order_qty": 1, "price": 79.61}],
                }

            def schedule_loc_sells(self):
                self.sell_schedule_calls += 1
                return {
                    "status": "completed",
                    "scheduled_count": 0,
                    "already_scheduled_count": 0,
                    "skipped_count": 0,
                    "error_count": 0,
                    "expected_count": 0,
                    "satisfied_count": 0,
                    "missing_count": 0,
                    "force_rebuild_count": 0,
                    "expected": [],
                }

            def rebuild_loc_reservations(self, symbols=None):
                self.rebuild_calls.append(list(symbols or []))
                return {"status": "completed", "cancel": {"cancelled_count": 1}, "buy": {}, "sell": {}}

            def _log_event(self, *args, **kwargs):
                return None

        engine = _Engine()
        self.struct._engine_obj = engine
        self.struct.run_due_external_cycle_sync = lambda force=False: {"executed": False}
        self.struct.run_due_firegate_sync = lambda: {"executed": False}
        self.struct.set_config("auto_trade_enabled", "true")
        self.struct._set_loc_reservation_rebuild_cooldown("test_recent_schedule")

        held = self.struct.run_due_loc_automation(verify=True, reason="10min_reservation_verify")

        self.assertEqual(engine.rebuild_calls, [])
        self.assertEqual(engine.buy_schedule_calls, 0)
        self.assertEqual(engine.sell_schedule_calls, 0)
        self.assertFalse(held["rebuild"]["executed"])
        self.assertTrue(held["rebuild"]["cooldown"])
        self.assertEqual(held["status"], "cooldown_wait")

        self.struct.set_config("loc_reservation_rebuild_cooldown_until_ts", str(time.time() - 1))
        retried = self.struct.run_due_loc_automation(verify=True, reason="10min_reservation_verify")

        self.assertEqual(engine.buy_schedule_calls, 1)
        self.assertEqual(engine.sell_schedule_calls, 1)
        self.assertEqual(engine.rebuild_calls, [["TQQQ"]])
        self.assertTrue(retried["rebuild"]["executed"])

    def test_newly_submitted_clean_reservations_keep_cooldown_for_broker_echo(self):
        class _Engine:
            def __init__(self):
                self.buy_schedule_calls = 0

            def _load_kis_api(self):
                return object()

            def schedule_loc_buys(self):
                self.buy_schedule_calls += 1
                return {
                    "status": "completed",
                    "scheduled_count": 1,
                    "already_scheduled_count": 0,
                    "skipped_count": 0,
                    "error_count": 0,
                    "expected_count": 1,
                    "satisfied_count": 1,
                    "missing_count": 0,
                    "force_rebuild_count": 0,
                    "expected": [{"symbol": "SOXL", "exchange": "AMEX", "order_type": "LOC", "order_qty": 1, "price": 192.41}],
                    "orders": [{"symbol": "SOXL", "price": 192.41, "order_type": "LOC"}],
                }

            def schedule_loc_sells(self):
                return {
                    "status": "completed",
                    "scheduled_count": 0,
                    "already_scheduled_count": 0,
                    "skipped_count": 0,
                    "error_count": 0,
                    "expected_count": 0,
                    "satisfied_count": 0,
                    "missing_count": 0,
                    "force_rebuild_count": 0,
                    "expected": [],
                }

            def rebuild_loc_reservations(self, symbols=None):
                raise AssertionError("clean new reservations should not rebuild")

            def _log_event(self, *args, **kwargs):
                return None

        engine = _Engine()
        self.struct._engine_obj = engine
        self.struct.run_due_external_cycle_sync = lambda force=False: {"executed": False}
        self.struct.run_due_firegate_sync = lambda: {"executed": False}
        self.struct.set_config("auto_trade_enabled", "true")

        first = self.struct.run_due_loc_automation(verify=True, reason="10min_reservation_verify")
        second = self.struct.run_due_loc_automation(verify=True, reason="10min_reservation_verify")

        self.assertEqual(engine.buy_schedule_calls, 1)
        self.assertEqual(first["buy"]["scheduled_count"], 1)
        self.assertGreater(self.struct._loc_reservation_rebuild_cooldown_remaining(), 0)
        self.assertEqual(second["status"], "cooldown_wait")
        self.assertFalse(second["buy"]["scheduled"])

    def test_force_rebuild_bypasses_new_order_cooldown_in_same_run(self):
        class _Engine:
            def __init__(self):
                self.rebuild_calls = []

            def _load_kis_api(self):
                return object()

            def schedule_loc_buys(self):
                return {
                    "status": "partial_pending",
                    "scheduled_count": 1,
                    "already_scheduled_count": 0,
                    "skipped_count": 1,
                    "error_count": 0,
                    "expected_count": 2,
                    "satisfied_count": 1,
                    "missing_count": 1,
                    "force_rebuild_count": 1,
                    "orders": [{"symbol": "SOXL", "price": 192.41, "order_type": "LOC"}],
                    "skipped": [{"symbol": "TQQQ", "force_rebuild": True}],
                    "expected": [
                        {"symbol": "SOXL", "exchange": "AMEX", "order_type": "LOC", "order_qty": 1, "price": 192.41},
                        {"symbol": "TQQQ", "exchange": "NASD", "order_type": "LOC", "order_qty": 1, "price": 43.62},
                    ],
                }

            def schedule_loc_sells(self):
                return {
                    "status": "completed",
                    "scheduled_count": 0,
                    "already_scheduled_count": 0,
                    "skipped_count": 0,
                    "error_count": 0,
                    "expected_count": 0,
                    "satisfied_count": 0,
                    "missing_count": 0,
                    "force_rebuild_count": 0,
                    "expected": [],
                }

            def rebuild_loc_reservations(self, symbols=None):
                self.rebuild_calls.append(list(symbols or []))
                return {"status": "completed", "cancel": {"cancelled_count": 2}, "buy": {}, "sell": {}}

            def _log_event(self, *args, **kwargs):
                return None

        engine = _Engine()
        self.struct._engine_obj = engine
        self.struct.run_due_external_cycle_sync = lambda force=False: {"executed": False}
        self.struct.run_due_firegate_sync = lambda: {"executed": False}
        self.struct.set_config("auto_trade_enabled", "true")

        result = self.struct.run_due_loc_automation(verify=True, reason="10min_reservation_verify")

        self.assertTrue(result["rebuild"]["executed"])
        self.assertEqual(engine.rebuild_calls, [["SOXL", "TQQQ"]])


if __name__ == "__main__":
    unittest.main()
