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
_FIRE_GATE_PUSH_STATUSES = _ACTIVE_STATUSES + ("COMPLETED",)
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
        return watchlist_db.rows(is_active=True, orderby="created", order="ASC", dump=200) or []
    except Exception:
        try:
            return watchlist_db.rows(orderby="created", order="ASC", dump=200) or []
        except Exception:
            return []


def _active_cycle(cycle_db, symbol):
    for status in _ACTIVE_STATUSES:
        row = cycle_db.get(symbol=symbol, status=status)
        if row:
            return row
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


def _portfolio_symbol(portfolio):
    return _normalize_symbol((portfolio or {}).get("ticker") or (portfolio or {}).get("symbol"))


def _is_infinitystock_portfolio(portfolio):
    source = str((portfolio or {}).get("source", "") or "")
    group = str((portfolio or {}).get("portfolioGroup", "") or "")
    category = str((portfolio or {}).get("category", "") or "")
    return source == "infinitystock" or group == "InfinityStock Auto" or category == "infinite_buy"


def _parse_firegate_datetime(value, fallback=None):
    text = str(value or "").strip()
    if text == "":
        return fallback
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d",
        "%Y. %m. %d",
        "%Y.%m.%d",
        "%Y/%m/%d",
    ):
        try:
            return _TIME.to_kst(text) if hasattr(_TIME, "to_kst") else __import__("datetime").datetime.strptime(text, fmt)
        except Exception:
            try:
                return __import__("datetime").datetime.strptime(text, fmt)
            except Exception:
                pass
    return fallback


def _firegate_running(portfolio):
    return _truthy((portfolio or {}).get("isRunning", True))


def _latest_cycle(cycle_db, symbol):
    try:
        rows = cycle_db.rows(symbol=symbol, orderby="cycle_number", order="DESC", dump=1) or []
        if rows:
            return rows[0]
    except Exception:
        pass
    return None


def _local_filled_trade_state(trading, cycle_id):
    state = {"buy_rounds": 0, "qty": 0, "spent": 0.0}
    if not cycle_id:
        return state
    try:
        trade_db = trading.db("cycle_trade")
        rows = trade_db.rows(cycle_id=cycle_id, orderby="created", order="ASC", dump=1000) or []
    except Exception:
        return state
    qty = 0
    spent = 0.0
    buy_rounds = 0
    for row in rows:
        if str(row.get("status", "") or "").upper() != "FILLED":
            continue
        action = str(row.get("action", "") or "").upper()
        filled_qty = max(_safe_int(row.get("filled_qty"), 0), 0)
        filled_amount = max(_safe_float(row.get("filled_amount"), 0), 0.0)
        commission = max(_safe_float(row.get("commission"), 0), 0.0)
        if action == "BUY":
            qty += filled_qty
            spent += filled_amount + commission
            buy_rounds += 1
        elif action == "SELL":
            qty = max(0, qty - filled_qty)
            if qty == 0:
                spent = 0.0
    return {"buy_rounds": buy_rounds, "qty": qty, "spent": round(spent, 2)}


def _local_state_newer_than_firegate(trading, cycle, remote_round, remote_qty, remote_spent):
    if not cycle:
        return False
    trade_state = _local_filled_trade_state(trading, cycle.get("id"))
    if trade_state["buy_rounds"] > _safe_int(remote_round, 0):
        return True
    if trade_state["qty"] > _safe_int(remote_qty, 0):
        return True
    if trade_state["spent"] > _safe_float(remote_spent, 0) + 0.01:
        return True
    return False


def _next_cycle_number(cycle_db, symbol):
    try:
        rows = cycle_db.rows(symbol=symbol, orderby="cycle_number", order="DESC", dump=1) or []
        if rows:
            return _safe_int(rows[0].get("cycle_number"), 0) + 1
    except Exception:
        pass
    return 1


def _firegate_portfolio_to_watchlist(trading, portfolio):
    symbol = _portfolio_symbol(portfolio)
    if not symbol:
        return None
    watchlist_db = trading.db("etf_watchlist")
    seed = _safe_float((portfolio or {}).get("seed"), 0)
    division_count = max(_safe_int((portfolio or {}).get("divisionDate"), 20), 1)
    target_profit = _safe_float((portfolio or {}).get("targetProfit"), _sell_profit_pct(symbol))
    now = _TIME.now()
    data = {
        "symbol": symbol,
        "name": (portfolio or {}).get("nickname") or symbol,
        "exchange": "NASD",
        "total_investment": seed,
        "division_count": division_count,
        "target_profit": target_profit,
        "cycle_mode": "auto",
        "is_active": True,
        "memo": f"FireGate portfolio {portfolio.get('id', '')}",
        "updated": now,
    }
    existing = watchlist_db.get(symbol=symbol)
    if existing:
        watchlist_db.update(data, id=existing["id"])
        return "updated"
    watchlist_db.insert({**data, "created": now})
    return "created"


def _firegate_portfolio_to_cycle(trading, portfolio):
    symbol = _portfolio_symbol(portfolio)
    if not symbol:
        return None
    cycle_db = trading.db("trading_cycle")
    now = _TIME.now()
    is_running = _firegate_running(portfolio)
    active = _active_cycle(cycle_db, symbol)
    existing = active or _latest_cycle(cycle_db, symbol)
    seed = _safe_float((portfolio or {}).get("seed"), 0)
    division_count = max(_safe_int((portfolio or {}).get("divisionDate"), 20), 1)
    target_profit = _safe_float((portfolio or {}).get("targetProfit"), _sell_profit_pct(symbol))
    holding_qty = max(_safe_int((portfolio or {}).get("holdingQty"), 0), 0)
    avg_price = _safe_float((portfolio or {}).get("avgPrice"), 0)
    total_buy = _safe_float((portfolio or {}).get("totalBuy"), 0)
    total_sell = _safe_float((portfolio or {}).get("totalSell"), 0)
    t_value = _safe_float((portfolio or {}).get("tValue"), 0)
    total_spent = avg_price * holding_qty if holding_qty > 0 else 0
    remaining = max(seed - (total_buy - total_sell), 0)
    current_round = int(math.floor(max(t_value, 0)))
    started_at = _parse_firegate_datetime((portfolio or {}).get("startDate"), now)
    completed_at = _parse_firegate_datetime((portfolio or {}).get("endDate"), None if is_running else now)
    status = "ACTIVE" if is_running else "COMPLETED"
    data = {
        "symbol": symbol,
        "status": status,
        "current_round": current_round,
        "t_value": t_value,
        "division_count": division_count,
        "target_profit": target_profit,
        "total_investment": seed,
        "total_spent": round(total_spent, 2),
        "total_qty": holding_qty,
        "avg_price": round(avg_price, 4),
        "current_price": _safe_float((portfolio or {}).get("sellPrice"), 0),
        "current_eval": round(total_sell, 2) if is_running is False and total_sell > 0 else 0.0,
        "profit_rate": 0.0,
        "remaining_investment": round(remaining, 2) if is_running else 0.0,
        "started_at": started_at,
        "completed_at": completed_at if is_running is False else None,
        "updated": now,
    }
    if existing:
        cycle_db.update(data, id=existing["id"])
        return "updated"
    cycle_db.insert({
        **data,
        "cycle_number": _next_cycle_number(cycle_db, symbol),
        "total_commission": 0.0,
        "partial_sold_count": 0,
        "crash_buy_count": 0,
        "created": now,
    })
    return "created"


def _pull_firegate_to_local(bridge, trading):
    portfolios = bridge.list_portfolios()
    rows = [p for p in portfolios if _portfolio_symbol(p) and _is_infinitystock_portfolio(p)]
    watchlist_created = 0
    watchlist_updated = 0
    cycles_created = 0
    cycles_updated = 0
    for portfolio in rows:
        wl_result = _firegate_portfolio_to_watchlist(trading, portfolio)
        if wl_result == "created":
            watchlist_created += 1
        elif wl_result == "updated":
            watchlist_updated += 1
        cycle_result = _firegate_portfolio_to_cycle(trading, portfolio)
        if cycle_result == "created":
            cycles_created += 1
        elif cycle_result == "updated":
            cycles_updated += 1
    return {
        "firegate_portfolios": len(rows),
        "watchlist_created": watchlist_created,
        "watchlist_updated": watchlist_updated,
        "cycles_created": cycles_created,
        "cycles_updated": cycles_updated,
    }


def _cycle_rows_for_push(trading, symbol_filter=""):
    cycle_db = trading.db("trading_cycle")
    rows = []
    for status in _FIRE_GATE_PUSH_STATUSES:
        try:
            chunk = cycle_db.rows(status=status, orderby="updated", order="DESC", dump=300) or []
        except Exception:
            chunk = []
        rows.extend(chunk)
    symbol_filter = _normalize_symbol(symbol_filter)
    if symbol_filter:
        rows = [row for row in rows if _normalize_symbol(row.get("symbol")) == symbol_filter]
    seen = set()
    unique = []
    for row in rows:
        row_id = row.get("id")
        if row_id in seen:
            continue
        seen.add(row_id)
        unique.append(row)
    return unique


def _local_rows_for_push(trading, symbol_filter=""):
    rows = _cycle_rows_for_push(trading, symbol_filter=symbol_filter)
    seen = {_normalize_symbol(row.get("symbol")) for row in rows if _normalize_symbol(row.get("symbol"))}
    watchlist_db = trading.db("etf_watchlist")
    symbol_filter = _normalize_symbol(symbol_filter)
    for item in _watchlist_rows(watchlist_db):
        symbol = _normalize_symbol(item.get("symbol"))
        if not symbol or symbol in seen:
            continue
        if symbol_filter and symbol != symbol_filter:
            continue
        rows.append(_virtual_cycle(item))
        seen.add(symbol)
    return rows


def _push_local_to_firegate(bridge, trading, symbol_filter=""):
    fg = _firegate_bridge_mod()
    trade_db = trading.db("cycle_trade")
    pushed_portfolios = 0
    created_portfolios = 0
    pushed_trades = 0
    skipped_trades = 0
    errors = []
    source_rows = _local_rows_for_push(trading, symbol_filter=symbol_filter)
    for cycle in source_rows:
        symbol = _normalize_symbol(cycle.get("symbol"))
        if not symbol:
            continue
        try:
            seed = _safe_float(cycle.get("total_investment"), 0)
            division_count = max(_safe_int(cycle.get("division_count"), 20), 1)
            target_profit = _safe_float(cycle.get("target_profit"), _sell_profit_pct(symbol))
            source = getattr(fg, "INFINITYSTOCK_SOURCE", "infinitystock")
            portfolio_group = getattr(fg, "INFINITYSTOCK_PORTFOLIO_GROUP", "InfinityStock Auto")
            portfolio_category = getattr(fg, "INFINITYSTOCK_PORTFOLIO_CATEGORY", "infinite_buy")
            source_cycle_id = (
                fg.infinitystock_source_cycle_id(cycle, symbol)
                if hasattr(fg, "infinitystock_source_cycle_id")
                else str(cycle.get("id", "") or f"{symbol}:ready")
            )
            nickname = (
                fg.infinitystock_portfolio_nickname(symbol, cycle)
                if hasattr(fg, "infinitystock_portfolio_nickname")
                else f"{portfolio_group} | {symbol}"
            )
            portfolio, created = bridge.ensure_v4_portfolio(
                symbol,
                seed,
                division_count=division_count,
                target_profit=target_profit,
                nickname=nickname,
                cycle=cycle,
                include_state=False,
                source=source,
                source_cycle_id=source_cycle_id,
                portfolio_group=portfolio_group,
                portfolio_category=portfolio_category,
            )
            pushed_portfolios += 1
            if created:
                created_portfolios += 1

            existing_transactions = bridge.list_transactions(portfolio.get("id"))
            synced_trade_ids = {
                str(tx.get("sourceTradeId", ""))
                for tx in existing_transactions
                if str(tx.get("source", "")) == "infinitystock"
            }
            trades = trade_db.rows(cycle_id=cycle.get("id"), orderby="created", order="ASC", dump=1000) or []
            cycle_pushed_trades = 0
            for trade in trades:
                trade_id = str(trade.get("id", ""))
                if trade_id in synced_trade_ids:
                    skipped_trades += 1
                    continue
                if str(trade.get("status", "")).upper() != "FILLED":
                    skipped_trades += 1
                    continue
                tx = fg.transaction_from_cycle_trade(trade, portfolio.get("id"), portfolio=portfolio)
                if not tx:
                    skipped_trades += 1
                    continue
                _, portfolio = bridge.add_transaction_and_update_portfolio(portfolio, tx)
                pushed_trades += 1
                cycle_pushed_trades += 1

            if created and cycle_pushed_trades == 0 and _safe_int(cycle.get("total_qty"), 0) > 0:
                snapshot = fg.build_v4_portfolio(
                    symbol,
                    seed,
                    division_count=division_count,
                    target_profit=target_profit,
                    nickname=nickname,
                    cycle=cycle,
                    include_state=True,
                    source=source,
                    source_cycle_id=source_cycle_id,
                    portfolio_group=portfolio_group,
                    portfolio_category=portfolio_category,
                )
                bridge.update_portfolio(portfolio.get("id"), snapshot)
        except Exception as e:
            errors.append(f"{symbol}: {str(e)}")
    return {
        "source_portfolios": len(source_rows),
        "pushed_portfolios": pushed_portfolios,
        "created_portfolios": created_portfolios,
        "pushed_trades": pushed_trades,
        "skipped_trades": skipped_trades,
        "errors": errors,
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


def refresh_prices():
    try:
        payload = _portfolio_payload(refresh=True)
        wiz.response.status(200, **payload)
    except Exception as e:
        if _is_response_exception(e):
            raise
        wiz.response.status(500, message=f"refresh_prices failed: {str(e)}")


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


def pull_fire_gate_portfolios():
    try:
        trading = _trading()
        fg = _firegate_bridge_mod()
        result = fg.sync_portfolios_to_local(trading)
        payload = _portfolio_payload(refresh=False)
        wiz.response.status(200, pulled=True, synced=True, result=result, **payload)
    except Exception as e:
        if _is_response_exception(e):
            raise
        wiz.response.status(500, message=f"pull_fire_gate_portfolios failed: {str(e)}", trace=traceback.format_exc())


def push_fire_gate_sync():
    try:
        trading = _trading()
        symbol = _normalize_symbol(wiz.request.query("symbol", ""))
        fg = _firegate_bridge_mod()
        sync_fn = getattr(fg, "sync_local_to_firegate", None)
        if sync_fn:
            result = sync_fn(trading, symbol_filter=symbol)
        else:
            result = _bridge_call(lambda bridge, _cfg: _push_local_to_firegate(bridge, trading, symbol_filter=symbol))
        payload = _portfolio_payload(refresh=False)
        wiz.response.status(200, pushed=True, synced=True, result=result, **payload)
    except Exception as e:
        if _is_response_exception(e):
            raise
        wiz.response.status(500, message=f"push_fire_gate_sync failed: {str(e)}", trace=traceback.format_exc())


def save_symbol():
    try:
        symbol = _normalize_symbol(wiz.request.query("symbol", ""))
        if not symbol:
            wiz.response.status(400, message="종목코드를 입력해주세요.")

        name = str(wiz.request.query("name", "") or "").strip() or symbol
        exchange = _normalize_exchange(wiz.request.query("exchange", "NASD"))
        seed = _safe_float(wiz.request.query("total_investment", wiz.request.query("seed", "0")), 0)
        division_count = max(_safe_int(wiz.request.query("division_count", "40"), 40), 1)
        target_profit = _safe_float(wiz.request.query("target_profit", "10"), 10)
        start = _truthy(wiz.request.query("start_cycle", "false"))

        if seed <= 0:
            wiz.response.status(400, message="시드는 0보다 커야 합니다.")

        trading = _trading()
        watchlist_db = trading.db("etf_watchlist")
        existing = watchlist_db.get(symbol=symbol)
        now = _TIME.now()
        data = {
            "symbol": symbol,
            "name": name,
            "exchange": exchange,
            "total_investment": seed,
            "division_count": division_count,
            "target_profit": target_profit,
            "cycle_mode": "auto",
            "is_active": True,
            "updated": now,
        }
        if existing:
            watchlist_db.update(data, id=existing["id"])
        else:
            watchlist_db.insert({**data, "created": now})

        started = None
        start_error = ""
        if start:
            try:
                started = trading.engine.start_cycle(symbol, seed, division_count, target_profit)
            except Exception as e:
                start_error = str(e)

        payload = _portfolio_payload(refresh=False)
        wiz.response.status(200, saved=True, started=started, start_error=start_error, **payload)
    except Exception as e:
        if _is_response_exception(e):
            raise
        wiz.response.status(500, message=f"save_symbol failed: {str(e)}", trace=traceback.format_exc())


def start_symbol_cycle():
    try:
        symbol = _normalize_symbol(wiz.request.query("symbol", ""))
        if not symbol:
            wiz.response.status(400, message="종목코드를 입력해주세요.")

        trading = _trading()
        watchlist_db = trading.db("etf_watchlist")
        item = watchlist_db.get(symbol=symbol, is_active=True)
        if not item:
            wiz.response.status(404, message=f"{symbol} 워치리스트가 없습니다.")

        seed = _safe_float(wiz.request.query("total_investment", item.get("total_investment")), _safe_float(item.get("total_investment"), 0))
        division_count = max(_safe_int(wiz.request.query("division_count", item.get("division_count")), _safe_int(item.get("division_count"), 40)), 1)
        target_profit = _safe_float(wiz.request.query("target_profit", item.get("target_profit")), _safe_float(item.get("target_profit"), 10))
        cycle = trading.engine.start_cycle(symbol, seed, division_count, target_profit)

        payload = _portfolio_payload(refresh=False)
        wiz.response.status(200, started=cycle, **payload)
    except Exception as e:
        if _is_response_exception(e):
            raise
        wiz.response.status(500, message=f"start_symbol_cycle failed: {str(e)}", trace=traceback.format_exc())


def fire_gate_link():
    wiz.response.status(200, url=_FIRE_GATE_URL, login_mode="external", fire_gate_bridge=_public_bridge_config(_bridge_config()))
