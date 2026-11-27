"""Daily report page API (11-27, /report).

Read-only. The report is built by portal/trading/daily_report from the two
trading.db files (opened ?mode=ro) and the runtime JSON files. Nothing here
calls KIS, Upbit or FireGate, writes a setting, or touches an order path.

Each server reads its own mode and the other mode's database through
STOCK8_LIVE_DB_PATH / STOCK8_PAPER_DB_PATH, like paper_subscription.py.
One report per (user, date, admin) is cached for 45 s and built once at a
time (single-flight, as the dashboard overview does).
"""
import copy
import os
import sys as _sys
import threading
import time

_TIME = wiz.model("portal/trading/kst")
_TRADING_MODE = str(os.environ.get("TRADING_MODE", "PAPER") or "PAPER").strip().upper()
_SHARED = _sys.__dict__.setdefault("_stock8_daily_report_v1", {})
_CACHE = _SHARED.setdefault("cache", {})
_LOCK = _SHARED.setdefault("lock", threading.Lock())
_FLIGHTS = _SHARED.setdefault("flights", {})
_TTL_SEC = 45.0
_FORCE_MIN_AGE_SEC = 5.0
_FLIGHT_WAIT_SEC = 30.0
_CACHE_MAX = 200


def _uid():
    return str(wiz.session.get("id") or "").strip()


def _is_admin(uid):
    """The page.coin controller rule (role admin or the operator account),
    read from the user row the same way that controller does. The project
    struct's user lookup is a plain read; the trading Struct (whose
    constructor migrates, seals and may start workers) is never built here.
    A failed lookup raises: the caller answers 503 and caches nothing."""
    user = wiz.model("struct").user.get(id=uid)
    role = str((user or {}).get("role", "") or "").lower()
    email = str((user or {}).get("email", "") or "").strip().lower()
    return role == "admin" or email == "gigukbyun@gmail.com"


def _truthy_env(name):
    return str(os.environ.get(name, "false")).lower() in ("1", "true", "yes", "on")


def _connection_cache(uid):
    """The dashboard's last KIS status for this user (this server's memory only)."""
    store = (_sys.__dict__.get("_stock8_dashboard_shared_v1") or {}).get("kis_status") or {}
    entry = store.get(f"user:{uid}") or {}
    result = entry.get("result")
    if not isinstance(result, dict):
        return None
    checked = float(entry.get("checked_at", 0.0) or 0.0)
    return {"success": result.get("success") is True, "message": str(result.get("message", "") or "")[:120],
            "age_sec": int(max(0.0, time.monotonic() - checked)) if checked else None}


def _live_workers():
    """LIVE per-account worker states (this process only), without threads.
    The report keeps only the rows of the user's own account policy."""
    if _TRADING_MODE != "LIVE":
        return None
    registry = getattr(_sys, "_stock8_live_policy_workers", None) or {}
    rows = []
    for (policy_key, job), item in list((registry.get("jobs") or {}).items()):
        if isinstance(item, dict):
            rows.append({"policy_key": policy_key, "job": job, "status": item.get("status", ""),
                         "message": item.get("message", ""), "error": item.get("error", ""),
                         "last_check": item.get("last_check", "")})
    return {"rows": rows, "error": str(registry.get("error", "") or "")}


def _build(uid, day, is_admin):
    model = wiz.model("portal/trading/daily_report")
    kis = wiz.model("portal/trading/struct/kis_api")
    market = wiz.model("portal/trading/domestic_market")
    secret = wiz.model("portal/trading/secret_box")
    root = wiz.server.path.root
    return model.build_report(
        uid, day, now=_TIME.now(), is_admin=is_admin, server_mode=_TRADING_MODE,
        db_paths={mode: model.mode_db_path(root, mode) for mode in ("LIVE", "PAPER")},
        data_dir=wiz.project.fs().abspath("data"), decrypt=secret.decrypt,
        krx_holidays=getattr(market, "KRX_HOLIDAYS", ()),
        us_holidays=getattr(kis, "US_MARKET_HOLIDAYS", {}), us_early_closes=getattr(kis, "US_EARLY_CLOSES", {}),
        process={"connection_cache": _connection_cache(uid), "live_workers": _live_workers()},
        daytrade_hard_locked=_truthy_env("STOCK8_DAYTRADE_HARD_LOCK"),
        coin_hard_locked=_truthy_env("STOCK8_COIN_HARD_LOCK"))


def _cached(key, max_age):
    with _LOCK:
        entry = _CACHE.get(key)
    if entry and time.monotonic() - entry[0] < max_age:
        return copy.deepcopy(entry[1]), round(time.monotonic() - entry[0], 1)
    return None, None


def _store(key, payload):
    now = time.monotonic()
    with _LOCK:
        _CACHE[key] = (now, copy.deepcopy(payload))
        for old in [k for k, (ts, _p) in _CACHE.items() if now - ts > _TTL_SEC * 10]:
            _CACHE.pop(old, None)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.pop(min(_CACHE, key=lambda k: _CACHE[k][0]), None)


def _report_once(key, build, force=False):
    """(payload, age_sec): cached for _TTL_SEC; one build per key at a time."""
    payload, age = _cached(key, _FORCE_MIN_AGE_SEC if force else _TTL_SEC)
    if payload is not None:
        return payload, age
    with _LOCK:
        event = _FLIGHTS.get(key)
        leader = event is None
        if leader:
            event = threading.Event()
            _FLIGHTS[key] = event
    if not leader:
        event.wait(_FLIGHT_WAIT_SEC)
        payload, age = _cached(key, _TTL_SEC)
        if payload is not None:
            return payload, age
        return build(), 0.0  # the leader failed: read again ourselves
    try:
        payload = build()
        _store(key, payload)
        return payload, 0.0
    finally:
        with _LOCK:
            event.set()
            _FLIGHTS.pop(key, None)


def report():
    uid = _uid()
    if not uid:
        wiz.response.status(401, message="로그인이 필요합니다.")
    model = wiz.model("portal/trading/daily_report")
    today = _TIME.now().date()
    try:
        day = model.parse_day(wiz.request.query("date", ""), today)
    except ValueError as exc:
        wiz.response.status(400, message=str(exc), dates=model.date_options(today))
    force = str(wiz.request.query("force", "") or "").lower() == "true"
    try:
        is_admin = _is_admin(uid)
    except Exception as exc:
        # Unknown is not "not an admin": nothing is built or cached.
        wiz.response.status(503, message=f"관리자 여부를 확인하지 못했습니다 ({type(exc).__name__}). 잠시 후 다시 시도하세요.")
    key = f"{uid}:{day.isoformat()}:{int(is_admin)}"
    try:
        payload, age = _report_once(key, lambda: _build(uid, day, is_admin), force=force)
    except Exception as exc:
        # The type only: exception text may carry server paths.
        wiz.response.status(500, message=f"일일 보고를 만들지 못했습니다 ({type(exc).__name__}).")
    payload["cache_age_sec"] = age
    wiz.response.status(200, **payload)
