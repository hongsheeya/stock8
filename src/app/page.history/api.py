import json
import math
import re
import datetime
import copy

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
    if action_detail.startswith("PRE_") or "RESERVED" in action_detail:
        return False

    qty = _safe_int(record.get("qty", 0), 0)
    price = _safe_float(record.get("price", 0), 0)
    amount = _safe_float(record.get("amount", 0), 0)
    if qty <= 0:
        return False
    if price <= 0 and amount <= 0:
        return False
    return True

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

def _first_nonzero_float(*values):
    for value in values:
        num = _safe_float(value, 0)
        if abs(num) > 1e-9:
            return num
    return 0.0

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

def _daytrade_record_fee(record):
    return _safe_float((record or {}).get("fee", 0), 0)

def _daytrade_record_cost_amount(record):
    """SELL row 기준 청산 매수원금. 총 매수누계와 손익 비교가 섞이지 않게 분리한다."""
    record = record if isinstance(record, dict) else {}
    action = _normalize_trade_action(record.get("action", ""))
    amount = _safe_float(record.get("amount", 0), 0)
    qty = _safe_int(record.get("qty", 0), 0)
    if action == "BUY":
        return amount
    if action != "SELL":
        return 0.0

    matched = _safe_float(record.get("matched_buy_amount", 0), 0)
    if matched > 0:
        return matched

    avg_buy_price = _safe_float(record.get("avg_buy_price", 0), 0)
    if avg_buy_price > 0 and qty > 0:
        return avg_buy_price * qty

    realized = _safe_float(record.get("realized", 0), 0)
    fee = _daytrade_record_fee(record)
    if amount > 0 and abs(realized) > 1e-9:
        estimated = amount - realized - max(0.0, fee)
        if estimated > 0:
            return estimated
    return 0.0

def _daytrade_sell_amount(record):
    record = record if isinstance(record, dict) else {}
    amount = _safe_float(record.get("amount", 0), 0)
    if amount > 0:
        return amount
    price = _safe_float(record.get("price", 0), 0)
    qty = _safe_int(record.get("qty", 0), 0)
    return price * qty if price > 0 and qty > 0 else 0.0

def _daytrade_closed_sell_components(sell_rows):
    closed = []
    unmatched = []
    for row in list(sell_rows or []):
        amount = _daytrade_sell_amount(row)
        cost = _daytrade_record_cost_amount(row)
        fee = _daytrade_record_fee(row)
        if amount > 0 and cost > 0:
            closed.append({
                "row": row,
                "amount": amount,
                "cost": cost,
                "fee": max(0.0, fee),
                "realized": amount - cost - max(0.0, fee),
            })
        elif amount > 0:
            unmatched.append(row)
    return closed, unmatched

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
        return f"{market}:{symbol}:{action}:{order_no}"
    return f"{market}:{symbol}:{record.get('action_detail', action)}:{record.get('timestamp', '')}:{record.get('qty', 0)}:{record.get('price', 0)}"

def _daytrade_source_rank(record):
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
    if incoming_rank > existing_rank:
        merged = dict(existing)
        for key in (
            "id", "timestamp", "market", "market_label", "symbol", "name", "strategy_id",
            "action", "action_detail", "order_type", "order_no", "price", "qty", "amount",
            "matched_buy_amount", "fee", "avg_buy_price",
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
    timestamp = _to_kst_string(created_kst, fmt="%Y-%m-%d %H:%M:%S") if created_kst else _to_kst_string(row.get("created"), fmt="%Y-%m-%d %H:%M:%S", assume_naive_utc=True)
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
    )
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
        "matched_buy_amount": round(matched_buy_amount, 2),
        "fee": round(fee, 4),
        "avg_buy_price": round(avg_buy_price, 4),
        "post_position_qty": _safe_int(runtime.get("post_position_qty", 0), 0),
        "post_avg_price": round(_safe_float(runtime.get("post_avg_price", 0), 0), 4),
        "message": _sanitize_user_log_message(reason),
        "source": "trade_log",
        "_sort": _daytrade_sort_key(timestamp),
    }
    return record

def _daytrade_record_from_period_log(row):
    row = row if isinstance(row, dict) else {}
    symbol = str(row.get("symbol", "") or "").upper()
    market = _daytrade_market(row.get("event_type", ""), symbol, row.get("market", "KS"))
    action = _normalize_trade_action(row.get("action", ""))
    action_detail = str(row.get("event_type", "") or "").upper()
    if action_detail.startswith("DT_KS_"):
        action_detail = action_detail.replace("DT_KS_", "")
    elif action_detail.startswith("DT_US_"):
        action_detail = action_detail.replace("DT_US_", "")
    if not action_detail:
        action_detail = action
    price = _safe_float(row.get("filled_price", 0), 0)
    qty = _safe_int(row.get("filled_qty", 0), 0)
    amount = _safe_float(row.get("amount", 0), 0) or (price * qty)
    timestamp = _to_kst_string(row.get("created", ""), fmt="%Y-%m-%d %H:%M:%S")
    realized = _safe_float(row.get("pnl_net", 0), 0) if action == "SELL" else 0.0
    fee = _safe_float(row.get("fee", 0), 0)
    buy_fee = _safe_float(row.get("buy_fee_component", 0), 0)
    matched_buy_amount = _safe_float(row.get("matched_buy_amount", 0), 0)
    message_parts = [str(row.get("message", "") or "KIS 실체결 동기화")]
    if action == "SELL":
        if matched_buy_amount > 0:
            message_parts.append(f"매수원금 {_format_history_money(matched_buy_amount, market)}")
        if fee + buy_fee > 0:
            message_parts.append(f"수수료/제세금 {_format_history_money(fee + buy_fee, market)}")
    message = " | ".join([part for part in message_parts if str(part or "").strip()])
    avg_buy_price = _safe_float(row.get("avg_buy_price", 0), 0)
    if action == "SELL" and matched_buy_amount <= 0 and amount > 0 and qty > 0:
        matched_buy_amount = max(0.0, amount - realized - max(0.0, fee + buy_fee))
    if action == "SELL" and avg_buy_price <= 0 and matched_buy_amount > 0 and qty > 0:
        avg_buy_price = matched_buy_amount / qty
    return {
        "id": f"kis:{row.get('order_no', '')}:{symbol}:{action}:{timestamp}",
        "timestamp": timestamp,
        "market": market,
        "market_label": "미장" if market == "US" else "국장",
        "symbol": symbol,
        "name": row.get("name", "") or symbol,
        "strategy_id": str(row.get("strategy_id", "") or ""),
        "action": action,
        "action_detail": action_detail,
        "order_type": str(row.get("order_type", "") or ""),
        "order_no": str(row.get("order_no", "") or ""),
        "price": round(price, 4),
        "qty": qty,
        "amount": round(amount, 2),
        "realized": round(realized, 2),
        "matched_buy_amount": round(matched_buy_amount if action == "SELL" else 0, 2),
        "fee": round(fee + buy_fee, 4),
        "avg_buy_price": round(avg_buy_price if action == "SELL" else 0, 4),
        "post_position_qty": 0,
        "post_avg_price": 0,
        "message": _sanitize_user_log_message(message),
        "source": "kis_broker",
        "_sort": _daytrade_sort_key(timestamp),
    }

def _collect_broker_daytrade_trades(trading):
    try:
        import sys as _sys
        engine = trading.daytrade_engine
        today = datetime.datetime.now(KST).date()
        date_from = (today - datetime.timedelta(days=21)).strftime("%Y-%m-%d")
        date_to = today.strftime("%Y-%m-%d")
        cache_key = "_history_daytrade_broker_records_v1"
        cache_ts_key = "_history_daytrade_broker_records_ts_v1"
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        cached = getattr(_sys, cache_key, None)
        cached_ts = getattr(_sys, cache_ts_key, 0.0)
        if cached is not None and (now_ts - cached_ts) < 20:
            return [dict(item) for item in list(cached)]
        summary = engine.period_trade_summary(
            date_from=date_from,
            date_to=date_to,
            sync_broker=True,
            broker_lookback_days=7,
            include_valuation=False,
        ) or {}
    except Exception:
        return []

    records = []
    allowed_symbols = set()
    try:
        state_map = engine._load_state_map() or {}
        for state_key, state in state_map.items():
            symbol = str((state if isinstance(state, dict) else {}).get("symbol", "") or str(state_key).split(".")[0]).upper()
            if symbol:
                allowed_symbols.add(symbol)
    except Exception:
        allowed_symbols = set()
    try:
        log_db = trading.db("trade_log")
        for row in log_db.rows(event_type__startswith="DT_", orderby="created", order="DESC", dump=5000) or []:
            symbol = str((row or {}).get("symbol", "") or "").upper()
            if symbol:
                allowed_symbols.add(symbol)
    except Exception:
        pass

    for row in list(summary.get("logs", []) or []):
        if str((row or {}).get("verification", "") or "").lower() != "kis":
            continue
        symbol = str((row or {}).get("symbol", "") or "").upper()
        if allowed_symbols and symbol not in allowed_symbols:
            continue
        record = _daytrade_record_from_period_log(row)
        if record.get("action") in ("BUY", "SELL") and record.get("symbol"):
            records.append(record)
    try:
        setattr(_sys, cache_key, [dict(item) for item in records])
        setattr(_sys, cache_ts_key, now_ts)
    except Exception:
        pass
    return records

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
    orders = list((state or {}).get("orders", []) or [])
    state_market = str((state or {}).get("market", "") or (str(state_key).split(".")[1] if "." in str(state_key) else "KS")).upper()
    state_market = "US" if state_market == "US" else "KS"

    for index, order in enumerate(orders):
        action_detail = str((order or {}).get("action", "") or "").upper()
        normalized = _normalize_trade_action(action_detail)
        price = _safe_float((order or {}).get("price", 0), 0)
        qty = _safe_int((order or {}).get("qty", 0), 0)

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

def _collect_daytrade_trades(trading, include_broker=False):
    cache_key = f"daytrade_records:{'broker' if include_broker else 'local'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    record_by_key = {}
    try:
        log_db = trading.db("trade_log")
        rows = log_db.rows(event_type__startswith="DT_", orderby="created", order="DESC", dump=5000) or []
    except Exception:
        rows = []
    for row in rows:
        record = _daytrade_record_from_log(row)
        if not _is_executable_daytrade_record(record):
            continue
        key = _daytrade_record_key(record)
        record_by_key[key] = _merge_daytrade_record(record_by_key.get(key), record)

    if include_broker:
        for record in _collect_broker_daytrade_trades(trading):
            if not _is_executable_daytrade_record(record):
                continue
            key = _daytrade_record_key(record)
            record_by_key[key] = _merge_daytrade_record(record_by_key.get(key), record)

    state_map = _load_daytrade_state(trading)
    for state_key, state in (state_map or {}).items():
        if not isinstance(state, dict):
            continue
        state_records = _daytrade_records_from_state_orders(str(state_key), state)
        for record in state_records:
            if not _is_executable_daytrade_record(record):
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

    records = list(record_by_key.values())
    records.sort(key=lambda x: x.get("_sort", ""), reverse=True)
    _cache_set(cache_key, records)
    return records

def _format_history_money(value, market="KS"):
    amount = _safe_float(value, 0)
    if str(market or "").upper() == "US":
        return f"${amount:,.2f}"
    return f"₩{round(amount):,}"

def _daytrade_record_to_log_row(record):
    market = str(record.get("market", "KS") or "KS").upper()
    price = _safe_float(record.get("price", 0), 0)
    qty = _safe_int(record.get("qty", 0), 0)
    realized = _safe_float(record.get("realized", 0), 0)
    action = _normalize_trade_action(record.get("action", ""))
    action_detail = str(record.get("action_detail", "") or action)
    name = str(record.get("name", "") or record.get("symbol", "") or "")
    message = str(record.get("message", "") or "")

    parts = [f"{name} {action_detail} 실행", f"{qty}주", f"체결가 {_format_history_money(price, market)}"]
    if action == "SELL" and abs(realized) > 1e-9:
        parts.append(f"실현손익 {_format_history_money(realized, market)}")
    if message:
        parts.append(message)

    return {
        "id": record.get("id", ""),
        "created": record.get("timestamp", ""),
        "symbol": record.get("symbol", ""),
        "event_type": f"DT_{market}_{action_detail}",
        "action": action,
        "order_price": price,
        "order_qty": qty,
        "filled_price": price,
        "filled_qty": qty,
        "message": _sanitize_user_log_message(" | ".join(parts)),
        "raw_response": "",
        "source": record.get("source", "live_state"),
        "_sort": _daytrade_sort_key(record.get("timestamp", "")),
    }

def _state_daytrade_log_rows(trading):
    rows = []
    for record in _collect_daytrade_trades(trading, include_broker=False):
        source = str(record.get("source", "") or "")
        if "trade_log" in source:
            continue
        rows.append(_daytrade_record_to_log_row(record))
    return rows

def _active_daytrade_positions(trading, market=""):
    state_map = _load_daytrade_state(trading)
    result = []
    market_filter = str(market or "").upper()
    for state_key, state in (state_map or {}).items():
        if not isinstance(state, dict):
            continue
        qty = _safe_int(state.get("position_qty", 0), 0)
        if qty <= 0:
            continue
        item_market = str(state.get("market", "") or (str(state_key).split(".")[1] if "." in str(state_key) else "KS")).upper()
        item_market = "US" if item_market == "US" else "KS"
        if market_filter and item_market != market_filter:
            continue
        avg_price = _safe_float(state.get("avg_price", 0), 0)
        result.append({
            "symbol": state.get("symbol", str(state_key).split(".")[0]),
            "market": item_market,
            "name": state.get("name", ""),
            "position_qty": qty,
            "avg_price": round(avg_price, 4),
            "cost_amount": round(avg_price * qty, 2),
            "updated_at": _to_kst_string(state.get("updated_at", ""), fmt="%Y-%m-%d %H:%M:%S"),
        })
    return result

def symbols():
    """활성 Watchlist의 종목 심볼 목록"""
    try:
        trading = struct.trading
        watchlist_db = trading.db("etf_watchlist")
        rows = watchlist_db.rows(orderby="symbol", order="ASC") or []
        symbols = {r["symbol"] for r in rows if r.get("symbol")}
        try:
            log_db = trading.db("trade_log")
            logs = log_db.rows(event_type__startswith="DT_", orderby="created", order="DESC", dump=1000) or []
            symbols.update([r.get("symbol") for r in logs if r.get("symbol")])
        except Exception:
            pass
        for state in (_load_daytrade_state(trading) or {}).values():
            if isinstance(state, dict) and state.get("symbol"):
                symbols.add(state.get("symbol"))
        symbols = sorted([s for s in symbols if s])
    except Exception as e:
        wiz.response.status(500, message=f"symbols failed: {e}")
    wiz.response.status(200, data=symbols)

def daytrade_trades():
    """단타 체결 이력: 사용자에게 필요한 핵심 체결 정보만 반환"""
    trading = struct.trading
    page = max(1, int(wiz.request.query("page", 1)))
    dump = 20
    market = str(wiz.request.query("market", "") or "").upper()
    action = _normalize_trade_action(wiz.request.query("action", ""))
    symbol = str(wiz.request.query("symbol", "") or "").upper()
    search = str(wiz.request.query("search", "") or "").strip().lower()
    sync_broker = str(wiz.request.query("sync_broker", "false") or "").strip().lower() in ("1", "true", "yes", "y")

    rows = _collect_daytrade_trades(trading, include_broker=sync_broker)
    filtered = []
    for row in rows:
        if market and row.get("market") != market:
            continue
        if action and row.get("action") != action:
            continue
        if symbol and row.get("symbol") != symbol:
            continue
        if search:
            haystack = " ".join([
                str(row.get("symbol", "")),
                str(row.get("name", "")),
                str(row.get("message", "")),
                str(row.get("action_detail", "")),
            ]).lower()
            if search not in haystack:
                continue
        filtered.append(row)

    total = len(filtered)
    total_pages = max(1, math.ceil(total / dump))
    start = (page - 1) * dump
    page_rows = filtered[start:start + dump]
    for row in page_rows:
        row.pop("_sort", None)

    buy_rows = [r for r in filtered if r.get("action") == "BUY"]
    sell_rows = [r for r in filtered if r.get("action") == "SELL"]
    closed_sells, unmatched_sells = _daytrade_closed_sell_components(sell_rows)
    positions = _active_daytrade_positions(trading, market=market)
    total_buy_amount = sum(_safe_float(r.get("amount", 0), 0) for r in buy_rows)
    gross_sell_amount = sum(_daytrade_sell_amount(r) for r in sell_rows)
    total_sell_amount = sum(item["amount"] for item in closed_sells)
    matched_buy_amount = sum(item["cost"] for item in closed_sells)
    fee_total = sum(item["fee"] for item in closed_sells)
    realized_total = sum(item["realized"] for item in closed_sells)
    record_realized_total = sum(_safe_float(r.get("realized", 0), 0) for r in sell_rows)
    unmatched_sell_amount = sum(_daytrade_sell_amount(r) for r in unmatched_sells)
    summary = {
        "buy_count": len(buy_rows),
        "sell_count": len(closed_sells),
        "total_sell_count": len(sell_rows),
        "closed_sell_count": len(closed_sells),
        "total_buy_amount": round(total_buy_amount, 2),
        "gross_sell_amount": round(gross_sell_amount, 2),
        "total_sell_amount": round(total_sell_amount, 2),
        "closed_buy_amount": round(matched_buy_amount, 2),
        "matched_buy_amount": round(matched_buy_amount, 2),
        "fee_total": round(fee_total, 4),
        "closed_gross_gap": round(total_sell_amount - matched_buy_amount, 2),
        "closed_net_gap": round(total_sell_amount - matched_buy_amount - fee_total, 2),
        "cash_flow_gap": round(total_sell_amount - total_buy_amount, 2),
        "unmatched_sell_count": len(unmatched_sells),
        "unmatched_sell_amount": round(unmatched_sell_amount, 2),
        "record_realized": round(record_realized_total, 2),
        "realized": round(realized_total, 2),
        "open_position_count": len(positions),
        "open_cost_amount": round(sum(_safe_float(p.get("cost_amount", 0), 0) for p in positions), 2),
        "positions": positions[:8],
    }

    wiz.response.status(
        200,
        rows=page_rows,
        total=total,
        total_pages=total_pages,
        page=page,
        summary=summary,
        broker_sync_deferred=(not sync_broker),
    )

def cycles():
    """사이클 목록 (필터 + 페이징)"""
    trading = struct.trading
    page = int(wiz.request.query("page", 1))
    dump = 15
    status = wiz.request.query("status", "")
    symbol = wiz.request.query("symbol", "")

    cycle_db = trading.db("trading_cycle")

    kwargs = dict(page=page, dump=dump, orderby="updated", order="DESC")
    if status:
        kwargs["status"] = status
    if symbol:
        kwargs["symbol"] = symbol

    rows = cycle_db.rows(**kwargs)

    # count
    count_kwargs = {}
    if status:
        count_kwargs["status"] = status
    if symbol:
        count_kwargs["symbol"] = symbol
    total = cycle_db.count(**count_kwargs)
    total_pages = max(1, math.ceil(total / dump))

    # datetime → string
    for r in rows:
        for k in ("started_at", "completed_at", "created", "updated"):
            if r.get(k):
                r[k] = str(r[k])

    wiz.response.status(200, rows=rows, total=total, total_pages=total_pages, page=page)

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

def trade_logs():
    """거래 로그 (필터 + 검색 + 페이징)"""
    trading = struct.trading
    page = int(wiz.request.query("page", 1))
    dump = 20
    symbol = wiz.request.query("symbol", "")
    action = wiz.request.query("action", "")
    search = wiz.request.query("search", "")

    log_db = trading.db("trade_log")

    try:
        rows = log_db.rows(orderby="created", order="DESC", dump=5000) or []
    except Exception:
        rows = []
    rows = list(rows) + _state_daytrade_log_rows(trading)

    filtered = []
    symbol_filter = str(symbol or "").upper()
    action_filter = _normalize_trade_action(action)
    search_text = str(search or "").strip().lower()
    for row in rows:
        if symbol_filter and str(row.get("symbol", "") or "").upper() != symbol_filter:
            continue
        if action_filter and _normalize_trade_action(row.get("action", "")) != action_filter:
            continue
        if search_text:
            haystack = " ".join([
                str(row.get("symbol", "")),
                str(row.get("event_type", "")),
                str(row.get("action", "")),
                str(row.get("message", "")),
            ]).lower()
            if search_text not in haystack:
                continue
        row["_sort"] = _daytrade_sort_key(row.get("created", ""))
        filtered.append(row)

    filtered.sort(key=lambda x: x.get("_sort", ""), reverse=True)
    total = len(filtered)
    total_pages = max(1, math.ceil(total / dump))
    start = (page - 1) * dump
    page_rows = filtered[start:start + dump]

    for r in page_rows:
        if r.get("created"):
            r["created"] = _to_kst_string(r["created"])
        if not r.get("market"):
            r["market"] = _daytrade_market(r.get("event_type", ""), r.get("symbol", ""), "KS")
        r["message"] = _sanitize_user_log_message(r.get("message", ""))
        r.pop("_sort", None)

    wiz.response.status(200, rows=page_rows, total=total, total_pages=total_pages, page=page)

def snapshots():
    """일별 자산 스냅샷 (페이징)"""
    trading = struct.trading
    page = int(wiz.request.query("page", 1))
    dump = 20

    snap_db = trading.db("account_snapshot")

    rows = snap_db.rows(page=page, dump=dump, orderby="snapshot_date", order="DESC")
    total = snap_db.count()
    total_pages = max(1, math.ceil(total / dump))

    for r in rows:
        if r.get("created"):
            r["created"] = str(r["created"])

    wiz.response.status(200, rows=rows, total=total, total_pages=total_pages, page=page)

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
