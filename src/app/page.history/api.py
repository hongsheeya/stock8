import json
import math
import re
import datetime
import copy
import time

struct = wiz.model("struct")
_TIME = wiz.model("portal/trading/kst")
KST = datetime.timezone(datetime.timedelta(hours=9))
_HISTORY_CACHE = {}
_HISTORY_CACHE_TTL_SEC = 20

def _cache_get(key):
    cached = _HISTORY_CACHE.get(key)
    if not cached:
        return None
    ts, value = cached
    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    if now - ts > _HISTORY_CACHE_TTL_SEC:
        _HISTORY_CACHE.pop(key, None)
        return None
    return copy.deepcopy(value)

def _cache_set(key, value):
    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    _HISTORY_CACHE[key] = (now, copy.deepcopy(value))

def _history_cache_scope():
    try:
        session = wiz.model("portal/season/session").use()
        user_id = str(session.get("id", "") or session.get("email", "") or "").strip()
        return f"user:{user_id}" if user_id else "anon"
    except Exception:
        return "anon"

def _sanitize_user_log_message(message):
    """사용자 화면에서는 기술 상세 파라미터를 숨긴다."""
    if not message:
        return ""

    text = str(message).strip()
    text = re.sub(r"\s*\((?=[^)]*(?:rt_cd|CANO|ACNT_PRDT_CD|tr_id|ord_dvsn|is_real|exchange=|qty=|price=))[^)]*\)", "", text)
    text = re.sub(r"\s*\|\s*symbol=.*$", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text

def _to_kst_string(value, fmt="%Y-%m-%d %H:%M", assume_naive_utc=False):
    if value in (None, ""):
        return ""
    dt = _TIME.to_kst(value, assume_naive_kst=(not assume_naive_utc))
    text = dt.strftime(fmt) if dt is not None else ""
    if text == "" and value not in (None, ""):
        return str(value)[:16]
    return text

def _safe_float(value, default=0.0):
    try:
        text = str(value if value is not None else "").replace(",", "").strip()
        if text == "":
            return default
        return float(text)
    except Exception:
        return default

def _safe_int(value, default=0):
    try:
        text = str(value if value is not None else "").replace(",", "").strip()
        if text == "":
            return default
        return int(float(text))
    except Exception:
        return default

def _normalize_trade_action(action=""):
    text = str(action or "").upper().strip()
    if text.startswith("PRE_SELL"):
        return "SELL"
    if text.startswith("BUY"):
        return "BUY"
    if text.startswith("SELL"):
        return "SELL"
    return text

def _is_executable_daytrade_record(record):
    record = record if isinstance(record, dict) else {}
    action = _normalize_trade_action(record.get("action", ""))
    if action not in ("BUY", "SELL"):
        return False

    action_detail = str(record.get("action_detail", "") or "").upper().strip()
    if (action_detail.startswith("PRE_") or "RESERVED" in action_detail) and str(record.get("status", "")).upper() != "FILLED":
        return False

    qty = _safe_int(record.get("qty", 0), 0)
    price = _safe_float(record.get("price", 0), 0)
    amount = _safe_float(record.get("amount", 0), 0)
    if qty <= 0:
        return False
    if price <= 0 and amount <= 0:
        return False
    return True

def _is_visible_daytrade_record(record):
    if _is_executable_daytrade_record(record):
        return True
    status = str((record or {}).get("status", "") or "").upper()
    action = str((record or {}).get("action", "") or "").upper()
    return status in ("REJECTED", "FAILED", "BLOCKED", "EXPIRED", "PENDING", "ACCEPTED", "ACCEPTED_UNVERIFIED") or action in ("ERROR", "SKIP", "PENDING")

def _daytrade_market(event_type="", symbol="", fallback="KS"):
    event = str(event_type or "").upper()
    if event.startswith("DT_US_"):
        return "US"
    if event.startswith("DT_KS_"):
        return "KS"
    sym = str(symbol or "").upper().strip()
    if sym.isdigit() and len(sym) == 6:
        return "KS"
    if sym and sym.replace(".", "").isalpha() and len(sym) <= 8:
        return "US"
    return str(fallback or "KS").upper()

def _raw_json(value):
    try:
        data = json.loads(value or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "y", "on")

def _first_nonzero_float(*values):
    for value in values:
        num = _safe_float(value, 0)
        if abs(num) > 1e-9:
            return num
    return 0.0

def _labeled_money(text, label):
    """`label ₩-528,509` / `label $12.30` in an engine log message, else 0."""
    match = re.search(rf"{label}\s*[:=]?\s*[$₩]?\s*([+-]?[0-9][0-9,]*(?:\.[0-9]+)?)", str(text or ""))
    return _safe_float(match.group(1), 0) if match else 0.0

def _realized_from_message(*messages):
    for message in messages:
        text = str(message or "")
        if text == "":
            continue
        for label in ("순손익", "실현손익", "pnl_net", "realized_pnl_net"):
            pattern = rf"{label}\s*[:=]?\s*([$₩]?\s*[+-]?[0-9][0-9,]*(?:\.[0-9]+)?)"
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return _safe_float(match.group(1).replace("$", "").replace("₩", ""), 0)
    return 0.0

def _realized_from_payload(action, raw=None, runtime=None, order=None, row=None, state=None):
    """SELL 체결의 실현손익을 가능한 모든 런타임/브로커 필드에서 복원한다."""
    if _normalize_trade_action(action) != "SELL":
        return 0.0
    raw = raw if isinstance(raw, dict) else {}
    runtime = runtime if isinstance(runtime, dict) else {}
    order = order if isinstance(order, dict) else {}
    row = row if isinstance(row, dict) else {}
    state = state if isinstance(state, dict) else {}
    value = _first_nonzero_float(
        runtime.get("realized"),
        runtime.get("realized_profit"),
        runtime.get("realized_pnl_net"),
        runtime.get("pnl_net"),
        runtime.get("pnl"),
        raw.get("realized"),
        raw.get("realized_profit"),
        raw.get("realized_pnl_net"),
        raw.get("pnl_net"),
        raw.get("pnl"),
        order.get("realized"),
        order.get("realized_profit"),
        order.get("realized_pnl_net"),
        order.get("pnl_net"),
        order.get("pnl"),
        row.get("realized"),
        row.get("realized_profit"),
        row.get("realized_pnl_net"),
        row.get("pnl_net"),
        row.get("pnl"),
        state.get("realized_profit"),
    )
    if abs(value) > 1e-9:
        return value
    return _realized_from_message(
        runtime.get("message", ""),
        raw.get("message", ""),
        order.get("message", ""),
        row.get("message", ""),
    )

def _daytrade_sort_key(timestamp=""):
    return str(timestamp or "").replace("T", " ")[:19]

def _daytrade_record_key(record):
    order_no = str(record.get("order_no", "") or "").strip()
    symbol = str(record.get("symbol", "") or "").strip()
    market = str(record.get("market", "") or "").strip()
    action = _normalize_trade_action(record.get("action", ""))
    if order_no:
        # A local PENDING row and the later authoritative KIS fill share an
        # order number. Merge them regardless of the provisional action.
        order_no = order_no.lstrip("0") or "0"
        return f"{market}:{symbol}:{str(record.get('timestamp', ''))[:10]}:{order_no}"
    return f"{market}:{symbol}:{record.get('action_detail', action)}:{record.get('timestamp', '')}:{record.get('qty', 0)}:{record.get('price', 0)}"

def _daytrade_source_rank(record):
    if record.get("verification") == "kis":
        return 4
    source = str((record or {}).get("source", "") or "").lower()
    if "kis" in source or "broker" in source:
        return 3
    if "trade_log" in source:
        return 2
    if "live_state" in source:
        return 1
    return 0

def _merge_daytrade_record(existing, incoming):
    if not existing:
        return incoming
    existing_rank = _daytrade_source_rank(existing)
    incoming_rank = _daytrade_source_rank(incoming)
    # A fill outranks an acceptance-only row from any source: trade_log keeps
    # the PENDING line while the state records the KIS fill (005930 09-30,
    # 114800 10-01 vanished from history this way).
    existing_filled = _is_executable_daytrade_record(existing)
    incoming_filled = _is_executable_daytrade_record(incoming)
    if existing_filled != incoming_filled:
        existing_rank, incoming_rank = (0, 1) if incoming_filled else (1, 0)
    if incoming_rank > existing_rank:
        merged = dict(existing)
        for key in (
            "id", "timestamp", "market", "market_label", "symbol", "name", "strategy_id",
            "action", "action_detail", "order_type", "order_no", "price", "qty", "amount",
            "matched_buy_amount", "fee", "avg_buy_price", "status", "verification",
            "post_position_qty", "post_avg_price", "message", "_sort",
        ):
            candidate = incoming.get(key, "")
            candidate_present = candidate not in ("", None) and not (
                isinstance(candidate, (int, float)) and abs(float(candidate)) <= 1e-9 and key not in ("realized",)
            )
            if candidate_present:
                merged[key] = candidate
        if incoming.get("action") == "SELL" or abs(_safe_float(incoming.get("realized", 0), 0)) > 1e-9:
            merged["realized"] = round(_safe_float(incoming.get("realized", 0), 0), 2)
        existing_source = str(existing.get("source", "") or "")
        incoming_source = str(incoming.get("source", "") or "")
        if incoming_source and incoming_source not in existing_source.split("+"):
            merged["source"] = "+".join([part for part in [existing_source, incoming_source] if part])
        return merged

    existing_realized = _safe_float(existing.get("realized", 0), 0)
    incoming_realized = _safe_float(incoming.get("realized", 0), 0)
    if abs(existing_realized) <= 1e-9 and abs(incoming_realized) > 1e-9:
        existing["realized"] = round(incoming_realized, 2)

    for key in ("post_position_qty", "post_avg_price", "order_type", "order_no", "price", "qty", "amount", "matched_buy_amount", "fee", "avg_buy_price"):
        current = existing.get(key, "")
        candidate = incoming.get(key, "")
        current_empty = current in ("", None) or (isinstance(current, (int, float)) and abs(float(current)) <= 1e-9)
        candidate_present = candidate not in ("", None) and not (isinstance(candidate, (int, float)) and abs(float(candidate)) <= 1e-9)
        if current_empty and candidate_present:
            existing[key] = candidate

    if not str(existing.get("message", "") or "").strip() and str(incoming.get("message", "") or "").strip():
        existing["message"] = incoming.get("message", "")

    existing_source = str(existing.get("source", "") or "")
    incoming_source = str(incoming.get("source", "") or "")
    if incoming_source and incoming_source not in existing_source.split("+"):
        existing["source"] = "+".join([part for part in [existing_source, incoming_source] if part])
    return existing

def _daytrade_record_from_log(row):
    raw = _raw_json(row.get("raw_response", ""))
    runtime = raw.get("runtime", {}) if isinstance(raw.get("runtime", {}), dict) else {}
    order = raw.get("order", {}) if isinstance(raw.get("order", {}), dict) else {}
    event_type = str(row.get("event_type", "") or "")
    symbol = str(row.get("symbol", "") or raw.get("symbol", "") or "").upper()
    market = _daytrade_market(event_type, symbol, raw.get("market", "KS"))
    action_detail = str(raw.get("action", "") or event_type.replace("DT_KS_", "").replace("DT_US_", "") or row.get("action", "")).upper()
    action = _normalize_trade_action(row.get("action", action_detail))
    price = _safe_float(row.get("filled_price", None), 0) or _safe_float(row.get("order_price", 0), 0)
    qty = _safe_int(row.get("filled_qty", 0), 0) or _safe_int(row.get("order_qty", 0), 0)
    created_kst = raw.get("created_kst", "") or runtime.get("created_kst", "")
    # 이 로컬 SQLite의 naive created 값은 저장 시점부터 KST다. UTC로 다시
    # 해석하면 거래 이력이 실제 주문보다 9시간 뒤로 표시된다.
    timestamp = _to_kst_string(created_kst, fmt="%Y-%m-%d %H:%M:%S") if created_kst else _to_kst_string(row.get("created"), fmt="%Y-%m-%d %H:%M:%S")
    reason = str(runtime.get("reason", "") or raw.get("message", "") or row.get("message", "") or "")
    realized = _realized_from_payload(action, raw=raw, runtime=runtime, order=order, row=row)
    matched_buy_amount = _first_nonzero_float(
        runtime.get("matched_buy_amount"),
        runtime.get("sold_cost"),
        runtime.get("cost_basis"),
        runtime.get("buy_amount_component"),
        raw.get("matched_buy_amount"),
        raw.get("sold_cost"),
        raw.get("cost_basis"),
        raw.get("buy_amount_component"),
        order.get("matched_buy_amount"),
        order.get("sold_cost"),
        order.get("cost_basis"),
        row.get("matched_buy_amount"),
    )
    # The engine writes "손익 … | 수수료 … | 순손익 …" into the row message;
    # runtime["realized"] is the gross figure before fees and tax.
    log_message = str(row.get("message", "") or "")
    fee = _first_nonzero_float(
        runtime.get("fee"),
        runtime.get("total_fee"),
        runtime.get("fee_krw"),
        runtime.get("fee_amount"),
        raw.get("fee"),
        raw.get("total_fee"),
        raw.get("fee_krw"),
        raw.get("fee_amount"),
        order.get("fee"),
        order.get("total_fee"),
        order.get("fee_krw"),
        row.get("fee"),
        _labeled_money(log_message, "수수료"),
    )
    net_realized = _labeled_money(log_message, "순손익") if action == "SELL" else 0.0
    # Gross P&L the engine computed on its own average cost; a PENDING row only
    # carries the pre-trade estimate.
    engine_gross = realized if action == "SELL" else 0.0
    avg_buy_price = _first_nonzero_float(
        runtime.get("avg_buy_price"),
        runtime.get("post_avg_price"),
        raw.get("avg_buy_price"),
        raw.get("post_avg_price"),
        order.get("avg_buy_price"),
        order.get("post_avg_price"),
        row.get("avg_buy_price"),
    )
    record = {
        "id": row.get("id", ""),
        "timestamp": timestamp,
        "market": market,
        "market_label": "미장" if market == "US" else "국장",
        "symbol": symbol,
        "name": raw.get("name", "") or symbol,
        "strategy_id": str(raw.get("strategy_id", "") or runtime.get("strategy_id", "") or ""),
        "action": action,
        "action_detail": action_detail,
        "order_type": str(order.get("order_type", "") or ""),
        "order_no": str(row.get("order_no", "") or order.get("order_no", "") or ""),
        "price": round(price, 4),
        "qty": qty,
        "amount": round(price * qty, 2),
        "realized": round(realized, 2),
        "net_realized": round(net_realized, 2),
        "engine_gross": round(engine_gross, 2),
        "matched_buy_amount": round(matched_buy_amount, 2),
        "fee": round(fee, 4),
        "avg_buy_price": round(avg_buy_price, 4),
        "post_position_qty": _safe_int(runtime.get("post_position_qty", 0), 0),
        "post_avg_price": round(_safe_float(runtime.get("post_avg_price", 0), 0), 4),
        "message": _sanitize_user_log_message(reason),
        "status": str(raw.get("execution_status", "") or ("FILLED" if action in ("BUY", "SELL") else "")),
        "source": "trade_log",
        "_sort": _daytrade_sort_key(timestamp),
    }
    return record

def _synthetic_realized_record_from_state(state_key, state):
    """예약 매도 체결처럼 로그만 남고 state.orders에 SELL이 누락된 이익 실현을 복원한다."""
    state = state if isinstance(state, dict) else {}
    realized = _safe_float(state.get("realized_profit", 0), 0)
    position_qty = _safe_int(state.get("position_qty", 0), 0)
    if position_qty > 0 or abs(realized) <= 1e-9:
        return None

    orders = list(state.get("orders", []) or [])
    has_sell_order = any(_normalize_trade_action((item or {}).get("action", "")) == "SELL" for item in orders)
    if has_sell_order:
        return None

    exit_order = None
    for item in reversed(orders):
        action_detail = str((item or {}).get("action", "") or "").upper()
        if "PRE_SELL" in action_detail or "SELL" in action_detail:
            exit_order = item
            break
    if exit_order is None and orders:
        exit_order = orders[-1]
    exit_order = exit_order if isinstance(exit_order, dict) else {}

    symbol = str(state.get("symbol", "") or str(state_key).split(".")[0]).upper()
    market = str(state.get("market", "") or (str(state_key).split(".")[1] if "." in str(state_key) else "KS")).upper()
    market = "US" if market == "US" else "KS"
    timestamp = _to_kst_string(state.get("last_exit_watch_at", "") or exit_order.get("timestamp", "") or state.get("updated_at", ""), fmt="%Y-%m-%d %H:%M:%S")
    price = _safe_float(state.get("last_exit_price", 0), 0) or _safe_float(exit_order.get("price", 0), 0)
    qty = _safe_int(exit_order.get("qty", 0), 0)
    action_detail = str(state.get("last_exit_action", "") or "SELL_FULL").upper()
    order_no = str(state.get("last_exit_order_no", "") or exit_order.get("order_no", "") or exit_order.get("reserve_order_no", "") or "")
    reason = str(state.get("last_exit_reason", "") or exit_order.get("reason", "") or "실현손익 반영")
    amount = price * qty
    matched_buy_amount = max(0.0, amount - realized) if amount > 0 and qty > 0 else 0.0
    avg_buy_price = matched_buy_amount / qty if matched_buy_amount > 0 and qty > 0 else 0.0

    return {
        "id": f"state-realized:{state_key}:{timestamp}:{order_no}",
        "timestamp": timestamp,
        "market": market,
        "market_label": "미장" if market == "US" else "국장",
        "symbol": symbol,
        "name": state.get("name", "") or symbol,
        "strategy_id": exit_order.get("strategy_id", "") or state.get("strategy_id", ""),
        "action": "SELL",
        "action_detail": action_detail,
        "order_type": str(exit_order.get("order_type", "") or "LIMIT"),
        "order_no": order_no,
        "price": round(price, 4),
        "qty": qty,
        "amount": round(amount, 2),
        "realized": round(realized, 2),
        "matched_buy_amount": round(matched_buy_amount, 2),
        "fee": 0,
        "avg_buy_price": round(avg_buy_price, 4),
        "post_position_qty": 0,
        "post_avg_price": 0,
        "message": _sanitize_user_log_message(reason),
        "source": "live_state_synthetic",
        "_sort": _daytrade_sort_key(timestamp),
    }

def _daytrade_record_from_state(state_key, state, order):
    symbol = str((state or {}).get("symbol", "") or state_key.split(".")[0]).upper()
    market = str((state or {}).get("market", "") or (state_key.split(".")[1] if "." in state_key else "KS")).upper()
    action_detail = str((order or {}).get("action", "") or "").upper()
    action = _normalize_trade_action(action_detail)
    price = _safe_float((order or {}).get("price", 0), 0)
    qty = _safe_int((order or {}).get("qty", 0), 0)
    amount = price * qty
    timestamp = _to_kst_string((order or {}).get("timestamp", ""), fmt="%Y-%m-%d %H:%M:%S")
    realized = _realized_from_payload(action, order=order)
    if abs(realized) <= 1e-9 and action == "SELL":
        state_realized = _safe_float((state or {}).get("realized_profit", 0), 0)
        order_no = str((order or {}).get("order_no", "") or (order or {}).get("reserve_order_no", "") or "")
        last_exit_order_no = str((state or {}).get("last_exit_order_no", "") or "")
        if abs(state_realized) > 1e-9 and order_no != "" and order_no == last_exit_order_no:
            realized = state_realized
        else:
            state_orders = list((state or {}).get("orders", []) or [])
            sell_orders = [
                item for item in state_orders
                if _normalize_trade_action((item or {}).get("action", "")) == "SELL"
            ]
            buy_orders = [
                item for item in state_orders
                if _normalize_trade_action((item or {}).get("action", "")) == "BUY"
            ]
            if abs(state_realized) > 1e-9 and len(sell_orders) == 1 and len(buy_orders) == 0:
                realized = state_realized
    avg_buy_price = _first_nonzero_float(
        (order or {}).get("avg_buy_price"),
        (order or {}).get("post_avg_price"),
        (state or {}).get("avg_price"),
    )
    fee = _first_nonzero_float((order or {}).get("fee"), (order or {}).get("total_fee"), (order or {}).get("fee_krw"))
    matched_buy_amount = _first_nonzero_float(
        (order or {}).get("matched_buy_amount"),
        (order or {}).get("sold_cost"),
        (order or {}).get("cost_basis"),
    )
    if action == "SELL" and matched_buy_amount <= 0 and avg_buy_price > 0 and qty > 0:
        matched_buy_amount = avg_buy_price * qty
    if action == "SELL" and matched_buy_amount <= 0 and amount > 0 and abs(realized) > 1e-9:
        matched_buy_amount = max(0.0, amount - realized - max(0.0, fee))
        if matched_buy_amount > 0 and qty > 0:
            avg_buy_price = matched_buy_amount / qty
    record = {
        "id": f"state:{state_key}:{timestamp}:{action_detail}",
        "timestamp": timestamp,
        "market": "US" if market == "US" else "KS",
        "market_label": "미장" if market == "US" else "국장",
        "symbol": symbol,
        "name": (state or {}).get("name", "") or symbol,
        "strategy_id": (order or {}).get("strategy_id", "") or (state or {}).get("strategy_id", ""),
        "action": action,
        "action_detail": action_detail,
        "order_type": str((order or {}).get("order_type", "") or ""),
        "order_no": str((order or {}).get("order_no", "") or (order or {}).get("reserve_order_no", "") or ""),
        "price": round(price, 4),
        "qty": qty,
        "amount": round(amount, 2),
        "realized": round(realized, 2),
        "matched_buy_amount": round(matched_buy_amount if action == "SELL" else 0, 2),
        "fee": round(fee, 4),
        "avg_buy_price": round(avg_buy_price if action == "SELL" else 0, 4),
        "post_position_qty": _safe_int((state or {}).get("position_qty", 0), 0),
        "post_avg_price": round(_safe_float((state or {}).get("avg_price", 0), 0), 4),
        "message": _sanitize_user_log_message((order or {}).get("reason", "")),
        "source": "live_state",
        "status": str(order.get("status", "")),
        "verification": str(order.get("verification", "")),
        "_sort": _daytrade_sort_key(timestamp),
    }
    return record

def _estimate_net_realized(lot_price, sell_price, qty, market="KS"):
    gross = (_safe_float(sell_price, 0) - _safe_float(lot_price, 0)) * max(0, _safe_int(qty, 0))
    buy_amount = _safe_float(lot_price, 0) * max(0, _safe_int(qty, 0))
    sell_amount = _safe_float(sell_price, 0) * max(0, _safe_int(qty, 0))
    if str(market or "").upper() == "US":
        fee = buy_amount * 0.0025 + sell_amount * 0.0025 + (sell_amount / 1_000_000.0 * 8.0)
        return gross - fee
    fee = buy_amount * 0.00015 + sell_amount * 0.00195
    return gross - fee

def _consume_fifo_realized_with_cost(lots, qty, sell_price, market="KS"):
    remaining = max(0, _safe_int(qty, 0))
    price = _safe_float(sell_price, 0)
    realized = 0.0
    matched_cost = 0.0
    while remaining > 0 and lots:
        lot = lots[0]
        lot_qty = max(0, _safe_int(lot.get("qty", 0), 0))
        lot_price = _safe_float(lot.get("price", 0), 0)
        if lot_qty <= 0:
            lots.pop(0)
            continue
        take = min(remaining, lot_qty)
        if price > 0 and lot_price > 0:
            realized += _estimate_net_realized(lot_price, price, take, market=market)
            matched_cost += lot_price * take
        lot["qty"] = lot_qty - take
        remaining -= take
        if lot["qty"] <= 0:
            lots.pop(0)
    return realized, matched_cost

def _consume_fifo_realized(lots, qty, sell_price, market="KS"):
    realized, _matched_cost = _consume_fifo_realized_with_cost(lots, qty, sell_price, market=market)
    return realized

def _presell_order_no(order):
    return str((order or {}).get("order_no", "") or (order or {}).get("reserve_order_no", "") or "").strip()

def _state_presell_is_filled(state, orders, index, order, available_qty=0):
    order_no = _presell_order_no(order)
    pending_order_no = str((state or {}).get("pending_sell_order_no", "") or "").strip()
    if order_no and pending_order_no and order_no == pending_order_no:
        return False

    last_exit_order_no = str((state or {}).get("last_exit_order_no", "") or "").strip()
    if order_no and last_exit_order_no and order_no == last_exit_order_no and _safe_int(available_qty, 0) > 0:
        return True

    status_text = " ".join([
        str((order or {}).get("status", "") or ""),
        str((order or {}).get("order_status", "") or ""),
        str((order or {}).get("message", "") or ""),
        str((order or {}).get("reason", "") or ""),
    ]).lower()
    explicit_filled_qty = _safe_int((order or {}).get("filled_qty", 0), 0) or _safe_int((order or {}).get("executed_qty", 0), 0)
    if explicit_filled_qty > 0 and _safe_int(available_qty, 0) > 0:
        return True
    if _safe_int(available_qty, 0) > 0 and any(token in status_text for token in ("filled", "executed", "체결")):
        return True

    return False

def _daytrade_records_from_state_orders(state_key, state):
    records = []
    lots = []
    orders = sorted(list((state or {}).get("orders", []) or []), key=lambda row: str(row.get("timestamp", "")))
    state_market = str((state or {}).get("market", "") or (str(state_key).split(".")[1] if "." in str(state_key) else "KS")).upper()
    state_market = "US" if state_market == "US" else "KS"

    for index, order in enumerate(orders):
        action_detail = str((order or {}).get("action", "") or "").upper()
        normalized = _normalize_trade_action(action_detail)
        price = _safe_float((order or {}).get("price", 0), 0)
        qty = _safe_int((order or {}).get("qty", 0), 0)
        status = str((order or {}).get("status", (order or {}).get("execution_status", "")) or "").upper()
        filled_qty = _safe_int((order or {}).get("filled_qty", 0), 0)
        filled_price = _safe_float((order or {}).get("filled_price", 0), 0)
        explicitly_filled = status in ("FILLED", "EXECUTED", "DONE", "COMPLETE", "COMPLETED") and filled_qty > 0 and filled_price > 0

        if filled_qty > 0 and filled_price > 0:
            # FIFO must use executed quantity/price, never the requested limit.
            order = dict(order, qty=filled_qty, price=filled_price)
            qty, price = filled_qty, filled_price
            explicitly_filled = True

        if normalized in ("BUY", "SELL") and not explicitly_filled:
            record = _daytrade_record_from_state(state_key, state, order)
            record.update({
                "action": "PENDING",
                "action_detail": f"{action_detail}_PENDING",
                "status": status or "ACCEPTED_UNVERIFIED",
                "message": _sanitize_user_log_message("주문 접수 · KIS 체결 확인 대기"),
            })
            records.append(record)
            continue

        if normalized == "BUY":
            record = _daytrade_record_from_state(state_key, state, order)
            records.append(record)
            if qty > 0 and price > 0:
                lots.append({"qty": qty, "price": price})
            continue

        if normalized == "SELL":
            realized, matched_cost = _consume_fifo_realized_with_cost(lots, qty, price, market=state_market)
            record = _daytrade_record_from_state(state_key, state, order)
            if abs(realized) > 1e-9:
                record["realized"] = round(realized, 2)
            if matched_cost > 0:
                record["matched_buy_amount"] = round(matched_cost, 2)
                record["avg_buy_price"] = round(matched_cost / qty, 4) if qty > 0 else 0
                record["fee"] = round(max(0.0, (price * qty) - matched_cost - realized), 4)
            records.append(record)
            continue

        available_qty = sum(max(0, _safe_int(lot.get("qty", 0), 0)) for lot in lots)
        if "PRE_SELL" in action_detail and _state_presell_is_filled(state, orders, index, order, available_qty=available_qty):
            realized, matched_cost = _consume_fifo_realized_with_cost(lots, qty, price, market=state_market)
            record = _daytrade_record_from_state(state_key, state, order)
            order_no = record.get("order_no", "")
            last_exit_order_no = str((state or {}).get("last_exit_order_no", "") or "")
            if order_no and order_no == last_exit_order_no and (state or {}).get("last_exit_watch_at"):
                timestamp = _to_kst_string((state or {}).get("last_exit_watch_at", ""), fmt="%Y-%m-%d %H:%M:%S")
                message = str((state or {}).get("last_exit_reason", "") or (order or {}).get("reason", "") or "")
            else:
                timestamp = record.get("timestamp", "")
                message = str((order or {}).get("reason", "") or "")
            record.update({
                "id": f"state-presell-fill:{state_key}:{timestamp}:{order_no}",
                "timestamp": timestamp,
                "action": "SELL",
                "action_detail": "SELL_FULL",
                "realized": round(realized, 2),
                "matched_buy_amount": round(matched_cost, 2),
                "avg_buy_price": round(matched_cost / qty, 4) if matched_cost > 0 and qty > 0 else record.get("avg_buy_price", 0),
                "fee": round(max(0.0, (price * qty) - matched_cost - realized), 4) if matched_cost > 0 else record.get("fee", 0),
                "message": _sanitize_user_log_message(f"사전 예약 지정가 매도 체결 | {message}"),
                "source": "live_state_presell_fill",
                "_sort": _daytrade_sort_key(timestamp),
            })
            records.append(record)

    return records

def _load_daytrade_state(trading):
    try:
        engine = trading.daytrade_engine
        return engine._load_state_map() or {}
    except Exception:
        return {}

def _cycle_trade_record_key(record):
    order_no = str(record.get("order_no", "") or "").strip()
    symbol = str(record.get("symbol", "") or "").strip()
    action = _normalize_trade_action(record.get("action", ""))
    if order_no:
        return f"cycle:{symbol}:{action}:{order_no}"
    return f"cycle:{symbol}:{action}:{record.get('cycle_id', '')}:{record.get('timestamp', '')}:{record.get('qty', 0)}:{record.get('price', 0)}"

def _cycle_trade_record_from_row(row):
    row = row if isinstance(row, dict) else {}
    order_type = str(row.get("order_type", "") or "").upper().strip()
    order_no = str(row.get("broker_order_no", "") or "").upper().strip()
    if order_type in ("RECON", "AUDIT") or order_no.startswith("RECONCILE-"):
        return None
    action = _normalize_trade_action(row.get("action", ""))
    if action not in ("BUY", "SELL"):
        if action not in ("SKIP", "ERROR"):
            return None
        created = row.get("created", "")
        timestamp = _to_kst_string(created, fmt="%Y-%m-%d %H:%M:%S") if created else str(row.get("trade_date", "") or "")
        return {
            "id": f"cycle-attempt:{row.get('id', '') or row.get('cycle_id', '')}:{timestamp}",
            "timestamp": timestamp,
            "market": "US",
            "market_label": "미장",
            "symbol": str(row.get("symbol", "") or "").upper(),
            "name": str(row.get("symbol", "") or "").upper(),
            "strategy": "무한매수",
            "strategy_id": str(row.get("cycle_id", "") or ""),
            "cycle_id": str(row.get("cycle_id", "") or ""),
            "action": action,
            "action_detail": f"INFINITE_{action}",
            "order_type": str(row.get("order_type", "") or ""),
            "order_no": str(row.get("broker_order_no", "") or ""),
            "price": round(_safe_float(row.get("order_price", 0), 0), 4),
            "qty": _safe_int(row.get("order_qty", 0), 0),
            "amount": 0.0,
            "realized": 0.0,
            "matched_buy_amount": 0.0,
            "fee": 0.0,
            "avg_buy_price": 0.0,
            "post_position_qty": _safe_int(row.get("total_qty_after", 0), 0),
            "post_avg_price": round(_safe_float(row.get("avg_buy_price", 0), 0), 4),
            "message": _sanitize_user_log_message(str(row.get("memo", "") or "주문이 체결되지 않았습니다.")),
            "status": "REJECTED" if action in ("SKIP", "ERROR") else str(row.get("status", "") or ""),
            "source": "cycle_trade",
            "_sort": _daytrade_sort_key(timestamp),
        }
    symbol = str(row.get("symbol", "") or "").upper()
    market = _daytrade_market("", symbol, "US")
    price = _safe_float(row.get("filled_price", 0), 0) or _safe_float(row.get("order_price", 0), 0)
    qty = _safe_int(row.get("filled_qty", 0), 0) or _safe_int(row.get("order_qty", 0), 0)
    amount = _safe_float(row.get("filled_amount", 0), 0) or (price * qty)
    if qty <= 0 or price <= 0:
        return None

    avg_buy_price = _safe_float(row.get("avg_buy_price", 0), 0)
    commission = _safe_float(row.get("commission", 0), 0)
    realized = 0.0
    matched_buy_amount = 0.0
    if action == "SELL":
        matched_buy_amount = avg_buy_price * qty if avg_buy_price > 0 else 0.0
        if matched_buy_amount > 0:
            realized = amount - matched_buy_amount - max(0.0, commission)

    trade_date = str(row.get("trade_date", "") or "").strip()
    created = row.get("created", "")
    if created:
        timestamp = _to_kst_string(created, fmt="%Y-%m-%d %H:%M:%S")
    elif trade_date:
        timestamp = f"{trade_date[:10]} 00:00:00"
    else:
        timestamp = ""

    order_type = str(row.get("order_type", "") or "")
    memo = str(row.get("memo", "") or "")
    message_parts = ["무한매수", f"{order_type} {action}".strip()]
    if memo:
        message_parts.append(memo)

    return {
        "id": f"cycle:{row.get('id', '') or row.get('broker_order_no', '') or symbol + ':' + timestamp}",
        "timestamp": timestamp,
        "market": market,
        "market_label": "미장" if market == "US" else "국장",
        "symbol": symbol,
        "name": symbol,
        "strategy": "무한매수",
        "strategy_id": str(row.get("cycle_id", "") or ""),
        "cycle_id": str(row.get("cycle_id", "") or ""),
        "action": action,
        "action_detail": "INFINITE_BUY" if action == "BUY" else "INFINITE_SELL",
        "order_type": order_type,
        "order_no": str(row.get("broker_order_no", "") or ""),
        "price": round(price, 4),
        "qty": qty,
        "amount": round(amount, 2),
        "realized": round(realized, 2),
        "matched_buy_amount": round(matched_buy_amount, 2),
        "fee": round(commission, 4),
        "avg_buy_price": round(avg_buy_price if action == "SELL" else 0, 4),
        "post_position_qty": _safe_int(row.get("total_qty_after", 0), 0),
        "post_avg_price": round(_safe_float(row.get("avg_buy_price", 0), 0), 4),
        "message": _sanitize_user_log_message(" | ".join([part for part in message_parts if part])),
        "status": str(row.get("status", "") or "FILLED"),
        "source": "cycle_trade",
        "_sort": _daytrade_sort_key(timestamp),
    }

# ── Fast reads ───────────────────────────────────────────────────────────
# sqlite3 releases the GIL for every fetched row. With the trading workers
# busy, taking it back cost 10-70 ms a row, so the history page's 900-row
# reads took 10-30 s. Each read below asks SQLite for one JSON row instead.

_READ_STATE = {"fallback": ""}

def _scoped_user_ids(db):
    """The user_id values _UserScopedDb.rows() would read for this session."""
    uid_fn = getattr(db, "_uid", None)
    if not callable(uid_fn):
        return None
    uid = str(uid_fn() or "").strip()
    if uid:
        return [uid, ""] if db._is_admin(uid) else [uid]
    return [""]

def _execute_one(trading, table, sql_builder):
    db = trading.db(table)
    raw = getattr(db, "_db", db)
    database = raw.orm._meta.database
    users = _scoped_user_ids(db)
    sql, args = sql_builder(users)
    raw._db_enter()
    try:
        return database.execute_sql(sql, args).fetchone()
    finally:
        raw._close_connection()
        raw._db_exit()

def _where_sql(users, where="", params=()):
    clauses, args = [], []
    if users is not None:
        clauses.append("user_id IN (%s)" % ",".join("?" for _ in users))
        args.extend(users)
    if where:
        clauses.append(f"({where})")
        args.extend(params)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", args

def _json_rows(trading, table, columns, where="", params=(), order_by="created DESC", limit=0, offset=0, distinct=False):
    def build(users):
        where_sql, args = _where_sql(users, where, params)
        inner = f'SELECT {"DISTINCT " if distinct else ""}{", ".join(columns)} FROM "{table}"{where_sql}'
        if order_by:
            inner += f" ORDER BY {order_by}"
        if limit:
            inner += f" LIMIT {int(limit)} OFFSET {max(0, int(offset or 0))}"
        pairs = ", ".join(f"'{column}', {column}" for column in columns)
        return f"SELECT json_group_array(json_object({pairs})) FROM ({inner})", args
    row = _execute_one(trading, table, build)
    return json.loads(row[0]) if row and row[0] else []

def _json_count(trading, table, where="", params=()):
    def build(users):
        where_sql, args = _where_sql(users, where, params)
        return f'SELECT count(*) FROM "{table}"{where_sql}', args
    row = _execute_one(trading, table, build)
    return int(row[0] or 0) if row else 0

def _read_fallback(name, error):
    _READ_STATE["fallback"] = f"{name}: {error}"[:200]

_DT_LOG_COLUMNS = ("id", "event_type", "symbol", "action", "order_no", "order_price", "order_qty",
                   "filled_price", "filled_qty", "message", "raw_response", "created")
# Rejections are ~90% of DT_ rows (1,128 TQQQ SELL_FULL retries alone) and never fills.
_DT_FILL_WHERE = "substr(event_type, 1, 3) = 'DT_' AND substr(event_type, -6) <> '_ERROR'"

def _daytrade_log_rows(trading, limit=3000):
    try:
        return _json_rows(trading, "trade_log", _DT_LOG_COLUMNS, where=_DT_FILL_WHERE, limit=limit)
    except Exception as e:
        _read_fallback("trade_log", e)
    try:
        rows = trading.db("trade_log").rows(event_type__startswith="DT_", orderby="created", order="DESC", dump=limit) or []
    except Exception:
        return []
    return [row for row in rows if not str(row.get("event_type", "") or "").upper().endswith("_ERROR")]

_CYCLE_TRADE_COLUMNS = ("id", "cycle_id", "symbol", "round", "trade_date", "action", "order_type", "order_price",
                        "order_qty", "filled_price", "filled_qty", "filled_amount", "commission", "avg_buy_price",
                        "total_qty_after", "status", "memo", "broker_order_no", "created")

def _cycle_trade_rows(trading, limit=3000):
    try:
        return _json_rows(trading, "cycle_trade", _CYCLE_TRADE_COLUMNS, limit=limit)
    except Exception as e:
        _read_fallback("cycle_trade", e)
    try:
        return trading.db("cycle_trade").rows(orderby="created", order="DESC", dump=limit) or []
    except Exception:
        return []

_CYCLE_COLUMNS = ("id", "symbol", "cycle_number", "status", "current_round", "division_count", "target_profit",
                  "total_investment", "total_spent", "total_qty", "avg_price", "current_price", "current_eval",
                  "profit_rate", "total_commission", "started_at", "completed_at", "created", "updated")

def _cycle_rows(trading):
    try:
        rows = _json_rows(trading, "trading_cycle", _CYCLE_COLUMNS, order_by="updated DESC", limit=1000)
    except Exception as e:
        _read_fallback("trading_cycle", e)
        try:
            rows = trading.db("trading_cycle").rows(orderby="updated", order="DESC") or []
        except Exception:
            rows = []
    for row in rows:
        for key in ("started_at", "completed_at", "created", "updated"):
            if row.get(key):
                row[key] = str(row[key])[:19]
    return rows

# ── Fill records ─────────────────────────────────────────────────────────

def _order_strategy_map(state_map):
    """order_no -> strategy_id from the day-trade state; trade_log rows before
    2026-10-16 did not record the strategy."""
    mapping = {}
    for state in (state_map or {}).values():
        if not isinstance(state, dict):
            continue
        for order in state.get("orders", []) or []:
            order_no = str((order or {}).get("order_no", "") or "").strip().lstrip("0")
            strategy_id = str((order or {}).get("strategy_id", "") or "").strip()
            if order_no and strategy_id:
                mapping[order_no] = strategy_id
    return mapping

def _collect_daytrade_trades(trading, max_log_rows=3000):
    max_log_rows = max(100, int(max_log_rows or 3000))
    cache_key = f"{_history_cache_scope()}:daytrade_records:{max_log_rows}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    record_by_key = {}
    for row in _daytrade_log_rows(trading, limit=max_log_rows):
        record = _daytrade_record_from_log(row)
        if not _is_visible_daytrade_record(record):
            continue
        key = _daytrade_record_key(record)
        record_by_key[key] = _merge_daytrade_record(record_by_key.get(key), record)

    state_map = _load_daytrade_state(trading)
    for state_key, state in (state_map or {}).items():
        if not isinstance(state, dict):
            continue
        state_records = _daytrade_records_from_state_orders(str(state_key), state)
        for record in state_records:
            if not _is_visible_daytrade_record(record):
                continue
            key = _daytrade_record_key(record)
            record_by_key[key] = _merge_daytrade_record(record_by_key.get(key), record)

        synthetic = _synthetic_realized_record_from_state(str(state_key), state)
        if synthetic and _is_executable_daytrade_record(synthetic):
            key = _daytrade_record_key(synthetic)
            has_presell_fill = any(
                item.get("action") == "SELL"
                and item.get("source") == "live_state_presell_fill"
                and str(item.get("order_no", "") or "") == str(synthetic.get("order_no", "") or "")
                for item in state_records
            )
            if not has_presell_fill:
                record_by_key[key] = _merge_daytrade_record(record_by_key.get(key), synthetic)

    strategies = _order_strategy_map(state_map)
    records = list(record_by_key.values())
    for record in records:
        if not record.get("strategy_id"):
            record["strategy_id"] = strategies.get(str(record.get("order_no", "") or "").strip().lstrip("0"), "")
    records.sort(key=lambda x: x.get("_sort", ""), reverse=True)
    _cache_set(cache_key, records)
    return records

def _collect_cycle_trade_records(trading, max_rows=3000):
    max_rows = max(100, int(max_rows or 3000))
    cache_key = f"{_history_cache_scope()}:cycle_trade_records:{max_rows}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    records = [record for record in map(_cycle_trade_record_from_row, _cycle_trade_rows(trading, limit=max_rows)) if record]
    records.sort(key=lambda x: x.get("_sort", ""), reverse=True)
    _cache_set(cache_key, records)
    return records

def _collect_trade_history_records(trading, max_log_rows=3000):
    record_by_key = {}
    for record in _collect_daytrade_trades(trading, max_log_rows=max_log_rows):
        normalized = dict(record)
        normalized.setdefault("strategy", "단타")
        record_by_key[f"daytrade:{_daytrade_record_key(normalized)}"] = normalized
    for record in _collect_cycle_trade_records(trading, max_rows=max_log_rows):
        record_by_key[_cycle_trade_record_key(record)] = record
    records = list(record_by_key.values())
    records.sort(key=lambda x: x.get("_sort", ""), reverse=True)
    return records

# ── Closed trades and statistics ─────────────────────────────────────────

_STRATEGY_LABELS = {
    "vrev": "눌림 반등", "volume_breakout": "거래량 돌파", "paper_regime_trend": "방향 추세",
    "paper_momentum_ride": "급등주 편승", "us_premarket": "갭업 하따", "us_breakout": "돌파",
    "us_pullback": "눌림", "us_vwap": "VWAP", "us_opening_reclaim": "시가 회복",
    "paper_selective_breakout": "선택 돌파", "paper_selective_pullback": "선택 눌림",
    "infinite_buy": "무한매수",
}
_PERIOD_DAYS = {"1D": 1, "1W": 7, "1M": 30, "3M": 90}

def _strategy_label(strategy_id):
    strategy_id = str(strategy_id or "").strip()
    return _STRATEGY_LABELS.get(strategy_id, strategy_id or "미분류")

def _record_strategy_id(record):
    if str(record.get("source", "") or "") == "cycle_trade":
        return "infinite_buy"
    return str(record.get("strategy_id", "") or "").strip()

def _exit_kind(action_detail="", message=""):
    detail = str(action_detail or "").upper()
    text = str(message or "")
    if detail.startswith("INFINITE"):
        return "infinite", "무한매수 매도"
    if "STOP_LOSS" in detail or "손절" in text:
        return "stop", "손절"
    if "JACKPOT" in detail or "익절" in text or "목표가" in text:
        return "target", "익절"
    if "DELEVERAGE" in detail:
        return "deleverage", "노출 축소"
    if "MANUAL" in detail:
        return "manual", "수동 매도"
    if "평탄화" in text or "장마감" in text or "오버나잇" in text:
        return "close", "장마감 청산"
    if "PARTIAL" in detail:
        return "partial", "분할 매도"
    return "exit", "청산"

_BUY_LABELS = {"BUY1": "1차 매수", "BUY2": "2차 매수", "INFINITE_BUY": "LOC 매수"}

def _fill_label(record):
    action = _normalize_trade_action(record.get("action", ""))
    detail = str(record.get("action_detail", "") or "").upper()
    if action == "BUY":
        return _BUY_LABELS.get(detail, "매수")
    return _exit_kind(detail, record.get("message", ""))[1]

# Mirrors DomesticDaytradeEngine._kr_sell_tax_exempt: domestic ETFs and ETNs
# pay no 0.18% transaction tax on the sale.
_KR_FUND_BRANDS = (
    "KODEX", "TIGER", "RISE", "KBSTAR", "ACE", "SOL", "HANARO", "KOSEF", "PLUS", "ARIRANG", "KIWOOM",
    "TIMEFOLIO", "WON", "1Q", "BNK", "TREX", "FOCUS", "KOACT", "UNICORN", "TRUSTON", "DAISHIN343", "VITA",
    "마이다스", "에셋플러스", "히어로즈", "마이티",
)
_KR_STOCK_SELL_TAX = 0.0018

def _kr_tax_exempt(name=""):
    text = str(name or "").strip().upper()
    return bool(text) and ("ETN" in text or any(text.startswith(brand + " ") for brand in _KR_FUND_BRANDS))

def _estimated_fee(market, cost, proceeds, name=""):
    # Same schedule as the engine's own log lines.
    if market == "US":
        return cost * 0.0025 + proceeds * 0.0025 + proceeds / 1_000_000.0 * 8.0
    tax = 0.0 if _kr_tax_exempt(name) else _KR_STOCK_SELL_TAX
    return cost * 0.00015 + proceeds * (0.00015 + tax)

def _minutes_between(start, end):
    try:
        a = datetime.datetime.strptime(str(start)[:19], "%Y-%m-%d %H:%M:%S")
        b = datetime.datetime.strptime(str(end)[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None
    return max(0, int((b - a).total_seconds() // 60))

def _closed_trades(records, cycles_by_id=None):
    """Pair fills into closed trades on the engine's average-cost book.

    Net P&L prefers the engine's own figure (the "순손익" in its log line, or
    the state FIFO result); only otherwise is it estimated from the book."""
    cycles_by_id = cycles_by_id or {}
    books = {}
    trips = []
    for record in sorted(records, key=lambda r: r.get("_sort", "") or r.get("timestamp", "")):
        if not _is_executable_daytrade_record(record):
            continue
        action = _normalize_trade_action(record.get("action", ""))
        market = "US" if str(record.get("market", "") or "").upper() == "US" else "KS"
        symbol = str(record.get("symbol", "") or "").upper()
        qty = _safe_int(record.get("qty", 0), 0)
        price = _safe_float(record.get("price", 0), 0)
        source = str(record.get("source", "") or "")
        infinite = source == "cycle_trade"
        strategy_id = _record_strategy_id(record)
        book = books.setdefault((market, symbol, infinite), {"qty": 0, "avg": 0.0, "opened_at": "", "strategy_id": ""})
        if action == "BUY":
            if book["qty"] <= 0:
                book.update(qty=0, avg=0.0, opened_at=record.get("timestamp", ""), strategy_id=strategy_id)
            total = book["qty"] + qty
            book["avg"] = (book["avg"] * book["qty"] + price * qty) / total if total > 0 else 0.0
            book["qty"] = total
            book["strategy_id"] = book["strategy_id"] or strategy_id
            continue
        if action != "SELL":
            continue

        held = min(qty, book["qty"]) if book["qty"] > 0 else 0
        avg = book["avg"] if held > 0 else 0.0
        entry_at = book["opened_at"] if held > 0 else ""
        trip_strategy = (book["strategy_id"] if held > 0 else "") or strategy_id
        if infinite:
            cycle = cycles_by_id.get(str(record.get("cycle_id", "") or ""), {}) or {}
            entry_at = entry_at or str(cycle.get("started_at", "") or "")[:19]
        if avg <= 0 and qty > 0:
            avg = _safe_float(record.get("avg_buy_price", 0), 0) or _safe_float(record.get("matched_buy_amount", 0), 0) / qty
        cost = avg * qty if avg > 0 else 0.0
        proceeds = price * qty
        logged_net = _safe_float(record.get("net_realized", 0), 0)
        engine_gross = _safe_float(record.get("engine_gross", 0), 0)
        # The state FIFO "realized" is not used: when the state's own orders do
        # not cover a sale it books the unmatched proceeds as fee (069500
        # 09-18: a ₩18M fee on an ₩87M sale).
        unmatched_qty = 0
        name = str(record.get("name", "") or "")
        if abs(logged_net) > 1e-9:
            net, fee = logged_net, max(0.0, _safe_float(record.get("fee", 0), 0))
            if market == "KS" and _kr_tax_exempt(name) and fee >= proceeds * _KR_STOCK_SELL_TAX * 0.9:
                # Logged before 10-16, when the engine charged ETFs the stock tax.
                fee -= proceeds * _KR_STOCK_SELL_TAX
                net += proceeds * _KR_STOCK_SELL_TAX
            if cost <= 0:
                cost = max(0.0, proceeds - net - fee)
                avg = cost / qty if qty > 0 else 0.0
        elif abs(engine_gross) > 1e-9 and not infinite and held < qty:
            # The engine's own average cost covers buys missing from the logs.
            cost = max(0.0, proceeds - engine_gross)
            avg = cost / qty if qty > 0 else 0.0
            fee = _estimated_fee(market, cost, proceeds, name)
            net = engine_gross - fee
        elif cost > 0:
            matched_qty = qty
            if not infinite and 0 < held < qty:
                # 069500 09-18 sold 793 shares with only 629 bought on record:
                # count the P&L of the shares whose purchase is known.
                matched_qty, unmatched_qty = held, qty - held
            cost = avg * matched_qty
            matched_proceeds = price * matched_qty
            fee = max(0.0, _safe_float(record.get("fee", 0), 0)) if infinite else _estimated_fee(market, cost, matched_proceeds, name)
            net = matched_proceeds - cost - fee
        else:
            net, fee = 0.0, 0.0

        if held > 0:
            book["qty"] -= held
            if book["qty"] <= 0:
                book.update(qty=0, avg=0.0, opened_at="", strategy_id="")
        exit_kind, exit_label = _exit_kind(record.get("action_detail", ""), record.get("message", ""))
        trips.append({
            "id": str(record.get("id", "") or ""),
            "market": market,
            "symbol": symbol,
            "name": str(record.get("name", "") or symbol),
            "strategy_id": trip_strategy,
            "strategy_label": _strategy_label(trip_strategy),
            "cycle_id": str(record.get("cycle_id", "") or "") if infinite else "",
            "entry_at": str(entry_at or "")[:19],
            "exit_at": str(record.get("timestamp", "") or "")[:19],
            "hold_min": _minutes_between(entry_at, record.get("timestamp", "")) if entry_at else None,
            "qty": qty,
            "entry_price": round(avg, 4),
            "exit_price": round(price, 4),
            "cost": round(cost, 2),
            "proceeds": round(proceeds, 2),
            "fee": round(fee, 2),
            "net": round(net, 2),
            "return_pct": round(net / cost * 100, 2) if cost > 0 else None,
            "cost_known": cost > 0,
            "unmatched_qty": unmatched_qty,
            "partial": held > 0 and book["qty"] > 0,
            "exit_kind": exit_kind,
            "exit_label": exit_label,
            "reason": _sanitize_user_log_message(record.get("message", "")),
        })
    trips.sort(key=lambda t: t["exit_at"], reverse=True)
    return trips

def _trade_stats(trips):
    # A sale whose purchase never reached the logs has no P&L to count.
    trips = [t for t in (trips or []) if t.get("cost_known", True)]
    wins = [t for t in trips if t["net"] > 0]
    losses = [t for t in trips if t["net"] < 0]
    gross_win = sum(t["net"] for t in wins)
    gross_loss = -sum(t["net"] for t in losses)
    returns = [t["return_pct"] for t in trips if t.get("return_pct") is not None]
    holds = [t["hold_min"] for t in trips if t.get("hold_min") is not None]

    def brief(trip):
        return {key: trip.get(key) for key in ("symbol", "name", "net", "return_pct", "exit_at")} if trip else None

    return {
        "closed": len(trips),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trips) * 100, 1) if trips else None,
        "net": round(sum(t["net"] for t in trips), 2),
        "fees": round(sum(t["fee"] for t in trips), 2),
        "avg_win": round(gross_win / len(wins), 2) if wins else None,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "avg_return_pct": round(sum(returns) / len(returns), 2) if returns else None,
        "avg_hold_min": int(sum(holds) / len(holds)) if holds else None,
        "best": brief(max(trips, key=lambda t: t["net"])) if wins else None,
        "worst": brief(min(trips, key=lambda t: t["net"])) if losses else None,
    }

def _period_start(period):
    days = _PERIOD_DAYS.get(str(period or "").upper())
    if not days:
        return ""
    today = datetime.datetime.now(KST).date()
    return (today - datetime.timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00:00")

def _fill_row(record, trip_by_id):
    market = "US" if str(record.get("market", "") or "").upper() == "US" else "KS"
    strategy_id = _record_strategy_id(record)
    trip = trip_by_id.get(str(record.get("id", "") or ""))
    return {
        "id": str(record.get("id", "") or ""),
        "timestamp": str(record.get("timestamp", "") or "")[:19],
        "market": market,
        "symbol": str(record.get("symbol", "") or "").upper(),
        "name": str(record.get("name", "") or record.get("symbol", "") or ""),
        "side": _normalize_trade_action(record.get("action", "")),
        "label": _fill_label(record),
        "strategy_id": strategy_id,
        "strategy_label": _strategy_label(strategy_id),
        "qty": _safe_int(record.get("qty", 0), 0),
        "price": round(_safe_float(record.get("price", 0), 0), 4),
        "amount": round(_safe_float(record.get("amount", 0), 0) or _safe_float(record.get("price", 0), 0) * _safe_int(record.get("qty", 0), 0), 2),
        "net": trip["net"] if trip else None,
        "return_pct": trip["return_pct"] if trip else None,
        "reason": _sanitize_user_log_message(record.get("message", "")),
    }

def _build_trades_payload(trading, period="1M", market="", strategy=""):
    timings = {}
    started = time.monotonic()

    def mark(name):
        timings[name] = round((time.monotonic() - started) * 1000)

    records = _collect_trade_history_records(trading)
    mark("records")
    cycles_by_id = {str(row.get("id", "")): row for row in _cycle_rows(trading)}
    trips_all = _closed_trades(records, cycles_by_id)
    trip_by_id = {trip["id"]: trip for trip in trips_all if trip.get("id")}
    mark("trips")

    since = _period_start(period)
    in_period = [t for t in trips_all if not since or t["exit_at"] >= since]
    in_market = [t for t in in_period if not market or t["market"] == market]
    trips = [t for t in in_market if not strategy or t["strategy_id"] == strategy]

    fills = []
    for record in records:
        if not _is_executable_daytrade_record(record):
            continue
        row = _fill_row(record, trip_by_id)
        if since and row["timestamp"] < since:
            continue
        if market and row["market"] != market:
            continue
        if strategy and row["strategy_id"] != strategy:
            continue
        fills.append(row)
    fills.sort(key=lambda r: r["timestamp"], reverse=True)

    summary = {}
    for key in ("KS", "US"):
        market_trips = [t for t in trips if t["market"] == key]
        market_fills = [f for f in fills if f["market"] == key]
        if not market_trips and not market_fills:
            continue
        stats = _trade_stats(market_trips)
        stats.update({
            "currency": "USD" if key == "US" else "KRW",
            "fill_count": len(market_fills),
            "buy_amount": round(sum(f["amount"] for f in market_fills if f["side"] == "BUY"), 2),
            "sell_amount": round(sum(f["amount"] for f in market_fills if f["side"] == "SELL"), 2),
        })
        summary[key] = stats

    groups = {}
    for trip in in_market:
        groups.setdefault((trip["market"], trip["strategy_id"]), []).append(trip)
    strategies = []
    for (group_market, strategy_id), group in groups.items():
        stats = _trade_stats(group)
        strategies.append({
            "market": group_market,
            "strategy_id": strategy_id,
            "label": _strategy_label(strategy_id),
            "closed": stats["closed"],
            "wins": stats["wins"],
            "win_rate": stats["win_rate"],
            "net": stats["net"],
            "avg_return_pct": stats["avg_return_pct"],
            "avg_hold_min": stats["avg_hold_min"],
            "profit_factor": stats["profit_factor"],
            "last_exit_at": max(t["exit_at"] for t in group),
        })
    strategies.sort(key=lambda s: (s["market"] != "KS", -s["closed"], s["label"]))

    daily = {}
    for trip in trips:
        if not trip.get("cost_known", True):
            continue
        day = trip["exit_at"][:10]
        bucket = daily.setdefault(day, {"date": day, "KS": 0.0, "US": 0.0, "closed": 0})
        bucket[trip["market"]] = round(bucket[trip["market"]] + trip["net"], 2)
        bucket["closed"] += 1

    options = {}
    for trip in trips_all:
        options.setdefault(trip["strategy_id"], trip["strategy_label"])
    for record in records:
        if _is_executable_daytrade_record(record):
            strategy_id = _record_strategy_id(record)
            options.setdefault(strategy_id, _strategy_label(strategy_id))
    mark("total")
    return {
        "period": str(period or "").upper(),
        "since": since,
        "summary": summary,
        "strategies": strategies,
        "daily": [daily[day] for day in sorted(daily)][-60:],
        "trips": trips[:500],
        "trip_count": len(trips),
        "fills": fills[:800],
        "fill_count": len(fills),
        "strategy_options": [{"id": key, "label": label} for key, label in sorted(options.items(), key=lambda item: item[1])],
        "timings_ms": timings,
        "read_fallback": _READ_STATE.get("fallback", ""),
    }

# ── Endpoints ────────────────────────────────────────────────────────────

def trades():
    """거래이력: 기간별 실현손익, 전략 성과, 왕복 거래, 체결 내역."""
    trading = struct.trading
    period = str(wiz.request.query("period", "1M") or "1M").upper()
    market = str(wiz.request.query("market", "") or "").upper()
    if market not in ("", "KS", "US"):
        market = ""
    strategy = str(wiz.request.query("strategy", "") or "").strip()
    cache_key = f"{_history_cache_scope()}:trades:{period}:{market}:{strategy}"
    payload = _cache_get(cache_key)
    if payload is None:
        payload = _build_trades_payload(trading, period=period, market=market, strategy=strategy)
        _cache_set(cache_key, payload)
    wiz.response.status(200, **payload)

def symbols():
    """사이클·로그 필터용 종목 목록"""
    trading = struct.trading
    found = set()
    for table in ("etf_watchlist", "trading_cycle", "cycle_trade", "trade_log"):
        try:
            rows = _json_rows(trading, table, ("symbol",), order_by="", distinct=True)
        except Exception as e:
            _read_fallback(table, e)
            rows = []
        found.update(str(row.get("symbol", "") or "").upper() for row in rows)
    wiz.response.status(200, data=sorted(symbol for symbol in found if symbol))

def _is_empty_cycle(cycle):
    """Completed with no round, no spend and no result: nothing to review."""
    return (str(cycle.get("status", "") or "").upper() == "COMPLETED"
            and _safe_int(cycle.get("current_round", 0), 0) <= 0
            and _safe_float(cycle.get("total_spent", 0), 0) <= 0
            and abs(_safe_float(cycle.get("profit_rate", 0), 0)) < 1e-9)

def cycles():
    """무한매수 사이클 목록 (필터 + 페이징)"""
    trading = struct.trading
    page = max(1, _safe_int(wiz.request.query("page", 1), 1))
    dump = 15
    status = str(wiz.request.query("status", "") or "").upper()
    symbol = str(wiz.request.query("symbol", "") or "").upper()

    all_cycles = _cycle_rows(trading)
    # Same average-cost book as the trades tab: sell rows often carry no
    # avg_buy_price, which left their realized P&L at zero.
    realized_by_cycle = {}
    for trip in _closed_trades(_collect_cycle_trade_records(trading), {str(c.get("id", "")): c for c in all_cycles}):
        if trip.get("cost_known") and trip.get("cycle_id"):
            realized_by_cycle[trip["cycle_id"]] = realized_by_cycle.get(trip["cycle_id"], 0.0) + trip["net"]

    rows = []
    now = datetime.datetime.now(KST).replace(tzinfo=None)
    for cycle in all_cycles:
        if _is_empty_cycle(cycle):
            continue
        if status and str(cycle.get("status", "") or "").upper() != status:
            continue
        if symbol and str(cycle.get("symbol", "") or "").upper() != symbol:
            continue
        cycle["realized"] = round(realized_by_cycle.get(str(cycle.get("id", "")), 0.0), 2)
        end = cycle.get("completed_at") or now.strftime("%Y-%m-%d %H:%M:%S")
        minutes = _minutes_between(cycle.get("started_at", ""), end)
        cycle["days"] = round(minutes / 1440, 1) if minutes is not None else None
        rows.append(cycle)

    total = len(rows)
    total_pages = max(1, math.ceil(total / dump))
    start = (page - 1) * dump
    wiz.response.status(200, rows=rows[start:start + dump], total=total, total_pages=total_pages, page=page)

_LOG_COLUMNS = ("id", "created", "symbol", "event_type", "action", "order_price", "order_qty",
                "filled_price", "filled_qty", "message")
# Written on every automation pass; they drown the order events (≈90% of trade_log).
_SYSTEM_EVENT_TYPES = (
    "IB_LOC_AUTOMATION_RUN", "IB_LOC_BUY_SKIPPED", "IB_LOC_SELL_SKIPPED",
    "IB_LOC_BUY_ALREADY_SCHEDULED", "IB_LOC_SELL_ALREADY_SCHEDULED",
    "IB_LOC_BUY_MISSING_FOR_REBUILD", "IB_LOC_SELL_MISSING_FOR_REBUILD",
    "IB_EXTERNAL_CYCLE_SYNC_RUN", "IB_BROKER_HOLDING_SNAPSHOT_ALIGNED",
)
_DT_EVENT_LABELS = {
    "BUY": "매수", "BUY1": "1차 매수", "BUY2": "2차 매수", "SELL_FULL": "전량 매도",
    "SELL_STOP_LOSS": "손절 매도", "PRE_SELL_JACKPOT": "목표가 매도", "SELL_DELEVERAGE": "노출 축소 매도",
    "SELL_MANUAL": "수동 매도", "SELL_MANUAL_NOW": "수동 매도", "SELL_PARTIAL": "분할 매도",
    "SELL_RESCUE": "구조 매도", "SELL_RECENT": "매도",
}
_IB_EVENT_LABELS = {
    "IB_BUY_FILLED": "매수 체결", "IB_SELL_FILLED": "매도 체결", "IB_PARTIAL_SELL_FILLED": "분할매도 체결",
    "IB_PAPER_LOC_SUBMITTED": "LOC 주문 제출", "IB_PAPER_LOC_INTENT": "LOC 주문 계획",
    "IB_LOC_BUY_ERROR": "LOC 매수 오류", "IB_LOC_SELL_ERROR": "LOC 매도 오류", "IB_BUY_ERROR": "매수 오류",
    "IB_ERROR": "오류", "IB_SKIP": "건너뜀", "IB_LOC_BUY_SCHEDULED": "LOC 매수 예약",
    "IB_LOC_SELL_SCHEDULED": "LOC 매도 예약", "IB_LOC_AUTOMATION_RUN": "LOC 자동 점검",
    "IB_LOC_BUY_MISSING_FOR_REBUILD": "LOC 매수 재구성", "IB_LOC_SELL_MISSING_FOR_REBUILD": "LOC 매도 재구성",
    "IB_EXTERNAL_TRADE_SYNCED": "KIS 체결 반영", "IB_EXTERNAL_TRADE_CORRECTED": "KIS 체결 정정",
    "IB_EXTERNAL_CYCLE_SYNC_RUN": "KIS 동기화", "IB_CYCLE_START": "사이클 시작",
    "IB_CYCLE_AUTO_RESTART": "사이클 자동 재시작", "IB_PENDING_EXTENSION": "미체결 연장",
    "IB_BROKER_HOLDING_SNAPSHOT_ALIGNED": "보유 수량 정렬", "IB_PAPER_ROUND_REPAIRED": "회차 보정",
    "IB_WATCHLIST_AUTO_CREATE": "관심종목 자동 등록", "IB_WATCHLIST_AUTO_ACTIVATE": "관심종목 자동 활성화",
    "IB_LOC_BUY_SKIPPED": "LOC 매수 생략", "IB_LOC_SELL_SKIPPED": "LOC 매도 생략",
    "IB_LOC_BUY_ALREADY_SCHEDULED": "LOC 매수 예약 유지", "IB_LOC_SELL_ALREADY_SCHEDULED": "LOC 매도 예약 유지",
    "IB_LOC_RESERVATION_CANCELLED": "LOC 예약 취소", "IB_LOC_BUY_PRICE_MISMATCH": "LOC 가격 불일치",
    "IB_FIREGATE_TRADE_SYNCED": "FireGate 체결 반영", "IB_CYCLE_DELETE": "사이클 삭제",
}

def _event_label(event_type=""):
    """(label, tone, lane) for a trade_log event type."""
    event = str(event_type or "").upper()
    if event.startswith("DT_KS_") or event.startswith("DT_US_"):
        lane = "국장 단타" if event.startswith("DT_KS_") else "미장 단타"
        body, suffix, tone = event[6:], "", ""
        if body.endswith("_ERROR"):
            body, suffix, tone = body[:-6], " 거절", "error"
        elif body.endswith("_PENDING"):
            body, suffix, tone = body[:-8], " 접수", "pending"
        tone = tone or ("buy" if body.startswith("BUY") else "sell")
        return _DT_EVENT_LABELS.get(body, body) + suffix, tone, lane
    label = _IB_EVENT_LABELS.get(event, event.replace("_", " ").title())
    if "ERROR" in event or "CANCEL" in event or "MISMATCH" in event:
        tone = "error"
    elif "BUY" in event:
        tone = "buy"
    elif "SELL" in event:
        tone = "sell"
    else:
        tone = "info"
    return label, tone, "무한매수" if event.startswith("IB_") else "시스템"

def trade_logs():
    """주문·체결 로그 (종류 + 종목 + 검색 + 페이징)"""
    trading = struct.trading
    page = max(1, _safe_int(wiz.request.query("page", 1), 1))
    dump = 30
    symbol = str(wiz.request.query("symbol", "") or "").upper().strip()
    kind = str(wiz.request.query("kind", "") or "").lower().strip()
    search = str(wiz.request.query("search", "") or "").strip()

    clauses, params = [], []
    if kind == "error":
        clauses.append("(event_type LIKE '%ERROR%' OR action IN ('ERROR', 'SKIP'))")
    elif kind != "all":
        clauses.append("event_type NOT IN (%s)" % ",".join("?" for _ in _SYSTEM_EVENT_TYPES))
        params.extend(_SYSTEM_EVENT_TYPES)
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol)
    if search:
        clauses.append("(message LIKE ? OR event_type LIKE ? OR symbol LIKE ?)")
        params.extend([f"%{search}%"] * 3)
    where = " AND ".join(clauses)
    try:
        total = _json_count(trading, "trade_log", where, params)
        rows = _json_rows(trading, "trade_log", _LOG_COLUMNS, where=where, params=params,
                          limit=dump, offset=(page - 1) * dump)
    except Exception as e:
        _read_fallback("trade_log", e)
        wiz.response.status(503, message="로그를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")

    rows.sort(key=lambda r: str(r.get("created", "") or ""), reverse=True)
    for row in rows:
        event = str(row.get("event_type", "") or "")
        row["created"] = _to_kst_string(row.get("created", ""), fmt="%Y-%m-%d %H:%M:%S")
        row["label"], row["tone"], row["lane"] = _event_label(event)
        row["market"] = _daytrade_market(event, row.get("symbol", ""), "US" if event.upper().startswith("IB_") else "KS")
        row["message"] = _sanitize_user_log_message(row.get("message", ""))
    total_pages = max(1, math.ceil(total / dump))
    wiz.response.status(200, rows=rows, total=total, total_pages=total_pages, page=page,
                        has_more=page < total_pages)

def cycle_detail():
    """사이클 상세 + 거래 내역"""
    trading = struct.trading
    cycle_id = wiz.request.query("cycle_id", True)

    cycle_db = trading.db("trading_cycle")
    trade_db = trading.db("cycle_trade")

    cycle = cycle_db.get(id=cycle_id)
    if not cycle:
        wiz.response.status(404, message="Cycle not found")

    # datetime → string
    for k in ("started_at", "completed_at", "created", "updated"):
        if cycle.get(k):
            cycle[k] = str(cycle[k])

    trades = trade_db.rows(cycle_id=cycle_id, orderby="round", order="ASC")
    for t in trades:
        if t.get("created"):
            t["created"] = str(t["created"])

    wiz.response.status(200, cycle=cycle, trades=trades)

def delete_cycle():
    """사이클 삭제 (PAUSED/COMPLETED 상태)"""
    cycle_id = wiz.request.query("cycle_id", True)
    trading = struct.trading
    engine = trading.engine
    try:
        result = engine.delete_cycle(cycle_id)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, **result)
