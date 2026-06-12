# =============================================================================
# Trading Package - Composite Struct (Singleton)
# =============================================================================
# 호출 예시:
#   trading = wiz.model("portal/trading/struct")
#   trading.kis_api.get_current_price("TQQQ")
#   trading.engine.run_cycle("TQQQ")
#   trading.db("trading_config").get(key="kis_app_key")
# =============================================================================

import datetime as _dt
import inspect
import sys as _sys
import threading
import time

_TIME = wiz.model("portal/trading/kst")


def _kst_now():
    return _TIME.now()


def _normalize_kst_timestamp(value=""):
    text = str(value or "").strip()
    if text == "":
        return ""
    return _TIME.normalize(text)


def _loc_schedule_mark_done(result):
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
    if scheduled_count > 0 or already_scheduled_count > 0:
        return True
    return status not in ("error", "partial_error") and error_count <= 0

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
        self._Engine = wiz.model("portal/trading/struct/engine")
        self._Strategy = wiz.model("portal/trading/struct/strategy")
        self._Daytrade = wiz.model("portal/trading/struct/daytrade")
        self._DaytradeEngine = None
        self._daytrade_model_id = 0
        self._daytrade_engine_model_id = 0
        self._kis_api_obj = None
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

    def get_config(self, key, default=None):
        """캐시에서 config 읽기. 캐시가 없으면 DB에서 단건 조회."""
        if not Struct._cfg_ready:
            self._load_config_cache()
        if key in Struct._cfg:
            return Struct._cfg.get(key, default)
        # 캐시 미스: DB 단건 조회 후 캐시 갱신
        try:
            db = self.orm.use("trading_config", module="trading")
            row = db.get(key=key)
            value = row.get("value", default) if row else default
            Struct._cfg[key] = value
            return value
        except Exception:
            return default

    def set_config(self, key, value, description="", is_secret=False):
        """config 쓰기 → DB 반영 + 캐시 즉시 갱신"""
        now = _kst_now()
        try:
            db = self.orm.use("trading_config", module="trading")
            existing = db.get(key=key)
            if existing:
                db.update({"value": str(value), "description": description, "is_secret": is_secret, "updated": now}, id=existing["id"])
            else:
                db.insert({"key": key, "value": str(value), "description": description, "is_secret": is_secret, "created": now, "updated": now})
        except Exception:
            pass
        Struct._cfg[key] = str(value)
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
        result = fg.sync_portfolios_to_local(self, symbol_filter=symbol_filter)
        return {
            **(result or {}),
            "enabled": True,
            "executed": bool((result or {}).get("executed", False)),
            "interval_sec": cfg.get("interval_sec", 600),
        }

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
        modern = str(self.get_config("daytrade_us_auto_enabled", "")).lower()
        legacy = str(self.get_config("us_daytrade_auto_enabled", "")).lower()
        if modern in ["true", "false"]:
            return modern == "true"
        if legacy in ["true", "false"]:
            return legacy == "true"
        return False

    def _us_exit_watch_enabled(self):
        modern = str(self.get_config("daytrade_us_exit_watch_enabled", "")).lower()
        legacy = str(self.get_config("us_daytrade_exit_watch_enabled", "")).lower()
        if modern in ["true", "false"]:
            return modern == "true"
        if legacy in ["true", "false"]:
            return legacy == "true"
        return True

    def _kr_exit_watch_effective_enabled(self):
        auto_enabled = str(self.get_config("daytrade_auto_enabled", "true")).lower() == "true"
        exit_watch_enabled = str(self.get_config("daytrade_exit_watch_enabled", "true")).lower() == "true"
        return auto_enabled and exit_watch_enabled

    def _us_exit_watch_effective_enabled(self):
        return self._us_auto_enabled() and self._us_exit_watch_enabled()

    def _run_daytrade_auto_once(self, market="KS"):
        engine = self.daytrade_engine
        if str(market or "KS").upper() == "US":
            enabled = self._us_auto_enabled()
            seed = float(self.get_config("daytrade_us_default_seed", self.get_config("daytrade_default_seed", "5000000")) or 5000000)
        else:
            enabled = str(self.get_config("daytrade_auto_enabled", "true")).lower() == "true"
            seed = float(self.get_config("daytrade_default_seed", "5000000") or 5000000)
        if enabled is False:
            return {"executed": False, "message": f"{'미장' if str(market or 'KS').upper() == 'US' else '국장'} 단타 자동매매 비활성"}
        result = engine.auto_cycle(requested_seed=seed, market=market)
        return result or {"executed": False, "message": f"{'미장' if str(market or 'KS').upper() == 'US' else '국장'} 단타 자동매매 결과 없음"}

    def run_due_loc_automation(self):
        """17:30 KST 이후 무한매수 LOC 예약을 서버 워커에서도 1일 1회 수행."""
        now = _kst_now()
        today = now.strftime("%Y-%m-%d")
        enabled = str(self.get_config("loc_auto_schedule_enabled", "true") or "true").lower() == "true"
        if enabled is False:
            return {"enabled": False, "executed": False, "message": "LOC 자동 예약 비활성"}
        if now.weekday() >= 5:
            return {"enabled": True, "executed": False, "waiting": True, "message": "주말이라 LOC 자동 예약 대기 중입니다.", "scheduled_at": "17:30 KST"}
        try:
            holiday = ""
            if hasattr(self.kis_api, "us_market_holiday_label"):
                holiday = str(self.kis_api.us_market_holiday_label(now) or "")
            if holiday:
                return {
                    "enabled": True,
                    "executed": False,
                    "waiting": True,
                    "message": f"미국 휴장일({holiday})이라 LOC 자동 예약을 대기합니다.",
                    "scheduled_at": "다음 미국 거래일 17:30 KST",
                    "holiday": holiday,
                }
        except Exception:
            pass
        if (now.hour, now.minute) < (17, 30):
            return {"enabled": True, "executed": False, "waiting": True, "message": "17:30 KST 이전이라 LOC 자동 예약 대기 중입니다.", "scheduled_at": "17:30 KST"}

        engine = self.engine
        sell_method = str(self.get_config("sell_method", "market") or "market").lower()
        buy_last_date = str(self.get_config("loc_buy_auto_schedule_last_date", "") or "")
        sell_last_date = str(self.get_config("loc_auto_schedule_last_date", "") or "")
        buy_result = {
            "enabled": True,
            "scheduled": False,
            "message": "오늘 LOC 자동 예약매수는 이미 접수했습니다." if buy_last_date == today else "LOC 자동 예약매수 대상 없음",
            "scheduled_at": "17:30 KST",
        }
        sell_result = {
            "enabled": True,
            "scheduled": False,
            "message": "매도 방식이 LOC가 아니라 자동 예약매도를 건너뜁니다." if sell_method != "loc" else ("오늘 LOC 자동 예약매도는 이미 접수했습니다." if sell_last_date == today else "LOC 자동 예약매도 대상 없음"),
            "scheduled_at": "17:30 KST",
        }

        buy_attempted = False
        sell_attempted = False

        if buy_last_date != today:
            buy_attempted = True
            try:
                raw_buy_result = engine.schedule_loc_buys()
                buy_result = {"enabled": True, "scheduled": True, "scheduled_at": "17:30 KST", **(raw_buy_result or {})}
                if _loc_schedule_mark_done(raw_buy_result):
                    self.set_config("loc_buy_auto_schedule_last_date", today, description="Last auto LOC buy schedule date")
            except Exception as e:
                buy_result = {
                    "enabled": True,
                    "scheduled": False,
                    "scheduled_at": "17:30 KST",
                    "status": "error",
                    "error_count": 1,
                    "message": str(e),
                    "orders": [],
                    "errors": [{"reason": str(e)}],
                }

        if sell_method == "loc" and sell_last_date != today:
            sell_attempted = True
            try:
                raw_sell_result = engine.schedule_loc_sells()
                sell_result = {"enabled": True, "scheduled": True, "scheduled_at": "17:30 KST", **(raw_sell_result or {})}
                if _loc_schedule_mark_done(raw_sell_result):
                    self.set_config("loc_auto_schedule_last_date", today, description="Last auto LOC sell schedule date")
            except Exception as e:
                sell_result = {
                    "enabled": True,
                    "scheduled": False,
                    "scheduled_at": "17:30 KST",
                    "status": "error",
                    "error_count": 1,
                    "message": str(e),
                    "orders": [],
                    "errors": [{"reason": str(e)}],
                }

        executed = bool(
            int((buy_result or {}).get("scheduled_count", 0) or 0) > 0
            or int((buy_result or {}).get("already_scheduled_count", 0) or 0) > 0
            or int((sell_result or {}).get("scheduled_count", 0) or 0) > 0
            or int((sell_result or {}).get("already_scheduled_count", 0) or 0) > 0
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
                    "sell_status": (sell_result or {}).get("status", ""),
                    "sell_scheduled_count": (sell_result or {}).get("scheduled_count", 0),
                    "sell_error_count": (sell_result or {}).get("error_count", 0),
                    "executed": executed,
                }
                message = "LOC 자동 예약 점검 결과: " + _json.dumps(summary, ensure_ascii=False)
                engine._log_event("SYSTEM", "", "LOC_AUTOMATION_RUN", message=message[:1800])
            except Exception:
                pass
        return {"enabled": True, "executed": executed, "scheduled_at": "17:30 KST", "buy": buy_result, "sell": sell_result}

    def _background_worker_loop(self, generation):
        state = self._worker_state()
        last_run_ts = 0.0
        while True:
            if generation != int(state.get("generation", 0) or 0):
                break
            try:
                interval = self._worker_interval_sec()
                enabled = str(self.get_config("daytrade_auto_enabled", "true")).lower() == "true"
                exit_watch_enabled = self._kr_exit_watch_effective_enabled()
                us_enabled = self._us_auto_enabled()
                us_exit_watch_enabled = self._us_exit_watch_effective_enabled()
                loc_schedule_enabled = str(self.get_config("loc_auto_schedule_enabled", "true") or "true").lower() == "true"
                firegate_cfg = self._firegate_sync_config()
                firegate_enabled = bool(firegate_cfg.get("enabled", False))
                firegate_interval_sec = max(30, int(firegate_cfg.get("interval_sec", 600) or 600))
                firegate_last_sync_ts = float(state.get("last_firegate_sync_ts", 0.0) or 0.0)
                now_ts = time.time()
                force_run = bool(state.get("force_run", False) or Struct._worker_force_run)
                firegate_due = firegate_enabled and (force_run or (now_ts - firegate_last_sync_ts) >= firegate_interval_sec)
                should_run = (enabled or exit_watch_enabled or us_enabled or us_exit_watch_enabled or loc_schedule_enabled or firegate_enabled) and (force_run or (now_ts - last_run_ts) >= interval or firegate_due)
                if should_run:
                    result = {
                        "auto_cycle": {"executed": False, "message": "국장 단타 실행 대기"} if enabled else {"executed": False, "message": "국장 단타 자동매매 비활성"},
                        "exit_watch": {"executed": False, "message": "국장 단타 자동청산 실행 대기"} if exit_watch_enabled else {"executed": False, "message": "국장 단타 자동청산 감시 비활성"},
                        "us_auto_cycle": {"executed": False, "message": "미장 단타 실행 대기"} if us_enabled else {"executed": False, "message": "미장 단타 자동매매 비활성"},
                        "us_exit_watch": {"executed": False, "message": "미장 단타 자동청산 실행 대기"} if us_exit_watch_enabled else {"executed": False, "message": "미장 단타 자동청산 감시 비활성"},
                        "loc_automation": {"executed": False, "message": "LOC 자동 예약 비활성"},
                        "firegate_sync": {"executed": False, "message": "FireGate 자동 동기화 비활성"} if firegate_enabled is False else {"executed": False, "waiting": True, "message": "FireGate 자동 동기화 대기 중", "interval_sec": firegate_interval_sec},
                    }
                    run_started_at = _kst_now().strftime("%Y-%m-%d %H:%M:%S")

                    def publish_result():
                        state["last_run_at"] = run_started_at
                        state["last_result"] = {
                            "interval_sec": interval,
                            "last_run_at": state["last_run_at"],
                            "enabled": enabled,
                            "exit_watch_enabled": exit_watch_enabled,
                            "us_enabled": us_enabled,
                            "us_exit_watch_enabled": us_exit_watch_enabled,
                            "loc_schedule_enabled": loc_schedule_enabled,
                            "firegate_sync_enabled": firegate_enabled,
                            "firegate_sync_interval_sec": firegate_interval_sec,
                            "firegate_last_sync_at": _normalize_kst_timestamp(state.get("last_firegate_sync_at", "")),
                            "result": result,
                        }
                        Struct._worker_last_run_at = state["last_run_at"]
                        Struct._worker_last_result = state["last_result"]
                        self._write_worker_status_snapshot(state["last_result"])

                    if firegate_due:
                        result["firegate_sync"] = {"executed": False, "running": True, "message": "FireGate 포트폴리오 동기화 중", "interval_sec": firegate_interval_sec}
                        publish_result()
                        result["firegate_sync"] = self.run_due_firegate_sync()
                        state["last_firegate_sync_ts"] = time.time()
                        state["last_firegate_sync_at"] = _kst_now().strftime("%Y-%m-%d %H:%M:%S")
                        publish_result()

                    if loc_schedule_enabled:
                        result["loc_automation"] = self.run_due_loc_automation()
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
                    "enabled": str(self.get_config("daytrade_auto_enabled", "true")).lower() == "true",
                    "exit_watch_enabled": self._kr_exit_watch_effective_enabled(),
                    "us_enabled": self._us_auto_enabled(),
                    "us_exit_watch_enabled": self._us_exit_watch_effective_enabled(),
                    "loc_schedule_enabled": str(self.get_config("loc_auto_schedule_enabled", "true") or "true").lower() == "true",
                    "firegate_sync_enabled": self._firegate_sync_config().get("enabled", False),
                    "firegate_sync_interval_sec": self._firegate_sync_config().get("interval_sec", 600),
                    "firegate_last_sync_at": _normalize_kst_timestamp(state.get("last_firegate_sync_at", "")),
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
            "enabled": str(self.get_config("daytrade_auto_enabled", "true")).lower() == "true",
            "us_enabled": self._us_auto_enabled(),
            "exit_watch_enabled": self._kr_exit_watch_effective_enabled(),
            "us_exit_watch_enabled": self._us_exit_watch_effective_enabled(),
            "loc_schedule_enabled": str(self.get_config("loc_auto_schedule_enabled", "true") or "true").lower() == "true",
            "firegate_sync_enabled": self._firegate_sync_config().get("enabled", False),
            "interval_sec": self._worker_interval_sec(),
            "last_run_at": _normalize_kst_timestamp(state.get("last_run_at", Struct._worker_last_run_at)),
            "firegate_last_sync_at": _normalize_kst_timestamp(state.get("last_firegate_sync_at", "")),
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
            # cycle_trade
            ("cycle_trade", "commission", "REAL DEFAULT 0.0"),
            ("cycle_trade", "strategy_type", 'VARCHAR(16) DEFAULT "NORMAL"'),
            # etf_watchlist
            ("etf_watchlist", "cycle_mode", 'VARCHAR(16) DEFAULT "auto"'),
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
        except Exception:
            pass

    def db(self, name):
        """ORM Wrapper 반환 (portal/trading/model/db/{name}.py)"""
        return self.orm.use(name, module="trading")

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
