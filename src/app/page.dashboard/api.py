import json
import datetime
import random
import re
import copy
import os
import threading
import traceback
import time
import sys as _sys
import urllib.parse
import urllib.request

_TIME = wiz.model("portal/trading/kst")
try:
    _SESSION_MODEL = wiz.model("portal/season/session")
except Exception:
    _SESSION_MODEL = None

_ERR_LOG = "/tmp/wiz_dashboard_api_errors.log"


def _dump_error(label, e):
    try:
        with open(_ERR_LOG, "a") as f:
            f.write(f"\n=== {_TIME.isoformat(with_offset=True)} [{label}] ===\n")
            f.write(f"{type(e).__name__}: {e}\n")
            f.write(traceback.format_exc())
            f.write("\n")
    except Exception:
        pass


try:
    logger = wiz.logger("dashboard", "api")
except Exception as e:
    logger = None
    _dump_error("logger_init", e)

KST = datetime.timezone(datetime.timedelta(hours=9))
_LOC_RESERVATION_START_HHMM = 1000
_LOC_RESERVATION_END_STANDARD_HHMM = 2320
_LOC_RESERVATION_END_SUMMER_HHMM = 2220
_STRUCT_CACHE = {"obj": None, "error": None, "error_at": 0.0}
_STRUCT_ERROR_TTL_SEC = 5.0
_KIS_STATUS_CACHE = {"checked_at": 0.0, "result": None, "last_success_at": 0.0}
_KIS_STATUS_SUCCESS_TTL_SEC = 20.0
_KIS_STATUS_FAILURE_TTL_SEC = 3.0
_KIS_STICKY_SUCCESS_GRACE_SEC = 180.0
_OVERVIEW_CACHE = {}
_TRADE_PREVIEW_CACHE = {}
_PROFIT_SUMMARY_CACHE = {}
_US_LIVE_PRICE_CACHE = {}
_DUE_AUTOMATION_LAST_BUCKET = ""
_CACHE_LOCK = threading.Lock()
_SINGLEFLIGHT_EVENTS = {}
_OVERVIEW_TTL_SEC = 30.0
_TRADE_PREVIEW_TTL_SEC = 12.0
_PROFIT_SUMMARY_TTL_SEC = 30.0
_EXTERNAL_CYCLE_SYNC_TTL_SEC = 300.0
_US_LIVE_PRICE_TTL_SEC = 10.0

_FIREGATE_INFINITY_SOURCE = "infinitystock"
_FIREGATE_INFINITY_GROUP = "InfinityStock Auto"
_FIREGATE_INFINITY_CATEGORY = "infinite_buy"


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
    now = now or _TIME.now()
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


def _cache_get(store, key, ttl_sec):
    with _CACHE_LOCK:
        entry = store.get(key)
    if isinstance(entry, dict) is False:
        return None, None
    age = time.monotonic() - float(entry.get("ts", 0.0) or 0.0)
    if age >= ttl_sec:
        return None, None
    return copy.deepcopy(entry.get("payload", {})), round(age, 2)


def _cache_set(store, key, payload):
    with _CACHE_LOCK:
        store[key] = {
            "ts": time.monotonic(),
            "payload": copy.deepcopy(payload),
        }


def _singleflight(key, builder, timeout_sec=60.0):
    leader = False
    with _CACHE_LOCK:
        event = _SINGLEFLIGHT_EVENTS.get(key)
        if event is None:
            event = threading.Event()
            _SINGLEFLIGHT_EVENTS[key] = event
            leader = True
    if leader:
        try:
            return builder(), True
        finally:
            with _CACHE_LOCK:
                event.set()
                _SINGLEFLIGHT_EVENTS.pop(key, None)
    event.wait(timeout=timeout_sec)
    return None, False


def _session_user_id():
    global _SESSION_MODEL
    try:
        if _SESSION_MODEL is None:
            _SESSION_MODEL = wiz.model("portal/season/session")
        session = _SESSION_MODEL.use()
        return str(session.get("id", "") or "").strip()
    except Exception:
        return ""


def _dashboard_cache_scope():
    user_id = _session_user_id()
    return f"user:{user_id}" if user_id else "anon"


def _broker_setup_state(trading, require_connection=False):
    user_id = _session_user_id()
    if not user_id:
        return {
            "allowed": False,
            "user_id": "",
            "broker_provider": "",
            "configured": False,
            "connected": False,
            "message": "로그인 세션을 확인하지 못했습니다. 다시 로그인한 뒤 이용해주세요.",
        }

    try:
        provider = str(trading.get_config("broker_provider", "kis") or "kis").strip().lower()
    except Exception:
        provider = "kis"
    if provider not in ("kis", "toss"):
        provider = "kis"

    missing = []
    if provider == "toss":
        if str(trading.get_config("toss_client_id", "") or "").strip() == "":
            missing.append("토스증권 클라이언트 ID")
        if str(trading.get_config("toss_client_secret", "") or "").strip() == "":
            missing.append("토스증권 클라이언트 비밀키")
    else:
        if str(trading.get_config("kis_app_key", "") or "").strip() == "":
            missing.append("한국투자증권 App Key")
        if str(trading.get_config("kis_app_secret", "") or "").strip() == "":
            missing.append("한국투자증권 App Secret")
        if str(trading.get_config("kis_account_no", "") or "").strip() == "":
            missing.append("한국투자증권 계좌번호")

    if missing:
        return {
            "allowed": False,
            "user_id": user_id,
            "broker_provider": provider,
            "configured": False,
            "connected": False,
            "message": "증권사 API 연결 전에는 개인정보 보호를 위해 대시보드 자산/수익/보유내역을 표시하지 않습니다. 설정에서 " + ", ".join(missing) + "을 입력해주세요.",
        }

    if require_connection:
        status = _kis_connection_status(trading, ttl_sec=0)
        sticky_only = status.get("sticky") is True and status.get("raw_success") is False
        if status.get("success") is not True or sticky_only:
            return {
                "allowed": False,
                "user_id": user_id,
                "broker_provider": provider,
                "configured": True,
                "connected": False,
                "message": "증권사 API 연결이 확인되지 않아 개인정보 보호를 위해 대시보드 자산/수익/보유내역을 표시하지 않습니다. 설정에서 연결 테스트를 완료해주세요.",
                "connection_message": str(status.get("message", "") or ""),
            }

    return {
        "allowed": True,
        "user_id": user_id,
        "broker_provider": provider,
        "configured": True,
        "connected": bool(require_connection),
        "message": "",
    }


def _require_dashboard_access(require_connection=True):
    trading = _require_trading()
    setup_state = _broker_setup_state(trading, require_connection=require_connection)
    if setup_state.get("allowed") is not True:
        message = setup_state.get("message", "")
        detail = str(setup_state.get("connection_message", "") or "").strip()
        if detail:
            message = f"{message} ({detail})"
        wiz.response.status(
            403,
            message=message,
            setup_required=True,
            privacy_locked=True,
            broker_provider=setup_state.get("broker_provider", ""),
            broker_configured=setup_state.get("configured", False),
            broker_connected=setup_state.get("connected", False),
        )
    return trading


def _log(level, message):
    try:
        if logger is None:
            return
        method = getattr(logger, level, None)
        if method is None:
            method = getattr(logger, "warning", None)
        if method is None:
            method = getattr(logger, "info", None)
        if method is not None:
            method(message)
    except Exception:
        pass


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "y", "yes", "on")


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


def _safe_float(value, default=0.0):
    try:
        text = str(value if value is not None else "").strip()
        if text == "":
            return float(default)
        return float(text)
    except Exception:
        return float(default)


def _normalize_symbol(value):
    return re.sub(r"[^A-Z0-9.\-]", "", str(value or "").upper().strip())


def _is_firegate_authoritative_portfolio(portfolio, source=_FIREGATE_INFINITY_SOURCE, group=_FIREGATE_INFINITY_GROUP, category=_FIREGATE_INFINITY_CATEGORY):
    portfolio = portfolio if isinstance(portfolio, dict) else {}
    if str(portfolio.get("source", "") or "") == str(source):
        return True
    if str(portfolio.get("portfolioGroup", "") or "") == str(group):
        return True
    if str(portfolio.get("category", "") or "") == str(category):
        return True
    return False


def _extract_firegate_authoritative_symbols(portfolios, source=_FIREGATE_INFINITY_SOURCE, group=_FIREGATE_INFINITY_GROUP, category=_FIREGATE_INFINITY_CATEGORY):
    symbols = []
    seen = set()
    for portfolio in portfolios or []:
        if _is_firegate_authoritative_portfolio(portfolio, source=source, group=group, category=category) is False:
            continue
        symbol = _normalize_symbol((portfolio or {}).get("ticker") or (portfolio or {}).get("symbol"))
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def _filter_rows_by_symbols(rows, symbols):
    symbol_set = {_normalize_symbol(symbol) for symbol in (symbols or []) if _normalize_symbol(symbol)}
    if len(symbol_set) == 0:
        return list(rows or [])
    filtered = []
    for row in rows or []:
        if _normalize_symbol((row or {}).get("symbol")) in symbol_set:
            filtered.append(row)
    return filtered


def _sync_external_cycle_trades_if_due(trading, force=False, symbol_filter=""):
    key = f"_dashboard_external_cycle_sync_ts:{str(symbol_filter or '').upper()}"
    bucket_key = f"_dashboard_external_cycle_sync_bucket:{str(symbol_filter or '').upper()}"
    now_ts = time.monotonic()
    now = _TIME.now()
    last_ts = float(getattr(_sys, key, 0.0) or 0.0)
    bucket = f"{now.strftime('%Y-%m-%d')}-{now.hour:02d}-{now.minute // 10}"
    last_bucket = str(getattr(_sys, bucket_key, "") or "")
    if force is False:
        if not (8 <= int(now.hour) < 10):
            return {"status": "deferred", "synced_count": 0, "message": "outside_morning_sync_window", "scheduled_window": "08:00-10:00 KST"}
        if last_bucket == bucket or (now_ts - last_ts) < 60:
            return {"status": "cached", "synced_count": 0, "bucket": bucket, "scheduled_window": "08:00-10:00 KST"}
    try:
        result = trading.engine.sync_external_cycle_trades(lookback_days=7, symbol_filter=symbol_filter) or {}
        if _external_cycle_sync_verified(result):
            setattr(_sys, key, now_ts)
            setattr(_sys, bucket_key, bucket)
        result["bucket"] = bucket
        result["scheduled_window"] = "08:00-10:00 KST"
        return result
    except Exception as e:
        _dump_error("external_cycle_sync", e)
        return {"status": "error", "message": str(e), "synced_count": 0}


def _loc_reservation_bucket(now):
    schedule_key = (now - datetime.timedelta(days=1)).strftime("%Y-%m-%d") if now.hour < 7 else now.strftime("%Y-%m-%d")
    return f"{schedule_key}-{now.hour:02d}-{now.minute // 5}"


def _sync_firegate_portfolios_before_loc(trading, symbol_filter=""):
    try:
        fg = wiz.model("portal/trading/struct/firegate_bridge")
        return fg.sync_portfolios_to_local(trading, symbol_filter=symbol_filter) or {}
    except Exception as e:
        _dump_error("firegate_before_loc", e)
        return {"executed": False, "status": "error", "message": str(e)}


def _scoped_engine_status(engine_status, cycles):
    scoped = dict(engine_status or {})
    counts = {
        "active_cycles": 0,
        "holding_cycles": 0,
        "paused_cycles": 0,
        "pending_extension_cycles": 0,
    }
    for cycle in cycles or []:
        status = str((cycle or {}).get("status", "") or "").upper()
        if status == "ACTIVE":
            counts["active_cycles"] += 1
        elif status == "HOLDING":
            counts["holding_cycles"] += 1
        elif status == "PAUSED":
            counts["paused_cycles"] += 1
        elif status == "PENDING_EXTENSION":
            counts["pending_extension_cycles"] += 1
    scoped.update(counts)
    return scoped


def _firegate_overview_scope(trading, force_refresh=False):
    fire_gate_bridge = {"enabled": False, "configured": False, "auto_sync_enabled": True, "auto_sync_interval_sec": 600}
    authoritative_symbols = []
    try:
        fg = wiz.model("portal/trading/struct/firegate_bridge")
        cfg = fg.load_bridge_config(trading)
        email = str((cfg or {}).get("email", "") or "")
        email_masked = email
        if "@" in email:
            name, domain = email.split("@", 1)
            email_masked = f"{name[:2]}***@{domain}"
        fire_gate_bridge = {
            "enabled": bool((cfg or {}).get("enabled", False)),
            "configured": bool(email and (((cfg or {}).get("id_token")) or ((cfg or {}).get("refresh_token")))),
            "auto_sync_enabled": bool((cfg or {}).get("auto_sync_enabled", True)),
            "auto_sync_interval_sec": max(int(float((cfg or {}).get("auto_sync_interval_sec", 600) or 600)), 30),
            "email_masked": email_masked,
        }
        if fire_gate_bridge["enabled"] and fire_gate_bridge["configured"]:
            if force_refresh:
                try:
                    sync_fn = getattr(fg, "sync_portfolios_to_local", None)
                    if callable(sync_fn):
                        sync_fn(trading)
                except Exception as e:
                    _log("warning", f"firegate overview pull failed: {e}")
            else:
                return fire_gate_bridge, authoritative_symbols
            try:
                bridge = fg.bridge_from_config(cfg)
                source = getattr(fg, "INFINITYSTOCK_SOURCE", _FIREGATE_INFINITY_SOURCE)
                group = getattr(fg, "INFINITYSTOCK_PORTFOLIO_GROUP", _FIREGATE_INFINITY_GROUP)
                category = getattr(fg, "INFINITYSTOCK_PORTFOLIO_CATEGORY", _FIREGATE_INFINITY_CATEGORY)
                authoritative_symbols = _extract_firegate_authoritative_symbols(
                    bridge.list_portfolios() or [],
                    source=source,
                    group=group,
                    category=category,
                )
            except Exception as e:
                _log("warning", f"firegate overview scope failed: {e}")
    except Exception:
        pass
    return fire_gate_bridge, authoritative_symbols


def _combine_profit_components(cycle_realized_profit=0.0, cycle_unrealized_profit=0.0, daytrade_realized_profit=0.0, daytrade_unrealized_profit=0.0):
    cycle_realized = float(cycle_realized_profit or 0)
    cycle_unrealized = float(cycle_unrealized_profit or 0)
    daytrade_realized = float(daytrade_realized_profit or 0)
    daytrade_unrealized = float(daytrade_unrealized_profit or 0)
    realized_profit = cycle_realized + daytrade_realized
    unrealized_profit = cycle_unrealized + daytrade_unrealized
    return {
        "realized_profit": realized_profit,
        "unrealized_profit": unrealized_profit,
        "total_profit": realized_profit + unrealized_profit,
    }


def _holding_eval_sum(holdings):
    by_symbol = {}
    for row in holdings or []:
        symbol = _normalize_symbol((row or {}).get("symbol", ""))
        qty = _safe_float((row or {}).get("qty", (row or {}).get("quantity", (row or {}).get("holding_qty", 0))), 0)
        if not symbol or qty <= 0:
            continue
        eval_amount = _safe_float((row or {}).get("eval_amount", (row or {}).get("value", 0)), 0)
        if eval_amount <= 0:
            eval_amount = qty * _safe_float((row or {}).get("current_price", (row or {}).get("price", 0)), 0)
        if eval_amount <= 0:
            continue
        previous = by_symbol.get(symbol)
        if previous is None or eval_amount >= previous:
            by_symbol[symbol] = eval_amount
    total = sum(by_symbol.values())
    count = len(by_symbol)
    return round(total, 2), count


def _yahoo_chart_extended_price(symbol, refresh=False):
    symbol = _normalize_symbol(symbol)
    if not symbol:
        return None
    cache_key = f"yahoo-chart:{symbol}"
    if refresh is False:
        cached, cache_age = _cache_get(_US_LIVE_PRICE_CACHE, cache_key, _US_LIVE_PRICE_TTL_SEC)
    else:
        cached, cache_age = None, None
    if isinstance(cached, dict):
        cached["cache_age_sec"] = cache_age
        ts_epoch = _safe_float(cached.get("timestamp_epoch"), 0)
        if ts_epoch > 0:
            cached["age_sec"] = round(max(0.0, time.time() - ts_epoch), 1)
        return cached
    try:
        query = urllib.parse.urlencode({
            "range": "1d",
            "interval": "1m",
            "includePrePost": "true",
        })
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{query}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 InfinityStockDashboard/1.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=4) as res:
            payload = json.loads(res.read().decode("utf-8"))

        chart = (payload or {}).get("chart", {}) or {}
        results = chart.get("result", []) or []
        if len(results) == 0:
            return None
        result = results[0] or {}
        timestamps = result.get("timestamp", []) or []
        quote = (((result.get("indicators", {}) or {}).get("quote", []) or [{}])[0]) or {}
        closes = quote.get("close", []) or []
        meta = result.get("meta", {}) or {}

        price = 0.0
        ts_epoch = 0
        for ts, close in reversed(list(zip(timestamps, closes))):
            close_price = _safe_float(close, 0)
            if close_price > 0:
                price = close_price
                ts_epoch = int(ts or 0)
                break

        if price <= 0:
            price = _safe_float(meta.get("regularMarketPrice"), 0)
            ts_epoch = int(_safe_float(meta.get("regularMarketTime"), 0))
        if price <= 0:
            return None

        timestamp = ""
        timestamp_kst = ""
        if ts_epoch > 0:
            ts_utc = datetime.datetime.fromtimestamp(ts_epoch, datetime.timezone.utc)
            timestamp = ts_utc.isoformat()
            timestamp_kst = ts_utc.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")

        result = {
            "symbol": symbol,
            "price": round(price, 4),
            "source": "yahoo_chart:1m_prepost",
            "timestamp": timestamp,
            "timestamp_kst": timestamp_kst,
            "timestamp_epoch": ts_epoch,
            "age_sec": round(max(0.0, time.time() - ts_epoch), 1) if ts_epoch > 0 else 0,
            "market_state": str(meta.get("marketState", "") or ""),
        }
        _cache_set(_US_LIVE_PRICE_CACHE, cache_key, result)
        return result
    except Exception as e:
        _log("warning", f"Yahoo chart extended price failed [{symbol}]: {e}")
        return None


def _config_or_env(trading, key, env_names, default=""):
    value = ""
    try:
        getter = getattr(trading, "get_config", None)
        if callable(getter):
            value = getter(key, "")
    except Exception:
        value = ""
    value = str(value or "").strip()
    if value:
        return value
    for env_name in env_names or []:
        env_value = str(os.environ.get(env_name, "") or "").strip()
        if env_value:
            return env_value
    return default


def _parse_feed_timestamp(value):
    text = str(value or "").strip()
    if not text:
        return "", "", 0
    normalized = text.replace("Z", "+00:00")
    if "." in normalized:
        head, tail = normalized.split(".", 1)
        tz = ""
        for idx in range(1, len(tail)):
            if tail[idx] in ("+", "-"):
                tz = tail[idx:]
                tail = tail[:idx]
                break
        normalized = f"{head}.{tail[:6].ljust(6, '0')}{tz}"
    try:
        parsed = datetime.datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        parsed_utc = parsed.astimezone(datetime.timezone.utc)
        return parsed_utc.isoformat(), parsed_utc.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST"), int(parsed_utc.timestamp())
    except Exception:
        return text, "", 0


def _alpaca_overnight_price(trading, symbol, refresh=False):
    symbol = _normalize_symbol(symbol)
    if not symbol:
        return None
    api_key = str(os.environ.get("ALPACA_API_KEY", "") or os.environ.get("APCA_API_KEY_ID", "") or "").strip()
    api_secret = str(os.environ.get("ALPACA_API_SECRET", "") or os.environ.get("ALPACA_SECRET_KEY", "") or os.environ.get("APCA_API_SECRET_KEY", "") or "").strip()
    if not api_key or not api_secret:
        return None

    feed = str(os.environ.get("ALPACA_DATA_FEED", "overnight") or "overnight").strip().lower()
    if feed not in ("overnight", "boats"):
        feed = "overnight"
    max_age_sec = _safe_float(os.environ.get("ALPACA_OVERNIGHT_MAX_AGE_SEC", "7200"), 7200)
    cache_key = f"alpaca:{feed}:{symbol}"
    if refresh is False:
        cached, cache_age = _cache_get(_US_LIVE_PRICE_CACHE, cache_key, _US_LIVE_PRICE_TTL_SEC)
    else:
        cached, cache_age = None, None
    if isinstance(cached, dict):
        cached["cache_age_sec"] = cache_age
        ts_epoch = _safe_float(cached.get("timestamp_epoch"), 0)
        if ts_epoch > 0:
            cached["age_sec"] = round(max(0.0, time.time() - ts_epoch), 1)
        if ts_epoch <= 0 or cached.get("age_sec", 0) <= max_age_sec:
            return cached
        return None

    try:
        query = urllib.parse.urlencode({"symbols": symbol, "feed": feed})
        url = f"https://data.alpaca.markets/v2/stocks/quotes/latest?{query}"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": api_secret,
                "User-Agent": "InfinityStockDashboard/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=4) as res:
            payload = json.loads(res.read().decode("utf-8"))
        quotes = (payload or {}).get("quotes", {}) or {}
        quote = quotes.get(symbol) or quotes.get(symbol.upper()) or {}
        bid_price = _safe_float(quote.get("bp"), 0)
        ask_price = _safe_float(quote.get("ap"), 0)
        if bid_price > 0 and ask_price > 0:
            price = (bid_price + ask_price) / 2
        else:
            price = ask_price or bid_price
        if price <= 0:
            return None
        timestamp, timestamp_kst, ts_epoch = _parse_feed_timestamp(quote.get("t"))
        age_sec = round(max(0.0, time.time() - ts_epoch), 1) if ts_epoch > 0 else 0
        if ts_epoch > 0 and age_sec > max_age_sec:
            _log("warning", f"Alpaca overnight price stale [{symbol}:{feed}]: age={age_sec}s")
            return None
        result = {
            "symbol": symbol,
            "price": round(price, 4),
            "source": f"alpaca:{feed}_quote",
            "timestamp": timestamp,
            "timestamp_kst": timestamp_kst,
            "timestamp_epoch": ts_epoch,
            "age_sec": age_sec,
            "market_state": "overnight",
            "bid_price": round(bid_price, 4) if bid_price > 0 else 0,
            "ask_price": round(ask_price, 4) if ask_price > 0 else 0,
        }
        _cache_set(_US_LIVE_PRICE_CACHE, cache_key, result)
        return result
    except Exception as e:
        _log("warning", f"Alpaca overnight price failed [{symbol}:{feed}]: {e}")
        return None


def _display_us_price(trading, symbol, exchange="NAS", refresh=False):
    symbol = _normalize_symbol(symbol)
    overnight_result = _alpaca_overnight_price(trading, symbol, refresh=refresh)
    overnight_price = _safe_float((overnight_result or {}).get("price"), 0)
    if overnight_price > 0:
        return overnight_result

    kis_price = 0.0
    kis_result = None
    try:
        broker = getattr(trading, "broker_api", None) or trading.kis_api
        kis_result = broker.get_current_price(symbol, exchange=exchange)
        kis_price = _safe_float((kis_result or {}).get("price"), 0)
    except Exception as e:
        _log("warning", f"broker display price failed [{symbol}:{exchange}]: {e}")
    live_result = _yahoo_chart_extended_price(symbol, refresh=refresh)
    live_price = _safe_float((live_result or {}).get("price"), 0)
    if live_price > 0 and (kis_price <= 0 or abs(live_price - kis_price) >= 0.01):
        return live_result
    if kis_price > 0:
        return {
            "symbol": symbol,
            "price": round(kis_price, 4),
            "source": f"{str((kis_result or {}).get('source') or 'BROKER')}:{(kis_result or {}).get('exchange', exchange)}",
            "timestamp": "",
            "timestamp_kst": "",
            "timestamp_epoch": 0,
            "age_sec": 0,
            "market_state": "",
        }
    return None


def _refresh_cycle_prices_for_display(trading, cycles, refresh=False):
    refreshed = []
    for cycle in cycles or []:
        row = dict(cycle or {})
        symbol = _normalize_symbol(row.get("symbol", ""))
        qty = _safe_float(row.get("total_qty", 0), 0)
        if not symbol or qty <= 0:
            refreshed.append(row)
            continue
        price_data = _display_us_price(trading, symbol, exchange="AMS" if symbol == "SOXL" else "NAS", refresh=refresh)
        price = _safe_float((price_data or {}).get("price"), 0)
        if price > 0:
            try:
                trading.engine.update_cycle_price(row.get("id"), price)
            except Exception:
                pass
            total_spent = _safe_float(row.get("total_spent", 0), 0)
            current_eval = qty * price
            row["current_price"] = round(price, 4)
            row["current_eval"] = round(current_eval, 2)
            row["price_source"] = (price_data or {}).get("source", "")
            row["price_timestamp"] = (price_data or {}).get("timestamp", "")
            row["price_timestamp_kst"] = (price_data or {}).get("timestamp_kst", "")
            row["price_age_sec"] = (price_data or {}).get("age_sec", 0)
            row["price_market_state"] = (price_data or {}).get("market_state", "")
            row["profit_rate"] = round(((current_eval - total_spent) / total_spent * 100) if total_spent > 0 else 0, 2)
        refreshed.append(row)
    return refreshed


def _apply_live_us_prices_to_holdings(trading, holdings, refresh=False):
    updated = []
    seen = set()
    for holding in holdings or []:
        row = dict(holding or {})
        symbol = _normalize_symbol(row.get("symbol", ""))
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        qty = _safe_float(row.get("qty", row.get("holding_qty", 0)), 0)
        if qty > 0:
            price_data = _display_us_price(trading, symbol, exchange="AMS" if symbol == "SOXL" else str(row.get("exchange", "NAS") or "NAS"), refresh=refresh)
            price = _safe_float((price_data or {}).get("price"), 0)
            if price > 0:
                row["current_price"] = price
                row["eval_amount"] = round(qty * price, 2)
                row["price_source"] = (price_data or {}).get("source", "")
                row["price_timestamp"] = (price_data or {}).get("timestamp", "")
                row["price_timestamp_kst"] = (price_data or {}).get("timestamp_kst", "")
                row["price_age_sec"] = (price_data or {}).get("age_sec", 0)
                avg = _safe_float(row.get("avg_price", 0), 0)
                if avg > 0:
                    row["profit_loss"] = round((price - avg) * qty, 2)
                    row["profit_rate"] = round(((price - avg) / avg) * 100, 2)
        updated.append(row)
    return updated


def _select_total_asset_krw(summary_total_asset_krw=0, present_total_asset_krw=0, direct_total_asset_krw=0, fallback_total_asset_krw=0):
    summary = _safe_float(summary_total_asset_krw, 0)
    if summary > 0:
        return summary, "summary_total_asset"
    present = _safe_float(present_total_asset_krw, 0)
    if present > 0:
        return present, "present_total_asset"
    direct = _safe_float(direct_total_asset_krw, 0)
    if direct > 0:
        return direct, "direct(cash+portfolio)"
    return _safe_float(fallback_total_asset_krw, 0), "fallback"


def _cycle_has_local_trade(cycle, trade_db=None, action=""):
    if trade_db is None:
        return True
    cycle_id = str((cycle or {}).get("id", "") or "")
    if not cycle_id:
        return True
    try:
        rows = trade_db.rows(cycle_id=cycle_id, orderby="created", order="DESC", dump=200) or []
    except TypeError:
        rows = trade_db.rows(cycle_id=cycle_id) or []
    except Exception:
        return True
    action = str(action or "").upper()
    for row in rows:
        row_action = str((row or {}).get("action", "") or "").upper()
        row_status = str((row or {}).get("status", "") or "").upper()
        qty = _safe_float((row or {}).get("filled_qty", (row or {}).get("qty", 0)), 0)
        amount = _safe_float((row or {}).get("filled_amount", (row or {}).get("amount", 0)), 0)
        if row_status and row_status != "FILLED":
            continue
        if action and row_action != action:
            continue
        if qty > 0 or amount > 0:
            return True
    return False


def _include_completed_cycle_in_realized(cycle, trade_db=None):
    cycle = cycle if isinstance(cycle, dict) else {}
    if str(cycle.get("status", "") or "").upper() != "COMPLETED":
        return False
    if _cycle_has_local_trade(cycle, trade_db=trade_db, action="SELL") is False:
        return False
    total_qty = int(float(cycle.get("total_qty", 0) or 0))
    current_eval = float(cycle.get("current_eval", 0) or 0)
    if total_qty > 0 and current_eval <= 0:
        return False
    return True


def _include_active_cycle_in_unrealized(cycle, trade_db=None):
    cycle = cycle if isinstance(cycle, dict) else {}
    if str(cycle.get("status", "") or "").upper() not in ("ACTIVE", "HOLDING", "PAUSED", "PENDING_EXTENSION"):
        return False
    if int(float(cycle.get("total_qty", 0) or 0)) <= 0:
        return False
    if float(cycle.get("total_spent", 0) or 0) <= 0:
        return False
    if _cycle_has_local_trade(cycle, trade_db=trade_db, action="BUY") is False:
        return False
    return True


def _cycle_trade_date_key(row):
    row = row if isinstance(row, dict) else {}
    trade_date = str(row.get("trade_date", "") or "").strip()
    if len(trade_date) >= 10:
        return trade_date[:10]
    created = row.get("created", "")
    if created:
        return str(created)[:10]
    return ""


def _is_cycle_partial_sell_trade(row):
    row = row if isinstance(row, dict) else {}
    if str(row.get("action", "") or "").upper() != "SELL":
        return False
    status = str(row.get("status", "") or "").upper()
    if status and status not in ("FILLED", "PARTIAL"):
        return False
    if _safe_float(row.get("filled_qty", row.get("order_qty", 0)), 0) <= 0:
        return False
    strategy_type = str(row.get("strategy_type", "") or "").upper()
    total_qty_after = _safe_float(row.get("total_qty_after", 0), 0)
    return strategy_type == "PARTIAL_SELL" or total_qty_after > 0


def _cycle_sell_trade_realized_components(row):
    row = row if isinstance(row, dict) else {}
    qty = _safe_float(row.get("filled_qty", row.get("order_qty", 0)), 0)
    price = _safe_float(row.get("filled_price", row.get("order_price", 0)), 0)
    amount = _safe_float(row.get("filled_amount", 0), 0)
    if amount <= 0 and qty > 0 and price > 0:
        amount = qty * price
    avg_buy_price = _safe_float(row.get("avg_buy_price", 0), 0)
    commission = max(0.0, _safe_float(row.get("commission", 0), 0))
    if qty <= 0 or amount <= 0 or avg_buy_price <= 0:
        return None
    cost = avg_buy_price * qty
    realized = amount - cost - commission
    return {
        "date": _cycle_trade_date_key(row),
        "realized": realized,
        "cost": cost,
        "amount": amount,
        "commission": commission,
    }


def _cycle_partial_sell_realized_summary(trade_db=None, date_from="", date_to=""):
    if trade_db is None:
        return {"realized": 0.0, "cost": 0.0, "count": 0, "by_date": {}}
    try:
        rows = trade_db.rows(orderby="created", order="DESC", dump=5000) or []
    except TypeError:
        rows = trade_db.rows() or []
    except Exception:
        rows = []

    total_realized = 0.0
    total_cost = 0.0
    count = 0
    by_date = {}
    date_from = str(date_from or "")
    date_to = str(date_to or "")

    for row in rows:
        if _is_cycle_partial_sell_trade(row) is False:
            continue
        components = _cycle_sell_trade_realized_components(row)
        if components is None:
            continue
        date_key = str(components.get("date", "") or "")
        if date_from and date_key and date_key < date_from:
            continue
        if date_to and date_key and date_key > date_to:
            continue
        realized = float(components.get("realized", 0) or 0)
        cost = float(components.get("cost", 0) or 0)
        total_realized += realized
        total_cost += cost
        count += 1
        if date_key:
            by_date[date_key] = by_date.get(date_key, 0.0) + realized

    return {
        "realized": total_realized,
        "cost": total_cost,
        "count": count,
        "by_date": by_date,
    }


def _infinite_buy_realized_date_window(period, filter_from="", filter_to="", now=None, explicit_dates=False):
    if explicit_dates or str(period or "").upper() != "1D":
        return str(filter_from or ""), str(filter_to or "")
    now = now or _TIME.aware_now()
    if getattr(now, "tzinfo", None) is None:
        now = now.replace(tzinfo=KST)
    today = now.strftime("%Y-%m-%d")
    # KIS 미국장 체결은 전일 US 거래일로 저장될 수 있어 KST 1D 실현손익에 같이 포함한다.
    previous_trade_date = (now - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    return previous_trade_date, str(filter_to or today)


def _daytrade_state_realized_total(trading, session_date=None):
    try:
        engine = trading.daytrade_engine
        state_map = engine._load_state_map() or {}
    except Exception:
        return 0.0
    total = 0.0
    session_method = getattr(engine, "_session_realized_value", None)
    used_session_method = False
    for state in state_map.values():
        if isinstance(state, dict) is False:
            continue
        if session_date:
            if str(state.get("session_date", "") or "") != str(session_date):
                continue
            if callable(session_method):
                try:
                    total += float(session_method(state, session_date) or 0)
                    used_session_method = True
                    continue
                except Exception:
                    pass
        if used_session_method:
            continue
        total += float(state.get("realized_profit", 0) or 0)
    return round(total, 2)


def _get_struct():
    shared = getattr(_sys, "_page_dashboard_struct_obj", None)
    if shared is not None:
        _STRUCT_CACHE["obj"] = shared
        _STRUCT_CACHE["error"] = None
        _STRUCT_CACHE["error_at"] = 0.0
        return shared
    cached = _STRUCT_CACHE.get("obj")
    if cached is not None:
        return cached
    err = _STRUCT_CACHE.get("error")
    if err is not None and (time.monotonic() - float(_STRUCT_CACHE.get("error_at", 0.0) or 0.0)) < _STRUCT_ERROR_TTL_SEC:
        raise err
    try:
        obj = wiz.model("struct")
        _STRUCT_CACHE["obj"] = obj
        setattr(_sys, "_page_dashboard_struct_obj", obj)
        _STRUCT_CACHE["error"] = None
        _STRUCT_CACHE["error_at"] = 0.0
        return obj
    except Exception as e:
        _STRUCT_CACHE["obj"] = None
        _STRUCT_CACHE["error"] = e
        _STRUCT_CACHE["error_at"] = time.monotonic()
        raise


def _require_trading():
    struct = _get_struct()
    trading = getattr(struct, "trading", None)
    if trading is None:
        raise Exception("trading struct not found")
    return trading


def _kis_connection_status(trading, ttl_sec=None):
    now = time.monotonic()
    scope = _dashboard_cache_scope()
    status_cache = _KIS_STATUS_CACHE.setdefault(scope, {"checked_at": 0.0, "result": None, "last_success_at": 0.0})
    try:
        provider = str(trading.get_config("broker_provider", "kis") or "kis").lower()
    except Exception:
        provider = "kis"
    cached = status_cache.get("result")
    checked_at = float(status_cache.get("checked_at", 0.0) or 0.0)
    if isinstance(cached, dict) and str(cached.get("broker_provider", "kis") or "kis").lower() == provider:
        cached_success = cached.get("success") is True
        effective_ttl = _KIS_STATUS_SUCCESS_TTL_SEC if cached_success else _KIS_STATUS_FAILURE_TTL_SEC
        if ttl_sec is not None:
            effective_ttl = float(ttl_sec)
        if (now - checked_at) < effective_ttl:
            return dict(cached)
    try:
        broker = getattr(trading, "broker_api", None) or trading.kis_api
        result = broker.test_connection() or {"success": False, "message": "empty response"}
    except Exception as e:
        result = {"success": False, "message": str(e)}
    result["broker_provider"] = provider
    last_success_at = float(status_cache.get("last_success_at", 0.0) or 0.0)
    recent_success = last_success_at > 0 and (now - last_success_at) < _KIS_STICKY_SUCCESS_GRACE_SEC
    if result.get("success") is not True and recent_success:
        result = {
            **dict(result),
            "success": True,
            "sticky": True,
            "raw_success": False,
            "message": str(result.get("message", "") or "최근 성공한 KIS 연결 상태를 유지합니다."),
        }
    status_cache["checked_at"] = now
    status_cache["result"] = dict(result)
    if result.get("success"):
        status_cache["last_success_at"] = now
    return dict(result)


def _safe_engine_status(trading):
    try:
        status = trading.engine.get_status() or {
            "active_cycles": 0,
            "holding_cycles": 0,
            "paused_cycles": 0,
            "pending_extension_cycles": 0,
            "completed_cycles": 0,
            "auto_trade": False,
        }
        loc_enabled = str(trading.get_config("loc_auto_schedule_enabled", "true") or "true").lower() == "true"
        status["loc_auto_schedule_enabled"] = loc_enabled
        status["auto_trade"] = bool(status.get("auto_trade", False)) and loc_enabled
        return status
    except Exception as e:
        _log("warning", f"engine.get_status failed: {e}")
        return {
            "active_cycles": 0,
            "holding_cycles": 0,
            "paused_cycles": 0,
            "pending_extension_cycles": 0,
            "completed_cycles": 0,
            "auto_trade": False,
        }


def _safe_active_cycles(trading):
    try:
        return trading.engine.get_active_cycles() or []
    except Exception as e:
        _log("warning", f"get_active_cycles failed: {e}")
        return []


def _attach_loc_buy_status(trading, cycles, with_summary=False):
    cycles = [dict(cycle or {}) for cycle in (cycles or [])]
    summary = {
        "total": len(cycles),
        "active": 0,
        "holding": 0,
        "paused": 0,
        "pending_extension": 0,
        "loc_required": 0,
        "loc_scheduled": 0,
        "loc_waiting": 0,
        "loc_attention": 0,
        "loc_not_required": 0,
        "loc_auto_enabled": False,
        "loc_buy_last_date": "",
    }
    try:
        summary["loc_auto_enabled"] = _truthy(trading.get_config("loc_auto_schedule_enabled", "true"))
        summary["loc_buy_last_date"] = str(trading.get_config("loc_buy_auto_schedule_last_date", "") or "")
    except Exception:
        pass
    now_kst = _TIME.now()
    schedule_key = (now_kst - datetime.timedelta(days=1)).strftime("%Y-%m-%d") if now_kst.hour < 7 else now_kst.strftime("%Y-%m-%d")
    loc_window_state = _loc_reservation_window_state(now_kst)
    before_auto_schedule = loc_window_state == "before"
    loc_schedule_window = _loc_reservation_window_label(now_kst)
    engine = getattr(trading, "engine", None)
    firegate_required = False
    firegate_states = {}
    firegate_error = ""
    try:
        if engine and hasattr(engine, "_firegate_reservation_authority_required"):
            firegate_required = bool(engine._firegate_reservation_authority_required())
        if firegate_required and engine and hasattr(engine, "_load_firegate_authoritative_states"):
            fg_context = engine._load_firegate_authoritative_states() or {}
            firegate_states = fg_context.get("states", {}) or {}
            firegate_error = fg_context.get("error", "") or ""
    except Exception as e:
        firegate_error = str(e)

    reservation_map = {}
    reservation_line_map = {}
    try:
        broker = getattr(trading, "broker_api", None) or trading.kis_api
        start_date = engine._reservation_query_start_date() if engine and hasattr(engine, "_reservation_query_start_date") else _TIME.now().strftime("%Y%m%d")
        reservations = broker.get_overseas_reservation_orders(start_date=start_date) or []
        for order in reservations:
            if str((order or {}).get("side", "") or "").upper() != "BUY":
                continue
            if engine and hasattr(engine, "_reservation_order_is_active"):
                if engine._reservation_order_is_active(order) is False:
                    continue
            else:
                status_text = str(order.get("status_name", order.get("status", "")) or "")
                cancel_yn = str(order.get("cancel_yn", order.get("cancel_yn_name", "")) or "").upper()
                if cancel_yn in ("Y", "CANCEL", "CANCELLED") or "취소" in status_text:
                    continue
            if engine and hasattr(engine, "_reservation_order_symbol_key"):
                key = engine._reservation_order_symbol_key(order.get("symbol", ""), order.get("exchange", "NASD"))
                line_key = engine._reservation_order_line_key(order.get("symbol", ""), order.get("exchange", "NASD"), order.get("price", 0))
            else:
                key = f"{_normalize_symbol(order.get('symbol', ''))}:{str(order.get('exchange', 'NASD') or 'NASD').upper()}"
                line_key = f"{key}:{float(order.get('price', 0) or 0):.4f}"
            reservation_map.setdefault(key, []).append(order)
            reservation_line_map.setdefault(line_key, []).append(order)
    except Exception as e:
        _log("warning", f"LOC reservation status load failed: {e}")

    try:
        watchlist_db = trading.db("etf_watchlist")
    except Exception:
        watchlist_db = None

    for cycle in cycles:
        status = str(cycle.get("status", "") or "").upper()
        if status == "ACTIVE":
            summary["active"] += 1
        elif status == "HOLDING":
            summary["holding"] += 1
        elif status == "PAUSED":
            summary["paused"] += 1
        elif status == "PENDING_EXTENSION":
            summary["pending_extension"] += 1

        symbol = _normalize_symbol(cycle.get("symbol", ""))
        planning_cycle = cycle
        firegate_authority_error = ""
        if firegate_required and engine and hasattr(engine, "_cycle_with_firegate_authority"):
            try:
                planning_cycle, firegate_authority_error = engine._cycle_with_firegate_authority(
                    cycle,
                    firegate_states,
                    required=True,
                    load_error=firegate_error,
                )
            except Exception as e:
                planning_cycle = None
                firegate_authority_error = str(e)
        current_round = int(float(cycle.get("current_round", 0) or 0))
        division_count = int(float(cycle.get("division_count", 0) or 0))
        if division_count <= 0:
            division_count = current_round + 1
        cycle["loc_buy_status"] = "not_required"
        cycle["loc_buy_status_label"] = "대상 아님"
        cycle["loc_buy_message"] = ""
        cycle["loc_buy_order_no"] = ""
        cycle["loc_buy_qty"] = 0
        cycle["loc_buy_price"] = 0
        cycle["loc_buy_round"] = current_round + 1

        if summary["loc_auto_enabled"] is False:
            cycle["loc_buy_status"] = "disabled"
            cycle["loc_buy_status_label"] = "자동예약 OFF"
            cycle["loc_buy_message"] = "LOC 자동 예약 설정이 꺼져 있습니다."
            summary["loc_not_required"] += 1
            continue
        if status != "ACTIVE" or current_round >= division_count:
            summary["loc_not_required"] += 1
            continue
        if planning_cycle is None:
            cycle["loc_buy_status"] = "attention"
            cycle["loc_buy_status_label"] = "확인 필요"
            cycle["loc_buy_message"] = firegate_authority_error or "FireGate 원본 상태를 읽지 못해 예약 상태를 계산하지 못했습니다."
            summary["loc_attention"] += 1
            continue

        exchange = "NASD"
        try:
            item = watchlist_db.get(symbol=symbol) if watchlist_db else None
            exchange = (item or {}).get("exchange", "NASD") or "NASD"
        except Exception:
            exchange = "NASD"
        engine = getattr(trading, "engine", None)
        if engine and hasattr(engine, "_resolve_order_exchange"):
            try:
                exchange = engine._resolve_order_exchange(symbol, exchange)
            except Exception:
                pass
        if engine and hasattr(engine, "_reservation_order_symbol_key"):
            key = engine._reservation_order_symbol_key(symbol, exchange)
        else:
            key = f"{symbol}:{str(exchange or 'NASD').upper()}"
        reservations = reservation_map.get(key, [])
        expected_orders = []
        expected_error = ""
        try:
            broker = getattr(trading, "broker_api", None) or trading.kis_api
            price_exchange = engine._price_exchange(exchange) if engine and hasattr(engine, "_price_exchange") else exchange
            price_data = broker.get_current_price(symbol, exchange=price_exchange) or {}
            prev_close = _safe_float(price_data.get("prev_close", 0), 0)
            if prev_close > 0 and engine and hasattr(engine, "calculate_buy_decision"):
                decision = engine.calculate_buy_decision(planning_cycle, prev_close) or {}
                if decision.get("should_buy") and str(decision.get("order_type", "") or "").upper() == "LOC":
                    raw_orders = decision.get("buy_orders") or [{
                        "label": "LOC",
                        "loc_price": decision.get("loc_price", 0),
                        "order_qty": decision.get("order_qty", 0),
                    }]
                    for order_plan in raw_orders:
                        order_qty = int(float(order_plan.get("order_qty", 0) or 0))
                        loc_price = _safe_float(order_plan.get("loc_price", 0), 0)
                        if order_qty <= 0 or loc_price <= 0:
                            continue
                        if engine and hasattr(engine, "_reservation_order_line_key"):
                            line_key = engine._reservation_order_line_key(symbol, exchange, loc_price)
                        else:
                            line_key = f"{key}:{loc_price:.4f}"
                        expected_orders.append({
                            "label": str(order_plan.get("label", "LOC") or "LOC"),
                            "qty": order_qty,
                            "price": loc_price,
                            "line_key": line_key,
                        })
        except Exception as e:
            expected_error = str(e)

        if not expected_orders:
            if expected_error:
                cycle["loc_buy_status"] = "attention"
                cycle["loc_buy_status_label"] = "확인 필요"
                cycle["loc_buy_message"] = f"LOC 예약 필요 라인을 계산하지 못했습니다: {expected_error}"
                summary["loc_attention"] += 1
            else:
                summary["loc_not_required"] += 1
            continue

        summary["loc_required"] += 1
        scheduled_lines = []
        missing_lines = []
        for expected in expected_orders:
            line_orders = reservation_line_map.get(expected["line_key"], [])
            reserved_qty = 0
            for order in line_orders:
                if engine and hasattr(engine, "_reservation_order_remaining_qty"):
                    reserved_qty += engine._reservation_order_remaining_qty(order)
                else:
                    reserved_qty += max(0, int(float(order.get("qty", 0) or 0)) - int(float(order.get("filled_qty", 0) or 0)))
            if reserved_qty >= expected["qty"]:
                scheduled_lines.append({**expected, "reserved_qty": reserved_qty, "orders": line_orders})
            else:
                missing_lines.append({**expected, "reserved_qty": reserved_qty})

        cycle["loc_buy_expected_count"] = len(expected_orders)
        cycle["loc_buy_scheduled_count"] = len(scheduled_lines)
        cycle["loc_buy_missing_count"] = len(missing_lines)
        if len(scheduled_lines) == len(expected_orders):
            order = (scheduled_lines[0].get("orders") or [{}])[0]
            cycle["loc_buy_status"] = "scheduled"
            cycle["loc_buy_status_label"] = "예약 접수"
            cycle["loc_buy_order_no"] = order.get("order_no", order.get("reserve_order_no", "")) or ""
            cycle["loc_buy_qty"] = int(float(order.get("qty", 0) or 0))
            cycle["loc_buy_price"] = float(order.get("price", 0) or 0)
            summary["loc_scheduled"] += 1
        elif scheduled_lines:
            cycle["loc_buy_status"] = "attention"
            cycle["loc_buy_status_label"] = "일부 누락"
            cycle["loc_buy_message"] = f"필요 예약 {len(expected_orders)}건 중 {len(scheduled_lines)}건만 확인됐습니다. 누락된 라인은 자동 재검증에서 다시 접수합니다."
            if reservations:
                order = reservations[0]
                cycle["loc_buy_order_no"] = order.get("order_no", order.get("reserve_order_no", "")) or ""
                cycle["loc_buy_qty"] = int(float(order.get("qty", 0) or 0))
                cycle["loc_buy_price"] = float(order.get("price", 0) or 0)
            summary["loc_attention"] += 1
        elif before_auto_schedule and summary["loc_buy_last_date"] != schedule_key:
            cycle["loc_buy_status"] = "waiting"
            cycle["loc_buy_status_label"] = "예약 대기"
            cycle["loc_buy_message"] = f"{loc_schedule_window} 전입니다. 시간이 되면 서버가 자동 접수합니다."
        else:
            cycle["loc_buy_status"] = "attention"
            cycle["loc_buy_status_label"] = "예약 없음"
            cycle["loc_buy_message"] = "오늘 필요한 LOC 예약매수가 확인되지 않았습니다. 서버 자동 재검증에서 다시 접수합니다."
            summary["loc_attention"] += 1

    summary["loc_waiting"] = max(0, summary["loc_required"] - summary["loc_scheduled"] - summary["loc_attention"])
    if with_summary:
        return cycles, summary
    return cycles


def _safe_recent_logs(trading, dump=20):
    try:
        log_db = trading.db("trade_log")
        return log_db.rows(orderby="created", order="DESC", page=1, dump=dump) or []
    except Exception as e:
        _log("warning", f"recent trade logs load failed: {e}")
        return []


def _safe_watchlist_info(trading):
    try:
        watchlist_db = trading.db("etf_watchlist")
        return watchlist_db.rows(is_active=True, orderby="created", order="ASC", page=1, dump=200) or []
    except Exception as e:
        _log("warning", f"watchlist load failed: {e}")
        return []


def _empty_overview_payload(message=""):
    return {
        "setup_required": True,
        "privacy_locked": True,
        "setup_message": str(message or ""),
        "server_time_kst": _TIME.now().strftime("%Y-%m-%d %H:%M:%S"),
        "buying_power": 0,
        "cash_asset_krw": 0,
        "cash_asset_source": "fallback",
        "buying_power_orderable": 0,
        "usd_buying_power": 0,
        "usd_sync_ok": False,
        "usd_sync_message": str(message or ""),
        "usd_sync_source": "",
        "krw_balance": 0,
        "krw_orderable_cash": 0,
        "krw_orderable_source": "",
        "krw_orderable_probe": "",
        "krw_orderable_gap": 0,
        "krw_buying_power_usd": 0,
        "balance_sync_ok": False,
        "balance_sync_message": str(message or ""),
        "balance_sync_source": "",
        "portfolio_value": 0,
        "total_asset": 0,
        "total_asset_source": "fallback",
        "portfolio_value_domestic_krw": 0,
        "portfolio_value_overseas_krw": 0,
        "portfolio_value_overseas_source": "fallback",
        "balance_diagnostics": [],
        "exchange_rate": 0,
        "currency": "KRW",
        "engine_status": {
            "active_cycles": 0,
            "holding_cycles": 0,
            "paused_cycles": 0,
            "pending_extension_cycles": 0,
            "completed_cycles": 0,
            "auto_trade": False,
        },
        "daytrade_runtime": {
            "started": False,
            "us_enabled": False,
            "last_run_at": "",
            "us_auto_cycle_executed": False,
            "us_auto_cycle_message": "",
            "us_exit_watch_executed": False,
            "us_exit_watch_message": "",
        },
        "api_connected": False,
        "is_mock": False,
        "holdings_source": "fallback",
        "cycles": [],
        "holdings": [],
        "recent_logs": [],
        "watchlist_info": [],
        "cached": False,
    }


def _empty_profit_summary_payload(period="1D", message=""):
    today = _TIME.now().strftime("%Y-%m-%d")
    return dict(
        period=period,
        currency="KRW",
        api_connected=False,
        setup_required=True,
        privacy_locked=True,
        message=str(message or ""),
        server_time_kst=_TIME.now().strftime("%Y-%m-%d %H:%M:%S"),
        session_anchor_9am=_session_anchor_9am().strftime("%Y-%m-%d %H:%M:%S"),
        exchange_rate=0,
        realized_profit=0,
        unrealized_profit=0,
        total_profit=0,
        total_invested=0,
        total_return=0,
        completed_cycles=0,
        avg_cycle_return=0,
        best_cycle_return=0,
        worst_cycle_return=0,
        cycle_realized_profit=0,
        cycle_unrealized_profit=0,
        daytrade_realized_profit=0,
        daytrade_unrealized_profit=0,
        daytrade_total_profit=0,
        ib_realized_profit=0,
        ib_unrealized_profit=0,
        ib_realized_cycle_count=0,
        realized_return=0,
        unrealized_return=0,
        base_asset=0,
        base_asset_source="privacy_locked",
        first_snapshot_date="",
        elapsed_days=0,
        live_asset_source="privacy_locked",
        live_total_asset=0,
        snapshots=[{
            "date": today,
            "total_asset": 0,
            "profit": 0,
            "profit_rate": 0,
            "daily_return_rate": 0,
        }],
        daily_return_avg=0,
        daily_return_best=0,
        daily_return_worst=0,
        latest_daily_return_rate=0,
        asset_change_prev_day=0,
    )


def _to_kst_string(value):
    if value in [None, ""]:
        return ""
    if isinstance(value, datetime.datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if text == "":
            return ""
        dt = None
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
            try:
                dt = datetime.datetime.strptime(text[:len(fmt.replace('%Y','0000').replace('%m','00').replace('%d','00').replace('%H','00').replace('%M','00').replace('%S','00'))], fmt)
                break
            except Exception:
                pass
        if dt is None:
            return text[:19]
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%d %H:%M")
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")


def _sanitize_user_log_message(message):
    text = str(message or "")
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _session_anchor_9am(now=None):
    now = now or _TIME.aware_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    if now.hour < 9:
        now = now - datetime.timedelta(days=1)
    return now.replace(hour=9, minute=0, second=0, microsecond=0)


def _generate_mock_cycle_detail(cycle_id):
    """Mock 사이클 상세 데이터 생성"""
    now = _TIME.now()
    symbols = {"mock-cycle-0": "TQQQ", "mock-cycle-1": "SOXL", "mock-cycle-2": "FNGU", "mock-cycle-3": "UPRO"}
    symbol = symbols.get(cycle_id, "TQQQ")
    cycle_num = int(cycle_id.split("-")[-1]) if "-" in cycle_id else 0

    base_price = {"TQQQ": 52.0, "SOXL": 24.0, "FNGU": 170.0, "UPRO": 70.0}.get(symbol, 50.0)
    start_date = now - datetime.timedelta(days=random.randint(10, 50))
    total_trades = random.randint(8, 25)

    # Mock 거래 내역 생성
    trades = []
    running_qty = 0
    running_spent = 0.0
    avg_prices = []
    buy_round = 0  # SKIP은 회차를 소진하지 않음 — BUY만 카운트

    for r in range(1, total_trades + 1):
        trade_date = start_date + datetime.timedelta(days=r)
        # 가격 변동 시뮬레이션
        price_change = random.uniform(-0.08, 0.05)
        price = round(base_price * (1 + price_change * r / total_trades), 2)

        action = "BUY"
        if random.random() < 0.15:
            action = "SKIP"

        if action == "BUY":
            buy_round += 1
            qty = max(1, int(round(200.0 / price)))
            amount = round(qty * price, 2)
            commission = round(amount * 0.0025, 2)
            running_qty += qty
            running_spent += amount
            avg = round(running_spent / running_qty, 4) if running_qty > 0 else 0

            trades.append({
                "id": f"mock-trade-{r}",
                "round": buy_round,
                "trade_date": trade_date.strftime("%Y-%m-%d"),
                "action": "BUY",
                "order_price": price,
                "filled_price": price,
                "filled_qty": qty,
                "filled_amount": amount,
                "commission": commission,
                "avg_buy_price": avg,
                "total_qty_after": running_qty,
                "total_spent_after": round(running_spent, 2),
                "profit_rate": round(((price * running_qty - running_spent) / running_spent * 100) if running_spent > 0 else 0, 2),
            })
            avg_prices.append({"round": buy_round, "avg_price": avg, "price": price, "profit_rate": trades[-1]["profit_rate"]})
        else:
            # SKIP은 회차를 소진하지 않음 — round는 현재 buy_round 유지
            trades.append({
                "id": f"mock-trade-{r}",
                "round": buy_round,
                "trade_date": trade_date.strftime("%Y-%m-%d"),
                "action": "SKIP",
                "order_price": price,
                "filled_price": 0,
                "filled_qty": 0,
                "filled_amount": 0,
                "commission": 0,
                "avg_buy_price": round(running_spent / running_qty, 4) if running_qty > 0 else 0,
                "total_qty_after": running_qty,
                "total_spent_after": round(running_spent, 2),
                "profit_rate": round(((price * running_qty - running_spent) / running_spent * 100) if running_spent > 0 else 0, 2),
            })
            avg_prices.append({"round": buy_round, "avg_price": trades[-1]["avg_buy_price"], "price": price, "profit_rate": trades[-1]["profit_rate"]})

    # Mock 이벤트 로그
    logs = []
    log_events = [
        ("CYCLE_START", f"Cycle #{cycle_num + 1} started for {symbol}"),
        ("BUY_ORDER", f"LOC Buy order placed @ ${base_price:.2f}"),
        ("BUY_FILLED", f"Buy order filled: {random.randint(3,10)} shares @ ${base_price:.2f}"),
        ("PRICE_CHECK", f"Current price: ${base_price * 1.02:.2f}, LOC limit: ${base_price * 0.97:.2f}"),
        ("SKIP", "Price above LOC limit, skipped"),
        ("BUY_ORDER", f"LOC Buy order placed @ ${base_price * 0.98:.2f}"),
        ("BUY_FILLED", f"Buy order filled: {random.randint(3,10)} shares @ ${base_price * 0.97:.2f}"),
    ]
    for i, (etype, msg) in enumerate(log_events):
        log_time = start_date + datetime.timedelta(days=i + 1, hours=random.randint(9, 15))
        logs.append({
            "id": f"mock-log-{i}",
            "event_type": etype,
            "action": "BUY" if "BUY" in etype else ("SKIP" if "SKIP" in etype else ""),
            "message": msg,
            "created": log_time.strftime("%Y-%m-%d %H:%M"),
        })

    current_price = round(base_price * (1 + random.uniform(-0.05, 0.1)), 2)
    eval_amount = round(running_qty * current_price, 2)
    profit_rate = round(((eval_amount - running_spent) / running_spent * 100) if running_spent > 0 else 0, 2)
    days_elapsed = (now - start_date).days

    return {
        "cycle": {
            "id": cycle_id,
            "symbol": symbol,
            "cycle_number": cycle_num + 1,
            "status": "ACTIVE",
            "started_at": start_date.strftime("%Y-%m-%d"),
            "days_elapsed": days_elapsed,
            "current_round": buy_round,
            "division_count": 40,
            "avg_price": round(running_spent / running_qty, 4) if running_qty > 0 else 0,
            "current_price": current_price,
            "total_qty": running_qty,
            "total_spent": round(running_spent, 2),
            "total_investment": round(running_spent + 3000, 2),
            "remaining_investment": 3000.0,
            "eval_amount": eval_amount,
            "profit_rate": profit_rate,
            "target_profit": 10.0,
            "total_commission": round(sum(t["commission"] for t in trades), 2),
        },
        "trades": trades,
        "chart_data": avg_prices,
        "logs": logs,
    }


def _build_overview_payload(force_refresh=False):
    trading = _require_trading()
    setup_state = _broker_setup_state(trading, require_connection=False)
    if setup_state.get("allowed") is not True:
        payload = _empty_overview_payload(setup_state.get("message", ""))
        payload["broker_provider"] = setup_state.get("broker_provider", "")
        payload["broker_configured"] = setup_state.get("configured", False)
        payload["broker_connected"] = False
        return payload
    fire_gate_bridge, authoritative_symbols = _firegate_overview_scope(trading, force_refresh=force_refresh)

    api_connected = False
    usd_buying_power = 0
    usd_sync_ok = False
    usd_sync_message = ""
    usd_sync_source = ""
    krw_balance = 0
    krw_buying_power_usd = 0
    exchange_rate = 0
    total_asset_krw = 0
    present_portfolio_eval_krw = 0
    unsettled_buy_krw = 0
    unsettled_sell_krw = 0
    balance_sync_ok = False
    balance_sync_message = ""
    balance_sync_source = ""
    krw_orderable_cash = 0
    krw_orderable_source = ""
    krw_orderable_probe = ""
    krw_orderable_gap = 0
    holdings_data = []
    domestic_holdings_data = []
    portfolio_value = 0
    overseas_portfolio_value_source = "none"
    domestic_portfolio_value_krw = 0
    domestic_summary_total_asset_krw = 0
    domestic_summary_eval_krw = 0
    usd_cash_balance = 0

    try:
        kis = getattr(trading, "broker_api", None) or trading.kis_api
        test_result = _kis_connection_status(trading)
        api_connected = test_result.get("success", False)
        if api_connected is not True:
            message = "증권사 API 연결이 확인되지 않아 개인정보 보호를 위해 대시보드 자산/수익/보유내역을 표시하지 않습니다. 설정에서 연결 테스트를 완료해주세요."
            detail = str(test_result.get("message", "") or "").strip()
            if detail:
                message = f"{message} ({detail})"
            payload = _empty_overview_payload(message)
            payload["broker_provider"] = setup_state.get("broker_provider", "")
            payload["broker_configured"] = True
            payload["broker_connected"] = False
            return payload

        if api_connected:
            balance = None

            try:
                present = kis.get_present_balance()
                meta = present.get("meta", {})
                exchange_rate = float(present.get("usd_krw", 0))
                krw_balance = float(present.get("withdrawable_krw", present.get("krw_balance", 0)))
                total_asset_krw = float(present.get("total_asset_krw", 0) or 0)
                present_portfolio_eval_krw = float(present.get("portfolio_eval_krw", 0) or 0)
                unsettled_buy_krw = float(present.get("unsettled_buy_krw", 0) or 0)
                unsettled_sell_krw = float(present.get("unsettled_sell_krw", 0) or 0)
                if meta.get("withdrawable_present") or meta.get("krw_present"):
                    balance_sync_ok = True
                    balance_sync_source = meta.get("withdrawable_key") or meta.get("krw_key") or ""
                else:
                    balance_sync_message = "원화 잔액 필드를 찾지 못했습니다"
                if exchange_rate <= 0 and balance_sync_ok:
                    balance_sync_message = "환율 필드를 찾지 못해 원화 환산 금액을 계산하지 못했습니다"
                _log("info", f"KRW balance: {krw_balance}, exchange_rate: {exchange_rate}, source={balance_sync_source}")
            except Exception as e:
                _log("error", f"get_present_balance failed: {e}")
                balance_sync_ok = False
                balance_sync_message = str(e)

            if krw_balance > 0 and exchange_rate > 0:
                krw_buying_power_usd = krw_balance / exchange_rate

            try:
                balance = kis.get_balance()
            except Exception as e:
                _log("error", f"get_balance failed: {e}")
                balance = None

            try:
                domestic_balance = kis.get_domestic_balance()
                domestic_holdings_data = domestic_balance.get("holdings", []) or []
                domestic_withdrawable_krw = float(domestic_balance.get("withdrawable_krw", 0) or 0)
                if domestic_withdrawable_krw > krw_balance:
                    krw_balance = domestic_withdrawable_krw
                domestic_portfolio_value_krw = float(domestic_balance.get("portfolio_eval_krw", 0) or 0)
                domestic_summary_eval_krw = domestic_portfolio_value_krw
                domestic_summary_total_asset_krw = float(domestic_balance.get("total_asset_krw", 0) or 0)
                if domestic_portfolio_value_krw <= 0:
                    for h in domestic_holdings_data:
                        qty = int(float(h.get("qty", 0) or 0))
                        eval_amount = float(h.get("eval_amount", 0) or 0)
                        current_price = float(h.get("current_price", 0) or 0)
                        if eval_amount > 0:
                            domestic_portfolio_value_krw += eval_amount
                        elif qty > 0 and current_price > 0:
                            domestic_portfolio_value_krw += (qty * current_price)

                raw_domestic = domestic_balance.get("raw", {}) or {}
                output2 = raw_domestic.get("output2", {})
                if isinstance(output2, list):
                    output2 = output2[0] if len(output2) > 0 else {}
                if isinstance(output2, dict):
                    for key in ["scts_evlu_amt", "evlu_amt_smtl_amt"]:
                        try:
                            amt = float(str(output2.get(key, 0) or 0).replace(",", ""))
                        except Exception:
                            amt = 0
                        if amt > domestic_summary_eval_krw:
                            domestic_summary_eval_krw = amt
                    if domestic_portfolio_value_krw <= 0:
                        for key in ["scts_evlu_amt", "tot_evlu_amt", "tot_evlu_pfls_amt", "evlu_amt_smtl_amt"]:
                            try:
                                amt = float(str(output2.get(key, 0) or 0).replace(",", ""))
                            except Exception:
                                amt = 0
                            if amt > domestic_portfolio_value_krw:
                                domestic_portfolio_value_krw = amt
                    for key in ["tot_evlu_amt", "nass_amt", "bfdy_tot_asst_evlu_amt", "tot_asst_amt"]:
                        try:
                            amt = float(str(output2.get(key, 0) or 0).replace(",", ""))
                        except Exception:
                            amt = 0
                        if amt > domestic_summary_total_asset_krw:
                            domestic_summary_total_asset_krw = amt
                if domestic_summary_eval_krw > 0:
                    domestic_portfolio_value_krw = domestic_summary_eval_krw
            except Exception as e:
                _log("warning", f"get_domestic_balance failed: {e}")

            try:
                order_symbol = "005930"
                if len(domestic_holdings_data) > 0:
                    order_symbol = str((domestic_holdings_data[0] or {}).get("symbol", order_symbol) or order_symbol)
                domestic_power = kis.get_domestic_buying_power_info(symbol=order_symbol, order_type="MARKET") or {}
                if domestic_power.get("ok") is True:
                    krw_orderable_cash = float(domestic_power.get("amount", domestic_power.get("executable_amount", 0)) or 0)
                    krw_orderable_source = str(domestic_power.get("source", "") or "")
                    display_amount = float(domestic_power.get("display_amount", 0) or 0)
                    display_source = str(domestic_power.get("display_source", "") or "")
                    if display_amount > 0 and abs(display_amount - krw_orderable_cash) > 1:
                        krw_orderable_gap = round(display_amount - krw_orderable_cash, 0)
                        krw_orderable_probe = f"{display_source} {display_amount:.0f}"
                    balance_sync_ok = True
                elif domestic_power.get("message"):
                    krw_orderable_probe = str(domestic_power.get("message", "") or "")
            except Exception as e:
                _log("warning", f"get_domestic_buying_power_info failed: {e}")

            if balance:
                holdings_data = _apply_live_us_prices_to_holdings(trading, balance.get("holdings", []), refresh=force_refresh)
                try:
                    usd_cash_balance = float(balance.get("cash_balance", 0) or 0)
                except Exception:
                    usd_cash_balance = 0

                try:
                    balance_total_eval = float(balance.get("total_eval", 0) or 0)
                except Exception:
                    balance_total_eval = 0

                holdings_eval_sum, holdings_eval_count = _holding_eval_sum(holdings_data)
                if holdings_eval_sum > 0:
                    portfolio_value = holdings_eval_sum
                    overseas_portfolio_value_source = "broker_holdings_eval_sum"
                    if balance_total_eval > 0 and abs(balance_total_eval - holdings_eval_sum) > max(1.0, holdings_eval_sum * 0.2):
                        _log(
                            "warning",
                            f"overseas balance total_eval mismatch ignored: total_eval={balance_total_eval}, holdings_sum={holdings_eval_sum}, holdings={holdings_eval_count}",
                        )
                elif balance_total_eval > 0:
                    portfolio_value = balance_total_eval
                    overseas_portfolio_value_source = "broker_total_eval"

                if not balance_sync_ok and usd_cash_balance > 0:
                    balance_sync_message = "원화 잔액 API 동기화 실패: 보유자산 조회만 성공했습니다"

            try:
                usd_info = kis.get_buying_power_info()
                usd_orderable = float(usd_info.get("amount", 0) or 0)
                usd_sync_ok = usd_info.get("ok") is True
                usd_sync_message = usd_info.get("message", "")
                usd_sync_source = usd_info.get("source", "")
                usd_buying_power = usd_orderable if usd_orderable > 0 else usd_cash_balance
                if usd_cash_balance > 0 and usd_orderable > 0 and abs(usd_cash_balance - usd_orderable) > 1:
                    usd_sync_message = f"USD 현금(${usd_cash_balance:.2f}) vs 주문가능(${usd_orderable:.2f})"
            except Exception as e:
                _log("error", f"get_buying_power failed: {e}")
                usd_sync_ok = False
                usd_sync_message = str(e)
                usd_buying_power = usd_cash_balance
                if usd_sync_source == "":
                    usd_sync_source = "balance.cash_balance"
    except Exception:
        pass

    engine_status = _safe_engine_status(trading)
    daytrade_runtime = {
        "started": False,
        "us_enabled": False,
        "last_run_at": "",
        "us_auto_cycle_executed": False,
        "us_auto_cycle_message": "",
        "us_exit_watch_executed": False,
        "us_exit_watch_message": "",
    }
    try:
        worker = trading.worker_status() or {}
        last_result = worker.get("last_result", {}) or {}
        us_auto = last_result.get("us_auto_cycle", {}) or {}
        us_exit = last_result.get("us_exit_watch", {}) or {}
        daytrade_runtime = {
            "started": bool(worker.get("started", False)),
            "us_enabled": bool(worker.get("us_enabled", False)),
            "last_run_at": str(worker.get("last_run_at", "") or ""),
            "us_auto_cycle_executed": bool(us_auto.get("executed", False)),
            "us_auto_cycle_message": str(us_auto.get("message", "") or ""),
            "us_exit_watch_executed": bool(us_exit.get("executed", False)),
            "us_exit_watch_message": str(us_exit.get("message", "") or ""),
        }
    except Exception:
        pass

    external_cycle_sync = _sync_external_cycle_trades_if_due(trading, force=force_refresh)
    cycles = _safe_active_cycles(trading)
    if len(authoritative_symbols) > 0:
        cycles = _filter_rows_by_symbols(cycles, authoritative_symbols)
        engine_status = _scoped_engine_status(engine_status, cycles)
    cycles = _refresh_cycle_prices_for_display(trading, cycles, refresh=force_refresh)
    cycles, infinite_buy_summary = _attach_loc_buy_status(trading, cycles, with_summary=True)

    holdings = []
    holdings_source = "broker"
    if api_connected and len(holdings_data) > 0:
        for h in holdings_data:
            try:
                qty = int(float(h.get("qty", h.get("holding_qty", 0)) or 0))
            except Exception:
                qty = 0
            if qty <= 0:
                continue
            try:
                avg_price = float(h.get("avg_price", h.get("purchase_price", 0)) or 0)
            except Exception:
                avg_price = 0.0
            try:
                current_price = float(h.get("current_price", h.get("price", 0)) or 0)
            except Exception:
                current_price = 0.0
            try:
                eval_amount = float(h.get("eval_amount", h.get("eval_value", qty * current_price)) or 0)
            except Exception:
                eval_amount = qty * current_price
            try:
                profit_rate = float(h.get("profit_rate", 0) or 0)
            except Exception:
                profit_rate = 0.0
            holdings.append({
                "symbol": h.get("symbol", ""),
                "qty": qty,
                "avg_price": round(avg_price, 4),
                "current_price": round(current_price, 4),
                "eval_amount": round(eval_amount, 2),
                "profit_rate": round(profit_rate, 2),
            })
    else:
        holdings_source = "cycle_fallback"
        for c in cycles:
            if int(c.get("total_qty", 0)) > 0:
                total_spent = float(c.get("total_spent", 0))
                total_qty = int(c.get("total_qty", 0))
                current_price = float(c.get("current_price", 0))
                eval_amount = total_qty * current_price
                profit_rate = ((eval_amount - total_spent) / total_spent * 100) if total_spent > 0 else 0
                holdings.append({
                    "symbol": c["symbol"],
                    "qty": total_qty,
                    "avg_price": float(c.get("avg_price", 0)),
                    "current_price": current_price,
                    "eval_amount": round(eval_amount, 2),
                    "profit_rate": round(profit_rate, 2),
                })

    fx = exchange_rate if exchange_rate > 0 else 0
    if fx <= 0:
        try:
            broker = getattr(trading, "broker_api", None) or trading.kis_api
            rate_data = broker._get_usd_krw_rate_fallback()
            fx = float(rate_data.get("rate", 0) or 0)
            if fx > 0:
                exchange_rate = fx
                _log("info", f"exchange_rate fallback: {fx}")
        except Exception as e:
            _log("warning", f"exchange_rate fallback failed: {e}")

    usd_cash_balance_krw = round(usd_cash_balance * fx, 0) if fx > 0 else 0
    buying_power_orderable_krw = round((usd_buying_power * fx) + krw_balance, 0) if fx > 0 else round(krw_balance, 0)
    overseas_portfolio_value_krw = round(portfolio_value * fx, 0) if fx > 0 else 0
    if overseas_portfolio_value_krw <= 0 and present_portfolio_eval_krw > 0:
        overseas_portfolio_value_krw = round(present_portfolio_eval_krw, 0)
        overseas_portfolio_value_source = "present_balance.portfolio_eval_krw"
    portfolio_value_krw = overseas_portfolio_value_krw + round(domestic_portfolio_value_krw, 0)

    direct_cash_asset_krw = round(krw_balance + usd_cash_balance_krw, 0)
    direct_total_asset = round(direct_cash_asset_krw + portfolio_value_krw, 0)
    orderable_plus_portfolio = round((krw_orderable_cash if krw_orderable_cash > 0 else krw_balance) + portfolio_value_krw, 0)
    present_plus_domestic = round(total_asset_krw + domestic_portfolio_value_krw, 0) if total_asset_krw > 0 and domestic_portfolio_value_krw > 0 else 0
    total_asset = direct_total_asset
    cash_asset_krw = direct_cash_asset_krw
    total_asset_source = "reconciled(direct_cash+portfolio)"
    cash_asset_source = "direct(krw+usd_cash)"
    present_total_asset_rounded = round(total_asset_krw, 0)
    if round(domestic_summary_total_asset_krw, 0) > 0:
        combined_asset = round(domestic_summary_total_asset_krw + overseas_portfolio_value_krw - unsettled_buy_krw + unsettled_sell_krw, 0)
        total_asset = combined_asset if overseas_portfolio_value_krw > 0 else round(domestic_summary_total_asset_krw, 0)
        cash_asset_krw = round(max(0.0, total_asset - portfolio_value_krw), 0)
        total_asset_source = "domestic_balance.total_asset_krw+live_us_eval-unsettled_us_buy"
        cash_asset_source = "derived(total_asset-portfolio)"
    elif present_plus_domestic > 0:
        total_asset = present_plus_domestic
        cash_asset_krw = round(max(0.0, total_asset - portfolio_value_krw), 0)
        total_asset_source = "present_balance.total_asset_krw+domestic_eval"
        cash_asset_source = "derived(total_asset-portfolio)"
    elif present_total_asset_rounded > 0 and portfolio_value_krw <= present_total_asset_rounded:
        total_asset = present_total_asset_rounded
        cash_asset_krw = round(max(0.0, total_asset - portfolio_value_krw), 0)
        total_asset_source = "present_balance.total_asset_krw"
        cash_asset_source = "derived(total_asset-portfolio)"
    elif orderable_plus_portfolio > total_asset:
        total_asset = orderable_plus_portfolio
        cash_asset_krw = round(max(0.0, total_asset - portfolio_value_krw), 0)
        total_asset_source = "domestic_orderable+portfolio_eval"
        cash_asset_source = "derived(orderable+portfolio-portfolio)"
    if total_asset <= 0:
        try:
            engine_budget = trading.daytrade_engine.shared_budget_status(requested_seed=0, use_cache_only=True, market="KS") or {}
            engine_total_asset = round(float(engine_budget.get("total_asset_krw", 0) or 0), 0)
            if engine_total_asset > 0 and portfolio_value_krw <= engine_total_asset:
                total_asset = engine_total_asset
                cash_asset_krw = round(max(0.0, total_asset - portfolio_value_krw), 0)
                total_asset_source = str(engine_budget.get("total_asset_source", total_asset_source) or total_asset_source)
                cash_asset_source = "derived(daytrade_engine.total_asset_krw-portfolio)"
        except Exception:
            pass
    recent_logs = _safe_recent_logs(trading)
    for log in recent_logs:
        if log.get("created"):
            log["created"] = _to_kst_string(log["created"])
        log["message"] = _sanitize_user_log_message(log.get("message", ""))

    watchlist_items = _safe_watchlist_info(trading)
    if len(authoritative_symbols) > 0:
        watchlist_items = _filter_rows_by_symbols(watchlist_items, authoritative_symbols)
    watchlist_info = []
    for w in watchlist_items:
        watchlist_info.append({
            "symbol": w.get("symbol", ""),
            "name": w.get("name", ""),
            "cycle_mode": w.get("cycle_mode", "auto"),
        })

    daytrade_positions = []
    daytrade_position_summary = {"count": 0, "eval_amount_krw": 0.0, "cost_amount_krw": 0.0, "pnl_krw": 0.0}
    try:
        positions = trading.daytrade_engine.active_positions(sync_broker=True) or []
    except Exception:
        try:
            positions = trading.daytrade_engine.active_positions_from_state() or []
        except Exception:
            positions = []
    fx_rate = exchange_rate if exchange_rate > 0 else fx
    for row in positions:
        market = str(row.get("market", "KS") or "KS").upper()
        symbol = _normalize_symbol(row.get("symbol", ""))
        if market == "US" and symbol in ("SOXL", "TQQQ"):
            continue
        qty = int(float(row.get("position_qty", row.get("qty", 0)) or 0))
        if qty <= 0:
            continue
        avg_price = float(row.get("avg_price", 0) or 0)
        current_price = float(row.get("current_price", 0) or 0)
        eval_amount = float(row.get("eval_amount", 0) or 0)
        if eval_amount <= 0:
            eval_amount = current_price * qty if current_price > 0 else avg_price * qty
        pnl_amount = float(row.get("pnl", 0) or 0)
        cost_amount = float(row.get("cost_amount", 0) or 0)
        if cost_amount <= 0:
            cost_amount = avg_price * qty
        if cost_amount <= 0 and eval_amount > 0:
            cost_amount = max(0.0, eval_amount - pnl_amount)
        multiplier = fx_rate if market == "US" and fx_rate > 0 else 1.0
        eval_amount_krw = round(eval_amount * multiplier, 2)
        cost_amount_krw = round(cost_amount * multiplier, 2)
        pnl_krw = round(pnl_amount * multiplier, 2)
        daytrade_positions.append({
            "symbol": symbol or row.get("symbol", ""),
            "market": market,
            "name": row.get("name", ""),
            "strategy_id": row.get("strategy_id", ""),
            "strategy_name": row.get("strategy_name", ""),
            "qty": qty,
            "avg_price": round(avg_price, 4),
            "current_price": round(current_price, 4),
            "eval_amount_krw": eval_amount_krw,
            "cost_amount_krw": cost_amount_krw,
            "pnl_krw": pnl_krw,
            "pnl_pct": round(float(row.get("pnl_pct", 0) or 0), 2),
            "opened_at": row.get("opened_at", ""),
            "updated_at": row.get("updated_at", ""),
            "source": row.get("source", ""),
        })
        daytrade_position_summary["count"] += 1
        daytrade_position_summary["eval_amount_krw"] += eval_amount_krw
        daytrade_position_summary["cost_amount_krw"] += cost_amount_krw
        daytrade_position_summary["pnl_krw"] += pnl_krw
    daytrade_positions.sort(key=lambda item: (0 if item.get("market") == "KS" else 1, item.get("symbol", "")))

    return {
        "setup_required": False,
        "privacy_locked": False,
        "server_time_kst": _TIME.now().strftime("%Y-%m-%d %H:%M:%S"),
        "buying_power": round(krw_orderable_cash if krw_orderable_cash > 0 else cash_asset_krw, 0),
        "cash_asset_krw": round(cash_asset_krw, 0),
        "cash_asset_source": cash_asset_source,
        "buying_power_orderable": round(krw_orderable_cash if krw_orderable_cash > 0 else buying_power_orderable_krw, 0),
        "usd_buying_power": round(usd_buying_power, 2),
        "usd_sync_ok": usd_sync_ok,
        "usd_sync_message": usd_sync_message,
        "usd_sync_source": usd_sync_source,
        "krw_balance": round(krw_balance, 0),
        "krw_orderable_cash": round(krw_orderable_cash if krw_orderable_cash > 0 else krw_balance, 0),
        "krw_orderable_source": krw_orderable_source,
        "krw_orderable_probe": krw_orderable_probe,
        "krw_orderable_gap": round(krw_orderable_gap, 0),
        "krw_buying_power_usd": round(krw_buying_power_usd, 2),
        "balance_sync_ok": balance_sync_ok,
        "balance_sync_message": balance_sync_message,
        "balance_sync_source": balance_sync_source,
        "portfolio_value": round(portfolio_value_krw, 0),
        "total_asset": round(total_asset, 0),
        "total_asset_source": total_asset_source,
        "portfolio_value_domestic_krw": round(domestic_portfolio_value_krw, 0),
        "portfolio_value_overseas_krw": round(overseas_portfolio_value_krw, 0),
        "portfolio_value_overseas_source": overseas_portfolio_value_source,
        "balance_diagnostics": [
            {"label": "국내 주문가능", "amount": round(krw_orderable_cash if krw_orderable_cash > 0 else krw_balance, 0), "source": krw_orderable_source or balance_sync_source, "ok": krw_orderable_cash > 0},
            {"label": "국내 평가액", "amount": round(domestic_portfolio_value_krw, 0), "source": "domestic_balance.portfolio_eval_krw", "ok": domestic_portfolio_value_krw > 0},
            {"label": "미장 평가액", "amount": round(overseas_portfolio_value_krw, 0), "source": overseas_portfolio_value_source, "ok": overseas_portfolio_value_krw > 0},
            {"label": "미장 미결제매수", "amount": round(unsettled_buy_krw, 0), "source": "present_balance.ustl_buy_amt_smtl", "ok": True},
            {"label": "총자산", "amount": round(total_asset, 0), "source": total_asset_source, "ok": total_asset > 0},
        ],
        "exchange_rate": round(exchange_rate, 2),
        "currency": "KRW",
        "engine_status": engine_status,
        "daytrade_runtime": daytrade_runtime,
        "api_connected": api_connected,
        "is_mock": False,
        "holdings_source": holdings_source,
        "cycles": cycles,
        "infinite_buy_cycles": cycles,
        "infinite_buy_summary": infinite_buy_summary,
        "holdings": holdings,
        "daytrade_positions": daytrade_positions,
        "daytrade_position_summary": {
            "count": int(daytrade_position_summary.get("count", 0) or 0),
            "eval_amount_krw": round(float(daytrade_position_summary.get("eval_amount_krw", 0) or 0), 2),
            "pnl_krw": round(float(daytrade_position_summary.get("pnl_krw", 0) or 0), 2),
        },
        "recent_logs": recent_logs,
        "watchlist_info": watchlist_info,
        "fire_gate_bridge": fire_gate_bridge,
        "external_cycle_sync": external_cycle_sync,
        "cached": False,
    }


def overview():
    """대시보드 종합 데이터"""
    force_refresh = _truthy(wiz.request.query("force_refresh", "false"))
    cache_key = _dashboard_cache_scope()
    try:
        trading_for_access = _require_trading()
        setup_state = _broker_setup_state(trading_for_access, require_connection=True)
        if setup_state.get("allowed") is not True:
            message = setup_state.get("message", "")
            detail = str(setup_state.get("connection_message", "") or "").strip()
            if detail:
                message = f"{message} ({detail})"
            payload = _empty_overview_payload(message)
            payload["broker_provider"] = setup_state.get("broker_provider", "")
            payload["broker_configured"] = setup_state.get("configured", False)
            payload["broker_connected"] = False
            _cache_set(_OVERVIEW_CACHE, cache_key, payload)
            wiz.response.status(200, **payload)
    except Exception as e:
        _dump_error("overview_access", e)
        payload = _empty_overview_payload(str(e))
        payload["degraded"] = True
        payload["degraded_message"] = str(e)
        wiz.response.status(200, **payload)
    if force_refresh is False:
        cached_payload, cache_age = _cache_get(_OVERVIEW_CACHE, cache_key, _OVERVIEW_TTL_SEC)
        if isinstance(cached_payload, dict):
            cached_payload["cached"] = True
            cached_payload["cache_age_sec"] = cache_age
            wiz.response.status(200, **cached_payload)

    def _builder():
        try:
            payload = _build_overview_payload(force_refresh=force_refresh)
            _cache_set(_OVERVIEW_CACHE, cache_key, payload)
            return payload
        except Exception as e:
            _dump_error("overview", e)
            fallback_payload, fallback_age = _cache_get(_OVERVIEW_CACHE, cache_key, _OVERVIEW_TTL_SEC * 6)
            if isinstance(fallback_payload, dict):
                fallback_payload["cached"] = True
                fallback_payload["cache_age_sec"] = fallback_age
                fallback_payload["degraded"] = True
                fallback_payload["degraded_message"] = str(e)
                return fallback_payload
            payload = _empty_overview_payload(message=str(e))
            payload["degraded"] = True
            payload["degraded_message"] = str(e)
            return payload

    payload, is_leader = _singleflight(f"dashboard:overview:{cache_key}", _builder, timeout_sec=45.0)
    if is_leader is False:
        cached_payload, cache_age = _cache_get(_OVERVIEW_CACHE, cache_key, _OVERVIEW_TTL_SEC)
        if isinstance(cached_payload, dict):
            cached_payload["cached"] = True
            cached_payload["cache_age_sec"] = cache_age
            wiz.response.status(200, **cached_payload)
        payload = _builder()
    wiz.response.status(200, **payload)

def cycle_detail():
    """사이클 상세 정보 (거래 내역 + 이벤트 로그)"""
    _require_dashboard_access(require_connection=True)
    cycle_id = wiz.request.query("cycle_id", True)
    trading = _get_struct().trading

    # Mock 데이터 확인
    if cycle_id.startswith("mock-"):
        result = _generate_mock_cycle_detail(cycle_id)
        wiz.response.status(200, **result)

    # 실제 데이터 조회
    cycle_db = trading.db("trading_cycle")
    trade_db = trading.db("cycle_trade")
    log_db = trading.db("trade_log")

    try:
        cycle = cycle_db.get(id=cycle_id)
    except Exception as e:
        wiz.response.status(404, message="Cycle not found")

    # 기본 정보 정리
    started_at = cycle.get("started_at", "")
    if started_at:
        started_at = str(started_at)[:10]
    days_elapsed = 0
    if started_at:
        try:
            start_dt = datetime.datetime.strptime(started_at, "%Y-%m-%d")
            days_elapsed = (_TIME.now() - start_dt).days
        except Exception:
            pass

    total_qty = int(cycle.get("total_qty", 0))
    current_price = float(cycle.get("current_price", 0))
    total_spent = float(cycle.get("total_spent", 0))
    eval_amount = round(total_qty * current_price, 2) if total_qty > 0 else 0

    cycle_info = {
        "id": cycle["id"],
        "symbol": cycle.get("symbol", ""),
        "cycle_number": cycle.get("cycle_number", 1),
        "status": cycle.get("status", ""),
        "started_at": started_at,
        "days_elapsed": days_elapsed,
        "current_round": cycle.get("current_round", 0),
        "division_count": cycle.get("division_count", 40),
        "avg_price": float(cycle.get("avg_price", 0)),
        "current_price": current_price,
        "total_qty": total_qty,
        "total_spent": total_spent,
        "total_investment": float(cycle.get("total_investment", 0)),
        "remaining_investment": float(cycle.get("remaining_investment", 0)),
        "eval_amount": eval_amount,
        "profit_rate": float(cycle.get("profit_rate", 0)),
        "target_profit": float(cycle.get("target_profit", 10.0)),
        "total_commission": float(cycle.get("total_commission", 0)),
    }

    # 거래 내역
    try:
        trades = trade_db.rows(cycle_id=cycle_id, orderby="round", order="ASC")
    except Exception:
        trades = []

    trade_list = []
    chart_data = []
    for t in trades:
        trade_list.append({
            "id": t.get("id", ""),
            "round": t.get("round", 0),
            "trade_date": str(t.get("trade_date", ""))[:10],
            "action": t.get("action", ""),
            "order_price": float(t.get("order_price", 0)),
            "filled_price": float(t.get("filled_price", 0)) if t.get("filled_price") else 0,
            "filled_qty": int(t.get("filled_qty", 0)),
            "filled_amount": float(t.get("filled_amount", 0)),
            "commission": float(t.get("commission", 0)),
            "avg_buy_price": float(t.get("avg_buy_price", 0)),
            "total_qty_after": int(t.get("total_qty_after", 0)),
            "total_spent_after": float(t.get("total_spent_after", 0)),
            "profit_rate": float(t.get("profit_rate", 0)),
        })
        chart_data.append({
            "round": t.get("round", 0),
            "avg_price": float(t.get("avg_buy_price", 0)),
            "price": float(t.get("filled_price", 0)) if t.get("filled_price") else float(t.get("order_price", 0)),
            "profit_rate": float(t.get("profit_rate", 0)),
        })

    # 이벤트 로그
    try:
        logs = log_db.rows(cycle_id=cycle_id, orderby="created", order="DESC")
    except Exception:
        logs = []

    log_list = []
    for l in logs:
        log_list.append({
            "id": l.get("id", ""),
            "event_type": l.get("event_type", ""),
            "action": l.get("action", ""),
            "message": _sanitize_user_log_message(l.get("message", "")),
            "created": _to_kst_string(l.get("created", "")),
        })

    wiz.response.status(200,
        cycle=cycle_info,
        trades=trade_list,
        chart_data=chart_data,
        logs=log_list,
    )


def _generate_mock_profit_summary(period):
    """Mock 수익 요약 데이터 생성"""
    now = _TIME.now()

    # 기간에 따라 날짜 범위 결정
    period_days = {"1W": 7, "1M": 30, "3M": 90, "6M": 180, "1Y": 365, "ALL": 730}
    days = period_days.get(period, 730)
    start_date = now - datetime.timedelta(days=days)

    # Mock 완료 사이클 통계
    completed_count = max(2, days // 30)
    realized_profit = round(random.uniform(180, 520) * (days / 90), 2)
    unrealized_profit = round(random.uniform(-200, 450), 2)
    total_invested = round(random.uniform(8000, 25000), 2)
    total_profit = round(realized_profit + unrealized_profit, 2)
    total_return = round((total_profit / total_invested * 100) if total_invested > 0 else 0, 2)

    # Mock 사이클별 수익률
    cycle_returns = [round(random.uniform(-8, 18), 2) for _ in range(completed_count)]
    avg_cycle_return = round(sum(cycle_returns) / len(cycle_returns), 2) if cycle_returns else 0
    best_cycle_return = max(cycle_returns) if cycle_returns else 0
    worst_cycle_return = min(cycle_returns) if cycle_returns else 0

    # Mock 일별 스냅샷 데이터 (자산 추이 차트용)
    snapshots = []
    base_asset = round(random.uniform(18000, 28000), 2)
    trend = random.uniform(-0.001, 0.003)
    # 최대 90포인트로 제한 (너무 많으면 차트가 느림)
    step = max(1, days // 90)
    for i in range(0, days, step):
        d = start_date + datetime.timedelta(days=i)
        noise = random.uniform(-0.015, 0.02)
        asset = round(base_asset * (1 + trend * i + noise), 2)
        profit = round(asset - base_asset, 2)
        snapshots.append({
            "date": d.strftime("%Y-%m-%d"),
            "total_asset": asset,
            "profit": profit,
            "profit_rate": round((profit / base_asset * 100) if base_asset > 0 else 0, 2),
        })

    return {
        "period": period,
        "realized_profit": realized_profit,
        "unrealized_profit": unrealized_profit,
        "total_profit": total_profit,
        "total_invested": total_invested,
        "total_return": total_return,
        "completed_cycles": completed_count,
        "avg_cycle_return": avg_cycle_return,
        "best_cycle_return": best_cycle_return,
        "worst_cycle_return": worst_cycle_return,
        "snapshots": snapshots,
    }


def _profit_summary_data(period, date_from="", date_to="", force_refresh=False):
    trading = _require_trading()
    setup_state = _broker_setup_state(trading, require_connection=True)
    if setup_state.get("allowed") is not True:
        message = setup_state.get("message", "")
        detail = str(setup_state.get("connection_message", "") or "").strip()
        if detail:
            message = f"{message} ({detail})"
        return _empty_profit_summary_payload(period=period, message=message)

    configured_base_asset = 0.0
    base_asset_source = "fallback:1000000"
    try:
        base_raw = trading.get_config("dashboard_base_asset_krw", "")
        if str(base_raw).strip() == "":
            base_raw = trading.get_config("daytrade_default_seed", "1000000")
            base_asset_source = "trading_config.daytrade_default_seed"
        else:
            base_asset_source = "trading_config.dashboard_base_asset_krw"
        configured_base_asset = float(base_raw or 0)
    except Exception:
        configured_base_asset = 0.0
    if configured_base_asset <= 0:
        configured_base_asset = 1000000.0
        base_asset_source = "fallback:1000000"

    # KIS API 연결 확인
    api_connected = False
    try:
        kis = getattr(trading, "broker_api", None) or trading.kis_api
        test_result = _kis_connection_status(trading)
        api_connected = test_result.get("success", False)
    except Exception:
        pass

    # --- 실제 데이터 ---
    now = _TIME.aware_now()
    session_anchor = _session_anchor_9am(now)
    today_str = now.strftime("%Y-%m-%d")
    cycle_db = trading.db("trading_cycle")
    snapshot_db = trading.db("account_snapshot")

    exchange_rate = 0.0
    live_asset_source = "local"
    live_total_asset_ref = 0.0
    live_unsettled_buy_krw = 0.0
    live_unsettled_sell_krw = 0.0
    if api_connected:
        try:
            present_balance = kis.get_present_balance()
            exchange_rate = float(present_balance.get("usd_krw", 0) or 0)
            live_unsettled_buy_krw = float(present_balance.get("unsettled_buy_krw", 0) or 0)
            live_unsettled_sell_krw = float(present_balance.get("unsettled_sell_krw", 0) or 0)
        except Exception:
            exchange_rate = 0.0

    if exchange_rate <= 0 and api_connected:
        try:
            fx_fallback = kis._get_usd_krw_rate_fallback()
            exchange_rate = float(fx_fallback.get("rate", 0) or 0)
        except Exception:
            exchange_rate = 0.0

    def usd_to_krw(value):
        amount = float(value or 0)
        if amount == 0:
            return 0.0
        if exchange_rate > 0:
            return amount * exchange_rate
        return amount

    def snapshot_to_krw(value):
        # 스냅샷 total_asset이 USD 단위로 저장된 경우 KRW로 변환
        # 100,000 미만 값은 USD로 판단 (KRW이면 최소 수십만 단위)
        amount = float(value or 0)
        if amount <= 0:
            return 0.0
        if amount < 100000 and exchange_rate > 0:
            return amount * exchange_rate
        return amount

    # 기간 필터
    period_days = {"1D": 1, "1W": 7, "1M": 30, "3M": 90, "6M": 180, "1Y": 365}
    if date_from and date_to:
        filter_from = date_from
        filter_to = date_to
    elif period == "1D":
        filter_from = today_str
        filter_to = today_str
    elif period in period_days:
        filter_from = (now - datetime.timedelta(days=period_days[period])).strftime("%Y-%m-%d")
        filter_to = today_str
    else:
        filter_from = ""
        filter_to = today_str
    ib_filter_from, ib_filter_to = _infinite_buy_realized_date_window(
        period,
        filter_from=filter_from,
        filter_to=filter_to,
        now=now,
        explicit_dates=bool(date_from or date_to),
    )

    # 실현 수익 (완료 사이클)
    try:
        if ib_filter_from:
            completed = cycle_db.rows(status="COMPLETED", orderby="completed_at", order="DESC") or []
            completed = [c for c in completed if str(c.get("completed_at", ""))[:10] >= ib_filter_from]
            if ib_filter_to:
                completed = [c for c in completed if str(c.get("completed_at", ""))[:10] <= ib_filter_to]
        else:
            completed = cycle_db.rows(status="COMPLETED", orderby="completed_at", order="DESC") or []
    except Exception:
        completed = []

    cycle_realized_profit = 0.0
    total_invested = 0.0
    cycle_returns = []
    broker_unrealized_profit = 0.0
    included_completed_cycles = 0
    try:
        cycle_trade_db = trading.db("cycle_trade")
    except Exception:
        cycle_trade_db = None
    partial_sell_realized = _cycle_partial_sell_realized_summary(
        cycle_trade_db,
        date_from=ib_filter_from,
        date_to=ib_filter_to,
    )

    for c in completed:
        if _include_completed_cycle_in_realized(c, trade_db=cycle_trade_db) is False:
            continue
        included_completed_cycles += 1
        c_eval = float(c.get("current_eval", 0) or 0)
        c_spent = float(c.get("total_spent", 0) or 0)
        c_eval_krw = usd_to_krw(c_eval)
        c_spent_krw = usd_to_krw(c_spent)
        c_profit = c_eval_krw - c_spent_krw
        cycle_realized_profit += c_profit
        total_invested += c_spent_krw
        c_rate = (c_profit / c_spent_krw * 100) if c_spent_krw > 0 else 0
        cycle_returns.append(round(c_rate, 2))

    cycle_realized_profit += usd_to_krw(partial_sell_realized.get("realized", 0))
    total_invested += usd_to_krw(partial_sell_realized.get("cost", 0))

    # 미실현 수익 (활성 사이클)
    active_cycles = _refresh_cycle_prices_for_display(trading, trading.engine.get_active_cycles(), refresh=force_refresh)
    cycle_unrealized_profit = 0.0
    for c in active_cycles:
        if _include_active_cycle_in_unrealized(c, trade_db=cycle_trade_db) is False:
            continue
        qty = int(c.get("total_qty", 0) or 0)
        price = float(c.get("current_price", 0) or 0)
        spent = float(c.get("total_spent", 0) or 0)
        spent_krw = usd_to_krw(spent)
        eval_krw = usd_to_krw(qty * price)
        total_invested += spent_krw
        cycle_unrealized_profit += (eval_krw - spent_krw)

    daytrade_realized_profit = 0.0
    daytrade_unrealized_profit = 0.0
    daytrade_trade_count = 0
    daytrade_position_count = 0
    daytrade_daily_breakdown = {}
    ib_daily_realized_breakdown = {}
    try:
        # ALL 기간(filter_from="")일 때 date_from=""이면 period_trade_summary가 오늘 하루만 계산함
        # → 전체 거래 내역이 조회되도록 안전한 초기 날짜 전달
        dt_date_from = filter_from.replace("-", "") if filter_from else "20250101"
        dt_date_to = filter_to.replace("-", "") if filter_to else ""
        try:
            daytrade_summary = trading.daytrade_engine.period_trade_summary(
                date_from=dt_date_from,
                date_to=dt_date_to,
                sync_broker=True,
                broker_lookback_days=7,
                include_valuation=api_connected and filter_to == today_str,
            ) or {}
        except Exception:
            daytrade_summary = trading.daytrade_engine.period_trade_summary(
                date_from=dt_date_from,
                date_to=dt_date_to,
                sync_broker=False,
                include_valuation=api_connected and filter_to == today_str,
            ) or {}
        daytrade_realized_profit = float(daytrade_summary.get("pnl_net", 0) or 0)
        if filter_from == today_str and filter_to == today_str:
            state_realized_profit = _daytrade_state_realized_total(trading, session_date=today_str)
            daytrade_realized_profit = state_realized_profit
        elif period == "ALL" and date_from == "" and date_to == "":
            state_realized_profit = _daytrade_state_realized_total(trading)
            if abs(state_realized_profit) > 0:
                daytrade_realized_profit = state_realized_profit
        if daytrade_summary.get("valuation_available", False):
            daytrade_unrealized_profit = float(daytrade_summary.get("remaining_unrealized_pnl", 0) or 0)
        daytrade_trade_count = int(daytrade_summary.get("trade_count", 0) or 0)
        daytrade_position_count = int(daytrade_summary.get("remaining_position_count", 0) or 0)
        total_invested += float(daytrade_summary.get("total_buy_amount", 0) or 0)
        total_invested += float(daytrade_summary.get("remaining_cost_amount", 0) or 0)
        for row in daytrade_summary.get("daily_breakdown", []) or []:
            date_key = str(row.get("date", "") or "")
            if date_key == "":
                continue
            daytrade_daily_breakdown[date_key] = float(row.get("pnl_net", 0) or 0)
    except Exception as e:
        _log("error", f"daytrade period summary failed: {e}")

    # 무한매수 완료사이클 실현손익 일별 집계
    for key, value in (partial_sell_realized.get("by_date", {}) or {}).items():
        ib_daily_realized_breakdown[key] = ib_daily_realized_breakdown.get(key, 0.0) + usd_to_krw(value)

    for c in completed:
        try:
            if _include_completed_cycle_in_realized(c, trade_db=cycle_trade_db) is False:
                continue
            completed_date = str(c.get("completed_at", "") or "")[:10]
            if completed_date == "":
                continue
            c_eval = float(c.get("current_eval", 0) or 0)
            c_spent = float(c.get("total_spent", 0) or 0)
            c_profit = usd_to_krw(c_eval) - usd_to_krw(c_spent)
            ib_daily_realized_breakdown[completed_date] = ib_daily_realized_breakdown.get(completed_date, 0.0) + c_profit
        except Exception:
            pass

    combined_daily_realized = {}
    for key, value in daytrade_daily_breakdown.items():
        combined_daily_realized[key] = combined_daily_realized.get(key, 0.0) + float(value or 0)
    for key, value in ib_daily_realized_breakdown.items():
        combined_daily_realized[key] = combined_daily_realized.get(key, 0.0) + float(value or 0)

    profit_totals = _combine_profit_components(
        cycle_realized_profit=cycle_realized_profit,
        cycle_unrealized_profit=cycle_unrealized_profit,
        daytrade_realized_profit=daytrade_realized_profit,
        daytrade_unrealized_profit=daytrade_unrealized_profit,
    )
    realized_profit = profit_totals["realized_profit"]
    unrealized_profit = profit_totals["unrealized_profit"]
    total_profit = profit_totals["total_profit"]
    total_return = (total_profit / total_invested * 100) if total_invested > 0 else 0

    # 실계좌 현재 총자산 확보 (차트 최신점/ALL 손익 보정 공용)
    if api_connected:
        try:
            present = kis.get_present_balance()
            live_exchange_rate = float(present.get("usd_krw", 0) or 0)
            live_total_asset_krw = float(present.get("total_asset_krw", 0) or 0)
            live_withdrawable_krw = float(present.get("withdrawable_krw", present.get("krw_balance", 0)) or 0)
            if live_exchange_rate <= 0:
                try:
                    fx_fallback = kis._get_usd_krw_rate_fallback()
                    live_exchange_rate = float(fx_fallback.get("rate", 0) or 0)
                except Exception:
                    live_exchange_rate = 0.0

            overseas_balance = kis.get_balance() or {}
            overseas_holdings = _apply_live_us_prices_to_holdings(trading, overseas_balance.get("holdings", []) or [], refresh=force_refresh)
            overseas_eval_usd, overseas_holding_count = _holding_eval_sum(overseas_holdings)
            overseas_total_eval_usd = float(overseas_balance.get("total_eval", 0) or 0)
            if overseas_eval_usd <= 0:
                overseas_eval_usd = overseas_total_eval_usd
            elif overseas_total_eval_usd > 0 and abs(overseas_total_eval_usd - overseas_eval_usd) > max(1.0, overseas_eval_usd * 0.2):
                _log(
                    "warning",
                    f"profit summary overseas total_eval mismatch ignored: total_eval={overseas_total_eval_usd}, holdings_sum={overseas_eval_usd}, holdings={overseas_holding_count}",
                )
            overseas_cash_usd = float(overseas_balance.get("cash_balance", 0) or 0)

            # 브로커 기준 미실현 손익 (해외)
            for h in overseas_holdings:
                h_profit = float(h.get("profit_loss", 0) or 0)
                if h_profit == 0:
                    qty = int(float(h.get("qty", 0) or 0))
                    avg = float(h.get("avg_price", 0) or 0)
                    cur = float(h.get("current_price", 0) or 0)
                    if qty > 0 and cur > 0:
                        h_profit = (cur - avg) * qty
                if live_exchange_rate > 0:
                    broker_unrealized_profit += (h_profit * live_exchange_rate)

            domestic_balance = kis.get_domestic_balance() or {}
            domestic_eval_krw = 0.0
            domestic_total_asset_krw = 0.0
            for h in (domestic_balance.get("holdings", []) or []):
                qty = int(float(h.get("qty", 0) or 0))
                eval_amount = float(h.get("eval_amount", 0) or 0)
                current_price = float(h.get("current_price", 0) or 0)
                if eval_amount > 0:
                    domestic_eval_krw += eval_amount
                elif qty > 0 and current_price > 0:
                    domestic_eval_krw += (qty * current_price)
                broker_unrealized_profit += float(h.get("profit_loss", 0) or 0)
            domestic_eval_krw = max(domestic_eval_krw, float(domestic_balance.get("portfolio_eval_krw", 0) or 0))
            domestic_total_asset_krw = float(domestic_balance.get("total_asset_krw", 0) or 0)

            if domestic_eval_krw <= 0:
                raw_domestic = domestic_balance.get("raw", {}) or {}
                output2 = raw_domestic.get("output2", {})
                if isinstance(output2, list):
                    output2 = output2[0] if len(output2) > 0 else {}
                if isinstance(output2, dict):
                    for key in ["scts_evlu_amt", "tot_evlu_amt", "tot_evlu_pfls_amt", "evlu_amt_smtl_amt"]:
                        amt = float(str(output2.get(key, 0) or 0).replace(",", ""))
                        if amt > domestic_eval_krw:
                            domestic_eval_krw = amt
                    for key in ["tot_evlu_amt", "nass_amt", "bfdy_tot_asst_evlu_amt", "tot_asst_amt"]:
                        amt = float(str(output2.get(key, 0) or 0).replace(",", ""))
                        if amt > domestic_total_asset_krw:
                            domestic_total_asset_krw = amt

            direct_live_total_asset = live_withdrawable_krw
            if live_exchange_rate > 0:
                direct_live_total_asset += ((overseas_cash_usd + overseas_eval_usd) * live_exchange_rate)
            direct_live_total_asset += domestic_eval_krw

            present_plus_domestic = live_total_asset_krw + domestic_eval_krw if live_total_asset_krw > 0 and domestic_eval_krw > 0 else 0.0
            combined_live_total_asset = 0.0
            if domestic_total_asset_krw > 0 and live_exchange_rate > 0 and overseas_eval_usd > 0:
                combined_live_total_asset = domestic_total_asset_krw + (overseas_eval_usd * live_exchange_rate) - live_unsettled_buy_krw + live_unsettled_sell_krw
            if combined_live_total_asset > 0:
                live_total_asset = combined_live_total_asset
                live_asset_source = "domestic_balance.total_asset_krw+live_us_eval-unsettled_us_buy"
            elif domestic_total_asset_krw > 0:
                live_total_asset = domestic_total_asset_krw
                live_asset_source = "domestic_balance.total_asset_krw"
            elif present_plus_domestic > 0:
                live_total_asset = present_plus_domestic
                live_asset_source = "present_balance.total_asset_krw+domestic_eval"
            elif live_total_asset_krw > 0:
                live_total_asset = live_total_asset_krw
                live_asset_source = "present_balance.total_asset_krw"
            else:
                live_total_asset = direct_live_total_asset
                live_asset_source = "direct(krw+domestic_eval+usd_cash+usd_eval)"
            if live_total_asset <= 0:
                try:
                    engine_budget = trading.daytrade_engine.shared_budget_status(requested_seed=0, use_cache_only=True, market="KS") or {}
                    engine_total_asset = float(engine_budget.get("total_asset_krw", 0) or 0)
                    if engine_total_asset > 0:
                        live_total_asset = engine_total_asset
                        live_asset_source = str(engine_budget.get("total_asset_source", live_asset_source) or live_asset_source)
                except Exception:
                    pass

            live_total_asset_ref = live_total_asset
            exchange_rate = live_exchange_rate if live_exchange_rate > 0 else exchange_rate

            # ALL 기간은 실계좌 현재 자산 값을 차트 최신점에 반영하되,
            # 실현손익은 전략별 집계를 그대로 유지한다.
            if period == "ALL" and date_from == "" and date_to == "":
                live_unrealized = cycle_unrealized_profit + daytrade_unrealized_profit
                if abs(live_unrealized) < 1 and abs(broker_unrealized_profit) > 1:
                    live_unrealized = broker_unrealized_profit
                unrealized_profit = live_unrealized
                total_profit = realized_profit + unrealized_profit
                total_invested = max(total_invested, live_total_asset - total_profit)
                total_return = (total_profit / total_invested * 100) if total_invested > 0 else 0
        except Exception as e:
            _log("error", f"live profit summary fallback to local data: {e}")

    avg_cycle_return = round(sum(cycle_returns) / len(cycle_returns), 2) if cycle_returns else 0
    best_cycle_return = max(cycle_returns) if cycle_returns else 0
    worst_cycle_return = min(cycle_returns) if cycle_returns else 0

    # 스냅샷 데이터 (차트용) — 실데이터만 사용
    try:
        raw_all_snapshots = snapshot_db.rows(orderby="snapshot_date", order="ASC") or []
        all_snapshots = raw_all_snapshots
        if filter_from:
            all_snapshots = [s for s in all_snapshots if s.get("snapshot_date", "") >= filter_from]
        if filter_to:
            all_snapshots = [s for s in all_snapshots if s.get("snapshot_date", "") <= filter_to]
        if len(all_snapshots) == 0 and len(raw_all_snapshots) > 0:
            all_snapshots = raw_all_snapshots
            base_asset_source = f"{base_asset_source}+snapshot_fallback_all"
    except Exception:
        all_snapshots = []

    snapshots = []
    snapshot_rows = []
    for s in all_snapshots:
        date_key = str(s.get("snapshot_date", "") or "")
        asset_krw = snapshot_to_krw(s.get("total_asset", 0) or 0)
        if date_key == "" or asset_krw <= 0:
            continue
        snapshot_rows.append({
            "date": date_key,
            "total_asset": round(asset_krw, 2),
        })

    should_include_today_live = (filter_to == today_str or filter_to == "") and live_total_asset_ref > 0
    if should_include_today_live:
        live_row = {
            "date": today_str,
            "total_asset": round(live_total_asset_ref, 2),
        }
        if len(snapshot_rows) > 0 and snapshot_rows[-1].get("date") == today_str:
            snapshot_rows[-1] = live_row
        else:
            snapshot_rows.append(live_row)

    snapshot_rows = sorted(snapshot_rows, key=lambda item: item.get("date", ""))
    if snapshot_rows:
        first_snapshot_asset = float(snapshot_rows[0].get("total_asset", 0) or 0)
        if configured_base_asset > 0 and first_snapshot_asset > 0 and first_snapshot_asset < configured_base_asset:
            base_asset = configured_base_asset
            base_asset_source = f"{base_asset_source}+floor_configured_base"
        else:
            base_asset = first_snapshot_asset
    elif live_total_asset_ref > 0:
        base_asset = live_total_asset_ref
        snapshot_rows = [{"date": today_str, "total_asset": round(live_total_asset_ref, 2)}]
    else:
        base_asset = configured_base_asset

    for row in snapshot_rows:
        asset_krw = float(row.get("total_asset", 0) or 0)
        profit = asset_krw - base_asset
        profit_rate = (profit / base_asset * 100) if base_asset > 0 else 0.0
        snapshots.append({
            "date": row.get("date", ""),
            "total_asset": round(asset_krw, 2),
            "profit": round(profit, 2),
            "profit_rate": round(profit_rate, 2),
        })

    # 일별 수익률 변화(전일 대비 %) 추가: 0% 기준 상/하 진동 그래프용
    prev_asset = None
    for s in snapshots:
        cur_asset = float(s.get("total_asset", 0) or 0)
        daily_return_rate = 0.0
        if prev_asset is not None and abs(prev_asset) > 0:
            daily_return_rate = ((cur_asset - prev_asset) / prev_asset) * 100
        s["daily_return_rate"] = round(daily_return_rate, 2)
        prev_asset = cur_asset

    # 일별 수익률 통계 (누적 대신 변동성/일평균 관측)
    daily_rates = []
    for i, s in enumerate(snapshots):
        if i == 0:
            continue
        daily_rates.append(float(s.get("daily_return_rate", 0) or 0))
    daily_return_avg = round(sum(daily_rates) / len(daily_rates), 2) if daily_rates else 0.0
    daily_return_best = round(max(daily_rates), 2) if daily_rates else 0.0
    daily_return_worst = round(min(daily_rates), 2) if daily_rates else 0.0
    latest_daily_return_rate = round(daily_rates[-1], 2) if daily_rates else 0.0
    asset_change_prev_day = 0.0
    if len(snapshots) >= 2:
        prev_asset = float(snapshots[-2].get("total_asset", 0) or 0)
        curr_asset = float(snapshots[-1].get("total_asset", 0) or 0)
        asset_change_prev_day = curr_asset - prev_asset

    # 수익률 평균/최고/최저: 완료사이클 데이터가 없으면 일별 실현손익 기반으로 계산
    if len(cycle_returns) == 0:
        rate_denominator = base_asset if base_asset > 0 else 0.0
        daily_rates = []
        if rate_denominator > 0:
            for _, pnl in sorted(combined_daily_realized.items()):
                daily_rates.append((float(pnl or 0) / rate_denominator) * 100)
        if len(daily_rates) > 0:
            avg_cycle_return = round(sum(daily_rates) / len(daily_rates), 2)
            best_cycle_return = round(max(daily_rates), 2)
            worst_cycle_return = round(min(daily_rates), 2)

    # 총수익률: 실제 투자금 기준 우선, 없으면 초기자산(설정값) 기준 fallback
    _return_denom = total_invested if total_invested > 0 else base_asset
    total_return = (total_profit / _return_denom * 100) if _return_denom > 0 else 0.0

    first_snapshot_date = ""
    if len(snapshots) > 0:
        first_snapshot_date = str(snapshots[0].get("date", "") or "")

    elapsed_days = 0
    if first_snapshot_date:
        try:
            elapsed_days = max(0, (datetime.datetime.strptime(today_str, "%Y-%m-%d") - datetime.datetime.strptime(first_snapshot_date, "%Y-%m-%d")).days)
        except Exception:
            elapsed_days = 0

    realized_return = (realized_profit / _return_denom * 100) if _return_denom > 0 else 0.0
    unrealized_return = (unrealized_profit / _return_denom * 100) if _return_denom > 0 else 0.0

    return dict(
        period=period,
        currency="KRW",
        api_connected=api_connected,
        setup_required=False,
        privacy_locked=False,
        server_time_kst=_TIME.now().strftime("%Y-%m-%d %H:%M:%S"),
        session_anchor_9am=session_anchor,
        exchange_rate=round(exchange_rate, 4),
        realized_profit=round(realized_profit, 2),
        unrealized_profit=round(unrealized_profit, 2),
        total_profit=round(total_profit, 2),
        total_invested=round(total_invested, 2),
        total_return=round(total_return, 2),
        completed_cycles=included_completed_cycles,
        avg_cycle_return=avg_cycle_return,
        best_cycle_return=best_cycle_return,
        worst_cycle_return=worst_cycle_return,
        cycle_realized_profit=round(cycle_realized_profit, 2),
        cycle_unrealized_profit=round(cycle_unrealized_profit, 2),
        daytrade_realized_profit=round(daytrade_realized_profit, 2),
        daytrade_unrealized_profit=round(daytrade_unrealized_profit, 2),
        daytrade_total_profit=round(daytrade_realized_profit + daytrade_unrealized_profit, 2),
        ib_realized_profit=round(cycle_realized_profit, 2),
        ib_unrealized_profit=round(cycle_unrealized_profit, 2),
        ib_realized_cycle_count=included_completed_cycles,
        realized_return=round(realized_return, 2),
        unrealized_return=round(unrealized_return, 2),
        base_asset=round(base_asset, 2),
        base_asset_source=base_asset_source,
        first_snapshot_date=first_snapshot_date,
        elapsed_days=elapsed_days,
        live_asset_source=live_asset_source,
        live_total_asset=round(live_total_asset_ref, 2),
        daytrade_trade_count=daytrade_trade_count,
        daytrade_position_count=daytrade_position_count,
        daily_return_avg=daily_return_avg,
        daily_return_best=daily_return_best,
        daily_return_worst=daily_return_worst,
        latest_daily_return_rate=latest_daily_return_rate,
        asset_change_prev_day=round(asset_change_prev_day, 2),
        snapshots=snapshots,
    )


def profit_summary():
    """기간별 수익 요약"""
    period = wiz.request.query("period", "ALL")
    date_from = wiz.request.query("date_from", "")
    date_to = wiz.request.query("date_to", "")
    force_refresh = _truthy(wiz.request.query("force_refresh", "false"))
    cache_key = json.dumps({"scope": _dashboard_cache_scope(), "period": period, "date_from": date_from, "date_to": date_to}, sort_keys=True)
    try:
        trading_for_access = _require_trading()
        setup_state = _broker_setup_state(trading_for_access, require_connection=True)
        if setup_state.get("allowed") is not True:
            message = setup_state.get("message", "")
            detail = str(setup_state.get("connection_message", "") or "").strip()
            if detail:
                message = f"{message} ({detail})"
            result = _empty_profit_summary_payload(period=period, message=message)
            _cache_set(_PROFIT_SUMMARY_CACHE, cache_key, result)
            wiz.response.status(200, **result)
    except Exception as e:
        _dump_error("profit_summary_access", e)
        result = _empty_profit_summary_payload(period=period, message=str(e))
        result["fallback"] = True
        wiz.response.status(200, **result)
    if force_refresh is False:
        cached_payload, cache_age = _cache_get(_PROFIT_SUMMARY_CACHE, cache_key, _PROFIT_SUMMARY_TTL_SEC)
        if isinstance(cached_payload, dict):
            cached_payload["cached"] = True
            cached_payload["cache_age_sec"] = cache_age
            wiz.response.status(200, **cached_payload)
    try:
        result = _profit_summary_data(period, date_from=date_from, date_to=date_to, force_refresh=force_refresh)
        _cache_set(_PROFIT_SUMMARY_CACHE, cache_key, result)
    except Exception as e:
        _dump_error("profit_summary", e)
        result = dict(
            period=period,
            currency="KRW",
            api_connected=False,
            session_anchor_9am="",
            exchange_rate=0,
            realized_profit=0,
            unrealized_profit=0,
            total_profit=0,
            total_invested=0,
            total_return=0,
            completed_cycles=0,
            avg_cycle_return=0,
            best_cycle_return=0,
            worst_cycle_return=0,
            cycle_realized_profit=0,
            cycle_unrealized_profit=0,
            daytrade_realized_profit=0,
            daytrade_unrealized_profit=0,
            daytrade_total_profit=0,
            ib_realized_profit=0,
            ib_unrealized_profit=0,
            ib_realized_cycle_count=0,
            realized_return=0,
            unrealized_return=0,
            base_asset=0,
            base_asset_source="error_fallback",
            first_snapshot_date="",
            elapsed_days=0,
            live_asset_source="",
            live_total_asset=0,
            daytrade_trade_count=0,
            daytrade_position_count=0,
            daily_return_avg=0,
            daily_return_best=0,
            daily_return_worst=0,
            latest_daily_return_rate=0,
            asset_change_prev_day=0,
            snapshots=[],
            fallback=True,
            message=str(e),
        )
    wiz.response.status(200, **result)


def toggle_auto_trade():
    """자동매매 토글"""
    trading = _require_dashboard_access(require_connection=True)
    current_auto = str(trading.get_config("auto_trade_enabled", "false") or "false").lower() == "true"
    current_loc = str(trading.get_config("loc_auto_schedule_enabled", "true") or "true").lower() == "true"
    new_enabled = not (current_auto and current_loc)
    new_val = "true" if new_enabled else "false"
    trading.set_config("auto_trade_enabled", new_val, description="자동매매 활성화")
    trading.set_config("loc_auto_schedule_enabled", new_val, description="무한매수 LOC 자동 예약 활성화")
    wiz.response.status(200, auto_trade=new_enabled, loc_auto_schedule_enabled=new_enabled)

def run_due_automation():
    """대시보드 폴링 시점에 서버 자동화와 같은 LOC 예약 검증 경로를 호출."""
    try:
        global _DUE_AUTOMATION_LAST_BUCKET
        trading = _require_dashboard_access(require_connection=True)
        now = _TIME.now()
        bucket = _loc_reservation_bucket(now)
        in_loc_verify_window = _loc_reservation_window_open(now)
        force_verify = bool(in_loc_verify_window and _DUE_AUTOMATION_LAST_BUCKET != bucket)
        result = trading.run_due_loc_automation(
            verify=force_verify,
            reason="dashboard_5min_reservation_verify" if force_verify else "dashboard_poll",
        )
        if force_verify:
            _DUE_AUTOMATION_LAST_BUCKET = bucket
        return wiz.response.status(200, **(result or {}))
    except Exception as e:
        if e.__class__.__name__ == "ResponseException":
            raise
        _dump_error("run_due_automation", e)
        return wiz.response.status(200,
            enabled=True,
            executed=False,
            scheduled_at=_loc_reservation_next_start_label(),
            schedule_window=_loc_reservation_window_label(),
            status="error",
            message=str(e),
            error_count=1,
            errors=[{"reason": str(e)}])

def run_engine():
    """엔진 수동 실행 (자동매매 비활성이어도 수동 실행은 허용)"""
    trading = _require_dashboard_access(require_connection=True)
    engine = trading.engine
    try:
        results = engine.run_all()
    except Exception as e:
        wiz.response.status(500, message=str(e))
    wiz.response.status(200, results=results)

def start_cycle():
    """특정 종목의 사이클 수동 시작 (사용자 지정 파라미터 지원)"""
    symbol = wiz.request.query("symbol", True)
    total_investment = wiz.request.query("total_investment", "")
    division_count = wiz.request.query("division_count", "")
    target_profit = wiz.request.query("target_profit", "")
    trading = _require_dashboard_access(require_connection=True)
    engine = trading.engine

    kwargs = {}
    if total_investment:
        kwargs["total_investment"] = float(total_investment)
    if division_count:
        kwargs["division_count"] = int(division_count)
    if target_profit:
        kwargs["target_profit"] = float(target_profit)

    try:
        cycle = engine.start_cycle(symbol, **kwargs)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, cycle=cycle)

def force_close_cycle():
    """사이클 강제 종료"""
    cycle_id = wiz.request.query("cycle_id", True)
    trading = _require_dashboard_access(require_connection=True)
    engine = trading.engine
    try:
        cycle = engine.force_close_cycle(cycle_id)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, cycle=cycle)

def pause_cycle():
    """사이클 일시 정지"""
    cycle_id = wiz.request.query("cycle_id", True)
    trading = _require_dashboard_access(require_connection=True)
    engine = trading.engine
    try:
        cycle = engine.pause_cycle(cycle_id)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, cycle=cycle)

def resume_cycle():
    """사이클 재개"""
    cycle_id = wiz.request.query("cycle_id", True)
    trading = _require_dashboard_access(require_connection=True)
    engine = trading.engine
    try:
        cycle = engine.resume_cycle(cycle_id)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, cycle=cycle)

def delete_cycle():
    """사이클 삭제 (PAUSED/COMPLETED 상태)"""
    cycle_id = wiz.request.query("cycle_id", True)
    trading = _require_dashboard_access(require_connection=True)
    engine = trading.engine
    try:
        result = engine.delete_cycle(cycle_id)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, **result)

def delete_trade():
    """개별 거래 삭제"""
    trade_id = wiz.request.query("trade_id", True)
    trading = _require_dashboard_access(require_connection=True)
    engine = trading.engine
    try:
        result = engine.delete_trade(trade_id)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, **result)

def update_cycle():
    """활성 사이클 파라미터 수정"""
    cycle_id = wiz.request.query("cycle_id", True)
    target_profit = wiz.request.query("target_profit", "")
    division_count = wiz.request.query("division_count", "")
    total_investment = wiz.request.query("total_investment", "")

    trading = _require_dashboard_access(require_connection=True)
    engine = trading.engine

    tp = float(target_profit) if target_profit else None
    dc = int(division_count) if division_count else None
    ti = float(total_investment) if total_investment else None

    try:
        cycle = engine.update_cycle_params(cycle_id, target_profit=tp, division_count=dc, total_investment=ti)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, cycle=cycle)

def extend_cycle():
    """사이클 연장 (추가 매수 진행)"""
    cycle_id = wiz.request.query("cycle_id", True)
    extra_rounds = wiz.request.query("extra_rounds", True)
    extra_investment = wiz.request.query("extra_investment", "0")
    trading = _require_dashboard_access(require_connection=True)
    engine = trading.engine
    try:
        extra_rounds = int(extra_rounds)
        extra_investment = float(extra_investment)
        cycle = engine.extend_cycle(cycle_id, extra_rounds, extra_investment)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, cycle=cycle)

def keep_holding():
    """홀딩 유지 (추가 매수 안 함)"""
    cycle_id = wiz.request.query("cycle_id", True)
    trading = _require_dashboard_access(require_connection=True)
    engine = trading.engine
    try:
        cycle = engine.keep_holding(cycle_id)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, cycle=cycle)

def trade_preview():
    """오늘 매매 예정 종목 프리뷰 (매수 + 매도)"""
    trading_for_access = _require_dashboard_access(require_connection=True)
    cache_key = _dashboard_cache_scope()
    cached_payload, cache_age = _cache_get(_TRADE_PREVIEW_CACHE, cache_key, _TRADE_PREVIEW_TTL_SEC)
    if isinstance(cached_payload, dict):
        cached_payload["cached"] = True
        cached_payload["cache_age_sec"] = cache_age
        wiz.response.status(200, **cached_payload)

    def _builder():
        trading = trading_for_access
        engine = trading.engine
        kis = getattr(trading, "broker_api", None) or trading.kis_api

        api_connected = False
        try:
            test_result = _kis_connection_status(trading)
            api_connected = test_result.get("success", False)
        except Exception:
            pass

        cycles = engine.get_active_cycles()
        previews = []

        for cycle in cycles:
            status = cycle.get("status", "")
            symbol = cycle["symbol"]
            cycle_number = cycle.get("cycle_number", 1)
            current_round = cycle.get("current_round", 0)
            division_count = cycle.get("division_count", 40)
            total_qty = int(cycle.get("total_qty", 0))

            prev_close = 0
            current_price = 0
            if api_connected:
                try:
                    watchlist_db = trading.db("etf_watchlist")
                    etf_item = watchlist_db.get(symbol=symbol)
                    order_exchange = etf_item.get("exchange", "NASD") if etf_item else "NASD"
                    price_exch_map = {"NASD": "NAS", "NYSE": "NYS", "AMEX": "AMS"}
                    price_exchange = price_exch_map.get(order_exchange, "NAS")
                    price_data = kis.get_current_price(symbol, exchange=price_exchange)
                    resolved_order_exchange = price_data.get("order_exchange", order_exchange)
                    if etf_item and resolved_order_exchange and resolved_order_exchange != order_exchange:
                        watchlist_db.update({
                            "exchange": resolved_order_exchange,
                            "updated": _TIME.now(),
                        }, id=etf_item["id"])
                    prev_close = price_data.get("prev_close", 0)
                    current_price = price_data.get("price", 0)
                except Exception:
                    pass

            entry = {
                "symbol": symbol,
                "cycle_number": cycle_number,
                "current_round": current_round,
                "division_count": division_count,
                "status": status,
                "current_price": current_price,
                "prev_close": prev_close,
                "avg_price": float(cycle.get("avg_price", 0)),
                "should_buy": False,
                "buy_amount": 0,
                "loc_price": 0,
                "order_type": None,
                "order_qty": 0,
                "buy_reason": "",
                "should_sell": False,
                "sell_type": None,
                "sell_qty": 0,
                "profit_rate": float(cycle.get("profit_rate", 0)),
                "sell_reason": "",
            }

            if status == "ACTIVE" and prev_close > 0:
                buy_decision = engine.calculate_buy_decision(cycle, prev_close)
                entry["should_buy"] = buy_decision.get("should_buy", False)
                entry["buy_amount"] = buy_decision.get("buy_amount", 0)
                entry["loc_price"] = buy_decision.get("loc_price", 0)
                entry["order_type"] = buy_decision.get("order_type")
                entry["order_qty"] = buy_decision.get("order_qty", 0)
                entry["buy_reason"] = buy_decision.get("reason", "")
            elif status == "ACTIVE":
                entry["buy_reason"] = "전일종가 조회 불가 — API 미연결 또는 비장시간"

            if total_qty > 0 and current_price > 0:
                sell_decision = engine.calculate_sell_decision(cycle, current_price)
                entry["should_sell"] = sell_decision.get("should_sell", False)
                entry["sell_type"] = sell_decision.get("sell_type")
                entry["sell_qty"] = sell_decision.get("sell_qty", 0)
                entry["profit_rate"] = sell_decision.get("profit_rate", 0)
                entry["sell_reason"] = sell_decision.get("reason", "")
            elif total_qty > 0:
                entry["sell_reason"] = "현재가 조회 불가"

            if not entry["should_buy"] and not entry["should_sell"] and not entry["buy_reason"]:
                entry["buy_reason"] = f"상태: {status} — 매매 대상 아님"

            previews.append(entry)

        payload = {
            "api_connected": api_connected,
            "previews": previews,
            "cached": False,
        }
        _cache_set(_TRADE_PREVIEW_CACHE, cache_key, payload)
        return payload

    payload, is_leader = _singleflight(f"dashboard:trade_preview:{cache_key}", _builder, timeout_sec=90.0)
    if is_leader is False:
        cached_payload, cache_age = _cache_get(_TRADE_PREVIEW_CACHE, cache_key, _TRADE_PREVIEW_TTL_SEC)
        if isinstance(cached_payload, dict):
            cached_payload["cached"] = True
            cached_payload["cache_age_sec"] = cache_age
            wiz.response.status(200, **cached_payload)
        payload = _builder()
    wiz.response.status(200, **payload)


def retry_loc_buy_reservation():
    """무한매수 예약을 해당 종목 기준으로 전체 취소 후 FireGate 표대로 다시 접수."""
    symbol = _normalize_symbol(wiz.request.query("symbol", ""))
    if not symbol:
        wiz.response.status(400, message="symbol is required")
    trading = _require_trading()
    external_sync = {}
    firegate_sync = {}
    try:
        lock_fn = getattr(trading, "_loc_reservation_lock", None)
        if callable(lock_fn):
            with lock_fn(timeout_sec=1) as acquired:
                if acquired is False:
                    result = trading._loc_reservation_locked_result(reason=f"manual_retry_{symbol}")
                else:
                    external_sync = _sync_external_cycle_trades_if_due(trading, force=True, symbol_filter=symbol)
                    firegate_sync = _sync_firegate_portfolios_before_loc(trading, symbol_filter=symbol)
                    result = trading.engine.rebuild_loc_reservations([symbol]) or {}
        else:
            external_sync = _sync_external_cycle_trades_if_due(trading, force=True, symbol_filter=symbol)
            firegate_sync = _sync_firegate_portfolios_before_loc(trading, symbol_filter=symbol)
            result = trading.engine.rebuild_loc_reservations([symbol]) or {}
    except Exception as e:
        _dump_error("retry_loc_buy_reservation", e)
        wiz.response.status(500, message=str(e), external_cycle_sync=external_sync, firegate_sync=firegate_sync)

    cycles = _safe_active_cycles(trading)
    cycles = [cycle for cycle in cycles if _normalize_symbol((cycle or {}).get("symbol")) == symbol]
    cycles, summary = _attach_loc_buy_status(trading, cycles, with_summary=True)
    wiz.response.status(200,
        symbol=symbol,
        result=result,
        external_cycle_sync=external_sync,
        firegate_sync=firegate_sync,
        cycles=cycles,
        infinite_buy_summary=summary,
    )


def get_watchlist_defaults():
    """워치리스트 종목의 기본 매매 파라미터 조회"""
    symbol = wiz.request.query("symbol", True)
    trading = _require_trading()
    watchlist_db = trading.db("etf_watchlist")

    try:
        etf = watchlist_db.get(symbol=symbol, is_active=True)
    except Exception as e:
        wiz.response.status(404, message=f"종목 [{symbol}]이 워치리스트에 없습니다.")

    if not etf:
        wiz.response.status(404, message=f"종목 [{symbol}]이 워치리스트에 없습니다.")

    wiz.response.status(200,
        symbol=etf.get("symbol", ""),
        name=etf.get("name", ""),
        total_investment=float(etf.get("total_investment", 0)),
        division_count=int(etf.get("division_count", 40)),
        target_profit=float(etf.get("target_profit", 10.0)),
        cycle_mode=etf.get("cycle_mode", "auto"),
    )
