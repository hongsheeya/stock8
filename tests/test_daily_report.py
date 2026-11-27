"""Daily report (11-27): one status per lane and why, for LIVE and PAPER.

Built on temp SQLite files and temp runtime JSON. The report must only read:
a failed read is 확인 불가, never 0 or normal.
"""
import ast
import datetime
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "src/portal/trading/model/daily_report.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report = _load("t_daily_report", MODEL)
domestic = _load("t_daily_report_domestic", ROOT / "src/portal/trading/model/domestic_market.py")


def _kis_constants():
    tree = ast.parse((ROOT / "src/portal/trading/model/struct/kis_api.py").read_text(encoding="utf-8"))
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "KisApi":
            for item in node.body:
                if isinstance(item, ast.Assign) and getattr(item.targets[0], "id", "") in ("US_MARKET_HOLIDAYS", "US_EARLY_CLOSES"):
                    found[item.targets[0].id] = ast.literal_eval(item.value)
    return found


KIS = _kis_constants()
UID = "user-7f3a9c"
DAY = datetime.date(2026, 11, 27)            # Friday; US 11-26 Thanksgiving, 11-27 early close
NOW = datetime.datetime(2026, 11, 27, 15, 40)
LIVE_ACCOUNT = "12345678-01"
PAPER_ACCOUNT = "50000000-01"


def _h(text, n):
    return hashlib.sha256(text.encode()).hexdigest()[:n]


LIVE_SCOPE = _h("kis:" + LIVE_ACCOUNT, 24)
PAPER_SCOPE = _h("kis:" + PAPER_ACCOUNT, 24)
LIVE_POLICY = "order_policy_v1:" + _h("kis:" + LIVE_ACCOUNT, 40)
PAPER_POLICY = "order_policy_v1:" + _h("kis:" + PAPER_ACCOUNT, 40)

_SCHEMA = """
CREATE TABLE trading_config (id TEXT PRIMARY KEY, key TEXT UNIQUE, value TEXT DEFAULT '', description TEXT DEFAULT '',
                             is_secret INTEGER DEFAULT 0, created TEXT, updated TEXT);
CREATE TABLE trade_log (id TEXT PRIMARY KEY, user_id TEXT DEFAULT '', cycle_id TEXT DEFAULT '', symbol TEXT,
                        event_type TEXT, action TEXT DEFAULT '', order_no TEXT DEFAULT '', order_price REAL DEFAULT 0,
                        order_qty INTEGER DEFAULT 0, filled_price REAL, filled_qty INTEGER DEFAULT 0,
                        message TEXT DEFAULT '', raw_response TEXT DEFAULT '', created TEXT);
CREATE TABLE trading_cycle (id TEXT PRIMARY KEY, user_id TEXT DEFAULT '', symbol TEXT, cycle_number INTEGER,
                            status TEXT, current_round INTEGER, division_count INTEGER, total_qty INTEGER,
                            avg_price REAL, updated TEXT);
"""


def log(event, created, message="", symbol="X", action="", filled_qty=0, filled_price=None, order_no="",
        order_qty=0, order_price=0, raw="", user=UID):
    return {"user_id": user, "symbol": symbol, "event_type": event, "action": action, "order_no": order_no,
            "order_price": order_price, "order_qty": order_qty, "filled_price": filled_price,
            "filled_qty": filled_qty, "message": message, "raw_response": raw, "created": created}


def rt(timestamp, message, level="info", symbol=""):
    return {"timestamp": timestamp, "level": level, "message": message, "symbol": symbol, "market": "KS",
            "strategy_id": "vrev", "meta": {}}


class Env:
    """Temp server root with both trading.db files and the runtime folders."""

    def __init__(self, test):
        self.root = tempfile.mkdtemp(prefix="stock8-report-")
        test.addCleanup(shutil.rmtree, self.root, True)
        self.data = os.path.join(self.root, "project", "main", "data")
        self.paths = {m: os.path.join(self.data, m.lower(), "trading.db") for m in ("LIVE", "PAPER")}
        self.config = {
            "LIVE": {
                f"user:{UID}:kis_live_account_no": LIVE_ACCOUNT, f"user:{UID}:broker_provider": "kis",
                f"user:{UID}:daytrade_feature_enabled": "true", f"user:{UID}:daytrade_auto_enabled": "true",
                f"user:{UID}:auto_trade_enabled": "true", f"user:{UID}:loc_auto_schedule_enabled": "true",
                LIVE_POLICY: json.dumps({"infinite_buy": True, "daytrade_ks": True, "daytrade_us": False,
                                         "symbols": {}, "owner_user_id": UID}),
            },
            "PAPER": {
                f"user:{UID}:kis_paper_account_no": PAPER_ACCOUNT, f"user:{UID}:daytrade_auto_enabled": "true",
                f"user:{UID}:daytrade_us_auto_enabled": "true", f"user:{UID}:auto_trade_enabled": "true",
                "paper_worker_owner_user_id": UID,
            },
        }
        self.logs = {"LIVE": [], "PAPER": []}
        self.cycles = {"LIVE": [], "PAPER": []}
        self.skip_db = set()
        # A quiet runtime log covering the whole day for every day-trade lane,
        # and a PAPER worker that ticked a minute before NOW.
        for mode in ("LIVE", "PAPER"):
            for name in ("runtime_logs_ks.json", "runtime_logs_us.json"):
                self.runtime(mode, name, [rt("2026-11-26 23:00:00", "어제"), rt("2026-11-27 08:00:00", "자동청산 감시 대상이 없습니다.")])
        self.worker("2026-11-27 15:39:00")

    def worker(self, last_run_at, result=None):
        self.file("paper/daytrade/worker_status.json", {"last_run_at": last_run_at, "result": result if result is not None else {
            "auto_cycle": {"message": "국내 주식 시장이 열려있지 않습니다."}, "exit_watch": {"message": "국장 종료"},
            "us_auto_cycle": {"message": "미국 주식 시장이 열려있지 않습니다."},
            "loc_automation": {"status": "waiting", "message": "모의 LOC 대체 대기"}}})

    def dt_root(self, mode):
        if mode == "LIVE":
            return os.path.join(self.data, "live", "daytrade", LIVE_SCOPE)
        return os.path.join(self.data, "paper", "daytrade")

    def runtime(self, mode, name, entries, raw_text=None):
        folder = self.dt_root(mode)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
            handle.write(raw_text if raw_text is not None else json.dumps(entries, ensure_ascii=False))

    def remove_runtime(self, mode, name):
        os.remove(os.path.join(self.dt_root(mode), name))

    def file(self, rel, payload):
        path = os.path.join(self.data, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False))
        return path

    def write(self):
        for mode, path in self.paths.items():
            if mode in self.skip_db:
                continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.exists(path):
                os.remove(path)
            db = sqlite3.connect(path)
            db.executescript(_SCHEMA)
            for i, (key, value) in enumerate(self.config[mode].items()):
                secret = key.endswith(("account_no",))
                db.execute("INSERT INTO trading_config(id, key, value, is_secret) VALUES (?,?,?,?)", (f"c{i}", key, value, int(secret)))
            for i, row in enumerate(self.logs[mode]):
                db.execute("INSERT INTO trade_log(id, user_id, symbol, event_type, action, order_no, order_price, order_qty, "
                           "filled_price, filled_qty, message, raw_response, created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (f"l{i}", row["user_id"], row["symbol"], row["event_type"], row["action"], row["order_no"],
                            row["order_price"], row["order_qty"], row["filled_price"], row["filled_qty"], row["message"],
                            row["raw_response"], row["created"]))
            for i, row in enumerate(self.cycles[mode]):
                db.execute("INSERT INTO trading_cycle(id, user_id, symbol, cycle_number, status, current_round, division_count, "
                           "total_qty, avg_price, updated) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (f"y{i}", row.get("user_id", UID), row["symbol"], 1, row["status"], 3, 40, row["qty"], 10.0, "2026-11-27"))
            db.commit()
            db.close()

    def build(self, uid=UID, is_admin=True, day=DAY, now=NOW, server_mode="PAPER", decrypt=None, **extra):
        self.write()
        return report.build_report(
            uid, day, now=now, is_admin=is_admin, server_mode=server_mode, db_paths=self.paths, data_dir=self.data,
            decrypt=decrypt, krx_holidays=domestic.KRX_HOLIDAYS, us_holidays=KIS["US_MARKET_HOLIDAYS"],
            us_early_closes=KIS["US_EARLY_CLOSES"], **extra)


def lane(result, key):
    for item in result["lanes"]:
        if item["key"] == key:
            return item
    raise AssertionError(f"{key} not in {[l['key'] for l in result['lanes']]}")


class StatusRuleTests(unittest.TestCase):
    def test_live_ks_entry_block_all_day_is_blocked(self):
        env = Env(self)
        entries = [rt("2026-11-26 23:00:00", "어제")]
        for minute in range(70):
            stamp = (datetime.datetime(2026, 11, 27, 9, 1) + datetime.timedelta(minutes=5 * minute)).strftime("%Y-%m-%d %H:%M:%S")
            entries.append(rt(stamp, "단타 신규 진입 차단 (KS): 학습·검증을 통과한 후보가 없습니다.", level="warning"))
        env.runtime("LIVE", "runtime_logs_ks.json", entries)
        item = lane(env.build(), "daytrade_ks:LIVE")
        self.assertEqual(item["status"], report.BLOCKED)
        self.assertIn("학습·검증을 통과한 후보가 없습니다", item["reason"])
        self.assertIn("×70", item["reason"])
        self.assertEqual((item["buys"], item["sells"]), (0, 0))

    def test_single_entry_block_with_buys_is_running_but_three_are_blocked(self):
        env = Env(self)
        env.logs["PAPER"] = [log("DT_KS_BUY1", "2026-11-27 10:00:00", "A BUY1 실행", symbol="A", action="BUY",
                                 filled_qty=1, filled_price=100, order_no="1")]
        block = "단타 신규 진입 차단 (KS): 예산 소진"
        env.runtime("PAPER", "runtime_logs_ks.json", [rt("2026-11-26 23:00:00", "어제"), rt("2026-11-27 11:00:00", block, "warning")])
        item = lane(env.build(), "daytrade_ks:PAPER")
        self.assertEqual(item["status"], report.RUNNING)
        self.assertTrue(any("일시적" in n for n in item["notes"]))
        env.runtime("PAPER", "runtime_logs_ks.json", [rt("2026-11-26 23:00:00", "어제")] +
                    [rt(f"2026-11-27 11:0{i}:00", block, "warning") for i in range(3)])
        self.assertEqual(lane(env.build(), "daytrade_ks:PAPER")["status"], report.BLOCKED)

    def test_live_infinite_buy_firegate_blocks(self):
        env = Env(self)
        env.cycles["LIVE"] = [{"symbol": "SOXL", "status": "ACTIVE", "qty": 165}]
        for day in ("2026-11-22", "2026-11-25", "2026-11-27"):
            env.logs["LIVE"] += [
                log("IB_LOC_BUY_FIREGATE_AUTHORITY_BLOCKED", f"{day} 14:00:42", "FireGate 연결 대상 사이클이 달라 적용하지 않았습니다.", "SOXL", "BUY"),
                log("IB_LOC_SELL_FIREGATE_AUTHORITY_BLOCKED", f"{day} 14:00:44", "FireGate 연결 대상 사이클이 달라 적용하지 않았습니다.", "SOXL", "SELL"),
                log("IB_FIREGATE_LINK_MISMATCH", f"{day} 00:03:38", "FireGate 포트폴리오 연결 불일치", "SOXL",
                    raw=json.dumps({"repeat": 5, "last_at": f"{day} 15:33:00"})),
            ]
        item = lane(env.build(), "infinite_buy:LIVE")
        self.assertEqual(item["status"], report.BLOCKED)
        self.assertIn("SOXL", item["reason"])
        self.assertIn("FireGate 권한 차단", item["reason"])
        self.assertIn("3일 발생 (처음 11/22)", item["reason"])
        mismatch = [p for p in item["problems"] if "연결 불일치" in p["message"]][0]
        self.assertEqual((mismatch["count"], mismatch["first_hhmm"], mismatch["last_hhmm"]), (5, "00:03", "15:33"))
        self.assertEqual(item["positions"][0]["symbol"], "SOXL")

    def test_live_us_order_policy_lane_false_is_off(self):
        env = Env(self)
        env.config["LIVE"][f"user:{UID}:daytrade_us_auto_enabled"] = "true"
        item = lane(env.build(), "daytrade_us:LIVE")
        self.assertEqual(item["status"], report.OFF)
        self.assertIn("daytrade_us=false", item["reason"])

    def test_live_policy_missing_is_off_and_corrupt_policy_is_blocked(self):
        env = Env(self)
        del env.config["LIVE"][LIVE_POLICY]
        item = lane(env.build(), "infinite_buy:LIVE")
        self.assertEqual(item["status"], report.OFF)
        self.assertIn("주문 정책이 없습니다", item["reason"])
        env = Env(self)
        env.config["LIVE"][LIVE_POLICY] = "{not json"
        self.assertEqual(lane(env.build(), "daytrade_ks:LIVE")["status"], report.BLOCKED)

    def test_paper_us_repeated_error_is_blocked_with_group_and_holiday_note(self):
        env = Env(self)
        start = datetime.datetime(2026, 11, 27, 0, 11, 34)
        for i in range(41):
            created = start + datetime.timedelta(seconds=int(i * (5 * 3600 + 26 * 60) / 40))
            env.logs["PAPER"].append(log("DT_US_BUY_ERROR", created.strftime("%Y-%m-%d %H:%M:%S"),
                                         "매수 주문 실패 [RIVN]: 모의투자 영업일이 아닙니다. (rt_cd=1, exchange=NASD, qty=52, price=11.83, ord_dvsn=00)",
                                         "RIVN", "ERROR", order_qty=52))
        item = lane(env.build(), "daytrade_us:PAPER")
        self.assertEqual(item["status"], report.BLOCKED)
        self.assertEqual(item["reason"], "매수 주문 실패 [RIVN]: 모의투자 영업일이 아닙니다. ×41 (00:11~05:37)")
        self.assertEqual((item["buys"], item["sells"]), (0, 0))
        self.assertTrue(any("Thanksgiving" in n for n in item["notes"]))

    def test_paper_ks_fills_are_running_and_pending_row_is_not_a_fill(self):
        env = Env(self)
        env.logs["PAPER"] = [
            log("DT_KS_BUY1_PENDING", "2026-11-27 09:30:07", "233740 BUY1 주문 접수", "233740", "PENDING", order_no="9", order_qty=402),
            log("DT_KS_BUY1", "2026-11-27 09:30:37", "233740 BUY1 실행", "233740", "BUY", 402, 4080.06, "9", 402),
            log("DT_KS_SELL_FULL", "2026-11-27 15:11:47", "233740 SELL_FULL 실행 | 손익 ₩+186,905 | 수수료 ₩520 | 순손익 ₩+186,385",
                "233740", "SELL", 402, 4545.0, "10", 402),
            log("DT_KS_SELL_FULL", "2026-11-27 15:12:06", "488080 SELL_FULL 실행 | 손익 ₩+20,790",
                "488080", "SELL", 42, 13240.0, "11", 42, raw=json.dumps({"runtime": {"realized": 20627}})),
            log("DT_KS_BUY", "2026-11-26 10:00:00", "어제 매수", "1", "BUY", 1, 1.0, "12"),
        ]
        item = lane(env.build(), "daytrade_ks:PAPER")
        self.assertEqual(item["status"], report.RUNNING)
        self.assertEqual((item["buys"], item["sells"]), (1, 2))
        self.assertEqual(item["realized"], 186385 + 20627)
        self.assertEqual([o["label"] for o in item["orders"]], ["1차 매수 접수"])

    def test_paper_account_unavailable_blocks_paper_lanes(self):
        env = Env(self)
        env.config["PAPER"][f"user:{UID}:kis_paper_account_unavailable_at"] = "2026-11-17T09:00:00"
        env.config["PAPER"][f"user:{UID}:kis_paper_account_unavailable_reason"] = "모의투자 신청내역을 확인하세요"
        env.cycles["PAPER"] = [{"symbol": "TQQQ", "status": "ACTIVE", "qty": 3}]
        result = env.build()
        for key in ("daytrade_ks:PAPER", "daytrade_us:PAPER", "infinite_buy:PAPER"):
            self.assertEqual(lane(result, key)["status"], report.BLOCKED, key)
            self.assertIn("모의계좌 사용 불가", lane(result, key)["reason"])
        self.assertEqual(result["safety"]["PAPER"]["paper_unavailable"]["since"], "2026-11-17T09:00:00")
        # A flag set after the chosen day does not rewrite that day.
        past = env.build(day=datetime.date(2026, 11, 16))
        self.assertNotIn("모의계좌 사용 불가", lane(past, "daytrade_ks:PAPER")["reason"])

    def test_account_halt_in_runtime_log_is_blocked(self):
        env = Env(self)
        env.runtime("PAPER", "runtime_logs_ks.json", [rt("2026-11-26 23:00:00", "어제"), rt(
            "2026-11-27 09:31:00", "A 주문 차단: KIS가 계좌 주문을 거부해 자동 주문을 정지했습니다 (09:30부터)", "warning")])
        item = lane(env.build(), "daytrade_ks:PAPER")
        self.assertEqual(item["status"], report.BLOCKED)
        self.assertIn("계좌 거부", item["reason"])

    def test_repeat_counter_counts_towards_three(self):
        env = Env(self)
        env.cycles["PAPER"] = [{"symbol": "TQQQ", "status": "ACTIVE", "qty": 3}]
        env.logs["PAPER"] = [log("IB_LOC_BUY_ERROR", "2026-11-27 10:00:00", "LOC 매수 예약 실패", "TQQQ",
                                 raw=json.dumps({"repeat": 3, "last_at": "2026-11-27 10:20:00"}))]
        item = lane(env.build(), "infinite_buy:PAPER")
        self.assertEqual(item["status"], report.BLOCKED)
        self.assertIn("×3 (10:00~10:20)", item["reason"])
        env.logs["PAPER"] = [log("IB_LOC_BUY_ERROR", "2026-11-27 10:00:00", "LOC 매수 예약 실패", "TQQQ")]
        self.assertEqual(lane(env.build(), "infinite_buy:PAPER")["status"], report.WAITING)

    def test_waiting_after_close_and_on_weekend(self):
        env = Env(self)
        item = lane(env.build(), "daytrade_ks:PAPER")
        self.assertEqual(item["status"], report.WAITING)
        self.assertIn("장 마감", item["reason"])
        sunday = lane(env.build(day=datetime.date(2026, 11, 22)), "daytrade_ks:PAPER")
        self.assertEqual(sunday["status"], report.WAITING)
        self.assertIn("주말", sunday["reason"])
        self.assertEqual(lane(env.build(), "infinite_buy:PAPER")["reason"], "운영 중인 사이클이 없습니다")

    def test_switch_off_is_off(self):
        env = Env(self)
        env.config["PAPER"][f"user:{UID}:daytrade_auto_enabled"] = "false"
        env.config["PAPER"][f"user:{UID}:auto_trade_enabled"] = "false"
        result = env.build()
        self.assertEqual(lane(result, "daytrade_ks:PAPER")["status"], report.OFF)
        self.assertEqual(lane(result, "infinite_buy:PAPER")["status"], report.OFF)
        self.assertIn("auto_trade_enabled", lane(result, "infinite_buy:PAPER")["reason"])


class UnknownTests(unittest.TestCase):
    def test_missing_db_is_unknown_never_zero(self):
        env = Env(self)
        env.skip_db.add("LIVE")
        result = env.build(server_mode="PAPER")
        for key in ("daytrade_ks:LIVE", "daytrade_us:LIVE", "infinite_buy:LIVE", "coin:LIVE"):
            item = lane(result, key)
            self.assertEqual(item["status"], report.UNKNOWN, key)
            self.assertEqual((item["buys"], item["sells"], item["realized"]), (None, None, None))
            self.assertIn("DB 파일이 없습니다", item["reason"])
        self.assertFalse(result["sources"]["LIVE"]["ok"])
        self.assertFalse(result["safety"]["LIVE"]["ok"])
        self.assertTrue(any("LIVE 데이터를 읽지 못해" in n for n in result["notes"]))
        self.assertEqual(lane(result, "daytrade_ks:PAPER")["status"], report.WAITING)
        self.assertFalse(os.path.exists(env.paths["LIVE"]), "the report must never create a database")

    def test_unreadable_db_is_unknown(self):
        env = Env(self)
        env.skip_db.add("PAPER")
        env.file("paper/trading.db", "not a database")
        result = env.build(server_mode="LIVE")
        self.assertEqual(lane(result, "daytrade_ks:PAPER")["status"], report.UNKNOWN)
        self.assertIn("DB를 읽지 못했습니다", lane(result, "daytrade_ks:PAPER")["reason"])

    def test_missing_or_corrupt_runtime_log_today_is_unknown_even_with_fills(self):
        env = Env(self)
        env.logs["PAPER"] = [log("DT_KS_BUY", "2026-11-27 10:00:00", "A BUY 실행", "A", "BUY", 1, 100.0, "1")]
        env.remove_runtime("PAPER", "runtime_logs_ks.json")
        item = lane(env.build(), "daytrade_ks:PAPER")
        self.assertEqual(item["status"], report.UNKNOWN)
        self.assertIn("런타임 로그 파일이 없습니다", item["reason"])
        self.assertEqual(item["buys"], 1)
        env.runtime("PAPER", "runtime_logs_ks.json", None, raw_text="{broken")
        self.assertIn("읽지 못했습니다", lane(env.build(), "daytrade_ks:PAPER")["reason"])
        env.runtime("PAPER", "runtime_logs_ks.json", [rt("2026-11-25 10:00:00", "그제")])
        item = lane(env.build(), "daytrade_ks:PAPER")
        self.assertEqual(item["status"], report.UNKNOWN)
        self.assertIn("오늘 런타임 로그 기록이 없습니다", item["reason"])

    def test_past_trading_day_without_runtime_log_is_unknown_unless_filled(self):
        env = Env(self)
        day = datetime.date(2026, 11, 20)
        item = lane(env.build(day=day), "daytrade_ks:PAPER")
        self.assertEqual(item["status"], report.UNKNOWN)
        self.assertIn("차단 여부를 알 수 없습니다", item["reason"])
        env.logs["PAPER"] = [log("DT_KS_BUY", "2026-11-20 10:00:00", "A BUY 실행", "A", "BUY", 1, 100.0, "1")]
        item = lane(env.build(day=day), "daytrade_ks:PAPER")
        self.assertEqual(item["status"], report.RUNNING)
        self.assertTrue(any("보관 범위 밖" in n for n in item["notes"]))

    def test_undecryptable_account_is_unknown(self):
        env = Env(self)
        env.config["LIVE"][f"user:{UID}:kis_live_account_no"] = "enc:v1:broken"
        result = env.build(decrypt=lambda value: "")
        for key in ("daytrade_ks:LIVE", "infinite_buy:LIVE"):
            self.assertEqual(lane(result, key)["status"], report.UNKNOWN, key)
            self.assertIn("복호화", lane(result, key)["reason"])

    def test_encrypted_account_resolves_with_secret_box(self):
        from cryptography.fernet import Fernet
        secret = _load("t_daily_report_secret", ROOT / "src/portal/trading/model/secret_box.py")
        previous = os.environ.get("STOCK8_CONFIG_KEY")
        os.environ["STOCK8_CONFIG_KEY"] = Fernet.generate_key().decode()
        secret.reset()
        try:
            env = Env(self)
            env.config["LIVE"][f"user:{UID}:kis_live_account_no"] = secret.encrypt(LIVE_ACCOUNT)
            env.runtime("LIVE", "runtime_logs_ks.json", [rt("2026-11-26 23:00:00", "어제"),
                                                         rt("2026-11-27 09:01:00", "단타 신규 진입 차단 (KS): 후보 없음", "warning")])
            self.assertEqual(lane(env.build(decrypt=secret.decrypt), "daytrade_ks:LIVE")["status"], report.BLOCKED)
        finally:
            secret.reset()
            if previous is None:
                os.environ.pop("STOCK8_CONFIG_KEY", None)
            else:
                os.environ["STOCK8_CONFIG_KEY"] = previous

    def test_same_db_path_for_both_modes_is_refused(self):
        env = Env(self)
        env.write()
        result = report.build_report(UID, DAY, now=NOW, is_admin=True, server_mode="PAPER",
                                     db_paths={"LIVE": env.paths["PAPER"], "PAPER": env.paths["PAPER"]}, data_dir=env.data)
        self.assertEqual(lane(result, "daytrade_ks:LIVE")["status"], report.UNKNOWN)
        self.assertIn("경로가 같습니다", lane(result, "daytrade_ks:LIVE")["reason"])


class ErrorGroupingTests(unittest.TestCase):
    def test_clean_message_drops_parameters_and_countdowns(self):
        self.assertEqual(report.clean_message("매수 주문 실패 [RIVN]: 모의투자 영업일이 아닙니다. (rt_cd=1, exchange=NASD, qty=52)"),
                         "매수 주문 실패 [RIVN]: 모의투자 영업일이 아닙니다.")
        self.assertEqual(report.clean_message("주문 실패 (rt_cd=1, exchange=NASD, qty=5"), "주문 실패")
        self.assertEqual(report.clean_message("RIVN 재시도 대기 중 (60초)"), report.clean_message("RIVN 재시도 대기 중 (188초)"))

    def test_groups_by_message_with_count_and_span(self):
        rows = [log("DT_US_BUY_ERROR", "2026-11-27 00:11:34", "실패 A (qty=1)"),
                log("DT_US_BUY_ERROR", "2026-11-27 05:37:50", "실패 A (qty=2)"),
                log("DT_US_SELL_FULL_ERROR", "2026-11-27 03:00:00", "실패 B", raw=json.dumps({"repeat": 4, "last_at": "2026-11-27 04:00:00"}))]
        groups = report.group_errors(rows)
        self.assertEqual([(g["message"], g["count"]) for g in groups], [("실패 B", 4), ("실패 A", 2)])
        self.assertEqual(report.group_text(groups[1]), "실패 A ×2 (00:11~05:37)")
        self.assertEqual(report.group_text(groups[0]), "실패 B ×4 (03:00~04:00)")


class ScopeTests(unittest.TestCase):
    def test_other_users_rows_and_switches_are_not_used(self):
        env = Env(self)
        env.config["PAPER"][f"user:{UID}:daytrade_auto_enabled"] = "false"
        env.config["PAPER"]["user:other:daytrade_auto_enabled"] = "true"
        env.config["PAPER"]["daytrade_auto_enabled"] = "true"   # legacy global key: admin fallback only when missing
        env.logs["PAPER"] = [log("DT_KS_BUY", "2026-11-27 10:00:00", "남의 매수", "A", "BUY", 1, 100.0, "1", user="other"),
                             log("DT_KS_SELL_FULL_ERROR", "2026-11-27 10:00:00", "남의 오류", "A", "ERROR", user="other")]
        item = lane(env.build(), "daytrade_ks:PAPER")
        self.assertEqual(item["status"], report.OFF)
        self.assertEqual(item["buys"], 0)
        self.assertEqual(item["problems"], [])

    def test_admin_reads_legacy_rows_and_keys_but_a_user_does_not(self):
        env = Env(self)
        del env.config["PAPER"][f"user:{UID}:auto_trade_enabled"]
        env.config["PAPER"]["auto_trade_enabled"] = "true"
        env.cycles["PAPER"] = [{"symbol": "TQQQ", "status": "ACTIVE", "qty": 3, "user_id": ""}]
        env.logs["PAPER"] = [log("IB_BUY_FILLED", "2026-11-27 06:00:00", "R1 매수 체결: 3주 @ $50.00", "TQQQ", "BUY", user="")]
        admin = lane(env.build(is_admin=True), "infinite_buy:PAPER")
        self.assertEqual((admin["status"], admin["buys"]), (report.RUNNING, 1))
        self.assertEqual(admin["fills"][0]["qty"], 3)
        user = lane(env.build(is_admin=False), "infinite_buy:PAPER")
        self.assertEqual(user["status"], report.OFF)
        self.assertEqual((user["buys"], user["positions"]), (0, []))

    def test_daytrade_is_admin_only_and_shared_paper_files_are_not_read(self):
        env = Env(self)
        env.runtime("PAPER", "runtime_logs_ks.json", [rt("2026-11-27 09:00:00", "단타 신규 진입 차단 (KS): 관리자 정보", "warning")])
        result = env.build(is_admin=False)
        for key in ("daytrade_ks:LIVE", "daytrade_ks:PAPER", "daytrade_us:LIVE", "daytrade_us:PAPER"):
            item = lane(result, key)
            self.assertEqual(item["status"], report.OFF, key)
            self.assertEqual(item["problems"], [])
        self.assertNotIn("관리자 정보", json.dumps(result, ensure_ascii=False))

    def test_worker_status_only_for_its_owner(self):
        env = Env(self)
        env.file("paper/daytrade/worker_status.json", {"last_run_at": "2026-11-27 15:39:00",
                                                       "result": {"auto_cycle": {"message": "국내 주식 시장이 열려있지 않습니다."}}})
        self.assertTrue(lane(env.build(), "daytrade_ks:PAPER")["worker"])
        env.config["PAPER"]["paper_worker_owner_user_id"] = "other"
        self.assertEqual(lane(env.build(), "daytrade_ks:PAPER")["worker"], [])

    def test_payload_carries_no_account_numbers_or_hashes(self):
        env = Env(self)
        text = json.dumps(env.build(), ensure_ascii=False)
        for secret in (LIVE_ACCOUNT, PAPER_ACCOUNT, LIVE_SCOPE, PAPER_SCOPE, UID):
            self.assertNotIn(secret, text)


class CoinTests(unittest.TestCase):
    def test_coin_lane_is_admin_only(self):
        env = Env(self)
        self.assertIn("coin:LIVE", [l["key"] for l in env.build(is_admin=True)["lanes"]])
        self.assertNotIn("coin:LIVE", [l["key"] for l in env.build(is_admin=False)["lanes"]])

    def test_coin_policy_states(self):
        env = Env(self)
        item = lane(env.build(), "coin:LIVE")
        self.assertEqual(item["status"], report.OFF)
        self.assertIn("coin_policy_v1", item["reason"])
        env.config["LIVE"]["coin_policy_v1"] = json.dumps({"mode": "off", "owner_user_id": UID})
        self.assertIn("꺼짐(off)", lane(env.build(), "coin:LIVE")["reason"])
        env.config["LIVE"]["coin_policy_v1"] = json.dumps({"mode": "live", "owner_user_id": UID})
        self.assertEqual(lane(env.build(), "coin:LIVE")["status"], report.WAITING)
        env.logs["LIVE"] = [log("COIN_SELL", "2026-11-27 11:00:00", "KRW-BTC SELL 실행 | 순손익 ₩+1,200 (+1.0%)", "KRW-BTC", "SELL")]
        item = lane(env.build(), "coin:LIVE")
        self.assertEqual((item["status"], item["sells"], item["realized"]), (report.RUNNING, 1, 1200))
        env.logs["LIVE"].append(log("COIN_HALT", "2026-11-27 12:00:00", "일 손실 한도", "COIN", "HALT"))
        self.assertEqual(lane(env.build(), "coin:LIVE")["status"], report.BLOCKED)
        env.logs["LIVE"].append(log("COIN_RESUME", "2026-11-27 13:00:00", "재개", "COIN", "RESUME"))
        self.assertEqual(lane(env.build(), "coin:LIVE")["status"], report.RUNNING)

    def test_trend_hold_row_only_while_enabled_for_its_owner(self):
        env = Env(self)
        self.assertNotIn("us_trend_hold:PAPER", [l["key"] for l in env.build()["lanes"]])
        env.config["PAPER"]["us_trend_hold_policy_v1"] = json.dumps({"enabled": True, "owner_user_id": UID})
        self.assertIn("us_trend_hold:PAPER", [l["key"] for l in env.build()["lanes"]])
        self.assertNotIn("us_trend_hold:PAPER", [l["key"] for l in env.build(is_admin=False)["lanes"]])


class SafetyTests(unittest.TestCase):
    def _ledger(self, records):
        return {"records": records, "last_run": {"at": "2026-11-27 15:12:37"}}

    def test_holds_and_earlier_account_ledgers(self):
        env = Env(self)
        env.file(f"paper/trade_verification/{PAPER_SCOPE}.json", self._ledger([
            {"symbol": "A", "status": "FAIL", "reason": "불일치", "at": "2026-11-27 10:00:00", "side": "BUY"},
            {"symbol": "A", "status": "UNCONFIRMED", "reason": "조회 실패", "at": "2026-11-27 10:05:00", "side": "BUY"},
            {"symbol": "B", "status": "FAIL", "acknowledged": {"at": "x"}, "side": "BUY"},
            {"symbol": "C", "status": "PASS", "side": "BUY"}]))
        old_scope = _h("kis:OLD-ACCOUNT", 40)
        env.config["PAPER"]["order_policy_v1:" + old_scope] = json.dumps({"symbols": {}, "owner_user_id": UID})
        env.config["PAPER"]["order_policy_v1:" + _h("kis:SOMEONE", 40)] = json.dumps({"symbols": {}, "owner_user_id": "other"})
        env.file(f"paper/trade_verification/{old_scope[:24]}.json", self._ledger(
            [{"symbol": s, "status": "FAIL", "side": "BUY"} for s in ("X", "Y", "Y")]))
        env.file(f"paper/trade_verification/{_h('kis:SOMEONE', 24)}.json", self._ledger([{"symbol": "Z", "status": "FAIL"}]))
        safety = env.build()["safety"]["PAPER"]
        self.assertEqual([h["symbol"] for h in safety["verification"]["holds"]], ["A"])
        self.assertEqual(safety["verification"]["hold_records"], 2)
        self.assertEqual([(o["holds"], o["hold_records"]) for o in safety["old_ledgers"]], [(2, 3)])

    def test_missing_or_corrupt_ledger_is_unknown_and_left_in_place(self):
        env = Env(self)
        self.assertEqual(env.build()["safety"]["PAPER"]["verification"]["status"], "missing")
        path = env.file(f"paper/trade_verification/{PAPER_SCOPE}.json", "{broken")
        self.assertEqual(env.build()["safety"]["PAPER"]["verification"]["status"], "error")
        self.assertTrue(os.path.exists(path))
        self.assertFalse(os.path.exists(path + ".corrupt"))


class ReadOnlyTests(unittest.TestCase):
    def test_build_changes_no_file(self):
        env = Env(self)
        env.logs["PAPER"] = [log("DT_KS_BUY", "2026-11-27 10:00:00", "A BUY 실행", "A", "BUY", 1, 100.0, "1")]
        env.write()

        def snapshot():
            files = {}
            for folder, _dirs, names in os.walk(env.root):
                for name in names:
                    path = os.path.join(folder, name)
                    with open(path, "rb") as handle:
                        files[path] = (os.path.getmtime(path), hashlib.sha256(handle.read()).hexdigest())
            return files

        before = snapshot()
        time.sleep(0.05)
        report.build_report(UID, DAY, now=NOW, is_admin=True, server_mode="LIVE", db_paths=env.paths, data_dir=env.data,
                            krx_holidays=domestic.KRX_HOLIDAYS, us_holidays=KIS["US_MARKET_HOLIDAYS"],
                            us_early_closes=KIS["US_EARLY_CLOSES"])
        self.assertEqual(snapshot(), before)


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.cal = report.Calendar(domestic.KRX_HOLIDAYS, KIS["US_MARKET_HOLIDAYS"], KIS["US_EARLY_CLOSES"])

    def test_thanksgiving_week(self):
        schedule = self.cal.schedule(DAY)
        us = {item["date"]: item for item in schedule["us"]}
        self.assertFalse(us["2026-11-26"]["open"])
        self.assertIn("Thanksgiving", us["2026-11-26"]["reason"])
        self.assertTrue(us["2026-11-27"]["early_close"])
        self.assertEqual(us["2026-11-27"]["hours_et"], "09:30~13:00 ET")
        self.assertEqual(us["2026-11-27"]["hours_kst"], "11/27 23:30 ~ 11/28 03:00 KST")
        self.assertEqual(us["2026-11-30"]["hours_kst"], "11/30 23:30 ~ 12/1 06:00 KST")
        self.assertEqual([k["date"] for k in schedule["krx"]], ["2026-11-27", "2026-11-30"])

    def test_krx_holiday_and_summer_time(self):
        self.assertFalse(self.cal.krx_day(datetime.date(2026, 12, 25))["open"])
        self.assertEqual(self.cal.next_krx_day(datetime.date(2026, 12, 24)), datetime.date(2026, 12, 28))
        self.assertEqual(self.cal.us_day(datetime.date(2026, 7, 6))["hours_kst"], "7/6 22:30 ~ 7/7 05:00 KST")


class InputTests(unittest.TestCase):
    def test_parse_day_limits(self):
        today = DAY
        self.assertEqual(report.parse_day("", today), today)
        self.assertEqual(report.parse_day("2026-11-14", today), datetime.date(2026, 11, 14))
        for bad in ("2026-11-13", "2026-11-28", "27-11-2026"):
            with self.assertRaises(ValueError):
                report.parse_day(bad, today)
        self.assertEqual(len(report.date_options(today)), 14)

    def test_db_paths_follow_the_environment(self):
        previous = os.environ.pop("STOCK8_LIVE_DB_PATH", None)
        try:
            self.assertTrue(report.mode_db_path("/srv", "LIVE").replace("\\", "/").endswith("project/main/data/live/trading.db"))
            os.environ["STOCK8_LIVE_DB_PATH"] = "elsewhere/live.db"
            self.assertTrue(report.mode_db_path("/srv", "LIVE").replace("\\", "/").endswith("elsewhere/live.db"))
        finally:
            os.environ.pop("STOCK8_LIVE_DB_PATH", None)
            if previous is not None:
                os.environ["STOCK8_LIVE_DB_PATH"] = previous

    def test_user_scoped_keys_match_struct(self):
        tree = ast.parse((ROOT / "src/portal/trading/model/struct.py").read_text(encoding="utf-8"))
        scoped = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "USER_SCOPED_CONFIG_KEYS":
                scoped = ast.literal_eval(node.value)
        self.assertTrue(report.USER_SCOPED_KEYS <= scoped, report.USER_SCOPED_KEYS - scoped)


class FileReadTests(unittest.TestCase):
    """Review 1: an engine's os.replace must not meet an open report handle."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="stock8-report-read-")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.path = os.path.join(self.folder, "state.json")
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"sleeves": {"A": 1}}, handle)

    def _replace(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"sleeves": {"B": 2}}, handle)
        os.replace(tmp, self.path)  # an engine's atomic save

    def test_handle_is_closed_before_parsing(self):
        original = report._decode_json
        replaced = []

        def decode_while_engine_saves(raw):
            self._replace()   # WinError 5 if the reader still held the file
            replaced.append(True)
            return original(raw)

        report._decode_json = decode_while_engine_saves
        try:
            data, status = report.read_json_file(self.path)
        finally:
            report._decode_json = original
        self.assertEqual((status, data), ("ok", {"sleeves": {"A": 1}}))
        self.assertEqual(replaced, [True])
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"sleeves": {"B": 2}})

    def test_missing_and_broken_files(self):
        self.assertEqual(report.read_json_file(os.path.join(self.folder, "none.json")), (None, "missing"))
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        self.assertEqual(report.read_json_file(self.path), (None, "error"))
        self.assertEqual(report.read_json_file(self.folder)[1], "error")

    @unittest.skipUnless(os.name == "nt", "Windows share modes")
    def test_windows_open_is_shared_for_read_write_delete(self):
        fd = report.open_shared(self.path)
        self.assertIsNotNone(fd)
        try:
            with open(self.path, "a", encoding="utf-8"):
                pass  # another writer is not locked out
            self.assertEqual(os.read(fd, 100), b'{"sleeves": {"A": 1}}')
        finally:
            os.close(fd)
        with self.assertRaises(FileNotFoundError):
            report.open_shared(os.path.join(self.folder, "none.json"))

    def test_ledger_read_takes_the_verifier_lock_of_this_process(self):
        verifier = _load("t_daily_report_verifier", ROOT / "src/portal/trading/model/trade_verifier.py")
        self.assertIs(report._ledger_lock(self.path), verifier._path_lock(self.path))


class WorkerLivenessTests(unittest.TestCase):
    """Review 2: a stopped or failing worker is never shown as 대기."""
    AT_1400 = datetime.datetime(2026, 11, 27, 14, 0)

    def fresh_runtime(self, env, mode, stamp="2026-11-27 13:58:00"):
        for name in ("runtime_logs_ks.json", "runtime_logs_us.json"):
            env.runtime(mode, name, [rt("2026-11-26 23:00:00", "어제"), rt(stamp, "국내 단타 자동순환 시작")])

    def test_paper_worker_stopped_in_session_is_unknown(self):
        env = Env(self)
        env.worker("2026-11-27 09:10:00")
        self.fresh_runtime(env, "PAPER")
        item = lane(env.build(now=self.AT_1400), "daytrade_ks:PAPER")
        self.assertEqual(item["status"], report.UNKNOWN)
        self.assertIn("PAPER 워커 응답 없음", item["reason"])
        self.assertIn("09:10", item["reason"])
        # Outside the session a stale heartbeat is only a note.
        late = lane(env.build(), "daytrade_ks:PAPER")
        self.assertEqual(late["status"], report.WAITING)
        self.assertTrue(any("PAPER 워커 마지막 기록" in n for n in late["notes"]))

    def test_runtime_log_cut_in_session_is_unknown(self):
        env = Env(self)
        env.worker("2026-11-27 14:59:00")
        self.fresh_runtime(env, "PAPER", "2026-11-27 09:05:00")
        item = lane(env.build(now=datetime.datetime(2026, 11, 27, 15, 0)), "daytrade_ks:PAPER")
        self.assertEqual(item["status"], report.UNKNOWN)
        self.assertIn("런타임 로그가 09:05 이후 끊겼습니다", item["reason"])

    def test_no_log_before_the_open_is_not_unknown(self):
        env = Env(self)
        env.worker("2026-11-27 08:29:00")
        env.runtime("PAPER", "runtime_logs_ks.json", [rt("2026-11-26 15:30:00", "어제 마감")])
        item = lane(env.build(now=datetime.datetime(2026, 11, 27, 8, 30)), "daytrade_ks:PAPER")
        self.assertEqual((item["status"], item["reason"]), (report.WAITING, "장 시작 전"))

    def test_paper_loc_error_and_loop_error_are_blocked(self):
        env = Env(self)
        env.worker("2026-11-27 13:59:00", {"loc_automation": {"status": "error", "message": "LOC 예약 실패 (rt_cd=1, qty=3)"}})
        item = lane(env.build(now=self.AT_1400), "infinite_buy:PAPER")
        self.assertEqual(item["status"], report.BLOCKED)
        self.assertEqual(item["reason"], "PAPER 워커 LOC 예약 오류: LOC 예약 실패")
        env.worker("2026-11-27 13:59:00", {"executed": False, "message": "database is locked"})
        self.fresh_runtime(env, "PAPER")
        self.assertIn("PAPER 워커 오류: database is locked", lane(env.build(now=self.AT_1400), "daytrade_ks:PAPER")["reason"])

    def test_live_jobs_on_the_live_server(self):
        env = Env(self)
        env.cycles["LIVE"] = [{"symbol": "SOXL", "status": "ACTIVE", "qty": 165}]
        self.fresh_runtime(env, "LIVE")

        def build(rows, error=""):
            return env.build(now=self.AT_1400, server_mode="LIVE", process={"live_workers": {"rows": rows, "error": error}})

        def job(name, status, error="", at="2026-11-27T13:59:30"):
            return {"policy_key": LIVE_POLICY, "job": name, "status": status, "message": "", "error": error, "last_check": at}

        ok = [job("entry_ks", "waiting"), job("exit_ks", "waiting"), job("loc", "waiting"), job("sync", "waiting")]
        result = build(ok)
        self.assertEqual(lane(result, "infinite_buy:LIVE")["status"], report.WAITING)
        self.assertEqual(lane(result, "daytrade_ks:LIVE")["status"], report.WAITING)
        failed = build(ok[:2] + [job("loc", "error", "FireGate 조회 실패"), job("sync", "waiting")])
        self.assertEqual(lane(failed, "infinite_buy:LIVE")["status"], report.BLOCKED)
        self.assertIn("LIVE 워커 LOC 예약 오류: FireGate 조회 실패", lane(failed, "infinite_buy:LIVE")["reason"])
        stale = build([job("entry_ks", "checking", at="2026-11-27T10:00:00"), job("exit_ks", "checking", at="2026-11-27T10:00:00")])
        self.assertIn("LIVE 워커 응답 없음", lane(stale, "daytrade_ks:LIVE")["reason"])
        changed = build([job("entry_ks", "account_changed")])
        self.assertIn("계좌가 바뀌어", lane(changed, "daytrade_ks:LIVE")["reason"])
        missing = build([])
        self.assertEqual(lane(missing, "daytrade_ks:LIVE")["status"], report.UNKNOWN)
        self.assertIn("실행하고 있지 않습니다", lane(missing, "daytrade_ks:LIVE")["reason"])
        other = build([{**job("loc", "error", "남의 오류"), "policy_key": "order_policy_v1:" + "0" * 40}] + ok)
        self.assertEqual(lane(other, "infinite_buy:LIVE")["status"], report.WAITING)
        self.assertNotIn("남의 오류", json.dumps(other, ensure_ascii=False))

    def test_live_infinite_buy_seen_from_paper_uses_run_records(self):
        env = Env(self)
        env.cycles["LIVE"] = [{"symbol": "SOXL", "status": "ACTIVE", "qty": 165}]
        env.logs["LIVE"] = [log("IB_LOC_AUTOMATION_RUN", "2026-11-27 10:00:10", "LOC 자동 예약 점검 결과: {}", "SYSTEM",
                                raw=json.dumps({"repeat": 40, "last_at": "2026-11-27 11:00:00"}))]
        item = lane(env.build(now=self.AT_1400), "infinite_buy:LIVE")
        self.assertEqual(item["status"], report.UNKNOWN)
        self.assertIn("LOC 자동 예약 실행 기록이 11:00 이후 없습니다", item["reason"])
        env.logs["LIVE"][0]["raw_response"] = json.dumps({"repeat": 40, "last_at": "2026-11-27 13:58:00"})
        self.assertEqual(lane(env.build(now=self.AT_1400), "infinite_buy:LIVE")["status"], report.WAITING)
        env.logs["LIVE"] = []
        self.assertIn("오늘 LOC 자동 예약 실행 기록이 없습니다", lane(env.build(now=self.AT_1400), "infinite_buy:LIVE")["reason"])

    def test_paper_infinite_buy_without_worker_state_is_unknown_in_window(self):
        env = Env(self)
        env.cycles["PAPER"] = [{"symbol": "TQQQ", "status": "ACTIVE", "qty": 3}]
        env.config["PAPER"]["paper_worker_owner_user_id"] = "other"
        item = lane(env.build(now=self.AT_1400), "infinite_buy:PAPER")
        self.assertEqual(item["status"], report.UNKNOWN)
        self.assertIn("워커 상태 확인 불가", item["reason"])


class LogVolumeAndTrimTests(unittest.TestCase):
    def test_overflow_is_unknown_and_noise_is_not_read(self):
        env = Env(self)
        env.logs["PAPER"] = [log("IB_LOC_AUTOMATION_RUN", f"2026-11-27 10:0{i}:00", "run") for i in range(8)]
        env.logs["PAPER"] += [log("DT_KS_BUY", f"2026-11-27 10:1{i}:00", "A BUY 실행", "A", "BUY", 1, 100.0, str(i)) for i in range(3)]
        previous = report.MAX_DAY_ROWS
        report.MAX_DAY_ROWS = 3
        try:
            self.assertEqual(lane(env.build(), "daytrade_ks:PAPER")["buys"], 3)
            env.logs["PAPER"].append(log("DT_KS_SELL_FULL", "2026-11-27 11:00:00", "A SELL", "A", "SELL", 1, 101.0, "9"))
            item = lane(env.build(), "daytrade_ks:PAPER")
        finally:
            report.MAX_DAY_ROWS = previous
        self.assertEqual(item["status"], report.UNKNOWN)
        self.assertIn("기록 과다", item["reason"])
        self.assertEqual(item["buys"], None)

    def test_past_day_trimmed_line_counts_as_repeated(self):
        env = Env(self)
        message = "매수 주문 실패 [RIVN]: 모의투자 영업일이 아닙니다. (rt_cd=1, exchange=NASD, qty=52)"
        env.logs["PAPER"] = [log("DT_US_BUY_ERROR", "2026-11-26 00:11:34", message, "RIVN", "ERROR"),
                             log("DT_US_BUY_ERROR", "2026-11-26 05:37:50", message, "RIVN", "ERROR")]
        item = lane(env.build(day=datetime.date(2026, 11, 26)), "daytrade_us:PAPER")
        self.assertEqual(item["status"], report.BLOCKED)
        self.assertIn("최소 2회 (00:11~05:37)", item["reason"])
        self.assertTrue(any("로그 정리" in n for n in item["notes"]))
        # Today the same two rows are just two errors.
        env.logs["PAPER"] = [log("DT_US_BUY_ERROR", "2026-11-27 00:11:34", message, "RIVN", "ERROR"),
                             log("DT_US_BUY_ERROR", "2026-11-27 05:37:50", message, "RIVN", "ERROR")]
        self.assertNotEqual(lane(env.build(), "daytrade_us:PAPER")["status"], report.BLOCKED)

    def test_rotated_runtime_log_counts_are_minimums(self):
        env = Env(self)
        block = "단타 신규 진입 차단 (KS): 학습·검증을 통과한 후보가 없습니다."
        env.runtime("LIVE", "runtime_logs_ks.json", [rt(f"2026-11-27 10:1{i}:00", block, "warning") for i in range(3)])
        item = lane(env.build(), "daytrade_ks:LIVE")
        self.assertEqual(item["status"], report.BLOCKED)
        self.assertIn("최소 3회 (10:10~10:12)", item["reason"])
        self.assertTrue(any("10:10 이후만" in n for n in item["notes"]))

    def test_past_infinite_buy_mentions_trimmed_firegate_rows(self):
        env = Env(self)
        item = lane(env.build(day=datetime.date(2026, 11, 20)), "infinite_buy:LIVE")
        self.assertTrue(any("MISMATCH" in n for n in item["notes"]))


class OwnershipAndDamageTests(unittest.TestCase):
    def test_account_policy_of_another_user_is_unknown_and_hidden(self):
        env = Env(self)
        env.config["LIVE"][LIVE_POLICY] = json.dumps({"infinite_buy": True, "daytrade_ks": True, "symbols": {},
                                                      "owner_user_id": "other"})
        env.runtime("LIVE", "runtime_logs_ks.json", [rt("2026-11-27 09:00:00", "단타 신규 진입 차단 (KS): 남의 정보", "warning")])
        env.file(f"live/trade_verification/{LIVE_SCOPE}.json", {"records": [{"symbol": "SECRET", "status": "FAIL"}]})
        result = env.build(server_mode="LIVE", process={"live_workers": {"rows": [
            {"policy_key": LIVE_POLICY, "job": "loc", "status": "error", "error": "남의 워커", "last_check": ""}], "error": ""}})
        for key in ("daytrade_ks:LIVE", "infinite_buy:LIVE"):
            self.assertEqual(lane(result, key)["status"], report.UNKNOWN, key)
            self.assertIn("다른 사용자 소유", lane(result, key)["reason"])
            self.assertEqual(lane(result, key)["worker"], [])
        self.assertEqual(result["safety"]["LIVE"]["verification"]["status"], "foreign")
        text = json.dumps(result, ensure_ascii=False)
        for leaked in ("남의 정보", "남의 워커", "SECRET"):
            self.assertNotIn(leaked, text)

    def test_damaged_coin_and_trend_hold_policies_are_unknown(self):
        env = Env(self)
        env.config["LIVE"]["coin_policy_v1"] = "{broken"
        env.config["PAPER"]["us_trend_hold_policy_v1"] = "[1, 2]"
        result = env.build()
        self.assertEqual(lane(result, "coin:LIVE")["status"], report.UNKNOWN)
        self.assertIn("손상", lane(result, "coin:LIVE")["reason"])
        self.assertEqual(lane(result, "us_trend_hold:PAPER")["status"], report.UNKNOWN)
        self.assertNotIn("us_trend_hold:PAPER", [l["key"] for l in env.build(is_admin=False)["lanes"]])

    def test_coin_hard_lock_is_unknown_on_the_paper_server(self):
        env = Env(self)
        self.assertTrue(any("코인 봉인" in n for n in lane(env.build(server_mode="PAPER"), "coin:LIVE")["notes"]))
        self.assertFalse(any("코인 봉인" in n for n in lane(env.build(server_mode="LIVE"), "coin:LIVE")["notes"]))

    def test_old_ledger_scope_must_be_a_hash(self):
        env = Env(self)
        env.config["PAPER"]["order_policy_v1:../../outside_ledger"] = json.dumps({"symbols": {}, "owner_user_id": UID})
        env.file("outside_ledger.json", {"records": [{"symbol": "X", "status": "FAIL"}]})
        self.assertEqual(env.build()["safety"]["PAPER"]["old_ledgers"], [])

    def test_db_errors_carry_no_paths(self):
        env = Env(self)
        env.write()
        from unittest import mock
        with mock.patch.object(report.sqlite3, "connect", side_effect=OSError(13, "denied", env.paths["LIVE"])):
            item = lane(report.build_report(UID, DAY, now=NOW, is_admin=True, server_mode="PAPER", db_paths=env.paths,
                                            data_dir=env.data), "daytrade_ks:LIVE")
        self.assertEqual(item["status"], report.UNKNOWN)
        self.assertNotIn(env.root, item["reason"])
        self.assertIn("(PermissionError)", item["reason"])  # OSError(13, ...) is a PermissionError


class MessageCleaningTests(unittest.TestCase):
    def test_raw_account_quotes_and_long_numbers_are_hidden(self):
        text = report.clean_message("잔고 조회 실패 (원본: '12345678-01', CANO: '12345678', ACNT_PRDT_CD: '01'). 주문번호 0030947397")
        self.assertNotIn("12345678", text)
        self.assertNotIn("0030947397", text)
        self.assertEqual(report.clean_message("계좌 오류 (원본: '1234567801"), "계좌 오류")
        self.assertIn("****", report.clean_message("포트폴리오(1780022179464)"))

    def test_hold_and_unavailable_reasons_are_cleaned(self):
        env = Env(self)
        env.config["PAPER"][f"user:{UID}:kis_paper_account_unavailable_at"] = "2026-11-17T09:00:00"
        env.config["PAPER"][f"user:{UID}:kis_paper_account_unavailable_reason"] = "신청내역 없음 (원본: '50000000-01'"
        env.file(f"paper/trade_verification/{PAPER_SCOPE}.json", {"records": [
            {"symbol": "A", "status": "FAIL", "reason": "KIS 접수번호 0030947397 없음"}]})
        text = json.dumps(env.build()["safety"]["PAPER"], ensure_ascii=False)
        self.assertNotIn("50000000", text)
        self.assertNotIn("0030947397", text)


class Status(Exception):
    def __init__(self, code, data):
        super().__init__(code)
        self.code, self.data = code, data


def _status(code=200, **data):
    raise Status(code, data)


class ApiTests(unittest.TestCase):
    def load_api(self, env, admin_ids=(UID,), query=None, user_lookup=None, session_uid=UID):
        sys.__dict__.pop("_stock8_daily_report_v1", None)
        self.addCleanup(sys.__dict__.pop, "_stock8_daily_report_v1", None)
        env.write()
        q = dict(query or {})

        def get_user(id=None):
            if user_lookup is not None:
                return user_lookup(id)
            return {"id": id, "role": "admin" if id in admin_ids else "user", "email": "someone@example.com"}

        # No `trading` attribute: building the trading Struct here would fail the test.
        models = {
            "portal/trading/kst": NS(now=lambda: NOW),
            "portal/trading/daily_report": report.Model,
            "portal/trading/struct/kis_api": NS(**KIS),
            "portal/trading/domestic_market": NS(KRX_HOLIDAYS=domestic.KRX_HOLIDAYS),
            "portal/trading/secret_box": NS(decrypt=lambda value: value),
            "struct": NS(user=NS(get=get_user)),
        }
        wiz = NS(model=lambda name: models[name], session=NS(get=lambda key: session_uid if key == "id" else None),
                 server=NS(path=NS(root=env.root)), project=NS(fs=lambda: NS(abspath=lambda rel: os.path.join(env.root, "project", "main", rel))),
                 request=NS(query=lambda key, default=None: q.get(key, default)), response=NS(status=_status))
        api = {"wiz": wiz, "__name__": "report_api"}
        previous = {k: os.environ.get(k) for k in ("TRADING_MODE", "STOCK8_LIVE_DB_PATH", "STOCK8_PAPER_DB_PATH")}
        os.environ["TRADING_MODE"] = "PAPER"
        os.environ.pop("STOCK8_LIVE_DB_PATH", None)
        os.environ.pop("STOCK8_PAPER_DB_PATH", None)

        def restore():
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        self.addCleanup(restore)
        exec(compile((ROOT / "src/app/page.report/api.py").read_text(encoding="utf-8"), "api.py", "exec"), api)
        return api

    def call(self, api):
        with self.assertRaises(Status) as ctx:
            api["report"]()
        return ctx.exception

    def test_admin_sees_coin_and_user_does_not(self):
        env = Env(self)
        res = self.call(self.load_api(env))
        self.assertEqual(res.code, 200)
        self.assertIn("coin:LIVE", [l["key"] for l in res.data["lanes"]])
        self.assertEqual(lane(res.data, "daytrade_ks:LIVE")["status"], report.WAITING)
        res = self.call(self.load_api(env, admin_ids=()))
        self.assertNotIn("coin:LIVE", [l["key"] for l in res.data["lanes"]])

    def test_report_is_cached_per_user_and_date(self):
        env = Env(self)
        api = self.load_api(env)
        builds = []
        original = api["_build"]
        api["_build"] = lambda *args: builds.append(args) or original(*args)
        first, second = self.call(api), self.call(api)
        self.assertEqual(len(builds), 1)
        self.assertEqual(second.data["date"], first.data["date"])
        self.assertIsNotNone(second.data["cache_age_sec"])

    def test_bad_date_is_refused(self):
        env = Env(self)
        res = self.call(self.load_api(env, query={"date": "2026-10-01"}))
        self.assertEqual(res.code, 400)
        self.assertIn("최근 14일", res.data["message"])

    def test_not_logged_in_is_401(self):
        env = Env(self)
        self.assertEqual(self.call(self.load_api(env, session_uid=None)).code, 401)

    def test_operator_email_counts_as_admin(self):
        env = Env(self)
        api = self.load_api(env, user_lookup=lambda id: {"id": id, "role": "user", "email": "GigukByun@gmail.com"})
        self.assertIn("coin:LIVE", [l["key"] for l in self.call(api).data["lanes"]])

    def test_admin_lookup_failure_is_503_and_not_cached(self):
        env = Env(self)
        state = {"fail": True}

        def lookup(id):
            if state["fail"]:
                raise RuntimeError("user table locked")
            return {"id": id, "role": "admin", "email": ""}

        api = self.load_api(env, user_lookup=lookup)
        res = self.call(api)
        self.assertEqual(res.code, 503)
        self.assertNotIn("user table locked", res.data["message"])
        self.assertEqual(sys.__dict__["_stock8_daily_report_v1"]["cache"], {})
        state["fail"] = False
        self.assertIn("coin:LIVE", [l["key"] for l in self.call(api).data["lanes"]])

    def test_build_failure_message_has_no_paths(self):
        env = Env(self)
        api = self.load_api(env)

        def broken(*_args):
            raise OSError(13, "denied", os.path.join(env.root, "secret", "trading.db"))
        api["_build"] = broken
        res = self.call(api)
        self.assertEqual(res.code, 500)
        self.assertNotIn(env.root, res.data["message"])


class PageWiringTests(unittest.TestCase):
    def test_route_menu_and_title(self):
        app = json.loads((ROOT / "src/app/page.report/app.json").read_text(encoding="utf-8"))
        self.assertEqual((app["viewuri"], app["controller"], app["layout"]), ("/report", "user", "layout.trading"))
        self.assertIn('routerLink="/report"', (ROOT / "src/app/component.nav.trading/view.pug").read_text(encoding="utf-8"))
        self.assertIn("일일 보고", (ROOT / "src/portal/trading/libs/page-meta.ts").read_text(encoding="utf-8"))
        api_source = (ROOT / "src/app/page.report/api.py").read_text(encoding="utf-8")
        for forbidden in ("set_config", "_write_config_value", "requests", "urlopen", "kis_api(", "broker_api", ".insert(", ".update("):
            self.assertNotIn(forbidden, api_source)


if __name__ == "__main__":
    unittest.main()
