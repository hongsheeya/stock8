# =============================================================================
# Trading Package - Composite Struct (Singleton)
# =============================================================================
# 호출 예시:
#   trading = wiz.model("portal/trading/struct")
#   trading.broker_api.get_current_price("TQQQ")
#   trading.engine.run_cycle("TQQQ")
#   trading.db("trading_config").get(key="kis_app_key")
# =============================================================================

import datetime as _dt
import contextlib
import inspect
import json as _json
import sys as _sys
import threading
import time

_TIME = wiz.model("portal/trading/kst")
DAYTRADE_HARD_LOCKED = True
DAYTRADE_LOCK_MESSAGE = "단타 기능은 현재 운영 안정화를 위해 완전히 봉인되어 있습니다."
DAYTRADE_ENABLE_KEYS = {
    "daytrade_feature_enabled",
    "daytrade_auto_enabled",
    "daytrade_exit_watch_enabled",
    "daytrade_us_auto_enabled",
    "us_daytrade_auto_enabled",
    "daytrade_us_exit_watch_enabled",
    "us_daytrade_exit_watch_enabled",
}

USER_SCOPED_CONFIG_KEYS = {
    "broker_provider",
    "kis_app_key",
    "kis_app_secret",
    "kis_account_no",
    "kis_account_suffix",
    "kis_is_real",
    "kis_access_token",
    "kis_token_expires",
    "toss_client_id",
    "toss_client_secret",
    "toss_account_seq",
    "toss_account_no",
    "toss_access_token",
    "toss_token_expires",
    "fire_gate_bridge",
    "auto_trade_enabled",
    "loc_auto_schedule_enabled",
    "loc_buy_auto_schedule_last_date",
    "loc_auto_schedule_last_date",
    "loc_reservation_rebuild_attempts",
    "loc_reservation_rebuild_cooldown_until_ts",
    "loc_reservation_rebuild_cooldown_reason",
    "loc_reservation_verified_date",
    "loc_reservation_verified_version",
    "loc_reservation_verified_signature",
    "loc_reservation_verified_streak",
    "loc_reservation_verified_target",
    "loc_reservation_verified_complete",
    "loc_reservation_verified_last_at",
    "loc_reservation_verified_failure_reason",
    "default_division_count",
    "default_target_profit",
    "buy_commission_rate",
    "sell_commission_rate",
    "tax_rate",
    "sell_strategy",
    "buy_method",
    "sell_method",
    "crash_buy_enabled",
    "crash_buy_drop_pct",
    "crash_buy_ma_drop_pct",
    "crash_buy_ratio",
    "crash_buy_max_per_cycle",
}
USER_SCOPED_TABLES = {
    "etf_watchlist",
    "trading_cycle",
    "cycle_trade",
    "trade_log",
    "account_snapshot",
    "daily_trade_summary",
}
_CONFIG_MISSING = object()
_LOC_RESERVATION_START_HHMM = 1000
_LOC_RESERVATION_END_STANDARD_HHMM = 2320
_LOC_RESERVATION_END_SUMMER_HHMM = 2220
_LOC_RESERVATION_VERIFY_VERSION = "firegate-authoritative-v3"
_LOC_RESERVATION_PROCESS_LOCK = threading.Lock()


class _UserScopedDb:
    """Session-aware guard for account/profile tables.

    Rows without user_id are treated as legacy owner rows. They remain visible to
    the admin account and to background legacy automation, but are hidden from
    regular users so a new signup cannot see the operator's portfolio.
    """

    def __init__(self, db, struct, table_name):
        self._db = db
        self._struct = struct
        self._table_name = table_name

    def __getattr__(self, name):
        return getattr(self._db, name)

    def _uid(self):
        return str(self._struct._current_user_id() or "").strip()

    def _is_admin(self, user_id):
        return bool(user_id and self._struct._current_user_is_admin(user_id))

    def _with_user(self, kwargs, user_id):
        scoped = dict(kwargs or {})
        scoped["user_id"] = str(user_id or "")
        return scoped

    def _control_keys(self, kwargs):
        controls = {}
        where = {}
        for key, value in (kwargs or {}).items():
            if key in ("orderby", "order", "page", "dump"):
                controls[key] = value
            else:
                where[key] = value
        return where, controls

    def _sort_and_limit(self, rows, controls):
        data = list(rows or [])
        orderby = controls.get("orderby")
        if orderby:
            reverse = str(controls.get("order", "ASC") or "ASC").upper() == "DESC"
            data.sort(key=lambda row: (row or {}).get(orderby), reverse=reverse)
        try:
            dump = int(float(controls.get("dump", 0) or 0))
        except Exception:
            dump = 0
        try:
            page = max(int(float(controls.get("page", 1) or 1)), 1)
        except Exception:
            page = 1
        if dump > 0:
            start = (page - 1) * dump
            data = data[start:start + dump]
        return data

    def _raw_get(self, **kwargs):
        try:
            return self._db.get(**kwargs)
        except Exception:
            return None

    def _raw_rows(self, **kwargs):
        try:
            return self._db.rows(**kwargs) or []
        except Exception:
            return []

    def get(self, **kwargs):
        uid = self._uid()
        if uid:
            row = self._raw_get(**self._with_user(kwargs, uid))
            if row:
                return row
            if self._is_admin(uid):
                return self._raw_get(**self._with_user(kwargs, ""))
            return None
        return self._raw_get(**self._with_user(kwargs, ""))

    def rows(self, **kwargs):
        uid = self._uid()
        where, controls = self._control_keys(kwargs)
        if uid:
            rows = list(self._raw_rows(**{**self._with_user(where, uid), **controls}))
            if self._is_admin(uid):
                seen = {str((row or {}).get("id", "")) for row in rows if (row or {}).get("id")}
                for row in self._raw_rows(**{**self._with_user(where, ""), **controls}):
                    row_id = str((row or {}).get("id", "") or "")
                    if row_id and row_id in seen:
                        continue
                    if row_id:
                        seen.add(row_id)
                    rows.append(row)
            return self._sort_and_limit(rows, controls)
        return self._raw_rows(**{**self._with_user(where, ""), **controls})

    def insert(self, data):
        row = dict(data or {})
        row.setdefault("user_id", self._uid())
        return self._db.insert(row)

    def _owned_row(self, row):
        uid = self._uid()
        owner = str((row or {}).get("user_id", "") or "").strip()
        if uid == "":
            return owner == ""
        if owner == uid:
            return True
        return owner == "" and self._is_admin(uid)

    def update(self, data, id=None, **kwargs):
        if id is not None:
            row = self._raw_get(id=id)
            if row and self._owned_row(row) is False:
                raise Exception("권한이 없는 데이터입니다.")
            return self._db.update(data, id=id)
        scoped = dict(kwargs or {})
        uid = self._uid()
        if uid and self._is_admin(uid) is False:
            scoped["user_id"] = uid
        elif uid == "":
            scoped["user_id"] = ""
        return self._db.update(data, id=id, **scoped)

    def delete(self, id=None, **kwargs):
        if id is not None:
            row = self._raw_get(id=id)
            if row and self._owned_row(row) is False:
                raise Exception("권한이 없는 데이터입니다.")
            return self._db.delete(id=id)
        scoped = dict(kwargs or {})
        uid = self._uid()
        if uid and self._is_admin(uid) is False:
            scoped["user_id"] = uid
        elif uid == "":
            scoped["user_id"] = ""
        return self._db.delete(id=id, **scoped)


def _kst_now():
    return _TIME.now()


def _normalize_kst_timestamp(value=""):
    text = str(value or "").strip()
    if text == "":
        return ""
    return _TIME.normalize(text)


def _loc_schedule_mark_done(result):
    if not isinstance(result, dict) or len(result) == 0:
        return False
    result = result or {}
    status = str(result.get("status", "") or "").lower()
    try:
        error_count = int(float(result.get("error_count", 0) or 0))
    except Exception:
        error_count = 0
    try:
        scheduled_count = int(float(result.get("scheduled_count", 0) or 0))
    except Exception:
        scheduled_count = 0
    try:
        already_scheduled_count = int(float(result.get("already_scheduled_count", 0) or 0))
    except Exception:
        already_scheduled_count = 0
    try:
        skipped_count = int(float(result.get("skipped_count", 0) or 0))
    except Exception:
        skipped_count = 0
    try:
        missing_count = int(float(result.get("missing_count", 0) or 0))
    except Exception:
        missing_count = 0
    expected_raw = result.get("expected_count", None)
    expected_count = None
    if expected_raw is not None:
        try:
            expected_count = int(float(expected_raw or 0))
        except Exception:
            expected_count = None
    try:
        satisfied_count = int(float(result.get("satisfied_count", scheduled_count + already_scheduled_count) or 0))
    except Exception:
        satisfied_count = scheduled_count + already_scheduled_count
    if status in ("error", "partial_error", "partial_pending") or error_count > 0 or skipped_count > 0 or missing_count > 0:
        return False
    if expected_count is not None:
        return satisfied_count >= expected_count
    if scheduled_count > 0 or already_scheduled_count > 0:
        return True
    return status not in ("error", "partial_error") and error_count <= 0


def _loc_result_int(result, key, default=0):
    try:
        return int(float((result or {}).get(key, default) or default))
    except Exception:
        return default


def _loc_result_new_order_count(*results):
    total = 0
    for result in results:
        total += _loc_result_int(result, "scheduled_count")
    return total


def _loc_result_verified_for_streak(result):
    result = result or {}
    status = str(result.get("status", "") or "").lower()
    if status != "completed":
        return False
    bad_keys = ("scheduled_count", "skipped_count", "error_count", "missing_count", "force_rebuild_count")
    if any(_loc_result_int(result, key) > 0 for key in bad_keys):
        return False
    expected_count = _loc_result_int(result, "expected_count")
    satisfied_count = _loc_result_int(result, "satisfied_count")
    if satisfied_count < expected_count:
        return False
    if expected_count > 0 and _loc_result_int(result, "already_scheduled_count") <= 0:
        return False
    return True


def _loc_expected_signature_rows(side, result):
    rows = []
    for item in (result or {}).get("expected", []) or []:
        try:
            price = round(float((item or {}).get("price", 0) or 0), 4)
        except Exception:
            price = 0.0
        try:
            qty = int(float((item or {}).get("order_qty", 0) or 0))
        except Exception:
            qty = 0
        rows.append({
            "side": side,
            "symbol": str((item or {}).get("symbol", "") or "").upper(),
            "exchange": str((item or {}).get("exchange", "NASD") or "NASD").upper(),
            "order_type": str((item or {}).get("order_type", "") or "").upper(),
            "price": price,
            "qty": qty,
        })
    rows.sort(key=lambda row: (row["side"], row["symbol"], row["exchange"], row["order_type"], row["price"], row["qty"]))
    return rows


def _loc_reservation_verification_signature(buy_result, sell_result):
    payload = {
        "buy": _loc_expected_signature_rows("BUY", buy_result),
        "sell": _loc_expected_signature_rows("SELL", sell_result),
        "buy_expected_count": _loc_result_int(buy_result, "expected_count"),
        "sell_expected_count": _loc_result_int(sell_result, "expected_count"),
    }
    return _json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loc_result_failure_reason(result, label):
    result = result or {}
    reasons = []
    status = str(result.get("status", "") or "").lower()
    if status and status != "completed":
        reasons.append(f"{label} status={status}")
    for key in ("scheduled_count", "skipped_count", "error_count", "missing_count", "force_rebuild_count"):
        value = _loc_result_int(result, key)
        if value > 0:
            reasons.append(f"{label} {key}={value}")
    expected_count = _loc_result_int(result, "expected_count")
    satisfied_count = _loc_result_int(result, "satisfied_count")
    if satisfied_count < expected_count:
        reasons.append(f"{label} satisfied={satisfied_count}/{expected_count}")
    if expected_count > 0 and _loc_result_int(result, "already_scheduled_count") <= 0 and _loc_result_int(result, "scheduled_count") <= 0:
        reasons.append(f"{label} broker_echo_missing")
    return ", ".join(reasons)


def _loc_schedule_problem_symbols(*results):
    symbols = []
    seen = set()

    def add(value):
        symbol = str(value or "").upper().strip()
        if not symbol or symbol in seen:
            return
        seen.add(symbol)
        symbols.append(symbol)

    def scan(value):
        if isinstance(value, dict):
            if "symbol" in value:
                add(value.get("symbol"))
            for nested_key in ("orders", "already_scheduled", "skipped", "errors", "missing", "buy", "sell"):
                scan(value.get(nested_key))
        elif isinstance(value, list):
            for item in value:
                scan(item)

    for result in results:
        scan(result)
    return symbols


def _loc_schedule_force_rebuild(*results):
    def scan(value):
        if isinstance(value, dict):
            if value.get("force_rebuild") is True:
                return True
            try:
                if int(float(value.get("force_rebuild_count", 0) or 0)) > 0:
                    return True
            except Exception:
                pass
            return any(scan(item) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return any(scan(item) for item in value)
        return False

    return any(scan(result) for result in results)


def _loc_result_all_missing_without_broker_signal(result):
    result = result or {}
    expected = _loc_result_int(result, "expected_count")
    if expected <= 0:
        return False
    return (
        _loc_result_int(result, "satisfied_count") == 0
        and _loc_result_int(result, "scheduled_count") == 0
        and _loc_result_int(result, "already_scheduled_count") == 0
        and _loc_result_int(result, "error_count") == 0
        and _loc_result_int(result, "missing_count") >= expected
    )


def _loc_schedule_key(now):
    if now.hour < 7:
        return (now - _dt.timedelta(days=1)).strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")


def _loc_hhmm_text(hhmm):
    return f"{int(hhmm) // 100:02d}:{int(hhmm) % 100:02d}"


def _nth_weekday(year, month, weekday, nth):
    day = _dt.date(year, month, 1)
    offset = (weekday - day.weekday()) % 7
    return day + _dt.timedelta(days=offset + (nth - 1) * 7)


def _us_summer_time_for_kst(now):
    try:
        from zoneinfo import ZoneInfo
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo("Asia/Seoul"))
        now_et = now.astimezone(ZoneInfo("America/New_York"))
        return bool(now_et.dst())
    except Exception:
        today = now.date()
        start = _nth_weekday(today.year, 3, 6, 2)
        end = _nth_weekday(today.year, 11, 6, 1)
        return start <= today < end


def _loc_reservation_cutoff_hhmm(now):
    return _LOC_RESERVATION_END_SUMMER_HHMM if _us_summer_time_for_kst(now) else _LOC_RESERVATION_END_STANDARD_HHMM


def _loc_reservation_window_label(now=None):
    now = now or _kst_now()
    return f"{_loc_hhmm_text(_LOC_RESERVATION_START_HHMM)}-{_loc_hhmm_text(_loc_reservation_cutoff_hhmm(now))} KST"


def _loc_reservation_next_start_label():
    return f"{_loc_hhmm_text(_LOC_RESERVATION_START_HHMM)} KST"


def _loc_reservation_window_state(now):
    hhmm = now.hour * 100 + now.minute
    cutoff = _loc_reservation_cutoff_hhmm(now)
    if hhmm < _LOC_RESERVATION_START_HHMM:
        return "before"
    if hhmm > cutoff:
        return "after"
    return "open"


def _loc_reservation_window_open(now):
    return _loc_reservation_window_state(now) == "open"


def _loc_reservation_bucket(now):
    return f"{_loc_schedule_key(now)}-{now.hour:02d}-{now.minute // 5}"


def _external_cycle_sync_window_open(now):
    return 8 <= int(now.hour) < 10


def _external_cycle_sync_verified(result):
    result = result or {}
    if result.get("verified") is True:
        return True
    status = str(result.get("status", "") or "").lower()
    if status != "completed":
        return False
    for key in ("error_count", "unresolved_count", "unverified_count"):
        try:
            if int(float(result.get(key, 0) or 0)) > 0:
                return False
        except Exception:
            return False
    return True

class Struct:
    # 클래스 레벨 캐시 — 싱글톤이므로 프로세스 수명 동안 유지
    _cfg: dict = {}
    _cfg_ready: bool = False
    _tables_initialized: bool = False   # 테이블 초기화 1회 전용
    _worker_started: bool = False
    _worker_thread = None
    _worker_lock = threading.Lock()
    _worker_force_run: bool = False
    _worker_last_run_at: str = ""
    _worker_last_result: dict = {}
    _worker_engine_id: int = 0   # id(DaytradeEngine 클래스) - 코드 변경 감지용
    _worker_daytrade_id: int = 0 # id(Daytrade 클래스) - 추천/학습 코드 변경 감지용
    # KIS 잔고 인메모리 캐시 — exec() 재실행해도 클래스 변수는 유지됨
    _kis_balance_cache: dict = {}
    _kis_balance_cache_ts: float = 0.0
    _KIS_BALANCE_CACHE_TTL: float = 15.0
    # 분봉 스냅샷 인메모리 캐시 (종목별 현재가 + 분봉)
    _snapshot_cache: dict = {}
    _SNAPSHOT_CACHE_TTL: float = 12.0  # 12초

    def __init__(self):
        self.orm = wiz.model("portal/season/orm")

        # Sub-Struct 클래스 로드
        self._KisApi = wiz.model("portal/trading/struct/kis_api")
        self._TossApi = wiz.model("portal/trading/struct/toss_api")
        self._Engine = wiz.model("portal/trading/struct/engine")
        self._Strategy = wiz.model("portal/trading/struct/strategy")
        self._Daytrade = wiz.model("portal/trading/struct/daytrade")
        self._DaytradeEngine = None
        self._daytrade_model_id = 0
        self._daytrade_engine_model_id = 0
        self._kis_api_obj = None
        self._toss_api_obj = None
        self._engine_obj = None
        self._daytrade_obj = None

        # 테이블 자동 생성 + 스키마 마이그레이션
        # dev 모드에서 exec()로 재생성돼도 sys 모듈 속성은 살아남으므로 1회만 실행
        import sys as _sys, os as _os
        _init_key = f"_trading_struct_tables_ok_{_os.getpid()}"
        if not getattr(_sys, _init_key, False):
            self._init_tables()
            setattr(_sys, _init_key, True)
        self._migrate_schema()

        # 설정 캐시 초기 로드 (싱글톤이므로 최초 1회만 실행)
        if not Struct._cfg_ready:
            self._load_config_cache()
        self._seal_daytrade_runtime()

        # 서버 상주형 단타 자동매매 워커 시작
        self._ensure_background_worker()

    def _load_config_cache(self):
        """trading_config 전체를 한 번에 로드 — 수십 회 DB 쿼리를 0회로 줄임"""
        try:
            db = self.orm.use("trading_config", module="trading")
            rows = db.rows(dump=1000)
            Struct._cfg = {r["key"]: r["value"] for r in (rows or [])}
            Struct._cfg_ready = True
        except Exception:
            Struct._cfg = {}
            Struct._cfg_ready = False

    def _current_user_id(self):
        try:
            session = wiz.model("portal/season/session").use()
            return str(session.get("id", "") or "").strip()
        except Exception:
            return ""

    def _current_user_is_admin(self, user_id=None):
        try:
            user_id = str(user_id or self._current_user_id() or "").strip()
            if user_id == "":
                return False
            user = self.orm.use("user").get(id=user_id)
            role = str((user or {}).get("role", "") or "").lower()
            email = str((user or {}).get("email", "") or "").strip().lower()
            return role == "admin" or email == "gigukbyun@gmail.com"
        except Exception:
            return False

    def _is_user_scoped_config_key(self, key):
        return str(key or "") in USER_SCOPED_CONFIG_KEYS

    def _user_config_key(self, user_id, key):
        return f"user:{str(user_id or '').strip()}:{key}"

    def _lookup_config_value(self, storage_key, missing=_CONFIG_MISSING):
        """캐시/DB에서 실제 저장 키 기준으로 조회한다."""
        if not Struct._cfg_ready:
            self._load_config_cache()
        if storage_key in Struct._cfg:
            return Struct._cfg.get(storage_key, "")
        # 캐시 미스: DB 단건 조회 후 캐시 갱신
        try:
            db = self.orm.use("trading_config", module="trading")
            row = db.get(key=storage_key)
            if row is None:
                return missing
            value = row.get("value", "")
            Struct._cfg[storage_key] = value
            return value
        except Exception:
            return missing

    def _write_config_value(self, storage_key, value, description="", is_secret=False):
        now = _kst_now()
        try:
            db = self.orm.use("trading_config", module="trading")
            existing = db.get(key=storage_key)
            if existing:
                db.update({"value": str(value), "description": description, "is_secret": is_secret, "updated": now}, id=existing["id"])
            else:
                db.insert({"key": storage_key, "value": str(value), "description": description, "is_secret": is_secret, "created": now, "updated": now})
        except Exception:
            pass
        Struct._cfg[storage_key] = str(value)

    def get_config(self, key, default=None):
        """캐시에서 config 읽기. 브로커/API 설정은 로그인 사용자별로 분리한다."""
        key = str(key or "")
        if self._is_user_scoped_config_key(key):
            user_id = self._current_user_id()
            if user_id:
                storage_key = self._user_config_key(user_id, key)
                scoped_value = self._lookup_config_value(storage_key, _CONFIG_MISSING)
                if scoped_value is not _CONFIG_MISSING:
                    return scoped_value

                if self._current_user_is_admin(user_id):
                    legacy_value = self._lookup_config_value(key, _CONFIG_MISSING)
                    if legacy_value is not _CONFIG_MISSING:
                        self._write_config_value(storage_key, legacy_value, f"User-scoped copy of {key}", key.endswith("_secret") or "token" in key or "key" in key or "account" in key)
                        return legacy_value
                return default

        value = self._lookup_config_value(key, _CONFIG_MISSING)
        if value is _CONFIG_MISSING:
            return default
        return value

    def set_config(self, key, value, description="", is_secret=False):
        """config 쓰기 → DB 반영 + 캐시 즉시 갱신"""
        key = str(key or "")
        if DAYTRADE_HARD_LOCKED and key in DAYTRADE_ENABLE_KEYS:
            value = "false"
        storage_keys = [key]
        user_id = self._current_user_id() if self._is_user_scoped_config_key(key) else ""
        if user_id:
            storage_keys = [self._user_config_key(user_id, key)]
            if self._current_user_is_admin(user_id):
                storage_keys.append(key)
        for storage_key in storage_keys:
            self._write_config_value(storage_key, value, description, is_secret)

        if key in USER_SCOPED_CONFIG_KEYS:
            if key.startswith("kis_"):
                self._kis_api_obj = None
            if key.startswith("toss_"):
                self._toss_api_obj = None
            if key == "broker_provider":
                self._kis_api_obj = None
                self._toss_api_obj = None
        auto_keys = {
            "daytrade_auto_enabled",
            "daytrade_exit_watch_enabled",
            "daytrade_us_auto_enabled",
            "us_daytrade_auto_enabled",
            "daytrade_us_exit_watch_enabled",
            "us_daytrade_exit_watch_enabled",
            "loc_auto_schedule_enabled",
            "fire_gate_bridge",
        }
        if key in auto_keys and str(value).lower() == "true":
            self._ensure_background_worker()
            Struct._worker_force_run = True
            self._worker_state()["force_run"] = True

    @property
    def daytrade_hard_locked(self):
        return DAYTRADE_HARD_LOCKED

    @property
    def daytrade_lock_message(self):
        return DAYTRADE_LOCK_MESSAGE

    def _seal_daytrade_runtime(self):
        if DAYTRADE_HARD_LOCKED is False:
            return
        for key in DAYTRADE_ENABLE_KEYS:
            try:
                if str(Struct._cfg.get(key, "false") or "false").lower() != "false":
                    self.set_config(key, "false", description="Daytrade hard locked")
                else:
                    Struct._cfg[key] = "false"
            except Exception:
                Struct._cfg[key] = "false"

    def _worker_state(self):
        key = "_trading_daytrade_worker_state"
        state = getattr(_sys, key, None)
        if isinstance(state, dict) is False:
            state = {
                "generation": 0,
                "engine_id": 0,
                "daytrade_model_id": 0,
                "thread": None,
                "force_run": False,
                "last_run_at": "",
                "last_result": {},
                "last_firegate_sync_at": "",
                "last_firegate_sync_ts": 0.0,
            }
            setattr(_sys, key, state)
        return state

    def _callable_accepts_kwarg(self, func, kwarg):
        if callable(func) is False:
            return False
        try:
            signature = inspect.signature(func)
        except Exception:
            return False
        return kwarg in signature.parameters

    def _firegate_sync_config(self):
        try:
            fg = wiz.model("portal/trading/struct/firegate_bridge")
            cfg = fg.load_bridge_config(self)
        except Exception:
            cfg = {}
        enabled = bool(cfg.get("enabled")) and bool(cfg.get("auto_sync_enabled", True)) and bool(cfg.get("email"))
        try:
            interval_sec = int(float(cfg.get("auto_sync_interval_sec", 600) or 600))
        except Exception:
            interval_sec = 600
        return {
            "enabled": enabled,
            "interval_sec": max(30, interval_sec),
            "configured": bool(cfg.get("email") and (cfg.get("id_token") or cfg.get("refresh_token"))),
        }

    def run_due_firegate_sync(self, symbol_filter=""):
        cfg = self._firegate_sync_config()
        if cfg.get("enabled") is False:
            return {"enabled": False, "executed": False, "message": "FireGate 자동 동기화 비활성"}
        fg = wiz.model("portal/trading/struct/firegate_bridge")
        sync_fn = getattr(fg, "sync_firegate_authoritative", None) or fg.sync_portfolios_to_local
        result = sync_fn(self, symbol_filter=symbol_filter)
        # FireGate pull can rewrite the same local rows on every poll. The
        # broker verification signature below is the authoritative reset signal.
        return {
            **(result or {}),
            "enabled": True,
            "executed": bool((result or {}).get("executed", False)),
            "interval_sec": cfg.get("interval_sec", 600),
        }

    def _run_loc_reservation_pre_sync(self, symbol_filter=""):
        authoritative = str(self.get_config("firegate_authoritative_reservations_only", "false") or "false").lower() in ("1", "true", "yes", "y", "on")
        if authoritative:
            external_result = {
                "enabled": True,
                "executed": False,
                "skipped": True,
                "message": "예약 검증은 FireGate 원본 기준으로 수행하므로 KIS 체결 동기화는 별도 루틴에서 처리합니다.",
            }
        else:
            external_result = self.run_due_external_cycle_sync(force=True)
        if symbol_filter and self._callable_accepts_kwarg(getattr(self, "run_due_firegate_sync", None), "symbol_filter"):
            firegate_result = self.run_due_firegate_sync(symbol_filter=symbol_filter)
        else:
            firegate_result = self.run_due_firegate_sync()
        return external_result, firegate_result

    def _ensure_background_worker(self):
        state = self._worker_state()
        with Struct._worker_lock:
            worker = state.get("thread")
            cached_engine_id = int(state.get("engine_id", 0) or 0)
            cached_daytrade_id = int(state.get("daytrade_model_id", 0) or 0)
            current_engine_id = id(self._daytrade_engine_model())
            current_daytrade_id = id(self._daytrade_model())
            if worker is not None and worker.is_alive() and cached_engine_id == current_engine_id and cached_daytrade_id == current_daytrade_id and cached_engine_id > 0:
                Struct._worker_started = True
                Struct._worker_thread = worker
                Struct._worker_engine_id = cached_engine_id
                Struct._worker_daytrade_id = cached_daytrade_id
                return
            generation = int(state.get("generation", 0) or 0) + 1
            state["generation"] = generation
            state["engine_id"] = current_engine_id
            state["daytrade_model_id"] = current_daytrade_id
            state["force_run"] = True
            thread = threading.Thread(target=self._background_worker_loop, args=(generation,), daemon=True, name="trading-daytrade-worker")
            thread.start()
            state["thread"] = thread
            Struct._worker_thread = thread
            Struct._worker_started = True
            Struct._worker_engine_id = current_engine_id
            Struct._worker_daytrade_id = current_daytrade_id
            Struct._worker_force_run = True

    def _worker_interval_sec(self):
        try:
            value = int(float(self.get_config("daytrade_auto_interval_sec", "15") or 15))
        except Exception:
            value = 15
        return max(5, value)

    def _write_worker_status_snapshot(self, payload):
        try:
            import json as _json
            fs = wiz.project.fs()
            fs.makedirs("data/daytrade")
            safe_payload = _json.loads(_json.dumps(payload or {}, ensure_ascii=False, default=str))
            fs.write.json("data/daytrade/worker_status.json", safe_payload)
        except Exception:
            pass

    def _us_auto_enabled(self):
        if DAYTRADE_HARD_LOCKED:
            return False
        if self._daytrade_feature_enabled() is False:
            return False
        modern = str(self.get_config("daytrade_us_auto_enabled", "")).lower()
        legacy = str(self.get_config("us_daytrade_auto_enabled", "")).lower()
        if modern in ["true", "false"]:
            return modern == "true"
        if legacy in ["true", "false"]:
            return legacy == "true"
        return False

    def _us_exit_watch_enabled(self):
        if DAYTRADE_HARD_LOCKED:
            return False
        if self._daytrade_feature_enabled() is False:
            return False
        modern = str(self.get_config("daytrade_us_exit_watch_enabled", "")).lower()
        legacy = str(self.get_config("us_daytrade_exit_watch_enabled", "")).lower()
        if modern in ["true", "false"]:
            return modern == "true"
        if legacy in ["true", "false"]:
            return legacy == "true"
        return True

    def _daytrade_feature_enabled(self):
        if DAYTRADE_HARD_LOCKED:
            return False
        return str(self.get_config("daytrade_feature_enabled", "false") or "false").lower() in ("1", "true", "yes", "y", "on")

    def _kr_exit_watch_effective_enabled(self):
        if self._daytrade_feature_enabled() is False:
            return False
        auto_enabled = str(self.get_config("daytrade_auto_enabled", "false")).lower() == "true"
        exit_watch_enabled = str(self.get_config("daytrade_exit_watch_enabled", "false")).lower() == "true"
        return auto_enabled and exit_watch_enabled

    def _us_exit_watch_effective_enabled(self):
        return self._us_auto_enabled() and self._us_exit_watch_enabled()

    def _run_daytrade_auto_once(self, market="KS"):
        if DAYTRADE_HARD_LOCKED:
            return {"executed": False, "message": DAYTRADE_LOCK_MESSAGE, "hard_locked": True}
        engine = self.daytrade_engine
        if str(market or "KS").upper() == "US":
            enabled = self._us_auto_enabled()
            seed = float(self.get_config("daytrade_us_default_seed", self.get_config("daytrade_default_seed", "5000000")) or 5000000)
        else:
            enabled = self._daytrade_feature_enabled() and str(self.get_config("daytrade_auto_enabled", "false")).lower() == "true"
            seed = float(self.get_config("daytrade_default_seed", "5000000") or 5000000)
        if enabled is False:
            return {"executed": False, "message": f"{'미장' if str(market or 'KS').upper() == 'US' else '국장'} 단타 자동매매 비활성"}
        result = engine.auto_cycle(requested_seed=seed, market=market)
        return result or {"executed": False, "message": f"{'미장' if str(market or 'KS').upper() == 'US' else '국장'} 단타 자동매매 결과 없음"}

    def _loc_reservation_verify_target(self):
        try:
            return max(3, int(float(self.get_config("loc_reservation_verify_target", "3") or 3)))
        except Exception:
            return 3

    def _loc_reservation_rebuild_cooldown_seconds(self):
        try:
            return max(60, int(float(self.get_config("loc_reservation_rebuild_cooldown_sec", "180") or 180)))
        except Exception:
            return 180

    def _loc_reservation_rebuild_cooldown_remaining(self):
        try:
            until_ts = float(self.get_config("loc_reservation_rebuild_cooldown_until_ts", "0") or 0)
        except Exception:
            until_ts = 0.0
        return max(0.0, until_ts - time.time())

    def _set_loc_reservation_rebuild_cooldown(self, reason=""):
        seconds = self._loc_reservation_rebuild_cooldown_seconds()
        until_ts = time.time() + seconds
        self.set_config(
            "loc_reservation_rebuild_cooldown_until_ts",
            f"{until_ts:.3f}",
            description="LOC reservation rebuild cooldown timestamp",
        )
        self.set_config(
            "loc_reservation_rebuild_cooldown_reason",
            str(reason or ""),
            description="LOC reservation rebuild cooldown reason",
        )
        return seconds

    def _clear_loc_reservation_rebuild_cooldown(self):
        self.set_config(
            "loc_reservation_rebuild_cooldown_until_ts",
            "0",
            description="Clear LOC reservation rebuild cooldown timestamp",
        )

    def _loc_reservation_verification_defaults(self):
        return {
            "loc_reservation_verified_date": "",
            "loc_reservation_verified_version": "",
            "loc_reservation_verified_signature": "",
            "loc_reservation_verified_streak": 0,
            "loc_reservation_verified_target": self._loc_reservation_verify_target(),
            "loc_reservation_verified_complete": False,
            "loc_reservation_verified_last_at": "",
            "loc_reservation_verified_failure_reason": "",
        }

    def _normalize_loc_reservation_verification_state(self, values):
        defaults = self._loc_reservation_verification_defaults()
        data = {**defaults, **(values or {})}
        for key in (
            "loc_reservation_verified_date",
            "loc_reservation_verified_version",
            "loc_reservation_verified_signature",
            "loc_reservation_verified_last_at",
            "loc_reservation_verified_failure_reason",
        ):
            data[key] = str(data.get(key, "") or "")
        for key in ("loc_reservation_verified_streak", "loc_reservation_verified_target"):
            try:
                data[key] = int(float(data.get(key, defaults.get(key, 0)) or 0))
            except Exception:
                data[key] = int(defaults.get(key, 0) or 0)
        complete_raw = data.get("loc_reservation_verified_complete", False)
        if isinstance(complete_raw, bool):
            data["loc_reservation_verified_complete"] = complete_raw
        else:
            data["loc_reservation_verified_complete"] = str(complete_raw or "").lower() in ("1", "true", "yes", "y", "on")
        return data

    def _loc_reservation_verification_state(self):
        state = self._worker_state()
        defaults = self._loc_reservation_verification_defaults()
        values = {}
        for key, default in defaults.items():
            stored = self.get_config(key, _CONFIG_MISSING)
            if stored is _CONFIG_MISSING:
                stored = state.get(key, default)
            values[key] = stored
        normalized = self._normalize_loc_reservation_verification_state(values)
        state.update(normalized)
        return normalized

    def _set_loc_reservation_verification_state(self, updates):
        normalized = self._normalize_loc_reservation_verification_state(updates)
        self._worker_state().update(normalized)
        for key, value in normalized.items():
            if isinstance(value, bool):
                stored = "true" if value else "false"
            else:
                stored = str(value if value is not None else "")
            self.set_config(key, stored, description="LOC reservation verification state")
        return normalized

    def _loc_reservation_verified_done(self, schedule_key):
        state = self._loc_reservation_verification_state()
        target = self._loc_reservation_verify_target()
        streak = int(state.get("loc_reservation_verified_streak", 0) or 0)
        return (
            str(state.get("loc_reservation_verified_date", "") or "") == str(schedule_key or "")
            and str(state.get("loc_reservation_verified_version", "") or "") == _LOC_RESERVATION_VERIFY_VERSION
            and streak >= target
            and str(state.get("loc_reservation_verified_signature", "") or "") != ""
        )

    def _record_loc_reservation_verification(self, schedule_key, buy_result, sell_result, rebuild_result=None, verify_only=False):
        state = self._loc_reservation_verification_state()
        target = self._loc_reservation_verify_target()
        signature = _loc_reservation_verification_signature(buy_result, sell_result)
        rebuild_executed = bool((rebuild_result or {}).get("executed", False))
        passed = (
            bool(verify_only)
            and rebuild_executed is False
            and _loc_result_verified_for_streak(buy_result)
            and _loc_result_verified_for_streak(sell_result)
        )
        if passed:
            prev_date = str(state.get("loc_reservation_verified_date", "") or "")
            prev_signature = str(state.get("loc_reservation_verified_signature", "") or "")
            prev_streak = int(state.get("loc_reservation_verified_streak", 0) or 0)
            streak = prev_streak + 1 if prev_date == schedule_key and prev_signature == signature else 1
            self._set_loc_reservation_verification_state({
                "loc_reservation_verified_date": schedule_key,
                "loc_reservation_verified_version": _LOC_RESERVATION_VERIFY_VERSION,
                "loc_reservation_verified_signature": signature,
                "loc_reservation_verified_streak": streak,
                "loc_reservation_verified_target": target,
                "loc_reservation_verified_complete": streak >= target,
                "loc_reservation_verified_last_at": _kst_now().strftime("%Y-%m-%d %H:%M:%S"),
                "loc_reservation_verified_failure_reason": "",
            })
            return {
                "passed": True,
                "complete": streak >= target,
                "streak": streak,
                "target": target,
                "signature": signature,
                "message": f"LOC 예약 {streak}/{target}회 연속 일치 검증",
            }

        reasons = []
        buy_reason = _loc_result_failure_reason(buy_result, "buy")
        sell_reason = _loc_result_failure_reason(sell_result, "sell")
        if buy_reason:
            reasons.append(buy_reason)
        if sell_reason:
            reasons.append(sell_reason)
        if rebuild_executed:
            reasons.append("rebuild_executed")
        if verify_only is False:
            reasons.append("not_verification_pass")
        reason = "; ".join(reasons) or "verification_not_clean"
        self._set_loc_reservation_verification_state({
            "loc_reservation_verified_date": schedule_key,
            "loc_reservation_verified_version": _LOC_RESERVATION_VERIFY_VERSION,
            "loc_reservation_verified_signature": signature,
            "loc_reservation_verified_streak": 0,
            "loc_reservation_verified_target": target,
            "loc_reservation_verified_complete": False,
            "loc_reservation_verified_last_at": _kst_now().strftime("%Y-%m-%d %H:%M:%S"),
            "loc_reservation_verified_failure_reason": reason,
        })
        return {
            "passed": False,
            "complete": False,
            "streak": 0,
            "target": target,
            "signature": signature,
            "message": f"LOC 예약 연속 검증 리셋: {reason}",
            "reason": reason,
        }

    def _verify_loc_reservations_now(self, engine, schedule_key):
        """Verify broker echo immediately after a rebuild without submitting new orders."""
        target = self._loc_reservation_verify_target()
        passes = []
        final_verification = {
            "passed": False,
            "complete": False,
            "streak": 0,
            "target": target,
            "message": "예약 검증 전",
        }
        last_buy = {}
        last_sell = {}
        for attempt in range(target):
            if attempt > 0:
                time.sleep(1.0)
            if self._callable_accepts_kwarg(getattr(engine, "schedule_loc_buys", None), "allow_new_orders"):
                last_buy = engine.schedule_loc_buys(allow_new_orders=False)
            else:
                last_buy = engine.schedule_loc_buys()
            if self._callable_accepts_kwarg(getattr(engine, "schedule_loc_sells", None), "allow_new_orders"):
                last_sell = engine.schedule_loc_sells(allow_new_orders=False)
            else:
                last_sell = engine.schedule_loc_sells()
            final_verification = self._record_loc_reservation_verification(
                schedule_key,
                last_buy,
                last_sell,
                {"executed": False},
                verify_only=True,
            )
            passes.append({
                "attempt": attempt + 1,
                "verification": dict(final_verification),
                "buy_status": (last_buy or {}).get("status", ""),
                "buy_expected_count": int(float((last_buy or {}).get("expected_count", 0) or 0)),
                "buy_missing_count": int(float((last_buy or {}).get("missing_count", 0) or 0)),
                "buy_error_count": int(float((last_buy or {}).get("error_count", 0) or 0)),
                "sell_status": (last_sell or {}).get("status", ""),
                "sell_expected_count": int(float((last_sell or {}).get("expected_count", 0) or 0)),
                "sell_missing_count": int(float((last_sell or {}).get("missing_count", 0) or 0)),
                "sell_error_count": int(float((last_sell or {}).get("error_count", 0) or 0)),
            })
            if final_verification.get("passed") is False:
                break
            if final_verification.get("complete"):
                break
        return {
            **final_verification,
            "passes": passes,
            "buy": last_buy or {},
            "sell": last_sell or {},
        }

    def _loc_reservation_lock_name(self):
        return "stock8_loc_reservation_rebuild"

    @contextlib.contextmanager
    def _loc_reservation_lock(self, timeout_sec=1):
        depth = int(getattr(self, "_loc_reservation_lock_depth", 0) or 0)
        if depth > 0:
            self._loc_reservation_lock_depth = depth + 1
            try:
                yield True
            finally:
                self._loc_reservation_lock_depth = depth
            return

        conn = None
        acquired = False
        process_lock_acquired = False
        lock_name = self._loc_reservation_lock_name()

        def _cfg_get(cfg, key, default=None):
            try:
                if hasattr(cfg, key):
                    return getattr(cfg, key)
            except Exception:
                pass
            try:
                return cfg.get(key, default)
            except Exception:
                return default

        try:
            try:
                import pymysql
                db_cfg = wiz.config("database").get("trading")
                conn = pymysql.connect(
                    host=_cfg_get(db_cfg, "host", "127.0.0.1"),
                    port=int(_cfg_get(db_cfg, "port", 3306) or 3306),
                    user=_cfg_get(db_cfg, "user", ""),
                    password=_cfg_get(db_cfg, "password", ""),
                    database=_cfg_get(db_cfg, "database", ""),
                    charset=_cfg_get(db_cfg, "charset", "utf8mb4"),
                    connect_timeout=3,
                    read_timeout=max(5, int(timeout_sec or 1) + 5),
                    write_timeout=5,
                    autocommit=True,
                )
                with conn.cursor() as cur:
                    cur.execute("SELECT GET_LOCK(%s, %s)", (lock_name, int(timeout_sec or 0)))
                    row = cur.fetchone()
                    acquired = bool(row and int(row[0] or 0) == 1)
                if acquired:
                    self._loc_reservation_lock_depth = 1
            except Exception:
                acquired = False
            if acquired is False:
                try:
                    process_lock_acquired = _LOC_RESERVATION_PROCESS_LOCK.acquire(timeout=max(0, int(timeout_sec or 0)))
                    acquired = process_lock_acquired
                    if acquired:
                        self._loc_reservation_lock_depth = 1
                except Exception:
                    acquired = False
            yield acquired
        finally:
            if acquired and conn is not None:
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
                except Exception:
                    pass
            if acquired:
                self._loc_reservation_lock_depth = 0
            if process_lock_acquired:
                try:
                    _LOC_RESERVATION_PROCESS_LOCK.release()
                except Exception:
                    pass
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _loc_reservation_locked_result(self, reason=""):
        now = _kst_now()
        schedule_key = _loc_schedule_key(now)
        schedule_window = _loc_reservation_window_label(now)
        scheduled_at = _loc_reservation_next_start_label()
        message = "다른 예약 검증/취소/재예약 작업이 진행 중이라 이번 호출은 건너뜁니다. 기존 작업이 끝난 뒤 다음 5분 검증에서 다시 확인합니다."
        return {
            "enabled": True,
            "executed": False,
            "scheduled": False,
            "waiting": True,
            "locked": True,
            "status": "locked",
            "reason": reason,
            "scheduled_at": scheduled_at,
            "schedule_window": schedule_window,
            "schedule_key": schedule_key,
            "verified": False,
            "verification_complete": False,
            "message": message,
            "verification": {
                "passed": False,
                "complete": False,
                "streak": 0,
                "target": self._loc_reservation_verify_target(),
                "reason": "reservation_lock_held",
                "message": message,
            },
            "buy": {"enabled": True, "scheduled": False, "status": "locked", "message": message},
            "sell": {"enabled": True, "scheduled": False, "status": "locked", "message": message},
            "rebuild": {"executed": False, "status": "locked", "message": message, "symbols": []},
        }

    def run_due_loc_automation(self, force=False, reason="worker", verify=False, symbols=None):
        with self._loc_reservation_lock(timeout_sec=1) as acquired:
            if acquired is False:
                return self._loc_reservation_locked_result(reason=reason)
            return self._run_due_loc_automation_unlocked(force=force, reason=reason, verify=verify, symbols=symbols)

    def _run_due_loc_automation_unlocked(self, force=False, reason="worker", verify=False, symbols=None):
        """한투 미국주식 예약주문 가능시간에 무한매수 LOC 예약을 검증/복구한다."""
        symbols = [str(symbol or "").upper().strip() for symbol in (symbols or []) if str(symbol or "").strip()]
        symbols = list(dict.fromkeys(symbols))
        symbol_filter = symbols[0] if len(symbols) == 1 else ""
        now = _kst_now()
        schedule_key = _loc_schedule_key(now)
        market_day = now - _dt.timedelta(days=1) if now.hour < 7 else now
        schedule_window = _loc_reservation_window_label(now)
        scheduled_at = _loc_reservation_next_start_label()
        verify_only = bool(verify or "reservation_verify" in str(reason or ""))
        auto_trade_enabled = str(self.get_config("auto_trade_enabled", "false") or "false").lower() == "true"
        loc_enabled = str(self.get_config("loc_auto_schedule_enabled", "true") or "true").lower() == "true"
        if auto_trade_enabled is False:
            return {"enabled": False, "executed": False, "message": "무한매수 매매 OFF"}
        if loc_enabled is False:
            return {"enabled": False, "executed": False, "message": "LOC 자동 예약 비활성"}
        if market_day.weekday() >= 5:
            return {"enabled": True, "executed": False, "waiting": True, "message": "주말이라 LOC 자동 예약 대기 중입니다.", "scheduled_at": scheduled_at, "schedule_window": schedule_window}
        try:
            holiday = ""
            broker = self.broker_api
            if hasattr(broker, "us_market_holiday_label"):
                holiday = str(broker.us_market_holiday_label(market_day) or "")
            if holiday:
                return {
                    "enabled": True,
                    "executed": False,
                    "waiting": True,
                    "message": f"미국 휴장일({holiday})이라 LOC 자동 예약을 대기합니다.",
                    "scheduled_at": f"다음 미국 거래일 {scheduled_at}",
                    "schedule_window": schedule_window,
                    "holiday": holiday,
                }
        except Exception:
            pass
        window_state = _loc_reservation_window_state(now)
        if window_state != "open":
            if window_state == "before":
                message = f"{schedule_window} 전이라 LOC 자동 예약 대기 중입니다."
            else:
                message = f"{schedule_window} 예약 접수시간이 지나 다음 예약 가능시간까지 대기합니다."
            return {"enabled": True, "executed": False, "waiting": True, "message": message, "scheduled_at": scheduled_at, "schedule_window": schedule_window}

        if verify_only and force is False:
            cooldown_remaining = self._loc_reservation_rebuild_cooldown_remaining()
            if cooldown_remaining > 0:
                cooldown_remaining_sec = int(cooldown_remaining + 0.999)
                self._set_loc_reservation_verification_state({
                    "loc_reservation_verified_date": schedule_key,
                    "loc_reservation_verified_version": _LOC_RESERVATION_VERIFY_VERSION,
                    "loc_reservation_verified_signature": "",
                    "loc_reservation_verified_streak": 0,
                    "loc_reservation_verified_target": self._loc_reservation_verify_target(),
                    "loc_reservation_verified_complete": False,
                    "loc_reservation_verified_last_at": _kst_now().strftime("%Y-%m-%d %H:%M:%S"),
                    "loc_reservation_verified_failure_reason": "broker_echo_cooldown",
                })
                message = f"방금 예약한 주문의 브로커 반영 대기 중입니다. {cooldown_remaining_sec}초 뒤 다시 FireGate 기준으로 검증합니다."
                cooldown_result = {
                    "enabled": True,
                    "scheduled": False,
                    "status": "cooldown_wait",
                    "scheduled_at": scheduled_at,
                    "schedule_window": schedule_window,
                    "schedule_key": schedule_key,
                    "verified": False,
                    "message": message,
                    "cooldown": True,
                    "cooldown_remaining_sec": cooldown_remaining_sec,
                }
                verification = {
                    "passed": False,
                    "complete": False,
                    "streak": 0,
                    "target": self._loc_reservation_verify_target(),
                    "message": "브로커 예약 반영 대기 중이라 이번 검증은 보류했습니다.",
                    "reason": "broker_echo_cooldown",
                }
                return {
                    "enabled": True,
                    "executed": False,
                    "verified": False,
                    "verification_complete": False,
                    "waiting": True,
                    "status": "cooldown_wait",
                    "scheduled_at": scheduled_at,
                    "schedule_window": schedule_window,
                    "schedule_key": schedule_key,
                    "message": message,
                    "verification": verification,
                    "buy": dict(cooldown_result),
                    "sell": dict(cooldown_result),
                    "rebuild": {
                        "executed": False,
                        "message": message,
                        "attempt_count": int(float(self.get_config("loc_reservation_rebuild_attempts", "0") or 0)),
                        "threshold": max(1, int(float(self.get_config("loc_reservation_rebuild_threshold", "3") or 3))),
                        "symbols": [],
                        "cooldown": True,
                        "cooldown_remaining_sec": cooldown_remaining_sec,
                    },
                }

        engine = self.engine
        buy_last_date = str(self.get_config("loc_buy_auto_schedule_last_date", "") or "")
        sell_last_date = str(self.get_config("loc_auto_schedule_last_date", "") or "")
        buy_result = {
            "enabled": True,
            "scheduled": False,
            "message": "오늘 LOC 자동 예약매수는 이미 접수했습니다." if buy_last_date == schedule_key and force is False else "LOC 자동 예약매수 대상 없음",
            "scheduled_at": scheduled_at,
            "schedule_window": schedule_window,
            "schedule_key": schedule_key,
        }
        sell_result = {
            "enabled": True,
            "scheduled": False,
            "message": "오늘 LOC 자동 예약매도는 이미 접수했습니다." if sell_last_date == schedule_key else "LOC 자동 예약매도 대상 없음",
            "scheduled_at": scheduled_at,
            "schedule_window": schedule_window,
            "schedule_key": schedule_key,
        }

        buy_attempted = False
        sell_attempted = False
        rebuild_result = {
            "executed": False,
            "message": "재예약 조건 미충족",
            "attempt_count": 0,
            "threshold": int(float(self.get_config("loc_reservation_rebuild_threshold", "3") or 3)),
            "symbols": [],
        }
        verification_result = {
            "passed": False,
            "complete": False,
            "streak": int(self._loc_reservation_verification_state().get("loc_reservation_verified_streak", 0) or 0),
            "target": self._loc_reservation_verify_target(),
            "message": "예약 검증 전",
        }

        if force and verify_only is False:
            try:
                external_result, firegate_result = self._run_loc_reservation_pre_sync(symbol_filter=symbol_filter)
                if self._callable_accepts_kwarg(getattr(engine, "rebuild_loc_reservations", None), "symbols"):
                    raw_rebuild = engine.rebuild_loc_reservations(symbols=symbols)
                else:
                    raw_rebuild = engine.rebuild_loc_reservations()
                cooldown_sec = 0
                post_rebuild_verification = {"passed": False, "complete": False, "streak": 0, "target": self._loc_reservation_verify_target(), "message": "강제 재예약 후 검증 전"}
                status = str((raw_rebuild or {}).get("status", "") or "").lower()
                if status == "completed":
                    self.set_config("loc_buy_auto_schedule_last_date", schedule_key, description="Last auto LOC buy schedule date")
                    self.set_config("loc_auto_schedule_last_date", schedule_key, description="Last auto LOC sell schedule date")
                    self.set_config("loc_reservation_rebuild_attempts", "0", description="Reset LOC reservation rebuild attempt count")
                    post_rebuild_verification = self._verify_loc_reservations_now(engine, schedule_key)
                    if post_rebuild_verification.get("complete"):
                        self._clear_loc_reservation_rebuild_cooldown()
                    else:
                        cooldown_sec = self._set_loc_reservation_rebuild_cooldown("forced_rebuild")
                else:
                    cooldown_sec = self._set_loc_reservation_rebuild_cooldown("forced_rebuild")
                return {
                    "enabled": True,
                    "executed": True,
                    "scheduled": True,
                    "forced": True,
                    "reason": reason,
                    "scheduled_at": scheduled_at,
                    "schedule_window": schedule_window,
                    "schedule_key": schedule_key,
                    "status": status or "completed",
                    "message": "예약 재검증 — 기존 예약 전체 취소 후 FireGate 기준 재예약",
                    "verification": post_rebuild_verification,
                    "external_cycle_sync": external_result,
                    "firegate_sync": firegate_result,
                    "rebuild": raw_rebuild or {},
                    "rebuild_cooldown_sec": cooldown_sec,
                }
            except Exception as e:
                return {
                    "enabled": True,
                    "executed": False,
                    "scheduled": False,
                    "forced": True,
                    "reason": reason,
                    "scheduled_at": scheduled_at,
                    "schedule_window": schedule_window,
                    "schedule_key": schedule_key,
                    "status": "error",
                    "message": str(e),
                    "error_count": 1,
                    "errors": [{"reason": str(e)}],
                }

        if verify_only or force or buy_last_date != schedule_key:
            buy_attempted = True
            try:
                external_result, firegate_result = self._run_loc_reservation_pre_sync(symbol_filter=symbol_filter)
                buy_fn = getattr(engine, "schedule_loc_buys", None)
                buy_kwargs = {}
                if symbol_filter and self._callable_accepts_kwarg(buy_fn, "symbol_filter"):
                    buy_kwargs["symbol_filter"] = symbol_filter
                if self._callable_accepts_kwarg(buy_fn, "allow_new_orders"):
                    buy_kwargs["allow_new_orders"] = not verify_only
                raw_buy_result = buy_fn(**buy_kwargs)
                buy_result = {
                    "enabled": True,
                    "scheduled": True,
                    "scheduled_at": scheduled_at,
                    "schedule_window": schedule_window,
                    "schedule_key": schedule_key,
                    "forced": bool(force and verify_only is False),
                    "verified": bool(verify_only),
                    "reason": reason,
                    "external_cycle_sync": external_result,
                    "firegate_sync": firegate_result,
                    **(raw_buy_result or {}),
                }
                if _loc_schedule_mark_done(raw_buy_result):
                    self.set_config("loc_buy_auto_schedule_last_date", schedule_key, description="Last auto LOC buy schedule date")
                elif force and buy_last_date == schedule_key:
                    self.set_config("loc_buy_auto_schedule_last_date", "", description="Reset incomplete auto LOC buy schedule date")
            except Exception as e:
                buy_result = {
                    "enabled": True,
                    "scheduled": False,
                    "scheduled_at": scheduled_at,
                    "schedule_window": schedule_window,
                    "schedule_key": schedule_key,
                    "forced": bool(force and verify_only is False),
                    "verified": bool(verify_only),
                    "status": "error",
                    "error_count": 1,
                    "message": str(e),
                    "orders": [],
                    "errors": [{"reason": str(e)}],
                }

        if verify_only or force or sell_last_date != schedule_key:
            sell_attempted = True
            try:
                sell_fn = getattr(engine, "schedule_loc_sells", None)
                sell_kwargs = {}
                if symbol_filter and self._callable_accepts_kwarg(sell_fn, "symbol_filter"):
                    sell_kwargs["symbol_filter"] = symbol_filter
                if self._callable_accepts_kwarg(sell_fn, "allow_new_orders"):
                    sell_kwargs["allow_new_orders"] = not verify_only
                raw_sell_result = sell_fn(**sell_kwargs)
                sell_result = {
                    "enabled": True,
                    "scheduled": True,
                    "scheduled_at": scheduled_at,
                    "schedule_window": schedule_window,
                    "schedule_key": schedule_key,
                    "forced": bool(force and verify_only is False),
                    "verified": bool(verify_only),
                    "reason": reason,
                    **(raw_sell_result or {}),
                }
                if _loc_schedule_mark_done(raw_sell_result):
                    self.set_config("loc_auto_schedule_last_date", schedule_key, description="Last auto LOC sell schedule date")
                elif force and sell_last_date == schedule_key:
                    self.set_config("loc_auto_schedule_last_date", "", description="Reset incomplete auto LOC sell schedule date")
            except Exception as e:
                sell_result = {
                    "enabled": True,
                    "scheduled": False,
                    "scheduled_at": scheduled_at,
                    "schedule_window": schedule_window,
                    "schedule_key": schedule_key,
                    "forced": bool(force and verify_only is False),
                    "verified": bool(verify_only),
                    "status": "error",
                    "error_count": 1,
                    "message": str(e),
                    "orders": [],
                    "errors": [{"reason": str(e)}],
                }

        if buy_attempted or sell_attempted:
            try:
                buy_done = True if buy_attempted is False else _loc_schedule_mark_done(buy_result)
                sell_done = True if sell_attempted is False else _loc_schedule_mark_done(sell_result)
                problem_symbols = _loc_schedule_problem_symbols(buy_result, sell_result)
                incomplete = (buy_done and sell_done) is False
                force_rebuild = _loc_schedule_force_rebuild(buy_result, sell_result)
                threshold = max(1, int(float(self.get_config("loc_reservation_rebuild_threshold", "3") or 3)))
                if force_rebuild or (force and verify_only is False):
                    threshold = 1
                if verify_only:
                    threshold = 1
                attempt_count = 0
                new_order_count = _loc_result_new_order_count(buy_result, sell_result)
                if new_order_count > 0:
                    self._set_loc_reservation_rebuild_cooldown("new_orders_submitted")
                broker_snapshot_empty = (
                    verify_only
                    and _loc_result_all_missing_without_broker_signal(buy_result)
                    and _loc_result_all_missing_without_broker_signal(sell_result)
                )
                if broker_snapshot_empty:
                    rebuild_result = {
                        "executed": False,
                        "status": "broker_query_empty",
                        "message": "브로커 예약조회가 매수/매도 모두 0건으로 응답해 자동 전체 재예약을 보류했습니다. 다음 주기에 다시 조회합니다.",
                        "attempt_count": int(float(self.get_config("loc_reservation_rebuild_attempts", "0") or 0)),
                        "threshold": threshold,
                        "symbols": problem_symbols,
                        "force_rebuild": False,
                        "broker_query_empty": True,
                    }
                elif incomplete and problem_symbols:
                    cooldown_remaining = self._loc_reservation_rebuild_cooldown_remaining()
                    if cooldown_remaining > 0 and force_rebuild is False and bool(force and verify_only is False) is False:
                        attempt_count = int(float(self.get_config("loc_reservation_rebuild_attempts", "0") or 0))
                        cooldown_remaining_sec = int(cooldown_remaining + 0.999)
                        rebuild_result = {
                            "executed": False,
                            "message": f"방금 예약한 주문의 브로커 반영 대기 중입니다. {cooldown_remaining_sec}초 뒤에도 FireGate와 다르면 전체 취소 후 재예약합니다.",
                            "attempt_count": attempt_count,
                            "threshold": threshold,
                            "symbols": problem_symbols,
                            "force_rebuild": force_rebuild,
                            "cooldown": True,
                            "cooldown_remaining_sec": cooldown_remaining_sec,
                            "new_order_count": new_order_count,
                        }
                    else:
                        attempt_count = int(float(self.get_config("loc_reservation_rebuild_attempts", "0") or 0)) + 1
                        self.set_config(
                            "loc_reservation_rebuild_attempts",
                            str(attempt_count),
                            description="Consecutive incomplete LOC reservation verification count",
                        )
                        rebuild_result = {
                            "executed": False,
                            "message": (
                                "FireGate 외 예약/초과 예약 감지 — 전체 취소 후 즉시 재예약"
                                if force_rebuild else
                                "예약 재검증 실패 — 기존 예약 전체 취소 후 즉시 재예약"
                                if force and verify_only is False else
                                f"LOC 예약 누락 감지 {attempt_count}/{threshold}회 — 임계치 도달 시 전체 취소 후 재예약"
                            ),
                            "attempt_count": attempt_count,
                            "threshold": threshold,
                            "symbols": problem_symbols,
                            "force_rebuild": force_rebuild or bool(force and verify_only is False),
                        }
                        if attempt_count >= threshold:
                            raw_rebuild = engine.rebuild_loc_reservations(problem_symbols)
                            cooldown_sec = self._set_loc_reservation_rebuild_cooldown("rebuild_executed")
                            rebuild_result = {
                                "executed": True,
                                "message": "반복 누락으로 활성 예약 전체 취소 후 재예약 실행",
                                "attempt_count": attempt_count,
                                "threshold": threshold,
                                "symbols": problem_symbols,
                                "cooldown_sec": cooldown_sec,
                                **(raw_rebuild or {}),
                            }
                            self.set_config(
                                "loc_reservation_rebuild_attempts",
                                "0",
                                description="Reset LOC reservation rebuild attempt count",
                            )
                            if str((raw_rebuild or {}).get("status", "") or "").lower() == "completed":
                                self.set_config("loc_buy_auto_schedule_last_date", schedule_key, description="Last auto LOC buy schedule date")
                                self.set_config("loc_auto_schedule_last_date", schedule_key, description="Last auto LOC sell schedule date")
                else:
                    self.set_config(
                        "loc_reservation_rebuild_attempts",
                        "0",
                        description="Reset LOC reservation rebuild attempt count",
                    )
                    if new_order_count <= 0:
                        self._clear_loc_reservation_rebuild_cooldown()
                    rebuild_result = {
                        "executed": False,
                        "message": "LOC 예약 누락 없음",
                        "attempt_count": 0,
                        "threshold": threshold,
                        "symbols": problem_symbols,
                    }
            except Exception as e:
                rebuild_result = {
                    "executed": False,
                    "status": "error",
                    "message": str(e),
                    "attempt_count": int(float(self.get_config("loc_reservation_rebuild_attempts", "0") or 0)),
                    "threshold": int(float(self.get_config("loc_reservation_rebuild_threshold", "3") or 3)),
                    "symbols": _loc_schedule_problem_symbols(buy_result, sell_result),
                    "errors": [{"reason": str(e)}],
                }

            verification_result = self._record_loc_reservation_verification(
                schedule_key,
                buy_result,
                sell_result,
                rebuild_result,
                verify_only=verify_only,
            )

        executed = bool(
            int((buy_result or {}).get("scheduled_count", 0) or 0) > 0
            or int((buy_result or {}).get("already_scheduled_count", 0) or 0) > 0
            or int((sell_result or {}).get("scheduled_count", 0) or 0) > 0
            or int((sell_result or {}).get("already_scheduled_count", 0) or 0) > 0
            or bool((rebuild_result or {}).get("executed", False))
        )
        if buy_attempted or sell_attempted:
            try:
                import json as _json
                summary = {
                    "buy_attempted": buy_attempted,
                    "sell_attempted": sell_attempted,
                    "buy_status": (buy_result or {}).get("status", ""),
                    "buy_scheduled_count": (buy_result or {}).get("scheduled_count", 0),
                    "buy_already_scheduled_count": (buy_result or {}).get("already_scheduled_count", 0),
                    "buy_skipped_count": (buy_result or {}).get("skipped_count", 0),
                    "buy_error_count": (buy_result or {}).get("error_count", 0),
                    "buy_expected_count": (buy_result or {}).get("expected_count", 0),
                    "buy_missing_count": (buy_result or {}).get("missing_count", 0),
                    "sell_status": (sell_result or {}).get("status", ""),
                    "sell_scheduled_count": (sell_result or {}).get("scheduled_count", 0),
                    "sell_already_scheduled_count": (sell_result or {}).get("already_scheduled_count", 0),
                    "sell_error_count": (sell_result or {}).get("error_count", 0),
                    "sell_expected_count": (sell_result or {}).get("expected_count", 0),
                    "sell_missing_count": (sell_result or {}).get("missing_count", 0),
                    "rebuild_executed": (rebuild_result or {}).get("executed", False),
                    "rebuild_attempt_count": (rebuild_result or {}).get("attempt_count", 0),
                    "rebuild_symbols": (rebuild_result or {}).get("symbols", []),
                    "executed": executed,
                    "forced": bool(force and verify_only is False),
                    "verified": bool(verification_result.get("passed", False)),
                    "reason": reason,
                    "schedule_key": schedule_key,
                    "schedule_window": schedule_window,
                    "verification_streak": verification_result.get("streak", 0),
                    "verification_complete": verification_result.get("complete", False),
                }
                message = "LOC 자동 예약 점검 결과: " + _json.dumps(summary, ensure_ascii=False)
                engine._log_event("SYSTEM", "", "LOC_AUTOMATION_RUN", message=message[:1800])
            except Exception:
                pass
        return {"enabled": True, "executed": executed, "scheduled_at": scheduled_at, "schedule_window": schedule_window, "schedule_key": schedule_key, "forced": bool(force and verify_only is False), "verified": bool(verification_result.get("passed", False)), "verification_complete": verification_result.get("complete", False), "verification": verification_result, "buy": buy_result, "sell": sell_result, "rebuild": rebuild_result}

    def run_due_external_cycle_sync(self, force=False):
        """08:00-10:00 KST 사이 10분 단위로 브로커 체결을 사이클에 반영."""
        now = _kst_now()
        state = self._worker_state()
        in_window = _external_cycle_sync_window_open(now)
        if force is False and in_window is False:
            return {
                "enabled": True,
                "executed": False,
                "waiting": True,
                "message": "08:00-10:00 KST 자동 체결 동기화 시간 전입니다.",
                "scheduled_window": "08:00-10:00 KST",
            }

        bucket = f"{now.strftime('%Y-%m-%d')}-{now.hour:02d}-{now.minute // 10}"
        last_bucket = str(state.get("last_external_cycle_sync_bucket", "") or "")
        if force is False and last_bucket == bucket:
            return {
                "enabled": True,
                "executed": False,
                "cached": True,
                "message": "이번 10분 구간은 이미 체결 동기화를 확인했습니다.",
                "bucket": bucket,
            }

        try:
            result = self.engine.sync_external_cycle_trades(lookback_days=7) or {}
            if _external_cycle_sync_verified(result):
                state["last_external_cycle_sync_bucket"] = bucket
                state["last_external_cycle_sync_error_ts"] = 0.0
            else:
                state["last_external_cycle_sync_error_ts"] = time.time()
            state["last_external_cycle_sync_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
            try:
                import json as _json
                message = "외부 체결 자동 동기화 결과: " + _json.dumps(result, ensure_ascii=False)
                self.engine._log_event("SYSTEM", "", "EXTERNAL_CYCLE_SYNC_RUN", message=message[:1800])
            except Exception:
                pass
            return {
                "enabled": True,
                "executed": True,
                "scheduled_window": "08:00-10:00 KST",
                "bucket": bucket,
                **result,
            }
        except Exception as e:
            state["last_external_cycle_sync_error_ts"] = time.time()
            state["last_external_cycle_sync_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
            return {
                "enabled": True,
                "executed": False,
                "status": "error",
                "message": str(e),
                "scheduled_window": "08:00-10:00 KST",
                "bucket": bucket,
            }

    def _background_maintenance_enabled(self):
        return str(self.get_config("background_maintenance_enabled", "true") or "true").lower() == "true"

    def _background_maintenance_interval_sec(self):
        try:
            return max(3600, int(float(self.get_config("background_maintenance_interval_sec", "21600") or 21600)))
        except Exception:
            return 21600

    def _run_background_maintenance(self):
        try:
            maintenance = self.model("maintenance")
            result = maintenance.database_maintenance() or {}
            return {
                "enabled": True,
                "executed": True,
                "status": "completed",
                **result,
            }
        except Exception as e:
            return {
                "enabled": True,
                "executed": False,
                "status": "error",
                "message": str(e),
            }

    def _background_worker_loop(self, generation):
        state = self._worker_state()
        last_run_ts = 0.0
        while True:
            if generation != int(state.get("generation", 0) or 0):
                break
            try:
                interval = self._worker_interval_sec()
                daytrade_feature_enabled = self._daytrade_feature_enabled()
                enabled = daytrade_feature_enabled and str(self.get_config("daytrade_auto_enabled", "false")).lower() == "true"
                exit_watch_enabled = self._kr_exit_watch_effective_enabled()
                us_enabled = self._us_auto_enabled()
                us_exit_watch_enabled = self._us_exit_watch_effective_enabled()
                auto_trade_enabled = str(self.get_config("auto_trade_enabled", "false") or "false").lower() == "true"
                loc_schedule_enabled = auto_trade_enabled and str(self.get_config("loc_auto_schedule_enabled", "true") or "true").lower() == "true"
                firegate_cfg = self._firegate_sync_config()
                firegate_enabled = bool(firegate_cfg.get("enabled", False))
                firegate_interval_sec = max(30, int(firegate_cfg.get("interval_sec", 600) or 600))
                firegate_last_sync_ts = float(state.get("last_firegate_sync_ts", 0.0) or 0.0)
                now_ts = time.time()
                now_kst = _kst_now()
                maintenance_enabled = self._background_maintenance_enabled()
                maintenance_interval_sec = self._background_maintenance_interval_sec()
                maintenance_last_ts = float(state.get("last_background_maintenance_ts", 0.0) or 0.0)
                force_run = bool(state.get("force_run", False) or Struct._worker_force_run)
                firegate_due = firegate_enabled and (force_run or (now_ts - firegate_last_sync_ts) >= firegate_interval_sec)
                maintenance_due = maintenance_enabled and (force_run or (now_ts - maintenance_last_ts) >= maintenance_interval_sec)
                external_cycle_sync_bucket = f"{now_kst.strftime('%Y-%m-%d')}-{now_kst.hour:02d}-{now_kst.minute // 10}"
                external_cycle_sync_last_error_ts = float(state.get("last_external_cycle_sync_error_ts", 0.0) or 0.0)
                external_cycle_sync_due = (
                    _external_cycle_sync_window_open(now_kst)
                    and str(state.get("last_external_cycle_sync_bucket", "") or "") != external_cycle_sync_bucket
                    and (now_ts - external_cycle_sync_last_error_ts) >= 60
                )
                loc_reservation_bucket = _loc_reservation_bucket(now_kst)
                loc_reservation_retry_due = (
                    loc_schedule_enabled
                    and _loc_reservation_window_open(now_kst)
                    and str(state.get("last_loc_reservation_check_bucket", "") or "") != loc_reservation_bucket
                )
                should_run = (
                    enabled or exit_watch_enabled or us_enabled or us_exit_watch_enabled or loc_schedule_enabled
                    or firegate_enabled or external_cycle_sync_due or loc_reservation_retry_due or maintenance_due
                ) and (
                    force_run or (now_ts - last_run_ts) >= interval or firegate_due
                    or external_cycle_sync_due or loc_reservation_retry_due or maintenance_due
                )
                if should_run:
                    result = {
                        "auto_cycle": {"executed": False, "message": "국장 단타 실행 대기"} if enabled else {"executed": False, "message": "국장 단타 자동매매 비활성"},
                        "exit_watch": {"executed": False, "message": "국장 단타 자동청산 실행 대기"} if exit_watch_enabled else {"executed": False, "message": "국장 단타 자동청산 감시 비활성"},
                        "us_auto_cycle": {"executed": False, "message": "미장 단타 실행 대기"} if us_enabled else {"executed": False, "message": "미장 단타 자동매매 비활성"},
                        "us_exit_watch": {"executed": False, "message": "미장 단타 자동청산 실행 대기"} if us_exit_watch_enabled else {"executed": False, "message": "미장 단타 자동청산 감시 비활성"},
                        "loc_automation": {"executed": False, "message": "LOC 자동 예약 비활성"},
                        "firegate_sync": {"executed": False, "message": "FireGate 자동 동기화 비활성"} if firegate_enabled is False else {"executed": False, "waiting": True, "message": "FireGate 자동 동기화 대기 중", "interval_sec": firegate_interval_sec},
                        "external_cycle_sync": {"executed": False, "waiting": True, "message": "외부 체결 자동 동기화 대기 중", "scheduled_window": "08:00-10:00 KST"},
                        "maintenance": {"executed": False, "waiting": True, "message": "백그라운드 DB 최적화 대기 중", "interval_sec": maintenance_interval_sec} if maintenance_enabled else {"executed": False, "message": "백그라운드 DB 최적화 비활성"},
                    }
                    run_started_at = _kst_now().strftime("%Y-%m-%d %H:%M:%S")

                    def publish_result():
                        verification_state = self._loc_reservation_verification_state()
                        state["last_run_at"] = run_started_at
                        state["last_result"] = {
                            "interval_sec": interval,
                            "last_run_at": state["last_run_at"],
                            "daytrade_feature_enabled": daytrade_feature_enabled,
                            "daytrade_hard_locked": DAYTRADE_HARD_LOCKED,
                            "enabled": enabled,
                            "exit_watch_enabled": exit_watch_enabled,
                            "us_enabled": us_enabled,
                            "us_exit_watch_enabled": us_exit_watch_enabled,
                            "loc_schedule_enabled": loc_schedule_enabled,
                            "firegate_sync_enabled": firegate_enabled,
                            "firegate_sync_interval_sec": firegate_interval_sec,
                            "firegate_last_sync_at": _normalize_kst_timestamp(state.get("last_firegate_sync_at", "")),
                            "background_maintenance_enabled": maintenance_enabled,
                            "background_maintenance_interval_sec": maintenance_interval_sec,
                            "background_maintenance_last_at": _normalize_kst_timestamp(state.get("last_background_maintenance_at", "")),
                            "external_cycle_sync_last_at": _normalize_kst_timestamp(state.get("last_external_cycle_sync_at", "")),
                            "loc_reservation_check_last_at": _normalize_kst_timestamp(state.get("last_loc_reservation_check_at", "")),
                            "loc_reservation_verified_streak": int(verification_state.get("loc_reservation_verified_streak", 0) or 0),
                            "loc_reservation_verified_target": int(verification_state.get("loc_reservation_verified_target", self._loc_reservation_verify_target()) or self._loc_reservation_verify_target()),
                            "loc_reservation_verified_complete": bool(verification_state.get("loc_reservation_verified_complete", False)),
                            "loc_reservation_verified_version": str(verification_state.get("loc_reservation_verified_version", "") or ""),
                            "loc_reservation_verified_last_at": _normalize_kst_timestamp(verification_state.get("loc_reservation_verified_last_at", "")),
                            "loc_reservation_verified_failure_reason": str(verification_state.get("loc_reservation_verified_failure_reason", "") or ""),
                            "result": result,
                        }
                        Struct._worker_last_run_at = state["last_run_at"]
                        Struct._worker_last_result = state["last_result"]
                        self._write_worker_status_snapshot(state["last_result"])

                    if maintenance_due:
                        result["maintenance"] = {"executed": False, "running": True, "message": "백그라운드 DB 최적화/요약 정리 중", "interval_sec": maintenance_interval_sec}
                        publish_result()
                        result["maintenance"] = self._run_background_maintenance()
                        state["last_background_maintenance_ts"] = time.time()
                        state["last_background_maintenance_at"] = _kst_now().strftime("%Y-%m-%d %H:%M:%S")
                        publish_result()

                    if firegate_due:
                        result["firegate_sync"] = {"executed": False, "running": True, "message": "FireGate 포트폴리오 동기화 중", "interval_sec": firegate_interval_sec}
                        publish_result()
                        result["firegate_sync"] = self.run_due_firegate_sync()
                        state["last_firegate_sync_ts"] = time.time()
                        state["last_firegate_sync_at"] = _kst_now().strftime("%Y-%m-%d %H:%M:%S")
                        publish_result()

                    if loc_schedule_enabled:
                        loc_reason = "5min_reservation_verify" if loc_reservation_retry_due else "worker"
                        result["loc_automation"] = {
                            "enabled": True,
                            "executed": False,
                            "running": True,
                            "verified": bool(loc_reservation_retry_due),
                            "reason": loc_reason,
                            "message": "LOC 예약을 FireGate 기준으로 검증/복구하는 중",
                            "schedule_window": _loc_reservation_window_label(now_kst),
                            "schedule_key": _loc_schedule_key(now_kst),
                            "verification_version": _LOC_RESERVATION_VERIFY_VERSION,
                        }
                        publish_result()
                        result["loc_automation"] = self.run_due_loc_automation(verify=loc_reservation_retry_due, reason=loc_reason)
                        if loc_reservation_retry_due:
                            state["last_loc_reservation_check_bucket"] = loc_reservation_bucket
                            state["last_loc_reservation_check_at"] = _kst_now().strftime("%Y-%m-%d %H:%M:%S")
                    publish_result()

                    if external_cycle_sync_due:
                        result["external_cycle_sync"] = {"executed": False, "running": True, "message": "브로커 체결 내역을 사이클에 반영하는 중", "scheduled_window": "08:00-10:00 KST"}
                        publish_result()
                        result["external_cycle_sync"] = self.run_due_external_cycle_sync()
                        publish_result()

                    if us_enabled:
                        result["us_auto_cycle"] = {"executed": False, "running": True, "message": "미장 단타 자동순환 점검 중"}
                        publish_result()
                        result["us_auto_cycle"] = self._run_daytrade_auto_once(market="US")
                    if us_exit_watch_enabled:
                        result["us_exit_watch"] = {"executed": False, "running": True, "message": "미장 단타 자동청산 감시 중"}
                        publish_result()
                        us_seed = float(self.get_config("daytrade_us_default_seed", self.get_config("daytrade_default_seed", "5000000")) or 5000000)
                        result["us_exit_watch"] = self.daytrade_engine.execute_exit_watch(requested_seed=us_seed, market="US")
                    publish_result()

                    if enabled:
                        result["auto_cycle"] = {"executed": False, "running": True, "message": "국장 단타 자동순환 점검 중"}
                        publish_result()
                        result["auto_cycle"] = self._run_daytrade_auto_once(market="KS")
                    if exit_watch_enabled:
                        result["exit_watch"] = {"executed": False, "running": True, "message": "국장 단타 자동청산 감시 중"}
                        publish_result()
                        seed = float(self.get_config("daytrade_default_seed", "5000000") or 5000000)
                        result["exit_watch"] = self.daytrade_engine.execute_exit_watch(requested_seed=seed, market="KS")
                    last_run_ts = time.time()
                    Struct._worker_force_run = False
                    state["force_run"] = False
                    publish_result()
                time.sleep(2)
            except Exception as e:
                state["last_result"] = {
                    "interval_sec": self._worker_interval_sec(),
                    "last_run_at": _kst_now().strftime("%Y-%m-%d %H:%M:%S"),
                    "daytrade_feature_enabled": self._daytrade_feature_enabled(),
                    "daytrade_hard_locked": DAYTRADE_HARD_LOCKED,
                    "enabled": self._daytrade_feature_enabled() and str(self.get_config("daytrade_auto_enabled", "false")).lower() == "true",
                    "exit_watch_enabled": self._kr_exit_watch_effective_enabled(),
                    "us_enabled": self._us_auto_enabled(),
                    "us_exit_watch_enabled": self._us_exit_watch_effective_enabled(),
                    "loc_schedule_enabled": str(self.get_config("loc_auto_schedule_enabled", "true") or "true").lower() == "true",
                    "firegate_sync_enabled": self._firegate_sync_config().get("enabled", False),
                    "firegate_sync_interval_sec": self._firegate_sync_config().get("interval_sec", 600),
                    "firegate_last_sync_at": _normalize_kst_timestamp(state.get("last_firegate_sync_at", "")),
                    "external_cycle_sync_last_at": _normalize_kst_timestamp(state.get("last_external_cycle_sync_at", "")),
                    "loc_reservation_check_last_at": _normalize_kst_timestamp(state.get("last_loc_reservation_check_at", "")),
                    "result": {"executed": False, "message": str(e)},
                }
                state["last_run_at"] = state["last_result"].get("last_run_at", "")
                Struct._worker_last_run_at = state["last_run_at"]
                Struct._worker_last_result = state["last_result"]
                self._write_worker_status_snapshot(state["last_result"])
                time.sleep(5)
        if generation == int(state.get("generation", 0) or 0):
            state["thread"] = None
        current = threading.current_thread()
        if Struct._worker_thread is current:
            Struct._worker_thread = None
            Struct._worker_started = False

    def worker_status(self):
        self._ensure_background_worker()
        state = self._worker_state()
        verification_state = self._loc_reservation_verification_state()
        worker = state.get("thread")
        last_result = (state.get("last_result", {}) or Struct._worker_last_result).get("result", {})
        auto_cycle = last_result.get("auto_cycle", {}) if isinstance(last_result, dict) else {}
        us_auto_cycle = last_result.get("us_auto_cycle", {}) if isinstance(last_result, dict) else {}
        waiting_items = []
        for cycle in (auto_cycle, us_auto_cycle):
            if not isinstance(cycle, dict):
                continue
            for item in list(cycle.get("results", []) or [])[:6]:
                if isinstance(item, dict) and not item.get("executed"):
                    waiting_items.append(item)
        return {
            "started": bool(worker is not None and worker.is_alive()),
            "alive": worker.is_alive() if worker is not None else False,
            "daytrade_feature_enabled": self._daytrade_feature_enabled(),
            "daytrade_hard_locked": DAYTRADE_HARD_LOCKED,
            "enabled": self._daytrade_feature_enabled() and str(self.get_config("daytrade_auto_enabled", "false")).lower() == "true",
            "us_enabled": self._us_auto_enabled(),
            "exit_watch_enabled": self._kr_exit_watch_effective_enabled(),
            "us_exit_watch_enabled": self._us_exit_watch_effective_enabled(),
            "loc_schedule_enabled": str(self.get_config("auto_trade_enabled", "false") or "false").lower() == "true" and str(self.get_config("loc_auto_schedule_enabled", "true") or "true").lower() == "true",
            "firegate_sync_enabled": self._firegate_sync_config().get("enabled", False),
            "interval_sec": self._worker_interval_sec(),
            "last_run_at": _normalize_kst_timestamp(state.get("last_run_at", Struct._worker_last_run_at)),
            "firegate_last_sync_at": _normalize_kst_timestamp(state.get("last_firegate_sync_at", "")),
            "external_cycle_sync_last_at": _normalize_kst_timestamp(state.get("last_external_cycle_sync_at", "")),
            "loc_reservation_check_last_at": _normalize_kst_timestamp(state.get("last_loc_reservation_check_at", "")),
            "loc_reservation_verified_streak": int(verification_state.get("loc_reservation_verified_streak", 0) or 0),
            "loc_reservation_verified_target": int(verification_state.get("loc_reservation_verified_target", self._loc_reservation_verify_target()) or self._loc_reservation_verify_target()),
            "loc_reservation_verified_complete": bool(verification_state.get("loc_reservation_verified_complete", False)),
            "loc_reservation_verified_version": str(verification_state.get("loc_reservation_verified_version", "") or ""),
            "loc_reservation_verified_last_at": _normalize_kst_timestamp(verification_state.get("loc_reservation_verified_last_at", "")),
            "loc_reservation_verified_failure_reason": str(verification_state.get("loc_reservation_verified_failure_reason", "") or ""),
            "last_result": last_result,
            "waiting_items": waiting_items[:12],
            "auto_cycle_wait_summary": auto_cycle.get("wait_summary", {}) if isinstance(auto_cycle, dict) else {},
            "us_auto_cycle_wait_summary": us_auto_cycle.get("wait_summary", {}) if isinstance(us_auto_cycle, dict) else {},
        }

    def refresh_config_cache(self):
        """캐시 강제 갱신 (config 외부 변경 후 호출)"""
        Struct._cfg_ready = False
        self._load_config_cache()

    def _init_tables(self):
        """trading DB 테이블이 없으면 자동 생성"""
        tables = [
            "trading_config",
            "etf_watchlist",
            "trading_cycle",
            "cycle_trade",
            "trade_log",
            "account_snapshot",
            "daily_trade_summary",
            "simulation_run",
            "simulation_trade",
        ]
        for name in tables:
            try:
                db = self.orm.use(name, module="trading")
                db.orm.create_table(safe=True)
            except Exception:
                pass

    def _migrate_schema(self):
        """기존 테이블에 누락된 컬럼 자동 추가 (ALTER TABLE)"""
        migrations = [
            # trading_cycle
            ("trading_cycle", "cycle_number", "INTEGER DEFAULT 1"),
            ("trading_cycle", "t_value", "REAL DEFAULT 0.0"),
            ("trading_cycle", "total_commission", "REAL DEFAULT 0.0"),
            ("trading_cycle", "partial_sold_count", "INTEGER DEFAULT 0"),
            ("trading_cycle", "crash_buy_count", "INTEGER DEFAULT 0"),
            ("trading_cycle", "user_id", 'VARCHAR(64) DEFAULT ""'),
            # cycle_trade
            ("cycle_trade", "user_id", 'VARCHAR(64) DEFAULT ""'),
            ("cycle_trade", "commission", "REAL DEFAULT 0.0"),
            ("cycle_trade", "strategy_type", 'VARCHAR(16) DEFAULT "NORMAL"'),
            ("cycle_trade", "broker_order_no", 'VARCHAR(64) DEFAULT ""'),
            ("cycle_trade", "source", 'VARCHAR(32) DEFAULT ""'),
            # trade_log
            ("trade_log", "user_id", 'VARCHAR(64) DEFAULT ""'),
            # etf_watchlist
            ("etf_watchlist", "user_id", 'VARCHAR(64) DEFAULT ""'),
            ("etf_watchlist", "cycle_mode", 'VARCHAR(16) DEFAULT "auto"'),
            # account_snapshot
            ("account_snapshot", "user_id", 'VARCHAR(64) DEFAULT ""'),
            # daily_trade_summary
            ("daily_trade_summary", "user_id", 'VARCHAR(64) DEFAULT ""'),
            # simulation_run
            ("simulation_run", "buy_commission_rate", "REAL DEFAULT 0.0"),
            ("simulation_run", "sell_commission_rate", "REAL DEFAULT 0.0"),
            ("simulation_run", "tax_rate", "REAL DEFAULT 0.0"),
            ("simulation_run", "total_commission", "REAL DEFAULT 0.0"),
        ]
        try:
            db = self.orm.use("trading_config", module="trading")
            database = db.orm._meta.database
            for table, col, col_type in migrations:
                try:
                    database.execute_sql(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                except Exception:
                    pass  # Column already exists
            self._drop_unique_single_column_index(database, "etf_watchlist", "symbol")
            self._drop_unique_single_column_index(database, "account_snapshot", "snapshot_date")
            self._drop_unique_single_column_index(database, "daily_trade_summary", "trade_date")
        except Exception:
            pass

    def _drop_unique_single_column_index(self, database, table, column):
        """Legacy unique indexes prevent per-user duplicate symbols/dates."""
        try:
            rows = database.execute_sql(f"SHOW INDEX FROM `{table}`").fetchall()
            by_name = {}
            for row in rows or []:
                try:
                    key_name = row[2]
                    non_unique = int(row[1])
                    column_name = str(row[4])
                except Exception:
                    continue
                by_name.setdefault(key_name, {"non_unique": non_unique, "columns": []})["columns"].append(column_name)
            for key_name, info in by_name.items():
                if key_name == "PRIMARY" or int(info.get("non_unique", 1)) != 0:
                    continue
                if info.get("columns") == [column]:
                    try:
                        database.execute_sql(f"ALTER TABLE `{table}` DROP INDEX `{key_name}`")
                    except Exception:
                        pass
            return
        except Exception:
            pass

        try:
            rows = database.execute_sql(f"PRAGMA index_list('{table}')").fetchall()
        except Exception:
            return
        for row in rows or []:
            try:
                index_name = row[1]
                is_unique = int(row[2]) == 1
            except Exception:
                continue
            if not is_unique or not index_name:
                continue
            try:
                info = database.execute_sql(f"PRAGMA index_info('{index_name}')").fetchall()
                columns = [str(item[2]) for item in (info or [])]
            except Exception:
                columns = []
            if columns == [column]:
                try:
                    database.execute_sql(f'DROP INDEX "{index_name}"')
                except Exception:
                    pass

    def db(self, name):
        """ORM Wrapper 반환 (portal/trading/model/db/{name}.py)"""
        raw = self.orm.use(name, module="trading")
        if str(name or "") in USER_SCOPED_TABLES:
            return _UserScopedDb(raw, self, str(name or ""))
        return raw

    def model(self, name):
        """portal/trading/model 하위 모델 로더."""
        return wiz.model(f"portal/trading/{name}")

    @property
    def kis_api(self):
        """한국투자증권 API Sub-Struct"""
        if self._kis_api_obj is None:
            self._kis_api_obj = self._KisApi(self)
        return self._kis_api_obj

    @property
    def toss_api(self):
        """토스증권 API Sub-Struct"""
        if self._toss_api_obj is None:
            self._toss_api_obj = self._TossApi(self)
        return self._toss_api_obj

    @property
    def broker_provider(self):
        provider = str(self.get_config("broker_provider", "kis") or "kis").strip().lower()
        if provider not in ("kis", "toss"):
            provider = "kis"
        return provider

    @property
    def broker_api(self):
        """현재 설정된 증권사 API. 무한매수 엔진은 이 속성을 통해 주문한다."""
        if self.broker_provider == "toss":
            return self.toss_api
        return self.kis_api

    @property
    def engine(self):
        """무한매수법 엔진 Sub-Struct"""
        required = ("_load_kis_api", "schedule_loc_buys", "schedule_loc_sells")
        if self._engine_obj is not None and any(hasattr(self._engine_obj, name) is False for name in required):
            self._Engine = wiz.model("portal/trading/struct/engine")
            self._engine_obj = None
        if self._engine_obj is None:
            self._engine_obj = self._Engine(self)
        return self._engine_obj

    @property
    def strategy(self):
        """고급 매도 전략 모듈"""
        return self._Strategy

    @property
    def daytrade(self):
        """국내 단타 연구/백테스트 Sub-Struct"""
        model = self._daytrade_model()
        if self._daytrade_obj is not None:
            accepts_requested_seed = self._callable_accepts_kwarg(getattr(self._daytrade_obj, "auto_train", None), "requested_seed")
            if self._daytrade_obj.__class__ is not model or accepts_requested_seed is False:
                self._daytrade_obj = None
        if self._daytrade_obj is None:
            self._daytrade_obj = model(self)
        return self._daytrade_obj

    @property
    def daytrade_engine(self):
        """국내 단타 라이브 엔진 청사진 Sub-Struct"""
        return self._daytrade_engine_model()(self)

    def _daytrade_engine_model(self):
        needs_reload = self._DaytradeEngine is None
        if needs_reload is False:
            required_attrs = ["_us_auto_buy_ready", "_us_auto_buy_window"]
            for attr in required_attrs:
                if hasattr(self._DaytradeEngine, attr) is False:
                    needs_reload = True
                    break
        if needs_reload:
            self._DaytradeEngine = wiz.model("portal/trading/struct/daytrade_engine")
            self._daytrade_engine_model_id = id(self._DaytradeEngine)
        else:
            self._daytrade_engine_model_id = id(self._DaytradeEngine)
        return self._DaytradeEngine

    def _daytrade_model(self):
        needs_reload = self._Daytrade is None
        if needs_reload is False and self._callable_accepts_kwarg(getattr(self._Daytrade, "auto_train", None), "requested_seed") is False:
            needs_reload = True
        if needs_reload:
            self._Daytrade = wiz.model("portal/trading/struct/daytrade")
        self._daytrade_model_id = id(self._Daytrade)
        return self._Daytrade

Model = Struct()
