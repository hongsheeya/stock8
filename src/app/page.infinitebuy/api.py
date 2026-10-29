import base64
import json
import math
import re
import time
import traceback

try:
    from season.lib.exception import ResponseException
except Exception:
    class ResponseException(Exception):
        pass

_TIME = wiz.model("portal/trading/kst")

_STRUCT_CACHE = {"obj": None, "error": None, "error_at": 0.0}
_STRUCT_ERROR_TTL_SEC = 5.0
_FIRE_GATE_URL = "https://fire-gate.app/"
_FIRE_GATE_BRIDGE_CONFIG_KEY = "fire_gate_bridge"
_ACTIVE_STATUSES = ("ACTIVE", "HOLDING", "PAUSED", "PENDING_EXTENSION")
_PRICE_EXCHANGE_MAP = {"NASD": "NAS", "NYSE": "NYS", "AMEX": "AMS"}


def _get_struct():
    cached = _STRUCT_CACHE.get("obj")
    if cached is not None:
        return cached

    cached_error = _STRUCT_CACHE.get("error")
    if cached_error is not None:
        elapsed = time.monotonic() - float(_STRUCT_CACHE.get("error_at", 0.0) or 0.0)
        if elapsed < _STRUCT_ERROR_TTL_SEC:
            raise cached_error
        _STRUCT_CACHE["error"] = None
        _STRUCT_CACHE["error_at"] = 0.0

    try:
        _STRUCT_CACHE["obj"] = wiz.model("struct")
    except Exception as e:
        _STRUCT_CACHE["obj"] = None
        _STRUCT_CACHE["error"] = e
        _STRUCT_CACHE["error_at"] = time.monotonic()
        raise

    return _STRUCT_CACHE["obj"]


def _trading():
    return _get_struct().trading


def _firegate_bridge_mod():
    return wiz.model("portal/trading/struct/firegate_bridge")


def _is_response_exception(error):
    return isinstance(error, ResponseException) or (
        str(error) == "season.core.exception.response" and hasattr(error, "get_response")
    )


def _safe_float(value, default=0.0):
    try:
        text = str(value if value is not None else "").replace(",", "").strip()
        if text == "":
            return float(default)
        return float(text)
    except Exception:
        return float(default)


def _safe_int(value, default=0):
    try:
        text = str(value if value is not None else "").replace(",", "").strip()
        if text == "":
            return int(default)
        return int(float(text))
    except Exception:
        return int(default)


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "y", "on")


def _jwt_payload(token):
    try:
        parts = str(token or "").split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8"))
    except Exception:
        return {}


def _id_token_expired_or_stale(id_token, grace_sec=300):
    payload = _jwt_payload(id_token)
    exp = _safe_int(payload.get("exp"), 0)
    if exp <= 0:
        return False
    return exp <= int(time.time()) + max(_safe_int(grace_sec, 300), 0)


def _bridge_config():
    trading = _trading()
    raw = ""
    try:
        raw = trading.get_config(_FIRE_GATE_BRIDGE_CONFIG_KEY, "{}")
    except Exception:
        row = trading.db("trading_config").get(key=_FIRE_GATE_BRIDGE_CONFIG_KEY)
        raw = row.get("value", "{}") if row else "{}"
    try:
        cfg = json.loads(raw or "{}")
        if not isinstance(cfg, dict):
            cfg = {}
    except Exception:
        cfg = {}
    cfg.setdefault("enabled", False)
    cfg.setdefault("auto_sync_enabled", True)
    cfg.setdefault("auto_sync_interval_sec", 600)
    cfg.setdefault("email", "")
    cfg.setdefault("id_token", "")
    cfg.setdefault("refresh_token", "")
    cfg.setdefault("updated_at", "")
    return cfg


def _save_bridge_config(cfg):
    cfg = dict(cfg or {})
    cfg["enabled"] = bool(cfg.get("enabled"))
    cfg["auto_sync_enabled"] = bool(cfg.get("auto_sync_enabled", True))
    cfg["auto_sync_interval_sec"] = max(_safe_int(cfg.get("auto_sync_interval_sec", 600), 600), 30)
    cfg["updated_at"] = _TIME.isoformat(with_offset=True)
    _trading().set_config(
        _FIRE_GATE_BRIDGE_CONFIG_KEY,
        json.dumps(cfg, ensure_ascii=False),
        description="FireGate Firebase bridge session",
        is_secret=True,
    )
    return cfg


def _public_bridge_config(cfg):
    email = str((cfg or {}).get("email", "") or "")
    masked = email
    if "@" in email:
        name, domain = email.split("@", 1)
        masked = f"{name[:2]}***@{domain}"
    return {
        "enabled": bool((cfg or {}).get("enabled")),
        "auto_sync_enabled": bool((cfg or {}).get("auto_sync_enabled", True)),
        "auto_sync_interval_sec": max(_safe_int((cfg or {}).get("auto_sync_interval_sec", 600), 600), 30),
        "configured": bool((cfg or {}).get("email") and ((cfg or {}).get("id_token") or (cfg or {}).get("refresh_token"))),
        "email": email,
        "email_masked": masked,
        "has_id_token": bool((cfg or {}).get("id_token")),
        "has_refresh_token": bool((cfg or {}).get("refresh_token")),
        "updated_at": (cfg or {}).get("updated_at", ""),
    }


def _refresh_bridge_token(cfg):
    fg = _firegate_bridge_mod()
    refresh_token = str((cfg or {}).get("refresh_token", "") or "").strip()
    if not refresh_token:
        raise Exception("FireGate 재로그인이 필요합니다. refresh token이 없습니다.")
    token_data = fg.refresh_id_token(refresh_token)
    cfg = dict(cfg or {})
    cfg["id_token"] = token_data.get("id_token") or token_data.get("idToken") or cfg.get("id_token", "")
    cfg["refresh_token"] = token_data.get("refresh_token") or token_data.get("refreshToken") or refresh_token
    payload = _jwt_payload(cfg.get("id_token"))
    cfg["email"] = cfg.get("email") or payload.get("email", "")
    cfg["enabled"] = True
    _save_bridge_config(cfg)
    return cfg


def _bridge_client(cfg=None, refresh_if_needed=True):
    cfg = dict(cfg or _bridge_config())
    should_refresh = refresh_if_needed and cfg.get("refresh_token") and (
        not cfg.get("id_token") or _id_token_expired_or_stale(cfg.get("id_token"))
    )
    if should_refresh:
        cfg = _refresh_bridge_token(cfg)
    fg = _firegate_bridge_mod()
    if not cfg.get("email") or not cfg.get("id_token"):
        raise Exception("FireGate 브릿지 로그인이 필요합니다.")
    return fg.FireGateBridge(cfg.get("email"), cfg.get("id_token")), cfg


def _bridge_call(fn):
    fg = _firegate_bridge_mod()
    cfg = _bridge_config()
    bridge, cfg = _bridge_client(cfg)
    try:
        return fn(bridge, cfg)
    except fg.FireGateAuthError:
        cfg = _refresh_bridge_token(cfg)
        bridge, cfg = _bridge_client(cfg, refresh_if_needed=False)
        return fn(bridge, cfg)


def _round2(value):
    return math.floor(float(value or 0) * 100 + 0.5) / 100


def _normalize_symbol(symbol):
    return re.sub(r"[^A-Z0-9.-]", "", str(symbol or "").upper().strip())


def _normalize_exchange(exchange):
    exchange = str(exchange or "NASD").upper().strip()
    if exchange not in ("NASD", "NYSE", "AMEX"):
        return "NASD"
    return exchange


def _watchlist_rows(watchlist_db):
    try:
        rows = watchlist_db.rows(is_active=True, orderby="created", order="ASC", dump=200) or []
    except Exception:
        try:
            rows = watchlist_db.rows(orderby="created", order="ASC", dump=200) or []
        except Exception:
            return []

    # Background broker reconciliation can legitimately create an unscoped
    # legacy row before a signed-in user has a scoped row.  They are the same
    # logical instrument and must never render as two portfolio cards.
    by_symbol = {}
    for row in rows:
        symbol = _normalize_symbol((row or {}).get("symbol"))
        if not symbol:
            continue
        current = by_symbol.get(symbol)
        row_stamp = str((row or {}).get("updated") or (row or {}).get("created") or "")
        current_stamp = str((current or {}).get("updated") or (current or {}).get("created") or "")
        if current is None or row_stamp >= current_stamp:
            by_symbol[symbol] = row
    return list(by_symbol.values())


def _active_cycle(cycle_db, symbol):
    for status in _ACTIVE_STATUSES:
        try:
            rows = cycle_db.rows(symbol=symbol, status=status, orderby="updated", order="DESC", dump=200) or []
        except Exception:
            row = cycle_db.get(symbol=symbol, status=status)
            rows = [row] if row else []
        if rows:
            # Prefer the row that represents the real broker holding.  This
            # prevents a newer but empty user-scoped shell cycle from hiding a
            # legacy cycle that owns the actual quantity and cost basis.
            return max(rows, key=lambda row: (
                _safe_int((row or {}).get("total_qty"), 0) > 0,
                _safe_float((row or {}).get("total_spent"), 0) > 0,
                _safe_int((row or {}).get("current_round"), 0),
                str((row or {}).get("updated") or (row or {}).get("created") or ""),
            ))
    return None


def _virtual_cycle(item):
    seed = _safe_float(item.get("total_investment"), 0)
    return {
        "id": "",
        "symbol": _normalize_symbol(item.get("symbol")),
        "cycle_number": None,
        "status": "READY",
        "current_round": 0,
        "division_count": max(_safe_int(item.get("division_count"), 40), 1),
        "target_profit": _safe_float(item.get("target_profit"), 10),
        "total_investment": seed,
        "total_spent": 0.0,
        "total_qty": 0,
        "avg_price": 0.0,
        "current_price": 0.0,
        "current_eval": 0.0,
        "profit_rate": 0.0,
        "remaining_investment": seed,
    }


def _price_snapshot(trading, symbol, exchange, refresh=False):
    if not refresh:
        return {}, exchange

    try:
        kis = getattr(trading, "broker_api", None) or trading.kis_api
        price_exchange = _PRICE_EXCHANGE_MAP.get(exchange, "NAS")
        data = kis.get_current_price(symbol, exchange=price_exchange) or {}
        resolved = data.get("order_exchange") or exchange
        return data, _normalize_exchange(resolved)
    except Exception as e:
        return {"error": str(e)}, exchange


def _buy_plan(engine, cycle, prev_close):
    if _safe_float(prev_close, 0) <= 0:
        return {
            "should_buy": False,
            "buy_amount": 0,
            "buy_orders": [],
            "reason": "전일종가 없음",
            "state_name": "",
            "t_value": _safe_float(cycle.get("t_value", cycle.get("current_round", 0)), 0),
        }
    try:
        return engine.calculate_buy_decision(cycle, prev_close) or {}
    except Exception as e:
        return {
            "should_buy": False,
            "buy_amount": 0,
            "buy_orders": [],
            "reason": f"매수가 계산 실패: {str(e)}",
            "state_name": "",
            "t_value": _safe_float(cycle.get("t_value", cycle.get("current_round", 0)), 0),
        }


def _sell_profit_pct(symbol):
    return 15.0 if str(symbol or "").upper() == "TQQQ" else 20.0


def _fallback_star_percent(symbol, division_count, t_value):
    symbol = str(symbol or "").upper()
    division_count = int(division_count or 0)
    t_value = float(t_value or 0)
    if symbol == "TQQQ":
        if division_count == 20:
            return max(0.0, 15.0 - 1.5 * t_value)
        if division_count == 30:
            return max(0.0, 15.0 - t_value)
        return max(0.0, 15.0 - 0.75 * t_value)
    if division_count == 20:
        return max(0.0, 20.0 - 2.0 * t_value)
    if division_count == 30:
        return max(0.0, 20.0 - (4.0 / 3.0) * t_value)
    return max(0.0, 20.0 - t_value)


def _sell_plan(cycle, buy_decision):
    symbol = str(cycle.get("symbol", "") or "").upper()
    qty = _safe_int(cycle.get("total_qty"), 0)
    avg_price = _safe_float(cycle.get("avg_price"), 0)
    if qty <= 0 or avg_price <= 0:
        return []

    division_count = max(_safe_int(cycle.get("division_count"), 40), 1)
    t_value = _safe_float(buy_decision.get("t_value", cycle.get("current_round", 0)), 0)
    star_percent = _safe_float(buy_decision.get("star_percent"), 0)
    if star_percent <= 0:
        star_percent = _fallback_star_percent(symbol, division_count, t_value)

    star_price = _safe_float(buy_decision.get("star_price"), 0)
    if star_price <= 0:
        star_price = _round2(avg_price * (1 + star_percent / 100))

    star_qty = qty // 4
    limit_qty = qty - star_qty
    limit_pct = _sell_profit_pct(symbol)
    limit_price = _round2(avg_price * (1 + limit_pct / 100))

    orders = []
    if star_qty > 0:
        orders.append({
            "label": f"LOC ★{star_percent:.2f}%",
            "role": "star",
            "order_type": "LOC",
            "price": star_price,
            "order_qty": star_qty,
        })
    if limit_qty > 0:
        orders.append({
            "label": f"지정가 +{limit_pct:.0f}%",
            "role": "limit",
            "order_type": "LIMIT",
            "price": limit_price,
            "order_qty": limit_qty,
        })
    return orders


def _normalize_order(order):
    price = _safe_float(order.get("loc_price", order.get("price", 0)), 0)
    qty = _safe_int(order.get("order_qty", order.get("qty", 0)), 0)
    return {
        "label": order.get("label", ""),
        "role": order.get("role", ""),
        "order_key": order.get("order_key", ""),
        "order_type": order.get("order_type", "LOC"),
        "loc_price": price,
        "price": price,
        "order_qty": qty,
        "reason": order.get("reason", ""),
    }


def _portfolio_payload(refresh=False):
    trading = _trading()
    engine = trading.engine
    watchlist_db = trading.db("etf_watchlist")
    cycle_db = trading.db("trading_cycle")

    items = []
    errors = []
    refreshed_at = _TIME.isoformat(with_offset=True)

    for item in _watchlist_rows(watchlist_db):
        symbol = _normalize_symbol(item.get("symbol"))
        if not symbol:
            continue

        exchange = _normalize_exchange(item.get("exchange"))
        cycle = _active_cycle(cycle_db, symbol)
        has_cycle = cycle is not None
        if not cycle:
            cycle = _virtual_cycle(item)

        price_data, resolved_exchange = _price_snapshot(trading, symbol, exchange, refresh=refresh)
        if resolved_exchange != exchange:
            try:
                watchlist_db.update({"exchange": resolved_exchange, "updated": _TIME.now()}, id=item["id"])
                exchange = resolved_exchange
            except Exception:
                pass

        current_price = _safe_float(price_data.get("price"), _safe_float(cycle.get("current_price"), 0))
        prev_close = _safe_float(price_data.get("prev_close"), current_price)
        price_error = price_data.get("error", "")
        if price_error:
            errors.append(f"{symbol}: {price_error}")

        if has_cycle and refresh and current_price > 0:
            try:
                engine.update_cycle_price(cycle["id"], current_price)
                cycle = cycle_db.get(id=cycle["id"]) or cycle
            except Exception as e:
                errors.append(f"{symbol}: 평가 갱신 실패 - {str(e)}")

        if current_price <= 0:
            current_price = _safe_float(cycle.get("current_price"), 0)
        if prev_close <= 0:
            prev_close = current_price

        buy_decision = {}
        if cycle.get("status") in ("ACTIVE", "READY"):
            buy_decision = _buy_plan(engine, cycle, prev_close)
        else:
            buy_decision = {
                "should_buy": False,
                "buy_amount": 0,
                "buy_orders": [],
                "reason": f"상태 {cycle.get('status')}는 신규 매수 대상 아님",
                "t_value": _safe_float(cycle.get("current_round"), 0),
            }

        buy_orders = [_normalize_order(order) for order in buy_decision.get("buy_orders", []) or []]
        try:
            raw_sell_orders = engine._firegate_v4_sell_orders(cycle) if hasattr(engine, "_firegate_v4_sell_orders") else []
        except Exception:
            raw_sell_orders = []
        if not raw_sell_orders:
            raw_sell_orders = _sell_plan(cycle, buy_decision)
        sell_orders = [_normalize_order(order) for order in raw_sell_orders]

        seed = _safe_float(cycle.get("total_investment"), _safe_float(item.get("total_investment"), 0))
        spent = _safe_float(cycle.get("total_spent"), 0)
        progress_pct = round((spent / seed * 100), 2) if seed > 0 else 0

        items.append({
            "id": item.get("id", ""),
            "symbol": symbol,
            "name": item.get("name") or symbol,
            "exchange": exchange,
            "cycle_id": cycle.get("id", ""),
            "cycle_number": cycle.get("cycle_number"),
            "status": cycle.get("status", "READY"),
            "has_cycle": has_cycle,
            "current_round": _safe_int(cycle.get("current_round"), 0),
            "division_count": max(_safe_int(cycle.get("division_count"), _safe_int(item.get("division_count"), 40)), 1),
            "target_profit": _safe_float(cycle.get("target_profit"), _safe_float(item.get("target_profit"), 10)),
            "total_investment": seed,
            "total_spent": spent,
            "remaining_investment": _safe_float(cycle.get("remaining_investment"), seed),
            "avg_price": _safe_float(cycle.get("avg_price"), 0),
            "total_qty": _safe_int(cycle.get("total_qty"), 0),
            "current_price": current_price,
            "prev_close": prev_close,
            "current_eval": _safe_float(cycle.get("current_eval"), 0),
            "profit_rate": _safe_float(cycle.get("profit_rate"), 0),
            "progress_pct": max(0, min(progress_pct, 1000)),
            "buy_amount": _safe_float(buy_decision.get("buy_amount"), 0),
            "state_name": buy_decision.get("state_name", ""),
            "t_value": _safe_float(buy_decision.get("t_value"), _safe_float(cycle.get("current_round"), 0)),
            "buy_reason": buy_decision.get("reason", ""),
            "should_buy": buy_decision.get("should_buy", False),
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "price_error": price_error,
            "updated": cycle.get("updated") or item.get("updated") or "",
        })

    return {
        "items": items,
        "errors": errors,
        "refreshed_at": refreshed_at,
        "fire_gate_url": _FIRE_GATE_URL,
        "fire_gate_login_mode": "external",
        "fire_gate_bridge": _public_bridge_config(_bridge_config()),
    }


def portfolio():
    try:
        refresh = _truthy(wiz.request.query("refresh", "false"))
        payload = _portfolio_payload(refresh=refresh)
        wiz.response.status(200, **payload)
    except Exception as e:
        if _is_response_exception(e):
            raise
        wiz.response.status(500, message=f"portfolio failed: {str(e)}", trace=traceback.format_exc())


def fire_gate_bridge_status():
    try:
        check = _truthy(wiz.request.query("check", "false"))
        cfg = _bridge_config()
        status = _public_bridge_config(cfg)
        status["connected"] = False
        status["portfolio_count"] = 0
        status["message"] = ""
        if check and status["configured"]:
            def _check(bridge, _cfg):
                portfolios = bridge.list_portfolios()
                return {"portfolio_count": len(portfolios or [])}
            try:
                result = _bridge_call(_check)
                status["connected"] = True
                status["portfolio_count"] = result.get("portfolio_count", 0)
            except Exception as e:
                status["message"] = str(e)
        wiz.response.status(200, **status)
    except Exception as e:
        if _is_response_exception(e):
            raise
        wiz.response.status(500, message=f"fire_gate_bridge_status failed: {str(e)}")


def save_fire_gate_bridge():
    try:
        existing = _bridge_config()
        id_token = str(wiz.request.query("id_token", "") or "").strip()
        refresh_token = str(wiz.request.query("refresh_token", "") or "").strip()
        email = str(wiz.request.query("email", "") or "").strip()
        enabled = _truthy(wiz.request.query("enabled", "true"))
        if not email and id_token:
            email = _jwt_payload(id_token).get("email", "")
        if not id_token:
            id_token = existing.get("id_token", "")
        if not refresh_token:
            refresh_token = existing.get("refresh_token", "")
        if not email:
            email = existing.get("email", "")
        if not email or (not id_token and not refresh_token):
            wiz.response.status(400, message="FireGate 브릿지 로그인 정보가 부족합니다.")
        cfg = _save_bridge_config({
            **existing,
            "enabled": enabled,
            "auto_sync_enabled": _truthy(wiz.request.query("auto_sync_enabled", str(existing.get("auto_sync_enabled", True)).lower())),
            "auto_sync_interval_sec": max(_safe_int(wiz.request.query("auto_sync_interval_sec", existing.get("auto_sync_interval_sec", 600)), 600), 30),
            "email": email,
            "id_token": id_token,
            "refresh_token": refresh_token,
        })
        try:
            trading = _trading()
            trading._ensure_background_worker()
            trading._worker_state()["force_run"] = True
            trading.__class__._worker_force_run = True
        except Exception:
            pass
        wiz.response.status(200, saved=True, **_public_bridge_config(cfg))
    except Exception as e:
        if _is_response_exception(e):
            raise
        wiz.response.status(500, message=f"save_fire_gate_bridge failed: {str(e)}", trace=traceback.format_exc())


def sync_fire_gate():
    try:
        trading = _trading()
        symbol = _normalize_symbol(wiz.request.query("symbol", ""))
        fg = _firegate_bridge_mod()
        sync_fn = getattr(fg, "sync_firegate_authoritative", None) or fg.sync_portfolios_to_local
        result = sync_fn(trading, symbol_filter=symbol)
        payload = _portfolio_payload(refresh=False)
        wiz.response.status(200, synced=True, result=result, **payload)
    except Exception as e:
        if _is_response_exception(e):
            raise
        wiz.response.status(500, message=f"sync_fire_gate failed: {str(e)}", trace=traceback.format_exc())


