import copy
import datetime
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request


FIRE_GATE_API_KEY = "AIzaSyB1hnlSuxJwlx5Xq9O9mj7gf33Me8F4-Mw"
FIRE_GATE_PROJECT_ID = "fire-gate-6add2"
FIRE_GATE_BRIDGE_CONFIG_KEY = "fire_gate_bridge"
FIRESTORE_ROOT = (
    "https://firestore.googleapis.com/v1/projects/"
    f"{FIRE_GATE_PROJECT_ID}/databases/(default)/documents"
)
FIRE_GATE_WATCHLIST_MEMO_PREFIX = "FireGate portfolio "
INFINITYSTOCK_SOURCE = "infinitystock"
INFINITYSTOCK_PORTFOLIO_GROUP = "InfinityStock Auto"
INFINITYSTOCK_PORTFOLIO_CATEGORY = "infinite_buy"


class FireGateBridgeError(Exception):
    pass


class FireGateAuthError(FireGateBridgeError):
    pass


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return float(default)
        text = str(value).replace(",", "").strip()
        if text == "":
            return float(default)
        return float(text)
    except Exception:
        return float(default)


def _safe_int(value, default=0):
    try:
        if value is None:
            return int(default)
        text = str(value).replace(",", "").strip()
        if text == "":
            return int(default)
        return int(float(text))
    except Exception:
        try:
            return int(default)
        except Exception:
            return 0


def _round2(value):
    return math.floor(_safe_float(value) * 100 + 0.5) / 100


def _jwt_payload(token):
    try:
        parts = str(token or "").split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(__import__("base64").urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8"))
    except Exception:
        return {}


def _id_token_expired_or_stale(id_token, grace_sec=300):
    payload = _jwt_payload(id_token)
    exp = _safe_int(payload.get("exp"), 0)
    if exp <= 0:
        return False
    return exp <= int(time.time()) + max(_safe_int(grace_sec, 300), 0)


def _millis():
    return int(time.time() * 1000)


def format_updated_at(now=None):
    now = now or datetime.datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")


def format_firegate_date(value=None):
    if value is None:
        value = datetime.date.today()
    if isinstance(value, datetime.datetime):
        value = value.date()
    if isinstance(value, datetime.date):
        return value.strftime("%Y. %m. %d")
    text = str(value or "").strip()
    if not text:
        return datetime.date.today().strftime("%Y. %m. %d")
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y. %m. %d", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(text, fmt).strftime("%Y. %m. %d")
        except Exception:
            pass
    return text


def _firestore_value(value):
    if value is None:
        return {"nullValue": "NULL_VALUE"}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [_firestore_value(v) for v in value]}}
    if isinstance(value, dict):
        return {"mapValue": {"fields": _firestore_fields(value)}}
    return {"stringValue": str(value)}


def _firestore_fields(data):
    return {str(key): _firestore_value(value) for key, value in (data or {}).items()}


def firestore_document(data):
    return {"fields": _firestore_fields(data)}


def _decode_value(value):
    if not isinstance(value, dict):
        return value
    if "nullValue" in value:
        return None
    if "booleanValue" in value:
        return bool(value.get("booleanValue"))
    if "integerValue" in value:
        return _safe_int(value.get("integerValue"), 0)
    if "doubleValue" in value:
        return _safe_float(value.get("doubleValue"), 0)
    if "stringValue" in value:
        return value.get("stringValue", "")
    if "timestampValue" in value:
        return value.get("timestampValue", "")
    if "arrayValue" in value:
        arr = value.get("arrayValue", {}).get("values", []) or []
        return [_decode_value(v) for v in arr]
    if "mapValue" in value:
        return decode_firestore_document({"fields": value.get("mapValue", {}).get("fields", {})})
    return value


def decode_firestore_document(document):
    fields = (document or {}).get("fields", {}) or {}
    data = {key: _decode_value(value) for key, value in fields.items()}
    name = (document or {}).get("name", "")
    if name:
        data["_doc_name"] = name
        data["_doc_id"] = name.rsplit("/", 1)[-1]
        data.setdefault("id", data["_doc_id"])
    return data


def refresh_id_token(refresh_token):
    token = str(refresh_token or "").strip()
    if not token:
        raise FireGateAuthError("FireGate refresh token is missing.")
    url = f"https://securetoken.googleapis.com/v1/token?key={FIRE_GATE_API_KEY}"
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": token,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise FireGateAuthError(f"FireGate token refresh failed: {e.code} {detail}")


def _with_api_key(params=None):
    payload = dict(params or {})
    payload.setdefault("key", FIRE_GATE_API_KEY)
    return payload


def load_bridge_config(struct):
    raw = "{}"
    try:
        raw = struct.get_config(FIRE_GATE_BRIDGE_CONFIG_KEY, "{}")
    except Exception:
        try:
            row = struct.db("trading_config").get(key=FIRE_GATE_BRIDGE_CONFIG_KEY)
            raw = row.get("value", "{}") if row else "{}"
        except Exception:
            raw = "{}"
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
    return cfg


def save_bridge_config(struct, cfg):
    cfg = dict(cfg or {})
    cfg["enabled"] = bool(cfg.get("enabled"))
    cfg["auto_sync_enabled"] = bool(cfg.get("auto_sync_enabled", True))
    cfg["auto_sync_interval_sec"] = max(_safe_int(cfg.get("auto_sync_interval_sec", 600), 600), 30)
    try:
        struct.set_config(
            FIRE_GATE_BRIDGE_CONFIG_KEY,
            json.dumps(cfg, ensure_ascii=False),
            description="FireGate Firebase bridge session",
            is_secret=True,
        )
    except Exception:
        pass
    return cfg


def bridge_from_config(struct):
    cfg = load_bridge_config(struct)
    if not cfg.get("enabled") or not cfg.get("email"):
        return None, cfg
    if cfg.get("refresh_token") and (not cfg.get("id_token") or _id_token_expired_or_stale(cfg.get("id_token"))):
        data = refresh_id_token(cfg.get("refresh_token"))
        cfg["id_token"] = data.get("id_token") or data.get("idToken") or cfg.get("id_token", "")
        cfg["refresh_token"] = data.get("refresh_token") or data.get("refreshToken") or cfg.get("refresh_token", "")
        save_bridge_config(struct, cfg)
    if not cfg.get("id_token"):
        return None, cfg
    return FireGateBridge(cfg.get("email"), cfg.get("id_token")), cfg


def _bridge_call_from_config(struct, fn):
    bridge, cfg = bridge_from_config(struct)
    if bridge is None:
        return None
    try:
        return fn(bridge, cfg)
    except FireGateAuthError:
        if not cfg.get("refresh_token"):
            raise
        data = refresh_id_token(cfg.get("refresh_token"))
        cfg["id_token"] = data.get("id_token") or data.get("idToken") or cfg.get("id_token", "")
        cfg["refresh_token"] = data.get("refresh_token") or data.get("refreshToken") or cfg.get("refresh_token", "")
        save_bridge_config(struct, cfg)
        bridge = FireGateBridge(cfg.get("email"), cfg.get("id_token"))
        return fn(bridge, cfg)


def _reverse_factor(division_count):
    division_count = _safe_int(division_count, 20)
    if division_count == 20:
        return 0.9
    if division_count == 30:
        return 28 / 30
    return 0.95


def _normalize_symbol(symbol):
    return "".join(ch for ch in str(symbol or "").upper().strip() if ch.isalnum() or ch in ".-")


def _cycle_t_value(cycle):
    if not cycle:
        return 0.0
    return _safe_float(cycle.get("t_value", cycle.get("current_round", 0)), 0)


_ACTIVE_CYCLE_STATUSES = ("ACTIVE", "HOLDING", "PAUSED", "PENDING_EXTENSION")
_FIRE_GATE_PUSH_STATUSES = _ACTIVE_CYCLE_STATUSES + ("COMPLETED",)


def _portfolio_symbol(portfolio):
    return _normalize_symbol((portfolio or {}).get("ticker") or (portfolio or {}).get("symbol"))


def _portfolio_source(portfolio):
    return str((portfolio or {}).get("source", "") or "")


def _is_infinitystock_portfolio(portfolio):
    if _portfolio_source(portfolio) == INFINITYSTOCK_SOURCE:
        return True
    if str((portfolio or {}).get("portfolioGroup", "") or "") == INFINITYSTOCK_PORTFOLIO_GROUP:
        return True
    if str((portfolio or {}).get("category", "") or "") == INFINITYSTOCK_PORTFOLIO_CATEGORY:
        return True
    return False


def default_target_profit(symbol):
    return 15.0 if _normalize_symbol(symbol) == "TQQQ" else 20.0


def infinitystock_source_cycle_id(cycle, symbol=""):
    cycle = cycle or {}
    cycle_id = str(cycle.get("id", "") or "").strip()
    if cycle_id:
        return cycle_id
    symbol = _normalize_symbol(symbol or cycle.get("symbol"))
    cycle_number = _safe_int(cycle.get("cycle_number"), 0)
    if symbol and cycle_number > 0:
        return f"{symbol}:cycle:{cycle_number}"
    if symbol:
        return f"{symbol}:ready"
    return ""


def infinitystock_portfolio_nickname(symbol, cycle=None):
    symbol = _normalize_symbol(symbol)
    cycle_number = _safe_int((cycle or {}).get("cycle_number"), 0)
    suffix = f"Cycle {cycle_number}" if cycle_number > 0 else "Ready"
    if symbol:
        return f"{INFINITYSTOCK_PORTFOLIO_GROUP} | {symbol} | {suffix}"
    return f"{INFINITYSTOCK_PORTFOLIO_GROUP} | {suffix}"


def _select_pull_portfolios(portfolios, symbol_filter=""):
    symbol_filter = _normalize_symbol(symbol_filter)
    rows = []
    seen = set()
    for item in portfolios or []:
        symbol = _portfolio_symbol(item)
        if not symbol:
            continue
        if symbol_filter and symbol != symbol_filter:
            continue
        if _is_infinitystock_portfolio(item) is False:
            continue
        key = str(item.get("sourceCycleId", "") or item.get("id", "") or f"{symbol}:{len(rows)}")
        if key in seen:
            continue
        seen.add(key)
        rows.append(item)
    rows.sort(key=lambda item: (
        _portfolio_symbol(item),
        0 if item.get("isRunning", True) else 1,
        str(item.get("sourceCycleId", "") or item.get("id", "")),
    ))
    return rows


def _parse_firegate_datetime(value, fallback=None):
    if value in (None, ""):
        return fallback
    if isinstance(value, datetime.datetime):
        return value
    text = str(value).strip()
    if not text:
        return fallback
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y. %m. %d",
    ):
        try:
            return datetime.datetime.strptime(text, fmt)
        except Exception:
            pass
    return fallback


def _firegate_running(portfolio):
    return bool((portfolio or {}).get("isRunning", False))


def _active_cycle(cycle_db, symbol):
    for status in _ACTIVE_CYCLE_STATUSES:
        row = cycle_db.get(symbol=symbol, status=status)
        if row:
            return row
    return None


def _latest_cycle(cycle_db, symbol):
    try:
        rows = cycle_db.rows(symbol=symbol, orderby="created", order="DESC", dump=1) or []
        return rows[0] if rows else None
    except Exception:
        return None


def _watchlist_from_portfolio(trading, portfolio):
    symbol = _portfolio_symbol(portfolio)
    if not symbol:
        return None
    watchlist_db = trading.db("etf_watchlist")
    now = datetime.datetime.now()
    data = {
        "symbol": symbol,
        "name": (portfolio or {}).get("nickname") or symbol,
        "exchange": "NASD",
        "total_investment": _safe_float((portfolio or {}).get("seed"), 0),
        "division_count": max(_safe_int((portfolio or {}).get("divisionDate"), 20), 1),
        "target_profit": _safe_float((portfolio or {}).get("targetProfit"), 10),
        "cycle_mode": "auto",
        "is_active": True,
        "memo": f"{FIRE_GATE_WATCHLIST_MEMO_PREFIX}{portfolio.get('id', '')}",
        "updated": now,
    }
    existing = watchlist_db.get(symbol=symbol)
    if existing:
        watchlist_db.update(data, id=existing["id"])
        return "updated"
    watchlist_db.insert({**data, "created": now})
    return "created"


def _cycle_status_from_portfolio(portfolio, holding_qty=0, total_buy=0.0, total_sell=0.0):
    if _firegate_running(portfolio):
        return "ACTIVE"
    if holding_qty > 0:
        return "PAUSED"
    end_date = str((portfolio or {}).get("endDate", "") or "").strip()
    if end_date and total_sell > 0 and total_sell + 0.01 >= total_buy:
        return "COMPLETED"
    return "PAUSED"


def _cycle_from_portfolio(trading, portfolio):
    symbol = _portfolio_symbol(portfolio)
    if not symbol:
        return None
    cycle_db = trading.db("trading_cycle")
    now = datetime.datetime.now()
    active = _active_cycle(cycle_db, symbol)
    existing = active or _latest_cycle(cycle_db, symbol)
    seed = _safe_float((portfolio or {}).get("seed"), 0)
    division_count = max(_safe_int((portfolio or {}).get("divisionDate"), 20), 1)
    target_profit = _safe_float((portfolio or {}).get("targetProfit"), 10)
    holding_qty = max(_safe_int((portfolio or {}).get("holdingQty"), 0), 0)
    avg_price = _safe_float((portfolio or {}).get("avgPrice"), 0)
    total_buy = _safe_float((portfolio or {}).get("totalBuy"), 0)
    total_sell = _safe_float((portfolio or {}).get("totalSell"), 0)
    t_value = _safe_float((portfolio or {}).get("tValue"), 0)
    total_spent = avg_price * holding_qty if holding_qty > 0 else max(total_buy - total_sell, 0)
    remaining = max(seed - max(total_buy - total_sell, 0), 0)
    current_round = int(math.floor(max(t_value, 0)))
    status = _cycle_status_from_portfolio(portfolio, holding_qty=holding_qty, total_buy=total_buy, total_sell=total_sell)
    started_at = _parse_firegate_datetime((portfolio or {}).get("startDate"), now)
    completed_at = _parse_firegate_datetime((portfolio or {}).get("endDate"), now if status == "COMPLETED" else None)
    current_price = _safe_float((portfolio or {}).get("sellPrice"), 0)
    current_eval = round(holding_qty * current_price, 2) if holding_qty > 0 and current_price > 0 else round(total_sell, 2)
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
        "current_price": current_price,
        "current_eval": current_eval,
        "profit_rate": 0.0,
        "remaining_investment": round(remaining, 2) if status != "COMPLETED" else 0.0,
        "started_at": started_at,
        "completed_at": completed_at,
        "updated": now,
    }
    if existing:
        cycle_db.update(data, id=existing["id"])
        return "updated"
    cycle_number = 1
    try:
        rows = cycle_db.rows(symbol=symbol, orderby="cycle_number", order="DESC", dump=1) or []
        if rows:
            cycle_number = max(_safe_int(rows[0].get("cycle_number"), 0), 0) + 1
    except Exception:
        cycle_number = 1
    cycle_db.insert({
        **data,
        "cycle_number": cycle_number,
        "total_commission": 0.0,
        "partial_sold_count": 0,
        "crash_buy_count": 0,
        "created": now,
    })
    return "created"


def _cleanup_removed_portfolios(trading, remote_symbols, symbol_filter=""):
    remote_symbols = {_normalize_symbol(symbol) for symbol in (remote_symbols or []) if _normalize_symbol(symbol)}
    symbol_filter = _normalize_symbol(symbol_filter)
    now = datetime.datetime.now()
    watchlist_db = trading.db("etf_watchlist")
    cycle_db = trading.db("trading_cycle")
    removed_watchlists = 0
    removed_cycles = 0
    removed_symbols = []

    managed_symbols = set()
    try:
        watch_rows = watchlist_db.rows(dump=500) or []
    except Exception:
        watch_rows = []
    for row in watch_rows:
        symbol = _normalize_symbol(row.get("symbol"))
        memo = str(row.get("memo", "") or "")
        if not symbol:
            continue
        if symbol_filter and symbol != symbol_filter:
            continue
        if memo.startswith(FIRE_GATE_WATCHLIST_MEMO_PREFIX):
            managed_symbols.add(symbol)

    stale_symbols = sorted([symbol for symbol in managed_symbols if symbol and symbol not in remote_symbols])
    for symbol in stale_symbols:
        removed_symbols.append(symbol)
        try:
            rows = watchlist_db.rows(symbol=symbol, dump=50) or []
        except Exception:
            rows = []
        for row in rows:
            memo = str(row.get("memo", "") or "")
            if symbol_filter or memo.startswith(FIRE_GATE_WATCHLIST_MEMO_PREFIX):
                try:
                    watchlist_db.delete(id=row.get("id"))
                    removed_watchlists += 1
                except Exception:
                    pass
        try:
            cycle_rows = cycle_db.rows(symbol=symbol, dump=200) or []
        except Exception:
            cycle_rows = []
        for row in cycle_rows:
            status = str(row.get("status", "") or "").upper()
            if status == "COMPLETED":
                continue
            try:
                cycle_db.update({
                    "status": "COMPLETED",
                    "remaining_investment": 0.0,
                    "completed_at": now,
                    "updated": now,
                }, id=row.get("id"))
                removed_cycles += 1
            except Exception:
                pass

    return {
        "removed_watchlists": removed_watchlists,
        "archived_cycles": removed_cycles,
        "removed_symbols": removed_symbols,
    }


def sync_portfolios_to_local(struct, symbol_filter=""):
    symbol_filter = _normalize_symbol(symbol_filter)

    def _sync(bridge, _cfg):
        portfolios = bridge.list_portfolios() or []
        rows = _select_pull_portfolios(portfolios, symbol_filter=symbol_filter)

        watchlist_created = 0
        watchlist_updated = 0
        cycles_created = 0
        cycles_updated = 0
        symbols = []
        for portfolio in rows:
            symbol = _portfolio_symbol(portfolio)
            if symbol:
                symbols.append(symbol)
            wl_result = _watchlist_from_portfolio(struct, portfolio)
            if wl_result == "created":
                watchlist_created += 1
            elif wl_result == "updated":
                watchlist_updated += 1
            cycle_result = _cycle_from_portfolio(struct, portfolio)
            if cycle_result == "created":
                cycles_created += 1
            elif cycle_result == "updated":
                cycles_updated += 1

        cleanup = _cleanup_removed_portfolios(struct, symbols, symbol_filter=symbol_filter)

        return {
            "executed": True,
            "mode": "firegate_pull_authoritative",
            "message": f"FireGate 포트폴리오 {len(rows)}건을 로컬 사이클/워치리스트에 반영했습니다.",
            "firegate_portfolios": len(rows),
            "watchlist_created": watchlist_created,
            "watchlist_updated": watchlist_updated,
            "cycles_created": cycles_created,
            "cycles_updated": cycles_updated,
            "removed_watchlists": cleanup.get("removed_watchlists", 0),
            "archived_cycles": cleanup.get("archived_cycles", 0),
            "synced_symbols": symbols,
            "removed_symbols": cleanup.get("removed_symbols", []),
        }

    result = _bridge_call_from_config(struct, _sync)
    if result is None:
        return {
            "executed": False,
            "mode": "firegate_pull_authoritative",
            "message": "FireGate 브릿지가 설정되지 않았습니다.",
            "firegate_portfolios": 0,
            "watchlist_created": 0,
            "watchlist_updated": 0,
            "cycles_created": 0,
            "cycles_updated": 0,
            "removed_watchlists": 0,
            "archived_cycles": 0,
            "synced_symbols": [],
            "removed_symbols": [],
        }
    return result


def _watchlist_rows(watchlist_db):
    try:
        return watchlist_db.rows(is_active=True, orderby="created", order="ASC", dump=500) or []
    except Exception:
        try:
            return watchlist_db.rows(orderby="created", order="ASC", dump=500) or []
        except Exception:
            return []


def _virtual_cycle(item):
    seed = _safe_float((item or {}).get("total_investment"), 0)
    return {
        "id": "",
        "symbol": _normalize_symbol((item or {}).get("symbol")),
        "cycle_number": None,
        "status": "READY",
        "current_round": 0,
        "division_count": max(_safe_int((item or {}).get("division_count"), 20), 1),
        "target_profit": _safe_float((item or {}).get("target_profit"), 10),
        "total_investment": seed,
        "total_spent": 0.0,
        "total_qty": 0,
        "avg_price": 0.0,
        "current_price": 0.0,
        "current_eval": 0.0,
        "profit_rate": 0.0,
        "remaining_investment": seed,
    }


def _cycle_rows_for_push(trading, symbol_filter=""):
    cycle_db = trading.db("trading_cycle")
    rows = []
    for status in _FIRE_GATE_PUSH_STATUSES:
        try:
            chunk = cycle_db.rows(status=status, orderby="updated", order="DESC", dump=500) or []
        except Exception:
            chunk = []
        rows.extend(chunk)
    symbol_filter = _normalize_symbol(symbol_filter)
    if symbol_filter:
        rows = [row for row in rows if _normalize_symbol(row.get("symbol")) == symbol_filter]
    seen = set()
    unique = []
    for row in rows:
        row_id = row.get("id") or f"{_normalize_symbol(row.get('symbol'))}:{row.get('cycle_number', '')}"
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
            target_profit = _safe_float(cycle.get("target_profit"), default_target_profit(symbol))
            source_cycle_id = infinitystock_source_cycle_id(cycle, symbol)
            portfolio, created = bridge.ensure_v4_portfolio(
                symbol,
                seed,
                division_count=division_count,
                target_profit=target_profit,
                nickname=infinitystock_portfolio_nickname(symbol, cycle),
                cycle=cycle,
                include_state=False,
                source=INFINITYSTOCK_SOURCE,
                source_cycle_id=source_cycle_id,
                portfolio_group=INFINITYSTOCK_PORTFOLIO_GROUP,
                portfolio_category=INFINITYSTOCK_PORTFOLIO_CATEGORY,
            )
            pushed_portfolios += 1
            if created:
                created_portfolios += 1

            existing_transactions = bridge.list_transactions(portfolio.get("id"))
            synced_trade_ids = {
                str(tx.get("sourceTradeId", ""))
                for tx in existing_transactions
                if str(tx.get("source", "")) == INFINITYSTOCK_SOURCE
            }
            try:
                trades = trade_db.rows(cycle_id=cycle.get("id"), orderby="created", order="ASC", dump=1000) or []
            except Exception:
                trades = []
            cycle_pushed_trades = 0
            for trade in trades:
                trade_id = str(trade.get("id", ""))
                if trade_id in synced_trade_ids:
                    skipped_trades += 1
                    continue
                if str(trade.get("status", "")).upper() != "FILLED":
                    skipped_trades += 1
                    continue
                tx = transaction_from_cycle_trade(trade, portfolio.get("id"), portfolio=portfolio)
                if not tx:
                    skipped_trades += 1
                    continue
                _, portfolio = bridge.add_transaction_and_update_portfolio(portfolio, tx)
                pushed_trades += 1
                cycle_pushed_trades += 1

            if created and cycle_pushed_trades == 0 and _safe_int(cycle.get("total_qty"), 0) > 0:
                snapshot = build_v4_portfolio(
                    symbol,
                    seed,
                    division_count=division_count,
                    target_profit=target_profit,
                    nickname=infinitystock_portfolio_nickname(symbol, cycle),
                    cycle=cycle,
                    include_state=True,
                    source=INFINITYSTOCK_SOURCE,
                    source_cycle_id=source_cycle_id,
                    portfolio_group=INFINITYSTOCK_PORTFOLIO_GROUP,
                    portfolio_category=INFINITYSTOCK_PORTFOLIO_CATEGORY,
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


def sync_local_to_firegate(struct, symbol_filter=""):
    symbol_filter = _normalize_symbol(symbol_filter)

    def _sync(bridge, _cfg):
        pushed = _push_local_to_firegate(bridge, struct, symbol_filter=symbol_filter)
        return {
            "executed": True,
            "mode": "local_push_authoritative",
            "message": f"로컬 무한매수 포트폴리오 {pushed.get('pushed_portfolios', 0)}건을 FireGate에 반영했습니다.",
            **pushed,
        }

    result = _bridge_call_from_config(struct, _sync)
    if result is None:
        return {
            "executed": False,
            "mode": "local_push_authoritative",
            "message": "FireGate 브릿지가 설정되지 않았습니다.",
            "source_portfolios": 0,
            "pushed_portfolios": 0,
            "created_portfolios": 0,
            "pushed_trades": 0,
            "skipped_trades": 0,
            "errors": [],
        }
    return result


def sync_portfolios_bidirectional(struct, symbol_filter=""):
    push = sync_local_to_firegate(struct, symbol_filter=symbol_filter)
    pull = sync_portfolios_to_local(struct, symbol_filter=symbol_filter)
    executed = bool(push.get("executed") or pull.get("executed"))
    errors = list(push.get("errors", []) or [])
    return {
        **(pull or {}),
        "executed": executed,
        "mode": "bidirectional",
        "message": (
            f"FireGate 양방향 동기화 완료: 푸시 {push.get('pushed_portfolios', 0)}건, "
            f"풀 {pull.get('firegate_portfolios', 0)}건"
        ),
        "push": push,
        "pull": pull,
        "pushed_portfolios": push.get("pushed_portfolios", 0),
        "created_portfolios": push.get("created_portfolios", 0),
        "pushed_trades": push.get("pushed_trades", 0),
        "skipped_trades": push.get("skipped_trades", 0),
        "errors": errors + list((pull or {}).get("errors", []) or []),
    }


def build_v4_portfolio(
    symbol,
    seed,
    division_count=20,
    target_profit=15,
    nickname="",
    commission_rate=0,
    cycle=None,
    include_state=True,
    source="",
    source_cycle_id="",
    portfolio_group="",
    portfolio_category="",
):
    symbol = _normalize_symbol(symbol)
    seed = _safe_float(seed, 0)
    division_count = max(_safe_int(division_count, 20), 1)
    target_profit = _safe_float(target_profit, 15)
    now_id = _millis()

    holding_qty = 0
    avg_price = 0.0
    total_buy = 0.0
    total_sell = 0.0
    t_value = 0.0
    reverse_mode = False
    is_running = True
    end_date = ""
    sell_price = 0.0
    if include_state and cycle:
        holding_qty = max(_safe_int(cycle.get("total_qty", cycle.get("holdingQty", 0)), 0), 0)
        avg_price = _round2(_safe_float(cycle.get("avg_price", cycle.get("avgPrice", 0)), 0))
        total_buy = _safe_float(cycle.get("total_buy", cycle.get("totalBuy", cycle.get("total_spent", 0))), 0)
        total_sell = _safe_float(cycle.get("total_sell", cycle.get("totalSell", 0)), 0)
        t_value = _cycle_t_value(cycle)
        reverse_mode = bool(cycle.get("reverseMode", cycle.get("reverse_mode", False)))
        status = str(cycle.get("status", "") or "").upper()
        is_running = status != "COMPLETED"
        if status == "COMPLETED":
            end_date = format_firegate_date(cycle.get("completed_at", ""))
            sell_price = _safe_float(cycle.get("current_price", 0), 0)

    payload = {
        "id": now_id,
        "nickname": nickname or "",
        "ticker": symbol,
        "sector": "Leveraged ETF",
        "isRunning": is_running,
        "startDate": datetime.date.today().isoformat(),
        "endDate": end_date,
        "seed": seed,
        "divisionDate": division_count,
        "targetProfit": target_profit,
        "avgPrice": avg_price,
        "holdingQty": holding_qty,
        "sellPrice": sell_price,
        "totalBuy": _round2(total_buy),
        "totalSell": _round2(total_sell),
        "commissionRate": _safe_float(commission_rate, 0),
        "quarterMode": False,
        "quarterModeCount": 0,
        "buyingUnit": seed / division_count if division_count > 0 else 0,
        "version": "v4",
        "orderIdx": 0,
        "currency": "USD",
        "tValue": _safe_float(t_value, 0),
        "reverseMode": reverse_mode,
        "updatedAt": format_updated_at(),
    }
    if source:
        payload["source"] = str(source)
    if source_cycle_id:
        payload["sourceCycleId"] = str(source_cycle_id)
    if portfolio_group:
        payload["portfolioGroup"] = str(portfolio_group)
    if portfolio_category:
        payload["category"] = str(portfolio_category)
    return payload


def transaction_from_cycle_trade(trade, portfolio_id, portfolio=None):
    action = str((trade or {}).get("action", "") or "").upper()
    if action not in ("BUY", "SELL"):
        return None
    price = _safe_float((trade or {}).get("filled_price") or (trade or {}).get("order_price"), 0)
    size = _safe_int((trade or {}).get("filled_qty") or (trade or {}).get("order_qty"), 0)
    if price <= 0 or size <= 0:
        return None
    tx = {
        "type": "buy" if action == "BUY" else "sell",
        "ticker": _normalize_symbol((trade or {}).get("symbol", (portfolio or {}).get("ticker", ""))),
        "date": format_firegate_date((trade or {}).get("trade_date")),
        "price": price,
        "size": size,
        "portfolioId": _safe_int(portfolio_id, portfolio_id),
        "commission": _safe_float((trade or {}).get("commission"), 0),
        "source": INFINITYSTOCK_SOURCE,
        "sourceTradeId": str((trade or {}).get("id", "")),
        "sourceCycleId": str((trade or {}).get("cycle_id", "")),
        "orderType": str((trade or {}).get("order_type", "")),
        "strategyType": str((trade or {}).get("strategy_type", "")),
    }
    if tx["type"] == "buy" and str(tx.get("strategyType", "")).upper() == "CRASH_BUY":
        tx["tDelta"] = 0
    elif tx["type"] == "buy" and portfolio:
        tx["tDelta"] = calculate_v4_t_delta(portfolio, tx)
    return tx


def calculate_v4_t_delta(portfolio, tx):
    if str((tx or {}).get("type", "")).lower() != "buy":
        return None
    if "tDelta" in (tx or {}) and tx.get("tDelta") is not None:
        return _safe_float(tx.get("tDelta"), 0)
    seed = _safe_float((portfolio or {}).get("seed"), 0)
    division_count = max(_safe_int((portfolio or {}).get("divisionDate"), 20), 1)
    total_buy = _safe_float((portfolio or {}).get("totalBuy"), 0)
    total_sell = _safe_float((portfolio or {}).get("totalSell"), 0)
    t_value = _safe_float((portfolio or {}).get("tValue"), 0)
    remaining_turns = max(division_count - t_value, 0.000001)
    one_turn = (seed - (total_buy - total_sell)) / remaining_turns
    if one_turn <= 0:
        return 1.0
    gross = _safe_float((tx or {}).get("price"), 0) * _safe_int((tx or {}).get("size"), 0)
    return 0.5 * math.ceil(gross / max(one_turn / 2, 0.000001))


def apply_v4_transaction(portfolio, tx):
    updated = copy.deepcopy(portfolio or {})
    tx_type = str((tx or {}).get("type", "") or "").lower()
    price = _safe_float((tx or {}).get("price"), 0)
    size = _safe_int((tx or {}).get("size"), 0)
    commission = _safe_float((tx or {}).get("commission"), 0)
    if tx_type not in ("buy", "sell") or price <= 0 or size <= 0:
        return updated

    holding_qty = max(_safe_int(updated.get("holdingQty"), 0), 0)
    avg_price = _safe_float(updated.get("avgPrice"), 0)
    total_buy = _safe_float(updated.get("totalBuy"), 0)
    total_sell = _safe_float(updated.get("totalSell"), 0)
    t_value = _safe_float(updated.get("tValue"), 0)
    division_count = max(_safe_int(updated.get("divisionDate"), 20), 1)
    reverse_mode = bool(updated.get("reverseMode", False))
    reverse_star_price = _safe_float(updated.get("reverseModeStarPrice"), 0)
    gross = price * size

    if tx_type == "buy":
        buy_amount = gross + commission
        if reverse_mode:
            t_value += (division_count - t_value) * 0.25
        else:
            t_delta = tx.get("tDelta") if "tDelta" in tx else calculate_v4_t_delta(updated, tx)
            t_value += _safe_float(t_delta, 0)
        avg_price = _round2(((avg_price * holding_qty) + buy_amount) / (holding_qty + size))
        holding_qty += size
        total_buy += buy_amount
    else:
        if reverse_mode:
            t_value *= _reverse_factor(division_count)
            if reverse_star_price <= 0:
                reverse_star_price = price
        else:
            t_value *= _safe_float(tx.get("tDelta"), 0.75)
        updated["isRunning"] = holding_qty > size
        updated["endDate"] = tx.get("date", "")
        updated["sellPrice"] = price
        total_sell += gross - commission
        holding_qty = max(0, holding_qty - size)
        if holding_qty == 0:
            avg_price = 0

    t_value = max(0, min(t_value, division_count))
    if t_value > division_count - 1:
        reverse_mode = True
    updated.update({
        "holdingQty": holding_qty,
        "avgPrice": _round2(avg_price),
        "totalBuy": _round2(total_buy),
        "totalSell": _round2(total_sell),
        "tValue": _round2(t_value),
        "reverseMode": reverse_mode,
        "reverseModeStarPrice": reverse_star_price,
        "updatedAt": format_updated_at(),
    })
    return updated


class FireGateBridge:
    def __init__(self, email, id_token, project_id=FIRE_GATE_PROJECT_ID):
        self.email = str(email or "").strip()
        self.id_token = str(id_token or "").strip()
        self.project_id = project_id

    @property
    def configured(self):
        return bool(self.email and self.id_token)

    def _headers(self):
        if not self.id_token:
            raise FireGateAuthError("FireGate id token is missing.")
        return {
            "Authorization": f"Bearer {self.id_token}",
            "Content-Type": "application/json",
            "X-Goog-Api-Key": FIRE_GATE_API_KEY,
        }

    def _path(self, collection, doc_id=None):
        email = urllib.parse.quote(self.email, safe="")
        collection = urllib.parse.quote(str(collection).strip("/"), safe="/")
        path = f"{FIRESTORE_ROOT}/users/{email}/{collection}"
        if doc_id is not None:
            path += f"/{urllib.parse.quote(str(doc_id), safe='')}"
        return path

    def _request(self, method, url, body=None, params=None):
        params = _with_api_key(params)
        if params:
            url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                text = res.read().decode("utf-8")
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            if e.code in (401, 403):
                raise FireGateAuthError(f"FireGate auth failed: {e.code} {detail}")
            raise FireGateBridgeError(f"FireGate request failed: {e.code} {detail}")

    def list_portfolios(self):
        data = self._request("GET", self._path("portfolios"))
        return [decode_firestore_document(doc) for doc in data.get("documents", []) or []]

    def get_portfolio(self, portfolio_id):
        data = self._request("GET", self._path("portfolios", portfolio_id))
        return decode_firestore_document(data)

    def create_portfolio(self, portfolio, doc_id=None):
        doc_id = doc_id or portfolio.get("id") or _millis()
        portfolio = {**portfolio, "id": _safe_int(doc_id, doc_id), "updatedAt": format_updated_at()}
        data = self._request(
            "POST",
            self._path("portfolios"),
            body=firestore_document(portfolio),
            params={"documentId": str(doc_id)},
        )
        return decode_firestore_document(data)

    def update_portfolio(self, portfolio_id, changes):
        changes = {**(changes or {}), "updatedAt": format_updated_at()}
        masks = [f"updateMask.fieldPaths={urllib.parse.quote(str(key), safe='')}" for key in changes.keys()]
        url = self._path("portfolios", portfolio_id)
        if masks:
            url += "?" + "&".join(masks)
        data = self._request("PATCH", url, body=firestore_document(changes))
        return decode_firestore_document(data)

    def list_transactions(self, portfolio_id):
        data = self._request("GET", self._path("transactions"))
        rows = [decode_firestore_document(doc) for doc in data.get("documents", []) or []]
        return [row for row in rows if str(row.get("portfolioId", "")) == str(portfolio_id)]

    def create_transaction(self, tx, doc_id=None):
        doc_id = doc_id or _millis()
        tx = {**(tx or {}), "id": _safe_int(doc_id, doc_id)}
        data = self._request(
            "POST",
            self._path("transactions"),
            body=firestore_document(tx),
            params={"documentId": str(doc_id)},
        )
        return decode_firestore_document(data)

    def find_portfolio(self, symbol, include_stopped=False, source=None, source_cycle_id=None, portfolio_group=None):
        symbol = _normalize_symbol(symbol)
        for item in self.list_portfolios():
            if _normalize_symbol(item.get("ticker")) != symbol:
                continue
            if source is not None and str(item.get("source", "") or "") != str(source):
                continue
            if source_cycle_id is not None and str(item.get("sourceCycleId", "") or "") != str(source_cycle_id):
                continue
            if portfolio_group is not None and str(item.get("portfolioGroup", "") or "") != str(portfolio_group):
                continue
            if include_stopped or item.get("isRunning", True):
                return item
        return None

    def ensure_v4_portfolio(
        self,
        symbol,
        seed,
        division_count=20,
        target_profit=15,
        nickname="",
        commission_rate=0,
        cycle=None,
        include_state=False,
        source="",
        source_cycle_id="",
        portfolio_group="",
        portfolio_category="",
    ):
        managed_lookup = bool(source or source_cycle_id or portfolio_group)
        existing = self.find_portfolio(
            symbol,
            include_stopped=managed_lookup,
            source=source if source else None,
            source_cycle_id=source_cycle_id if source_cycle_id else None,
            portfolio_group=portfolio_group if portfolio_group and not source_cycle_id else None,
        )
        payload = build_v4_portfolio(
            symbol,
            seed,
            division_count=division_count,
            target_profit=target_profit,
            nickname=nickname,
            commission_rate=commission_rate,
            cycle=cycle,
            include_state=include_state,
            source=source,
            source_cycle_id=source_cycle_id,
            portfolio_group=portfolio_group,
            portfolio_category=portfolio_category,
        )
        if existing:
            static_changes = {
                "nickname": nickname or existing.get("nickname", ""),
                "seed": payload["seed"],
                "divisionDate": payload["divisionDate"],
                "targetProfit": payload["targetProfit"],
                "buyingUnit": payload["buyingUnit"],
                "version": "v4",
                "currency": "USD",
            }
            for key in ("source", "sourceCycleId", "portfolioGroup", "category"):
                if key in payload:
                    static_changes[key] = payload[key]
            updated = self.update_portfolio(existing.get("id"), static_changes)
            return {**existing, **updated}, False
        created = self.create_portfolio(payload)
        return created, True

    def add_transaction_and_update_portfolio(self, portfolio, tx):
        portfolio_id = portfolio.get("id")
        if portfolio_id is None:
            raise FireGateBridgeError("FireGate portfolio id is missing.")
        tx = {**(tx or {}), "portfolioId": _safe_int(portfolio_id, portfolio_id)}
        if tx.get("type") == "buy" and "tDelta" not in tx:
            tx["tDelta"] = calculate_v4_t_delta(portfolio, tx)
        saved_tx = self.create_transaction(tx)
        updated_payload = apply_v4_transaction(portfolio, tx)
        updated = self.update_portfolio(portfolio_id, updated_payload)
        return saved_tx, {**updated_payload, **updated}


def sync_cycle_trade(struct, cycle, trade, force=False):
    cfg = load_bridge_config(struct)
    if not force and (not cfg.get("enabled") or not cfg.get("auto_sync_enabled", True)):
        return {"synced": False, "reason": "disabled"}
    action = str((trade or {}).get("action", "") or "").upper()
    status = str((trade or {}).get("status", "") or "").upper()
    if action not in ("BUY", "SELL") or status != "FILLED":
        return {"synced": False, "reason": "unsupported_trade"}
    symbol = _normalize_symbol((trade or {}).get("symbol") or (cycle or {}).get("symbol"))
    if not symbol:
        return {"synced": False, "reason": "missing_symbol"}

    def _sync(bridge, _cfg):
        source_cycle_id = infinitystock_source_cycle_id(cycle, symbol) or str((trade or {}).get("cycle_id", "") or "")
        portfolio = bridge.find_portfolio(
            symbol,
            include_stopped=True,
            source=INFINITYSTOCK_SOURCE,
            source_cycle_id=source_cycle_id if source_cycle_id else None,
        )
        if not portfolio and action != "BUY":
            return {"synced": False, "reason": "missing_portfolio"}
        if not portfolio:
            seed = _safe_float((cycle or {}).get("total_investment"), 0)
            division_count = max(_safe_int((cycle or {}).get("division_count"), 20), 1)
            target_profit = _safe_float((cycle or {}).get("target_profit"), default_target_profit(symbol))
            portfolio, _created = bridge.ensure_v4_portfolio(
                symbol,
                seed,
                division_count=division_count,
                target_profit=target_profit,
                nickname=infinitystock_portfolio_nickname(symbol, cycle),
                cycle=None,
                include_state=False,
                source=INFINITYSTOCK_SOURCE,
                source_cycle_id=source_cycle_id,
                portfolio_group=INFINITYSTOCK_PORTFOLIO_GROUP,
                portfolio_category=INFINITYSTOCK_PORTFOLIO_CATEGORY,
            )
        source_trade_id = str((trade or {}).get("id", ""))
        if source_trade_id:
            for tx in bridge.list_transactions(portfolio.get("id")):
                if str(tx.get("source", "")) == INFINITYSTOCK_SOURCE and str(tx.get("sourceTradeId", "")) == source_trade_id:
                    return {"synced": False, "reason": "duplicate", "portfolio_id": portfolio.get("id")}
        tx = transaction_from_cycle_trade(trade, portfolio.get("id"), portfolio=portfolio)
        if not tx:
            return {"synced": False, "reason": "invalid_trade"}
        saved_tx, updated = bridge.add_transaction_and_update_portfolio(portfolio, tx)
        return {
            "synced": True,
            "portfolio_id": portfolio.get("id"),
            "transaction_id": saved_tx.get("id"),
            "ticker": updated.get("ticker", symbol),
        }

    result = _bridge_call_from_config(struct, _sync)
    return result or {"synced": False, "reason": "not_configured"}


class _FireGateBridgeModel:
    FireGateBridgeError = FireGateBridgeError
    FireGateAuthError = FireGateAuthError
    FireGateBridge = FireGateBridge
    INFINITYSTOCK_SOURCE = INFINITYSTOCK_SOURCE
    INFINITYSTOCK_PORTFOLIO_GROUP = INFINITYSTOCK_PORTFOLIO_GROUP
    INFINITYSTOCK_PORTFOLIO_CATEGORY = INFINITYSTOCK_PORTFOLIO_CATEGORY

    refresh_id_token = staticmethod(refresh_id_token)
    load_bridge_config = staticmethod(load_bridge_config)
    save_bridge_config = staticmethod(save_bridge_config)
    bridge_from_config = staticmethod(bridge_from_config)
    sync_portfolios_to_local = staticmethod(sync_portfolios_to_local)
    sync_local_to_firegate = staticmethod(sync_local_to_firegate)
    sync_portfolios_bidirectional = staticmethod(sync_portfolios_bidirectional)
    build_v4_portfolio = staticmethod(build_v4_portfolio)
    default_target_profit = staticmethod(default_target_profit)
    infinitystock_source_cycle_id = staticmethod(infinitystock_source_cycle_id)
    infinitystock_portfolio_nickname = staticmethod(infinitystock_portfolio_nickname)
    calculate_v4_t_delta = staticmethod(calculate_v4_t_delta)
    apply_v4_transaction = staticmethod(apply_v4_transaction)
    transaction_from_cycle_trade = staticmethod(transaction_from_cycle_trade)
    sync_cycle_trade = staticmethod(sync_cycle_trade)


Model = _FireGateBridgeModel()
