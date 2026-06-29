"""
Trading Scheduler API
=====================
스케줄러 엔드포인트: 외부 cron 또는 수동으로 엔진 실행을 트리거.
- /api/trading/scheduler/run     - 전체 활성 종목 일일 매매 실행
- /api/trading/scheduler/run/<symbol> - 특정 종목만 실행
- /api/trading/scheduler/loc-buy  - LOC 매수 예약 일괄 접수
- /api/trading/scheduler/loc-sell - LOC 매도 예약 일괄 접수
- /api/trading/scheduler/due-loc  - FireGate 기준 LOC 예약 검증/복구
- /api/trading/scheduler/external-sync[/<symbol>] - 브로커 체결 내역 사이클 반영
- /api/trading/scheduler/status  - 스케줄러 상태 조회
- /api/trading/scheduler/snapshot - 계좌 스냅샷 저장
- /api/trading/scheduler/health  - 헬스체크
"""
import json
import datetime
import threading

_TIME = wiz.model("portal/trading/kst")
_DAYTRADE_HARD_LOCKED = True
_DAYTRADE_LOCK_MESSAGE = "단타 기능은 현재 운영 안정화를 위해 완전히 봉인되어 있습니다."
_LOC_RESERVATION_START_HHMM = 1000
_LOC_RESERVATION_END_STANDARD_HHMM = 2320
_LOC_RESERVATION_END_SUMMER_HHMM = 2220

# ─── 전역 실행 잠금 ───
_scheduler_lock = threading.Lock()
_is_running = False
_last_run = None
_last_result = None


def _config_value(trading, key, default=""):
    return trading.get_config(key, default)


def _set_config_value(trading, key, value, description=""):
    trading.set_config(key, value, description=description)


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "y", "on")


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


def _configured_base_asset_krw(trading):
    for key in ["dashboard_base_asset_krw", "daytrade_default_seed"]:
        try:
            value = float(_config_value(trading, key, "0") or 0)
            if value > 0:
                return value
        except Exception:
            pass
    return 0.0


def _sync_firegate_before_loc(trading):
    try:
        if hasattr(trading, "run_due_firegate_sync"):
            return trading.run_due_firegate_sync()
    except Exception as e:
        return {"executed": False, "status": "error", "message": str(e)}
    return {"executed": False, "message": "not_available"}


def now_kst():
    return _TIME.now()


def _loc_hhmm_text(hhmm):
    return f"{int(hhmm) // 100:02d}:{int(hhmm) % 100:02d}"


def _nth_weekday(year, month, weekday, nth):
    day = datetime.date(year, month, 1)
    offset = (weekday - day.weekday()) % 7
    return day + datetime.timedelta(days=offset + (nth - 1) * 7)


def _us_summer_time_for_kst(now):
    try:
        from zoneinfo import ZoneInfo
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo("Asia/Seoul"))
        return bool(now.astimezone(ZoneInfo("America/New_York")).dst())
    except Exception:
        today = now.date()
        start = _nth_weekday(today.year, 3, 6, 2)
        end = _nth_weekday(today.year, 11, 6, 1)
        return start <= today < end


def _loc_reservation_cutoff_hhmm(now):
    return _LOC_RESERVATION_END_SUMMER_HHMM if _us_summer_time_for_kst(now) else _LOC_RESERVATION_END_STANDARD_HHMM


def _loc_reservation_window_label(now=None):
    now = now or now_kst()
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


def _should_run_maintenance(trading, now=None):
    now = now or now_kst()
    run_hour = int(float(_config_value(trading, "maintenance_run_hour", "23") or 23))
    run_minute = int(float(_config_value(trading, "maintenance_run_minute", "0") or 0))
    last_run_date = str(_config_value(trading, "maintenance_last_run_date", "") or "").strip()
    today = now.date()
    scheduled_today = now.replace(hour=run_hour, minute=run_minute, second=0, microsecond=0)
    target_date = today if now >= scheduled_today else (today - datetime.timedelta(days=1))
    if last_run_date == target_date.strftime("%Y-%m-%d"):
        return False, target_date
    return True, target_date


def run_maintenance_if_due(trading, force=False):
    now = now_kst()
    should_run, target_date = _should_run_maintenance(trading, now=now)
    if force is False and should_run is False:
        return {
            "executed": False,
            "target_date": target_date.strftime("%Y-%m-%d"),
            "last_run_date": str(_config_value(trading, "maintenance_last_run_date", "") or ""),
        }
    try:
        maintenance = trading.model("maintenance")
        result = maintenance.database_maintenance() or {}
    except Exception as e:
        return {
            "executed": False,
            "target_date": target_date.strftime("%Y-%m-%d"),
            "status": "skipped",
            "message": f"maintenance unavailable: {str(e)}",
        }
    _set_config_value(trading, "maintenance_last_run_date", target_date.strftime("%Y-%m-%d"), "Last trading maintenance run date")
    _set_config_value(trading, "maintenance_last_run_at", _TIME.isoformat(now, with_offset=True), "Last trading maintenance run timestamp")
    return {
        "executed": True,
        "target_date": target_date.strftime("%Y-%m-%d"),
        "executed_at": _TIME.isoformat(now, with_offset=True),
        **result,
    }


def run_daytrade_automation(trading):
    if _DAYTRADE_HARD_LOCKED:
        return {"enabled": False, "executed": False, "message": _DAYTRADE_LOCK_MESSAGE, "hard_locked": True}
    enabled = str(_config_value(trading, "daytrade_auto_enabled", "true")).lower() == "true"
    if enabled is False:
        return {"enabled": False, "executed": False, "message": "단타 자동운용 비활성"}
    seed = float(_config_value(trading, "daytrade_default_seed", "5000000") or 5000000)
    result = trading.daytrade_engine.auto_cycle(requested_seed=seed)
    return {"enabled": True, **result}


def run_daytrade_exit_watch(trading):
    if _DAYTRADE_HARD_LOCKED:
        return {"enabled": False, "executed": False, "message": _DAYTRADE_LOCK_MESSAGE, "hard_locked": True}
    auto_enabled = str(_config_value(trading, "daytrade_auto_enabled", "true")).lower() == "true"
    enabled = auto_enabled and str(_config_value(trading, "daytrade_exit_watch_enabled", "true")).lower() == "true"
    if enabled is False:
        return {"enabled": False, "executed": False, "message": "단타 OFF 상태라 자동청산 감시도 비활성"}
    seed = float(_config_value(trading, "daytrade_default_seed", "5000000") or 5000000)
    result = trading.daytrade_engine.execute_exit_watch(requested_seed=seed, market="ALL")
    return {"enabled": True, **result}


def schedule_loc_sell_if_due(trading):
    enabled = str(_config_value(trading, "loc_auto_schedule_enabled", "true")).lower() == "true"
    now = now_kst()
    scheduled_at = _loc_reservation_next_start_label()
    schedule_window = _loc_reservation_window_label(now)
    window_state = _loc_reservation_window_state(now)

    if enabled is False:
        return {"enabled": False, "scheduled": False, "message": "LOC 자동 예약 비활성"}
    if window_state != "open":
        message = f"{schedule_window} 전이라 FireGate 매도 예약 대기 중입니다." if window_state == "before" else f"{schedule_window} 예약 접수시간이 지나 FireGate 매도 예약을 대기합니다."
        return {"enabled": True, "scheduled": False, "message": message, "scheduled_at": scheduled_at, "schedule_window": schedule_window}

    automation = trading.run_due_loc_automation(verify=True, reason="scheduler_due_loc_sell")
    result = (automation or {}).get("sell") or {}
    return {"enabled": True, "scheduled": bool((automation or {}).get("executed", False)), "scheduled_at": scheduled_at, "schedule_window": schedule_window, "automation": automation, **result}


def schedule_loc_buy_if_due(trading):
    enabled = str(_config_value(trading, "loc_auto_schedule_enabled", "true")).lower() == "true"
    now = now_kst()
    scheduled_at = _loc_reservation_next_start_label()
    schedule_window = _loc_reservation_window_label(now)
    window_state = _loc_reservation_window_state(now)

    if enabled is False:
        return {"enabled": False, "scheduled": False, "message": "LOC 자동 예약 비활성"}
    if window_state != "open":
        message = f"{schedule_window} 전이라 LOC 자동 예약매수 대기 중입니다." if window_state == "before" else f"{schedule_window} 예약 접수시간이 지나 LOC 자동 예약매수를 대기합니다."
        return {"enabled": True, "scheduled": False, "message": message, "scheduled_at": scheduled_at, "schedule_window": schedule_window}

    automation = trading.run_due_loc_automation(verify=True, reason="scheduler_due_loc_buy")
    result = (automation or {}).get("buy") or {}
    return {"enabled": True, "scheduled": bool((automation or {}).get("executed", False)), "scheduled_at": scheduled_at, "schedule_window": schedule_window, "automation": automation, **result}


def verify_token():
    """스케줄러 토큰 검증 (선택적 — 토큰 미설정 시 통과)"""
    struct = wiz.model("struct")
    trading = struct.trading
    config_db = trading.db("trading_config")
    token_row = config_db.get(key="scheduler_token")
    if not token_row or not token_row.get("value"):
        return True  # 토큰 미설정 시 검증 스킵
    expected = token_row["value"]
    provided = wiz.request.query("token", "")
    if not provided:
        provided = wiz.request.headers("X-Scheduler-Token", "")
    return provided == expected


def take_snapshot(trading, force_update=False):
    """계좌 스냅샷 저장"""
    snap_db = trading.db("account_snapshot")
    today = _TIME.today()

    existing = snap_db.get(snapshot_date=today)
    if existing and force_update is False:
        return {
            "snapshot_date": today,
            "skipped": True,
            "reason": "today_snapshot_exists",
            "id": existing.get("id", ""),
            "created": existing.get("created", ""),
        }

    kis = getattr(trading, "broker_api", None) or trading.kis_api
    cash = 0
    eval_amount = 0
    cash_krw = 0.0
    eval_amount_krw = 0.0
    exchange_rate = 0.0
    present_total_asset_krw = 0.0
    holdings_count = 0

    try:
        if hasattr(kis, "get_present_balance"):
            present = kis.get_present_balance()
            exchange_rate = float(present.get("usd_krw", 0) or 0)
            present_total_asset_krw = float(present.get("total_asset_krw", 0) or 0)
            krw_balance = float(present.get("withdrawable_krw", present.get("krw_balance", 0)) or 0)
            cash_krw += krw_balance
    except Exception:
        pass

    try:
        balance = kis.get_balance()
        cash = float(balance.get("cash_balance", 0) or 0)
        holdings = balance.get("holdings", [])
        holdings_count = len(holdings)
        for h in holdings:
            eval_amount += float(h.get("eval_amount", 0))
        usd_cash = float(balance.get("cash_balance", 0) or 0)
        if usd_cash > cash:
            cash = usd_cash
    except Exception:
        pass

    domestic_eval_krw = 0.0
    try:
        domestic = kis.get_domestic_balance() or {}
        domestic_holdings = domestic.get("holdings", []) or []
        for h in domestic_holdings:
            qty = int(float(h.get("qty", 0) or 0))
            current_price = float(h.get("current_price", 0) or 0)
            if qty > 0 and current_price > 0:
                domestic_eval_krw += (qty * current_price)
        holdings_count += len(domestic_holdings)
        domestic_wd = float(domestic.get("withdrawable_krw", 0) or 0)
        if domestic_wd > cash_krw:
            cash_krw = domestic_wd
    except Exception:
        pass

    if exchange_rate > 0:
        cash_krw += (cash * exchange_rate)
        eval_amount_krw += (eval_amount * exchange_rate)
    eval_amount_krw += domestic_eval_krw

    total_asset = cash + eval_amount
    total_asset_krw = cash_krw + eval_amount_krw
    if present_total_asset_krw > 0 and present_total_asset_krw >= total_asset_krw * 0.5:
        total_asset_krw = present_total_asset_krw

    cycle_db = trading.db("trading_cycle")
    active_cycles = (cycle_db.count(status="ACTIVE") or 0) + (cycle_db.count(status="HOLDING") or 0)

    total_profit = 0
    total_profit_krw = 0.0
    profit_rate = 0
    configured_base_asset = _configured_base_asset_krw(trading)
    initial_asset = 0.0
    first_snap = snap_db.rows(orderby="snapshot_date", order="ASC", page=1, dump=1)
    if first_snap:
        initial_asset = float(first_snap[0].get("total_asset", 0) or 0)
        if initial_asset > 0 and initial_asset < 100000 and exchange_rate > 0 and total_asset_krw > 100000:
            initial_asset = initial_asset * exchange_rate
    if configured_base_asset > 0 and (initial_asset <= 0 or initial_asset < configured_base_asset):
        initial_asset = configured_base_asset
    if initial_asset > 0 and total_asset_krw > 0:
        total_profit_krw = total_asset_krw - initial_asset
        total_profit = total_profit_krw
        profit_rate = (total_profit_krw / initial_asset) * 100
    elif initial_asset > 0:
        total_profit = total_asset - initial_asset
        profit_rate = (total_profit / initial_asset) * 100

    saved_cash = cash_krw if cash_krw > 0 else cash
    saved_eval = eval_amount_krw if eval_amount_krw > 0 else eval_amount
    saved_asset = total_asset_krw if total_asset_krw > 0 else total_asset
    saved_profit = total_profit_krw if total_asset_krw > 0 else total_profit

    snap_data = {
        "snapshot_date": today,
        "cash_balance": round(saved_cash, 2),
        "eval_amount": round(saved_eval, 2),
        "total_asset": round(saved_asset, 2),
        "total_profit": round(saved_profit, 2),
        "profit_rate": round(profit_rate, 2),
        "holdings_count": holdings_count,
        "active_cycles": active_cycles,
        "created": _TIME.now(),
    }

    if existing:
        snap_db.update(snap_data, id=existing["id"])
    else:
        snap_db.insert(snap_data)

    return snap_data


def run_engine(trading, symbol=None):
    """엔진 실행 (잠금 기반)"""
    global _is_running, _last_run, _last_result

    if _is_running:
        return {"success": False, "message": "엔진이 이미 실행 중입니다."}

    with _scheduler_lock:
        _is_running = True
        try:
            engine = trading.engine
            maintenance_result = run_maintenance_if_due(trading)
            auto_trade = engine._get_config_value("auto_trade_enabled", "false") == "true"
            daytrade_auto = False if _DAYTRADE_HARD_LOCKED else str(_config_value(trading, "daytrade_auto_enabled", "true")).lower() == "true"
            daytrade_exit_watch = False if _DAYTRADE_HARD_LOCKED else daytrade_auto and str(_config_value(trading, "daytrade_exit_watch_enabled", "true")).lower() == "true"
            loc_auto = str(_config_value(trading, "loc_auto_schedule_enabled", "true")).lower() == "true"

            if auto_trade is False and daytrade_auto is False and daytrade_exit_watch is False and loc_auto is False:
                _is_running = False
                return {"success": False, "message": "자동매매/단타 자동운용/단타 자동청산 감시/LOC 자동예약이 모두 비활성 상태입니다."}

            start_time = _TIME.now()
            engine_results = []

            if symbol:
                if auto_trade:
                    result = engine.run_daily(symbol)
                    result["symbol"] = symbol
                    engine_results = [result]
            else:
                if auto_trade:
                    engine_results = engine.run_all()

            daytrade_result = None
            if symbol is None and daytrade_auto:
                daytrade_result = run_daytrade_automation(trading)

            daytrade_exit_result = None
            if symbol is None and daytrade_exit_watch:
                daytrade_exit_result = run_daytrade_exit_watch(trading)

            loc_buy_result = None
            loc_sell_result = None
            loc_automation_result = None
            if symbol is None and loc_auto:
                loc_automation_result = trading.run_due_loc_automation(
                    verify=True,
                    reason="scheduler_run_5min_reservation_verify",
                )
                loc_buy_result = (loc_automation_result or {}).get("buy")
                loc_sell_result = (loc_automation_result or {}).get("sell")

            end_time = _TIME.now()
            elapsed = (end_time - start_time).total_seconds()

            snapshot = None
            try:
                snapshot = take_snapshot(trading)
            except Exception:
                pass

            _last_run = _TIME.isoformat(end_time, with_offset=True)
            _last_result = {
                "success": True,
                "maintenance": maintenance_result,
                "results": engine_results,
                "daytrade": daytrade_result,
                "daytrade_exit_watch": daytrade_exit_result,
                "loc_auto": {
                    "buy": loc_buy_result,
                    "sell": loc_sell_result,
                    "automation": loc_automation_result,
                },
                "elapsed_seconds": round(elapsed, 2),
                "executed_at": _last_run,
            }

            engine._log_event("SYSTEM", "", "SCHEDULER_RUN",
                              message=f"스케줄러 실행 완료: 무한매수 {len(engine_results)}건, 단타자동 {'ON' if daytrade_auto else 'OFF'}, 단타자동청산 {'ON' if daytrade_exit_watch else 'OFF'}, {elapsed:.1f}초 소요")

            return _last_result

        except Exception as e:
            try:
                engine = trading.engine
                engine._log_event("SYSTEM", "", "SCHEDULER_ERROR",
                                  message=f"스케줄러 오류: {str(e)}")
            except Exception:
                pass
            _last_result = {"success": False, "message": str(e)}
            return _last_result
        finally:
            _is_running = False


# ═══════════════════════════════════════════════════════════════════════════
# Route 핸들러 (스크립트 방식)
# ═══════════════════════════════════════════════════════════════════════════

segment = wiz.request.match("/api/trading/scheduler/<action>/<param>")
if not segment:
    segment = wiz.request.match("/api/trading/scheduler/<action>")

if not segment:
    wiz.response.status(404, message="Not Found")

action = segment.action
param = getattr(segment, 'param', None)

# ─── Health Check (토큰 불필요) ───
if action == "health":
    wiz.response.status(200,
        status="ok",
        is_running=_is_running,
        last_run=_last_run,
        timestamp=_TIME.isoformat(with_offset=True))

# ─── 토큰 검증 ───
if not verify_token():
    wiz.response.status(401, message="Invalid scheduler token")

struct = wiz.model("struct")
trading = struct.trading
maintenance_status = run_maintenance_if_due(trading)

# ─── Run Engine ───
if action == "run":
    result = run_engine(trading, symbol=param)
    if result.get("success"):
        wiz.response.status(200, **result)
    else:
        wiz.response.status(409, **result)

# ─── Due LOC Automation / Verification ───
if action in ["due", "due-loc", "loc-due", "run-due-automation", "verify-reservations", "reservation-verify"]:
    force = _truthy(wiz.request.query("force", ""))
    verify_param = str(wiz.request.query("verify", "") or "").strip()
    verify = _truthy(verify_param) if verify_param else (not force)
    symbol_text = str(wiz.request.query("symbols", wiz.request.query("symbol", "")) or "")
    symbols = [
        item.strip().upper()
        for item in symbol_text.replace(";", ",").split(",")
        if item.strip()
    ]
    try:
        result = trading.run_due_loc_automation(
            force=force,
            verify=verify,
            reason=f"scheduler_{action}",
            symbols=symbols,
        )
    except Exception as e:
        wiz.response.status(500, message=str(e))
    wiz.response.status(200, **(result or {}))

# ─── LOC Sell Schedule ───
if action in ["loc-buy", "locbuy", "schedule-loc-buy"]:
    try:
        result = trading.run_due_loc_automation(force=True, reason=f"scheduler_{action}")
    except Exception as e:
        wiz.response.status(500, message=str(e))
    wiz.response.status(200, **result)

# ─── LOC Sell Schedule ───
if action in ["loc-sell", "locsell", "schedule-loc-sell"]:
    confirm_execute = str(wiz.request.query("execute", "") or "").strip().lower() in ("1", "true", "yes", "y", "on")
    if confirm_execute is False:
        wiz.response.status(409,
            status="blocked",
            executed=False,
            message="LOC 예약매도 수동 실행은 실주문을 만들 수 있어 execute=true 확인 파라미터가 필요합니다.",
            required_confirm="execute=true")
    try:
        result = trading.run_due_loc_automation(force=True, reason=f"scheduler_{action}")
    except Exception as e:
        wiz.response.status(500, message=str(e))
    wiz.response.status(200, **result)

# ─── External Broker Fill Sync ───
if action in ["external-sync", "external-cycle-sync", "sync-external-cycles"]:
    try:
        result = trading.engine.sync_external_cycle_trades(lookback_days=7, symbol_filter=param or "")
    except Exception as e:
        wiz.response.status(500, message=str(e))
    wiz.response.status(200, **result)

# ─── Status ───
if action == "status":
    engine_status = trading.engine.get_status()
    wiz.response.status(200,
        is_running=_is_running,
        last_run=_last_run,
        last_result=_last_result,
        maintenance=maintenance_status,
        engine=engine_status,
        timestamp=_TIME.isoformat(with_offset=True))

# ─── Snapshot ───
if action == "snapshot":
    try:
        snap = take_snapshot(trading, force_update=True)
    except Exception as e:
        wiz.response.status(500, message=str(e))
    wiz.response.status(200, snapshot=snap)

wiz.response.status(404, message=f"Unknown action: {action}")
