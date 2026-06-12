import json
import traceback as _tb
import os as _os
import time as _time
import datetime as _datetime
import copy as _copy

_TIME = wiz.model("portal/trading/kst")

# === 에러 덤프 (서버 500 디버그용) ===
_ERR_LOG = "/tmp/wiz_api_errors.log"

def _dump_error(label, e):
    try:
        msg = f"[{label}] {type(e).__name__}: {e}\n{_tb.format_exc()}\n"
        with open(_ERR_LOG, "a") as f:
            f.write(f"\n=== {_kst_now()} ===\n" + msg)
    except Exception:
        pass

# ==========================================================
# struct 지연 로드 — api.py 파싱 즉시 막히지 않도록
# ==========================================================
_STRUCT_ERROR_TTL_SEC = 5.0
_struct_cache = {"obj": None, "loaded": False, "error": None, "error_at": 0.0}
_DAILY_LOG_CACHE_TTL_SEC = 3.0
_daily_log_cache = {}
_LIVE_STATUS_CACHE_TTL_SEC = 12.0
_live_status_cache = {}
_ACTIVE_POSITIONS_CACHE_TTL_SEC = 4.0
_active_positions_cache = {}
_ACTIVE_POSITION_QUOTE_TTL_SEC = 4.0
_active_position_quote_cache = {}
_BROKER_SYNC_LOOKBACK_DAYS = 7

def _kst_now():
    return _TIME.now()

def _get_struct():
    if _struct_cache["obj"] is not None:
        return _struct_cache["obj"]
    if _struct_cache["error"] is not None:
        if (_time.monotonic() - float(_struct_cache.get("error_at", 0.0) or 0.0)) < _STRUCT_ERROR_TTL_SEC:
            raise _struct_cache["error"]
        _struct_cache["error"] = None
        _struct_cache["error_at"] = 0.0
        _struct_cache["loaded"] = False
    t0 = _time.monotonic()
    try:
        _struct_cache["obj"] = wiz.model("struct")
        _struct_cache["loaded"] = True
    except Exception as e:
        _struct_cache["obj"] = None
        _struct_cache["error"] = e
        _struct_cache["error_at"] = _time.monotonic()
        _struct_cache["loaded"] = False
        _dump_error("struct_load", e)
        raise
    return _struct_cache["obj"]


def ping():
    wiz.response.status(200, pong=True, timestamp=_TIME.isoformat())


def _daytrade():
    return _get_struct().trading.daytrade


def _engine():
    return _get_struct().trading.daytrade_engine

def _recommendation_price_cap(engine, budget_status, seed):
    fallback_seed = float(seed or 0) if float(seed or 0) > 0 else 0
    base_seed = (
        budget_status.get("slot_seed_limit_krw", 0)
        or budget_status.get("per_symbol_seed_krw", 0)
        or budget_status.get("remaining_seed_krw", 0)
        or fallback_seed
    )
    raw_price_cap = max(float(base_seed or 0), 0) * 0.985
    if raw_price_cap <= 0:
        return 0
    if raw_price_cap < 100000:
        return int(raw_price_cap / 1000.0) * 1000
    return int(raw_price_cap / 10000.0) * 10000


def _sync_recommendation_budget(recommendation, budget_status, requested_seed, price_cap):
    if not isinstance(recommendation, dict):
        return recommendation
    payload = dict(recommendation)
    payload["requested_seed"] = round(float(requested_seed or 0), 2)
    payload["price_cap_krw"] = round(float(price_cap or 0), 2)
    payload["total_seed_krw"] = round(float(budget_status.get("total_seed_krw", requested_seed) or 0), 2)
    payload["remaining_seed_krw"] = round(float(budget_status.get("remaining_seed_krw", 0) or 0), 2)
    payload["slot_seed_limit_krw"] = round(float(budget_status.get("slot_seed_limit_krw", 0) or 0), 2)
    payload["per_symbol_seed_krw"] = round(float(budget_status.get("per_symbol_seed_krw", 0) or 0), 2)
    payload["slot_target_count"] = int(budget_status.get("slot_target_count", 0) or 0)
    payload["available_slot_count"] = int(budget_status.get("available_slot_count", 0) or 0)
    return payload

def _stable_recommendation(service, engine, budget_status, requested_seed, market="KS", strategy_id="", symbol=""):
    price_cap = _recommendation_price_cap(engine, budget_status, requested_seed)
    recommendation = service.latest_recommendation(
        seed=requested_seed,
        strategy_id=strategy_id,
        price_cap=price_cap,
        allow_stale_day=True,
        market=market,
    ) or service.latest_recommendation(allow_stale_day=True, market=market)

    if not isinstance(recommendation, dict) or not recommendation.get("selected"):
        recommendation = service._fallback_recommendation(
            symbol=symbol,
            market=market,
            seed=requested_seed,
            strategy_id=strategy_id,
            reason="추천 캐시가 비어 기본 추천을 유지합니다.",
        )

    recommendation = _sync_recommendation_budget(recommendation, budget_status, requested_seed, price_cap)
    return recommendation, price_cap


def _merge_budget_with_worker_cache(budget_status, worker_status):
    budget = dict(budget_status or {})
    worker_budget = {}
    if isinstance(worker_status, dict):
        worker_budget = worker_status.get("budget", {}) or {}
    if not isinstance(worker_budget, dict) or len(worker_budget) == 0:
        return budget

    numeric_fill_keys = [
        "total_asset_krw",
        "fallback_total_asset_krw",
        "summary_total_asset_krw",
        "total_seed_krw",
        "used_seed_krw",
        "remaining_seed_krw",
        "effective_daytrade_seed",
        "capacity_daytrade_seed_krw",
        "slot_seed_limit_krw",
        "per_symbol_seed_krw",
        "withdrawable_krw",
        "krw_balance",
    ]
    for key in numeric_fill_keys:
        current_value = float(budget.get(key, 0) or 0)
        worker_value = float(worker_budget.get(key, 0) or 0)
        if current_value <= 0 and worker_value > 0:
            budget[key] = worker_value

    if str(budget.get("source", "")).strip() in ("", "cache_miss") and worker_budget.get("source"):
        budget["source"] = f"{budget.get('source', 'cache_miss')}+worker_cache:{worker_budget.get('source')}"
    return budget


def _normalize_budget_total_asset(budget_status):
    budget = dict(budget_status or {})
    summary_key = str(budget.get("summary_total_asset_key", "") or "").strip()
    candidates = [
        (_safe_float(budget.get("summary_total_asset_krw", 0), 0), f"summary_total_asset:{summary_key}" if summary_key else "domestic_balance.summary_total_asset_krw"),
        (_safe_float(budget.get("present_total_asset_krw", 0), 0), "present_balance.total_asset_krw"),
        (_safe_float(budget.get("total_asset_krw", 0), 0), str(budget.get("total_asset_source", "") or "")),
        (_safe_float(budget.get("direct_total_asset_krw", 0), 0), "direct(krw+domestic_eval+usd_cash+usd_eval)"),
        (_safe_float(budget.get("fallback_total_asset_krw", 0), 0), "fallback_total_asset_krw"),
    ]
    total_asset_krw, total_asset_source = next(((amount, source) for amount, source in candidates if _safe_float(amount, 0) > 0), (0, ""))
    budget["total_asset_krw"] = round(_safe_float(total_asset_krw, 0), 2)
    if budget["total_asset_krw"] > 0 and str(total_asset_source or "").strip() != "":
        budget["total_asset_source"] = total_asset_source
    return budget


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _cached_domestic_quote(symbol):
    key = str(symbol or "").strip()
    if key == "":
        return None
    cached = _active_position_quote_cache.get(key)
    if isinstance(cached, dict):
        age = _time.monotonic() - float(cached.get("ts", 0) or 0)
        if age < _ACTIVE_POSITION_QUOTE_TTL_SEC:
            return _copy.deepcopy(cached.get("payload", {}))
    quote = _get_struct().trading.kis_api.get_domestic_current_price(key)
    payload = dict(quote or {})
    _active_position_quote_cache[key] = {
        "ts": _time.monotonic(),
        "payload": _copy.deepcopy(payload),
    }
    return payload


def _active_position_sort_key(row):
    row = row or {}
    opened_at = str(row.get("opened_at", "") or "").strip()
    first_buy_date = str(row.get("first_buy_date", "") or "").strip().replace("-", "")[:8]
    if opened_at == "" and len(first_buy_date) == 8:
        opened_at = f"{first_buy_date[:4]}-{first_buy_date[4:6]}-{first_buy_date[6:8]} 00:00:00"
    symbol = str(row.get("symbol", "") or "")
    strategy_id = str(row.get("strategy_id", "") or "")
    return (opened_at == "", opened_at, symbol, strategy_id)


def _fast_active_positions_snapshot(market="KS", refresh_quotes=True):
    market_key = str(market or "KS").upper().strip()
    cache_key = f"{market_key}:{'quotes' if refresh_quotes else 'state'}"
    cached = _active_positions_cache.get(cache_key)
    if isinstance(cached, dict):
        age = _time.monotonic() - float(cached.get("ts", 0) or 0)
        if age < _ACTIVE_POSITIONS_CACHE_TTL_SEC:
            return _copy.deepcopy(cached.get("payload", []))

    engine = _engine()
    rows = []
    for row in (engine.active_positions_from_state() or []):
        row_market = str(row.get("market", "KS") or "KS").upper()
        if market_key == "US":
            if row_market not in ("US", "NYSE", "NASD", "AMEX", "NYS"):
                continue
        elif row_market not in ("KS", "KQ", "KR"):
            continue

        item = dict(row or {})
        if refresh_quotes and market_key != "US":
            symbol = str(item.get("symbol", "") or "").strip()
            if symbol != "":
                try:
                    quote = _cached_domestic_quote(symbol)
                    price = _safe_float((quote or {}).get("price", 0), 0)
                    qty = _safe_int(item.get("position_qty", 0), 0)
                    avg_price = _safe_float(item.get("avg_price", 0), 0)
                    if price > 0:
                        pnl = ((price - avg_price) * qty) if avg_price > 0 else 0.0
                        pnl_pct = ((price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
                        item["current_price"] = round(price, 4)
                        item["pnl"] = round(pnl, 2)
                        item["pnl_pct"] = round(pnl_pct, 2)
                        item["updated_at"] = str((quote or {}).get("timestamp", item.get("updated_at", "")) or item.get("updated_at", ""))
                        item["source"] = "quote_fast"
                except Exception:
                    pass
        rows.append(item)

    rows.sort(key=_active_position_sort_key)
    _active_positions_cache[cache_key] = {
        "ts": _time.monotonic(),
        "payload": _copy.deepcopy(rows),
    }
    return rows

def _date_compact(value=""):
    return str(value or "").strip().replace("-", "")[:8]

def _date_display(value=""):
    text = _date_compact(value)
    if len(text) != 8:
        return str(value or "")
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def _session_date_9am(now=None):
    now = now or _kst_now()
    anchor = now
    if now.hour < 9:
        anchor = now - _datetime.timedelta(days=1)
    return anchor.strftime("%Y%m%d")


def _to_kst_datetime(value):
    if value in (None, ""):
        return None
    dt = value
    if isinstance(dt, str):
        text = dt.strip()
        for parse_fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                dt = _datetime.datetime.strptime(text[:26], parse_fmt)
                break
            except Exception:
                dt = None
        if dt is None:
            return None
    if isinstance(dt, _datetime.datetime) is False:
        return None
    if dt.tzinfo is None:
        dt = dt + _datetime.timedelta(hours=9)
    else:
        dt = dt.astimezone(_datetime.timezone(_datetime.timedelta(hours=9)))
    return dt


def _to_kst_string(value, fmt="%Y-%m-%d %H:%M:%S"):
    dt = _to_kst_datetime(value)
    if dt is None:
        return ""
    return dt.strftime(fmt)





def _build_live_plan_payload(status, budget_status, effective_seed, requested_seed):
    sig = status.get("signal", {}) if isinstance(status, dict) else {}
    st = status.get("state", {}) if isinstance(status, dict) else {}
    profile = status.get("profile", {}) if isinstance(status, dict) else {}
    runtime = status.get("runtime", {}) if isinstance(status, dict) else {}
    current = float(sig.get("current_price", 0) or 0)
    anchor = float(sig.get("anchor_price", 0) or 0)
    buy_budget_val = float(effective_seed or 0)
    est_qty = int(buy_budget_val / current) if current > 0 else 0
    pos_qty = int(st.get("position_qty", 0) or 0)
    avg_price = float(st.get("avg_price", 0) or 0)
    jackpot_pct = float(profile.get("jackpot_take_profit_pct", 2.0))
    buy1_price = round(float(sig.get("buy1_trigger", 0) or 0))
    stop_loss_pct_plan = float(profile.get("stop_loss_pct", 1.5))
    manual_sell_price = round(float(st.get("manual_sell_target_price", 0) or 0))
    manual_sell_enabled = bool(st.get("manual_sell_enabled", False))
    stop_loss_price = round(float(st.get("stop_loss_price", 0) or 0))
    stop_loss_enabled = bool(st.get("stop_loss_enabled", False))
    projected_jackpot_price = round(buy1_price * (1 + jackpot_pct / 100)) if buy1_price > 0 else 0
    plan = {
        "seed": effective_seed,
        "requested_seed": requested_seed,
        "active_budget": round(buy_budget_val),
        "buy_budget": round(buy_budget_val),
        "budget_ratio": 1.0,
        "budget_status": budget_status,
        "projected_jackpot_price": projected_jackpot_price,
        "jackpot_pct": jackpot_pct,
        "stop_loss_pct": stop_loss_pct_plan,
        "auto_stop_price": round(buy1_price * (1 - stop_loss_pct_plan / 100)) if buy1_price > 0 else 0,
        "auto_exit": runtime.get("exit_watch", {}),
        "entries": [
            {
                "label": "매수 트리거 (BUY1)",
                "trigger_price": buy1_price,
                "trigger_pct": float(profile.get("buy_trigger_1_pct", -0.5)),
                "est_qty": est_qty,
                "est_amount": round(buy_budget_val),
                "used": bool(st.get("buy1_used")),
            },
        ],
        "exits": [],
        "position": None,
    }
    if pos_qty > 0 and avg_price > 0:
        pnl = round((current - avg_price) * pos_qty)
        pnl_pct = round((current - avg_price) / avg_price * 100, 2) if avg_price > 0 else 0
        jackpot_price = round(float(sig.get("jackpot_target", 0) or (avg_price * (1 + jackpot_pct / 100))))
        recent_price = round(float(sig.get("recent_target", 0) or (anchor * (1 + float(profile.get("recent_lot_take_profit_pct", 0.6)) / 100)))) if anchor > 0 else 0
        rescue_price = round(float(sig.get("rescue_target", 0) or (avg_price * (1 + float(profile.get("rescue_take_profit_pct", 0.5)) / 100))))
        auto_stop_price = round(float(sig.get("auto_stop_price", 0) or (avg_price * (1 - stop_loss_pct_plan / 100)))) if stop_loss_pct_plan > 0 else 0
        plan["position"] = {
            "qty": pos_qty,
            "avg_price": round(avg_price),
            "current_price": round(current),
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "value": round(current * pos_qty),
        }
        plan["projected_jackpot_price"] = jackpot_price
        plan["jackpot_est_profit"] = round((jackpot_price - avg_price) * pos_qty) if jackpot_price > 0 else 0
        exits = [
            {
                "label": "잭팟 전량 청산",
                "target_price": jackpot_price,
                "target_pct": jackpot_pct,
                "condition": "평단가 대비",
                "est_profit": round((jackpot_price - avg_price) * pos_qty) if jackpot_price > 0 else 0,
            },
            {
                "label": "방어 부분 청산",
                "target_price": recent_price,
                "target_pct": float(profile.get("recent_lot_take_profit_pct", 0.6)),
                "condition": "기준가 대비",
                "est_profit": round((recent_price - avg_price) * min(pos_qty, est_qty)) if recent_price > 0 else 0,
            },
            {
                "label": "구조 부분 청산",
                "target_price": rescue_price,
                "target_pct": float(profile.get("rescue_take_profit_pct", 0.5)),
                "condition": "평단가 대비",
                "est_profit": round((rescue_price - avg_price) * min(pos_qty, est_qty)) if rescue_price > 0 else 0,
            },
            {
                "label": "자동 손절가",
                "target_price": auto_stop_price,
                "target_pct": round(((auto_stop_price - avg_price) / avg_price * 100), 2) if avg_price > 0 and auto_stop_price > 0 else 0,
                "condition": "기본 안전장치",
                "est_profit": round((auto_stop_price - avg_price) * pos_qty) if auto_stop_price > 0 else 0,
            },
        ]
        if manual_sell_price > 0:
            exits.insert(0, {
                "label": "사용자 지정 판매가",
                "target_price": manual_sell_price,
                "target_pct": round(((manual_sell_price - avg_price) / avg_price * 100), 2) if avg_price > 0 else 0,
                "condition": "직접 설정",
                "est_profit": round((manual_sell_price - avg_price) * pos_qty),
                "enabled": manual_sell_enabled,
            })
        if stop_loss_price > 0:
            exits.insert(1 if manual_sell_price > 0 else 0, {
                "label": "사용자 지정 손절가",
                "target_price": stop_loss_price,
                "target_pct": round(((stop_loss_price - avg_price) / avg_price * 100), 2) if avg_price > 0 else 0,
                "condition": "직접 설정",
                "est_profit": round((stop_loss_price - avg_price) * pos_qty),
                "enabled": stop_loss_enabled,
            })
        plan["exits"] = [item for item in exits if float(item.get("target_price", 0) or 0) > 0]
    return plan


def bootstrap():
    try:
        requested_seed = float(wiz.request.query("seed", "0") or 0)
        service = _daytrade()
        engine = _engine()
        worker_status = _get_struct().trading.worker_status()
        defaults = service.defaults()
        symbol = defaults.get("symbol", "035420")
        market = defaults.get("market", "KS")
        strategy = defaults.get("strategy", "vrev")
        seed = requested_seed if requested_seed > 0 else defaults.get("seed", 5000000)
        kis_status = engine.check_kis_connection()
        budget_status = engine.shared_budget_status(requested_seed=seed, use_cache_only=True)
        budget_status = _merge_budget_with_worker_cache(budget_status, worker_status)
        budget_status = _normalize_budget_total_asset(budget_status)
        rec, price_cap = _stable_recommendation(service, engine, budget_status, seed, market=market, strategy_id="", symbol=symbol)
        active_positions = _fast_active_positions_snapshot(market=market, refresh_quotes=False)
        defaults["seed"] = round(float(seed or defaults.get("seed", 0) or 0), 2)
        defaults["effective_seed"] = budget_status.get("effective_daytrade_seed", budget_status.get("live_order_seed", seed)) or seed
        selected_name = service.symbol_name(symbol)
        auto_enabled = engine.auto_enabled()
        if (active_positions or []):
            active = active_positions[0]
            symbol = active.get("symbol", symbol)
            market = active.get("market", market)
            selected_name = active.get("name", selected_name)
            strategy = active.get("strategy_id", strategy)
        elif rec and rec.get("selected"):
            selected = rec.get("selected", {})
            symbol = selected.get("symbol", symbol)
            market = selected.get("market", market)
            selected_name = selected.get("name", selected_name)
            strategy = selected.get("strategy_id", strategy)
        defaults["symbol"] = symbol
        defaults["market"] = market
        defaults["strategy"] = strategy
        daily_loss = engine.daily_loss_status(requested_seed=defaults["seed"], use_live_price=False, use_cache_only=True, market=market)
    except Exception as e:
        wiz.response.status(500, message=str(e))
    wiz.response.status(200,
        defaults=defaults,
        selected_name=selected_name,
        recommendation=rec,
        kis_status=kis_status,
        budget_status=budget_status,
        default_candidates=service.candidate_universe(),
        strategy_options=service.strategy_options(),
        strategy_spec=service.strategy_spec(strategy),
        active_positions=active_positions,
        auto_enabled=auto_enabled,
        worker_status=worker_status,
        daily_loss=daily_loss,
        max_affordable_per_share=price_cap,
        bootstrap_light=True,
    )


def active_positions_snapshot():
    market = wiz.request.query("market", "KS")
    refresh_quotes = wiz.request.query("refresh_quotes", "true").lower() != "false"
    try:
        active_positions = _fast_active_positions_snapshot(market=market, refresh_quotes=refresh_quotes)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, active_positions=active_positions, market=str(market or "KS").upper())


def initial_data():
    symbol = wiz.request.query("symbol", "035420")
    market = wiz.request.query("market", "KS")
    strategy = wiz.request.query("strategy", "vrev")
    seed = float(wiz.request.query("seed", "5000000"))
    service = None
    engine = None
    bars = []
    triggers = {}
    plan = None
    budget_status = {}
    signal = {}
    state = {}
    runtime = {}
    feature_snapshot = {}
    backtest = None
    day_boundaries = []
    effective_seed = seed
    degraded = False
    message = ""
    active_positions = []
    try:
        service = _daytrade()
        engine = _engine()
        name = service.symbol_name(symbol)
        budget_status = engine.shared_budget_status(requested_seed=seed, use_cache_only=True)
        effective_seed = budget_status.get("effective_daytrade_seed", budget_status.get("live_order_seed", seed))
        try:
            sessions = service._prepare_dataset(symbol, market=market, period="5d", interval="5m")
            for session in sessions:
                if session.get("bars"):
                    day_boundaries.append(len(bars))
                for bar in session.get("bars", []):
                    bars.append({
                        "t": bar.get("timestamp", ""),
                        "c": round(bar.get("close", 0)),
                        "h": round(bar.get("high", 0)),
                        "l": round(bar.get("low", 0)),
                    })
        except Exception as e:
            degraded = True
            message = f"차트 봉 데이터 로드 실패: {str(e)}"
            _dump_error("chart_data_dataset", e)

        # 2) 시그널 + 트리거 정보
        status = engine.signal_status(symbol=symbol, market=market, seed=effective_seed, name=name, strategy_id=strategy)
        signal = status.get("signal", {})
        profile = status.get("profile", {})
        state = status.get("state", {})
        runtime = status.get("runtime", {})
        feature_snapshot = status.get("feature_snapshot", {}) or {}
        if not feature_snapshot:
            try:
                feature_snapshot = service.feature_snapshot(symbol, market=market) or {}
            except Exception as e:
                degraded = True
                if message == "":
                    message = f"분석 지표 로드 실패: {str(e)}"
                _dump_error("chart_data_feature_snapshot", e)
                feature_snapshot = {}

        anchor = signal.get("anchor_price", 0)
        current = signal.get("current_price", 0)
        avg_price = float(state.get("avg_price", 0) or 0)
        pos_qty = int(state.get("position_qty", 0) or 0)

        triggers = {
            "anchor": round(anchor),
            "buy1": round(signal.get("buy1_trigger", 0)),
            "buy2": round(signal.get("buy2_trigger", 0)),
            "current": round(current),
        }
        if avg_price > 0 and pos_qty > 0:
            jackpot_tp = float(profile.get("jackpot_take_profit_pct", 2.0))
            triggers["jackpot"] = round(avg_price * (1 + jackpot_tp / 100))
            triggers["recent"] = round(anchor * (1 + float(profile.get("recent_lot_take_profit_pct", 0.6)) / 100))
            triggers["rescue"] = round(avg_price * (1 + float(profile.get("rescue_take_profit_pct", 0.5)) / 100))
            slp = float(profile.get("stop_loss_pct", 1.5))
            if slp > 0:
                triggers["auto_stop"] = round(avg_price * (1 - slp / 100))
        if float(state.get("manual_sell_target_price", 0) or 0) > 0:
            triggers["manual_sell"] = round(float(state.get("manual_sell_target_price", 0) or 0))
        if float(state.get("stop_loss_price", 0) or 0) > 0:
            triggers["stop_loss"] = round(float(state.get("stop_loss_price", 0) or 0))
        # BB 상단 (라이브)
        bb_upper_ft = feature_snapshot.get("bb_upper", 0) if feature_snapshot else 0
        if bb_upper_ft > 0:
            triggers["bb_upper"] = round(bb_upper_ft)

        # 3) 매매 계획
        budget_ratio = float(profile.get("budget_ratio", 0.95))  # 0.15 → 0.95 기본값 수정
        split_ratio = float(profile.get("buy_split_ratio", 1.0))  # 0.5 → 1.0 기본값 수정
        active_budget = effective_seed * budget_ratio
        buy_budget = active_budget * split_ratio
        est_qty = int(buy_budget / current) if current > 0 else 0

        # 예상 매도가: BUY1 트리거가에서 진입했다고 가정 시 잭팟 청산가
        jackpot_pct = float(profile.get("jackpot_take_profit_pct", 2.0))
        stop_loss_pct_plan = float(profile.get("stop_loss_pct", 1.5))
        buy1_price = triggers.get("buy1", 0)
        projected_jackpot_price = round(buy1_price * (1 + jackpot_pct / 100)) if buy1_price > 0 else 0

        plan = {
            "seed": effective_seed,
            "requested_seed": seed,
            "active_budget": round(active_budget),
            "buy_budget": round(buy_budget),
            "budget_ratio": budget_ratio,
            "budget_status": budget_status,
            "strategy": service.strategy_spec(strategy),
            "auto_exit": runtime.get("exit_watch", {}),
            "projected_jackpot_price": projected_jackpot_price,
            "jackpot_pct": jackpot_pct,
            "stop_loss_pct": stop_loss_pct_plan,
            "auto_stop_price": round(triggers.get("buy1", 0) * (1 - stop_loss_pct_plan / 100)) if triggers.get("buy1") else 0,
            "entries": [
                {
                    "label": "매수 트리거 (BUY1)",
                    "trigger_price": triggers["buy1"],
                    "trigger_pct": float(profile.get("buy_trigger_1_pct", -0.5)),
                    "est_qty": est_qty,
                    "est_amount": round(buy_budget),
                    "used": bool(state.get("buy1_used")),
                },
            ],
            "exits": [],
            "position": None,
        }

        if pos_qty > 0 and avg_price > 0:
            pnl = round((current - avg_price) * pos_qty)
            pnl_pct = round((current - avg_price) / avg_price * 100, 2) if avg_price > 0 else 0
            jackpot_actual = triggers.get("jackpot", 0)
            # 보유 중에는 실제 잭팟가(평단가 기준)로 덮어씀
            plan["projected_jackpot_price"] = jackpot_actual or projected_jackpot_price
            plan["jackpot_est_profit"] = round((jackpot_actual - avg_price) * pos_qty) if jackpot_actual and avg_price > 0 else 0
            plan["position"] = {
                "qty": pos_qty,
                "avg_price": round(avg_price),
                "current_price": round(current),
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "value": round(current * pos_qty),
            }
            plan["exits"] = [
                {
                    "label": "잭팟 전량 청산",
                    "target_price": triggers.get("jackpot", 0),
                    "target_pct": float(profile.get("jackpot_take_profit_pct", 1.0)),
                    "condition": "평단가 대비",
                    "est_profit": round((triggers.get("jackpot", 0) - avg_price) * pos_qty) if triggers.get("jackpot") else 0,
                },
                {
                    "label": "방어 부분 청산",
                    "target_price": triggers.get("recent", 0),
                    "target_pct": float(profile.get("recent_lot_take_profit_pct", 0.6)),
                    "condition": "기준가 대비",
                    "est_profit": round((triggers.get("recent", 0) - avg_price) * min(pos_qty, est_qty)) if triggers.get("recent") else 0,
                },
                {
                    "label": "구조 부분 청산",
                    "target_price": triggers.get("rescue", 0),
                    "target_pct": float(profile.get("rescue_take_profit_pct", 0.5)),
                    "condition": "평단가 대비",
                    "est_profit": round((triggers.get("rescue", 0) - avg_price) * min(pos_qty, est_qty)) if triggers.get("rescue") else 0,
                },
            ]
            if triggers.get("manual_sell", 0) > 0:
                plan["exits"].insert(0, {
                    "label": "사용자 지정 판매가",
                    "target_price": triggers.get("manual_sell", 0),
                    "target_pct": round(((triggers.get("manual_sell", 0) - avg_price) / avg_price * 100), 2) if avg_price > 0 else 0,
                    "condition": "직접 설정",
                    "est_profit": round((triggers.get("manual_sell", 0) - avg_price) * pos_qty),
                    "enabled": bool(state.get("manual_sell_enabled", False)),
                })
            if triggers.get("stop_loss", 0) > 0:
                plan["exits"].insert(1, {
                    "label": "사용자 지정 손절가",
                    "target_price": triggers.get("stop_loss", 0),
                    "target_pct": round(((triggers.get("stop_loss", 0) - avg_price) / avg_price * 100), 2) if avg_price > 0 else 0,
                    "condition": "직접 설정",
                    "est_profit": round((triggers.get("stop_loss", 0) - avg_price) * pos_qty),
                    "enabled": bool(state.get("stop_loss_enabled", False)),
                })

        # 4) 백테스트 요약
        latest = service.latest_training(market=market)
        if latest and latest.get("symbol") == symbol and latest.get("strategy_id", latest.get("best", {}).get("summary", {}).get("strategy_id", "vrev")) == service._normalize_strategy(strategy):
            best = latest.get("best", {})
            backtest = best.get("summary", {})
        try:
            active_positions = engine.active_positions() if engine else []
        except Exception as e:
            degraded = True
            if message == "":
                message = f"활성 포지션 조회 실패: {str(e)}"
            _dump_error("chart_data_active_positions", e)
            active_positions = []

    except Exception as e:
        degraded = True
        message = str(e)
        _dump_error("chart_data", e)
        try:
            if service is None:
                service = _daytrade()
            if engine is None:
                engine = _engine()
            if not budget_status:
                budget_status = engine.shared_budget_status(requested_seed=seed, use_cache_only=True)
            effective_seed = budget_status.get("effective_daytrade_seed", budget_status.get("live_order_seed", seed)) or seed
            status = engine.signal_status(symbol=symbol, market=market, seed=effective_seed, name=service.symbol_name(symbol), strategy_id=strategy)
            signal = status.get("signal", {})
            profile = status.get("profile", {})
            state = status.get("state", {})
            runtime = status.get("runtime", {})
            feature_snapshot = status.get("feature_snapshot", {}) or {}

            anchor = signal.get("anchor_price", 0)
            current = signal.get("current_price", 0)
            avg_price = float(state.get("avg_price", 0) or 0)
            pos_qty = int(state.get("position_qty", 0) or 0)

            triggers = {
                "anchor": round(anchor),
                "buy1": round(signal.get("buy1_trigger", 0)),
                "buy2": round(signal.get("buy2_trigger", 0)),
                "current": round(current),
            }
            if avg_price > 0 and pos_qty > 0:
                jackpot_tp = float(profile.get("jackpot_take_profit_pct", 2.0))
                triggers["jackpot"] = round(avg_price * (1 + jackpot_tp / 100))
                triggers["recent"] = round(anchor * (1 + float(profile.get("recent_lot_take_profit_pct", 0.6)) / 100))
                triggers["rescue"] = round(avg_price * (1 + float(profile.get("rescue_take_profit_pct", 0.5)) / 100))
                slp = float(profile.get("stop_loss_pct", 1.5))
                if slp > 0:
                    triggers["auto_stop"] = round(avg_price * (1 - slp / 100))
            if float(state.get("manual_sell_target_price", 0) or 0) > 0:
                triggers["manual_sell"] = round(float(state.get("manual_sell_target_price", 0) or 0))
            if float(state.get("stop_loss_price", 0) or 0) > 0:
                triggers["stop_loss"] = round(float(state.get("stop_loss_price", 0) or 0))
            if feature_snapshot.get("bb_upper", 0):
                triggers["bb_upper"] = round(feature_snapshot.get("bb_upper", 0))

            plan = _build_live_plan_payload(status, budget_status, effective_seed, seed)
            plan["is_loading"] = bool(runtime.get("risk_status") == "DEGRADED_LOADING")
        except Exception as inner:
            _dump_error("chart_data_fallback", inner)
    wiz.response.status(200,
        bars=bars,
        triggers=triggers,
        plan=plan,
        budget_status=budget_status,
        signal=signal,
        state=state,
        runtime=runtime,
        feature_snapshot=feature_snapshot,
        strategy_options=service.strategy_options() if service else [],
        selected_strategy=service.strategy_spec(strategy) if service else {},
        active_positions=active_positions,
        backtest=backtest,
        day_boundaries=day_boundaries,
        degraded=degraded,
        message=message,
    )


def recommend():
    seed = float(wiz.request.query("seed", "5000000"))
    strategy = wiz.request.query("strategy", "")
    force = wiz.request.query("force", "false").lower() in ("true", "1", "yes")
    try:
        engine = _engine()
        budget_status = engine.shared_budget_status(requested_seed=seed, use_cache_only=False)
        price_cap = _recommendation_price_cap(engine, budget_status, seed)
        result = _daytrade().recommend(seed=seed, force=force, strategy_id=strategy, price_cap=price_cap)
        result = _sync_recommendation_budget(result, budget_status, seed, price_cap)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, result=result, budget_status=budget_status, max_affordable_per_share=price_cap)


def sync_seed():
    seed = float(wiz.request.query("seed", "0") or 0)
    if seed <= 0:
        wiz.response.status(400, message="유효한 시드가 필요합니다.")
    try:
        trading = _get_struct().trading
        normalized_seed = max(100000.0, seed)
        trading.set_config("daytrade_default_seed", normalized_seed, description="Domestic daytrade default requested seed")
        engine = _engine()
        budget_status = engine.shared_budget_status(requested_seed=normalized_seed, use_cache_only=False)
        price_cap = _recommendation_price_cap(engine, budget_status, normalized_seed)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200,
        requested_seed=round(normalized_seed, 2),
        budget_status=budget_status,
        max_affordable_per_share=price_cap,
        worker_status=_get_struct().trading.worker_status(),
    )


def train_symbol():
    symbol = wiz.request.query("symbol", "035420")
    market = wiz.request.query("market", "KS")
    strategy = wiz.request.query("strategy", "vrev")
    seed = float(wiz.request.query("seed", "5000000"))
    period = wiz.request.query("period", "")  # 빈값이면 strategy별 기본값 사용
    try:
        result = _daytrade().optimize(symbol=symbol, market=market, seed=seed, strategy_id=strategy, period=period or "5d")
    except Exception as e:
        _dump_error("train_symbol", e)
        result = {
            "skipped": True,
            "symbol": symbol,
            "market": market,
            "strategy_id": strategy,
            "message": f"학습 실패 종목으로 제외했습니다: {str(e)}",
        }
    wiz.response.status(200, result=result)


def debug_balance():
    """실제 잔고 및 캐시 상태 디버그"""
    try:
        import json as _json, os as _os
        engine = _engine()
        engine._invalidate_kis_cache()
        worker_status = _get_struct().trading.worker_status()
        fresh_budget = engine.shared_budget_status(requested_seed=0, use_cache_only=False)
        domestic_balance = engine.struct.kis_api.get_domestic_balance()
        present_balance = engine.struct.kis_api.get_present_balance()
        overseas_balance = engine.struct.kis_api.get_balance()

        # live_state.json에서 마지막 seed 확인
        live_state_path = engine._fs().abspath(engine._state_path())
        live_state = {}
        try:
            if _os.path.exists(live_state_path):
                with open(live_state_path) as f:
                    live_state = _json.load(f)
        except Exception:
            pass

        # 마지막 worker 실행 결과
        last_result = worker_status.get("last_result", {})
        budget = last_result.get("budget", {})

        # KIS 설정 (계좌/실전여부)
        kis_is_real = engine.struct.kis_api.is_real
        kis_account = engine.struct.kis_api.account_prefix or ""

        result = {
            "worker_status": worker_status,
            "fresh_budget": fresh_budget,
            "portfolio_usage": fresh_budget.get("portfolio", {}),
            "last_budget": {
                "withdrawable_krw": budget.get("withdrawable_krw"),
                "krw_balance": budget.get("krw_balance"),
                "available_for_daytrade": budget.get("available_for_daytrade"),
                "effective_daytrade_seed": budget.get("effective_daytrade_seed"),
                "capacity_daytrade_seed_krw": budget.get("capacity_daytrade_seed_krw"),
                "total_seed_krw": budget.get("total_seed_krw"),
                "used_seed_krw": budget.get("used_seed_krw"),
                "remaining_seed_krw": budget.get("remaining_seed_krw"),
                "same_day_sell_krw": budget.get("same_day_sell_krw"),
                "same_day_buy_krw": budget.get("same_day_buy_krw"),
                "intraday_usable_krw": budget.get("intraday_usable_krw"),
                "source": budget.get("source"),
            },
            "domestic_balance": {
                "krw_balance": domestic_balance.get("krw_balance"),
                "withdrawable_krw": domestic_balance.get("withdrawable_krw"),
                "nxdy_excc_amt": domestic_balance.get("nxdy_excc_amt"),
                "same_day_buy_krw": domestic_balance.get("same_day_buy_krw"),
                "same_day_sell_krw": domestic_balance.get("same_day_sell_krw"),
                "holdings_count": len(domestic_balance.get("holdings", []) or []),
                "raw_output2": domestic_balance.get("raw", {}).get("output2", {}),
            },
            "present_balance": {
                "usd_krw": present_balance.get("usd_krw"),
                "krw_balance": present_balance.get("krw_balance"),
                "withdrawable_krw": present_balance.get("withdrawable_krw"),
                "meta": present_balance.get("meta", {}),
                "raw_output3": present_balance.get("raw", {}).get("output3", {}),
            },
            "overseas_balance": {
                "total_eval": overseas_balance.get("total_eval"),
                "cash_balance": overseas_balance.get("cash_balance"),
                "holdings_count": len(overseas_balance.get("holdings", []) or []),
            },
            "live_state_seed_samples": {k: (v.get("seed") if isinstance(v, dict) else v) for k, v in list(live_state.items())[:5]} if isinstance(live_state, dict) else {},
            "is_real": kis_is_real,
            "account": kis_account[:4] + "****" if len(kis_account) > 4 else kis_account,
        }
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, result=result)


def live_status():
    symbol = wiz.request.query("symbol", "035420")
    market = wiz.request.query("market", "KS")
    strategy = wiz.request.query("strategy", "vrev")
    seed = float(wiz.request.query("seed", "5000000"))
    force_refresh = wiz.request.query("force_refresh", "false").lower() == "true"
    cache_key = f"{symbol}:{market}:{strategy}:{round(float(seed or 0), 2)}"
    cached_entry = _live_status_cache.get(cache_key)
    if force_refresh is False and isinstance(cached_entry, dict):
        cache_age = _time.monotonic() - float(cached_entry.get("ts", 0) or 0)
        if cache_age < _LIVE_STATUS_CACHE_TTL_SEC:
            payload = _copy.deepcopy(cached_entry.get("payload", {}))
            payload["cached"] = True
            payload["cache_age_sec"] = round(cache_age, 2)
            wiz.response.status(200, **payload)

    engine = None
    budget_status = {}
    effective_seed = seed
    auto_enabled = False
    kis_status = {}
    worker_status = {}
    active_positions = []
    daily_loss = {}
    plan = None
    status = None
    is_loading = False  # 시그널 계산 중 플래그

    try:
        engine = _engine()
        if force_refresh:
            engine._invalidate_kis_cache()
        try:
            kis_status = engine.check_kis_connection()
        except Exception:
            kis_status = (cached_entry or {}).get("payload", {}).get("kis_status", {}) if isinstance(cached_entry, dict) else {}
        # 폴링에서는 KIS 강제 조회를 피하고, 수동 갱신에서만 실조회한다.
        budget_status = engine.shared_budget_status(requested_seed=seed, use_cache_only=(force_refresh is False))
        effective_seed = budget_status.get("effective_daytrade_seed", budget_status.get("live_order_seed", seed)) or seed
        auto_enabled = engine.auto_enabled()
        try:
            worker_status = _get_struct().trading.worker_status()
        except Exception:
            worker_status = (cached_entry or {}).get("payload", {}).get("worker_status", {}) if isinstance(cached_entry, dict) else {}
        budget_status = _merge_budget_with_worker_cache(budget_status, worker_status)
        budget_status = _normalize_budget_total_asset(budget_status)
        try:
            if force_refresh:
                active_positions = engine.active_positions(sync_broker=True)
            else:
                active_positions = _fast_active_positions_snapshot(market=market, refresh_quotes=True)
        except Exception:
            active_positions = (cached_entry or {}).get("payload", {}).get("active_positions", []) if isinstance(cached_entry, dict) else []
        try:
            daily_loss = engine.daily_loss_status(requested_seed=seed, use_live_price=force_refresh, use_cache_only=(force_refresh is False), market=market)
        except Exception:
            daily_loss = (cached_entry or {}).get("payload", {}).get("daily_loss", {}) if isinstance(cached_entry, dict) else {}
    except Exception as e:
        if isinstance(cached_entry, dict):
            payload = _copy.deepcopy(cached_entry.get("payload", {}))
            payload["cached"] = True
            payload["degraded"] = True
            payload["message"] = f"엔진 초기화 오류로 캐시 응답 사용: {str(e)}"
            wiz.response.status(200, **payload)
        wiz.response.status(400, message=f"엔진 초기화 오류: {str(e)}")

    # ─────────────────────────────────────────────────────────────
    # signal_status 계산
    # 엔진 내부 fallback/오류 복원력을 사용하고, 임시 스레드 타임아웃은 쓰지 않는다.
    # 타임아웃 스레드는 종료되지 않고 누적될 수 있어 서버 안정성을 해친다.
    # ─────────────────────────────────────────────────────────────
    try:
        sym_name = engine.strategy.symbol_name(symbol)
        status = engine.signal_status(
            symbol=symbol,
            market=market,
            seed=effective_seed,
            name=sym_name,
            strategy_id=strategy,
            sync_broker=force_refresh,
        )
        runtime = status.get("runtime", {}) if isinstance(status, dict) else {}
        is_loading = bool(runtime.get("risk_status") == "DEGRADED_LOADING")
    except Exception as e:
        _dump_error("live_status_signal", e)
        is_loading = False
        status = None

    # 시그널이 없으면 마지막 저장된 state에서 lite 구성
    if status is None:
        try:
            saved_map = engine._load_state_map()
            key = engine._state_key(symbol, market)
            saved_state = saved_map.get(key, {})
            profile = engine._profile_for(symbol, strategy_id=strategy)
            _cur = float(saved_state.get("last_price", 0) or 0)
            _anchor = float(saved_state.get("anchor_price", 0) or 0)
            _b1 = _anchor * (1 + float(profile.get("buy_trigger_1_pct", -0.5)) / 100) if _anchor > 0 else 0
            status = {
                "signal": {
                    "action": saved_state.get("last_signal", "HOLD"),
                    "reason": "데이터 로딩 중...",
                    "current_price": _cur,
                    "anchor_price": _anchor,
                    "buy1_trigger": _b1,
                    "buy2_trigger": 0,
                    "avg_price": float(saved_state.get("avg_price", 0) or 0),
                    "position_qty": int(saved_state.get("position_qty", 0) or 0),
                    "price_source": "cached_state",
                    "session_date": saved_state.get("session_date", ""),
                    "strategy_id": strategy,
                },
                "state": saved_state,
                "profile": profile,
                "runtime": {},
                "feature_snapshot": None,
                "is_loading": True,
            }
        except Exception:
            # 최소 응답 구성
            status = {
                "signal": {"action": "HOLD", "reason": "데이터 로딩 중...", "current_price": 0,
                           "buy1_trigger": 0, "buy2_trigger": 0, "price_source": "unavailable"},
                "state": {}, "profile": {}, "runtime": {}, "feature_snapshot": None, "is_loading": True,
            }

    # ─────────────────────────────────────────────────────────────
    # plan 구성
    # ─────────────────────────────────────────────────────────────
    try:
        plan = _build_live_plan_payload(status, budget_status, effective_seed, seed)
        plan["is_loading"] = is_loading
    except Exception as e:
        plan = {"is_loading": is_loading, "budget_status": budget_status, "error": str(e)}

    try:
        max_affordable_per_share = _recommendation_price_cap(engine, budget_status, seed)
    except Exception:
        max_affordable_per_share = _recommendation_price_cap(_engine(), budget_status, seed)

    try:
        recommendation, max_affordable_per_share = _stable_recommendation(
            _daytrade(),
            engine,
            budget_status,
            seed,
            market=market,
            strategy_id="" if strategy == "all" else strategy,
            symbol=status.get("signal", {}).get("symbol", symbol),
        )
    except Exception:
        recommendation = None

    payload = {
        "status": status,
        "budget_status": budget_status,
        "kis_status": kis_status,
        "auto_enabled": auto_enabled,
        "active_positions": active_positions,
        "daily_loss": daily_loss,
        "plan": plan,
        "max_affordable_per_share": max_affordable_per_share,
        "worker_status": worker_status,
        "recommendation": recommendation,
        "is_loading": is_loading,
        "cached": False,
        "degraded": False,
    }
    _live_status_cache[cache_key] = {"ts": _time.monotonic(), "payload": _copy.deepcopy(payload)}
    wiz.response.status(200, **payload)


def execute_live():
    symbol = wiz.request.query("symbol", "035420")
    market = wiz.request.query("market", "KS")
    strategy = wiz.request.query("strategy", "vrev")
    seed = float(wiz.request.query("seed", "5000000"))
    try:
        engine = _engine()
        budget_status = engine.shared_budget_status(requested_seed=seed)
        effective_seed = budget_status.get("effective_daytrade_seed", budget_status.get("live_order_seed", seed))
        result = engine.execute_live(
            symbol=symbol, market=market, seed=effective_seed,
            name=engine.strategy.symbol_name(symbol),
            strategy_id=strategy,
            force=False,
        )
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, result=result, budget_status=budget_status)


def update_trade_settings():
    symbol = wiz.request.query("symbol", "035420")
    market = wiz.request.query("market", "KS")
    strategy = wiz.request.query("strategy", "vrev")
    seed = float(wiz.request.query("seed", "5000000"))
    manual_sell_enabled = wiz.request.query("manual_sell_enabled", "")
    manual_sell_target_price = wiz.request.query("manual_sell_target_price", "")
    stop_loss_enabled = wiz.request.query("stop_loss_enabled", "")
    stop_loss_price = wiz.request.query("stop_loss_price", "")
    try:
        budget_status = _engine().shared_budget_status(requested_seed=seed)
        effective_seed = budget_status.get("effective_daytrade_seed", budget_status.get("live_order_seed", seed))
        value = None
        manual_enabled = None
        stop_enabled = None
        stop_value = None
        if manual_sell_enabled != "":
            manual_enabled = manual_sell_enabled.lower() in ("true", "1", "yes")
        if manual_sell_target_price != "":
            value = float(manual_sell_target_price)
        if stop_loss_enabled != "":
            stop_enabled = stop_loss_enabled.lower() in ("true", "1", "yes")
        if stop_loss_price != "":
            stop_value = float(stop_loss_price)
        status = _engine().update_trade_settings(
            symbol=symbol,
            market=market,
            seed=effective_seed,
            name=_daytrade().symbol_name(symbol),
            strategy_id=strategy,
            manual_sell_enabled=manual_enabled,
            manual_sell_target_price=value,
            stop_loss_enabled=stop_enabled,
            stop_loss_price=stop_value,
        )
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, status=status, budget_status=budget_status)


def manual_sell():
    symbol = wiz.request.query("symbol", "035420")
    market = wiz.request.query("market", "KS")
    strategy = wiz.request.query("strategy", "vrev")
    seed = float(wiz.request.query("seed", "5000000"))
    try:
        budget_status = _engine().shared_budget_status(requested_seed=seed)
        effective_seed = budget_status.get("effective_daytrade_seed", budget_status.get("live_order_seed", seed))
        result = _engine().manual_sell(
            symbol=symbol,
            market=market,
            seed=effective_seed,
            name=_daytrade().symbol_name(symbol),
            strategy_id=strategy,
        )
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, result=result, budget_status=budget_status)


def search_symbols():
    query = wiz.request.query("query", "")
    try:
        results = _daytrade().search_symbols(query=query)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, results=results)


def daily_log():
    date = wiz.request.query("date", "")
    try:
        engine = _engine()
        today = _kst_now().strftime("%Y%m%d")
        target_date = _date_compact(date) or today
        
        # Use the more direct and likely optimized engine method
        summary = engine.period_trade_summary(
            date_from=target_date,
            date_to=target_date,
            sync_broker=True,
            broker_lookback_days=_BROKER_SYNC_LOOKBACK_DAYS,
            include_valuation=(target_date == today)
        )

        if isinstance(summary, dict):
            selected_date = _date_display(target_date or summary.get("date_from", ""))
            summary["session_date"] = selected_date
            
            # Ensure essential keys are present, falling back to defaults if necessary
            summary["realized_profit"] = summary.get("pnl_gross", 0)
            summary["realized_profit_net"] = summary.get("pnl_net", 0)
            summary["remaining_positions"] = summary.get("remaining_positions", []) or []
            summary["remaining_position_count"] = len(summary.get("remaining_positions", []))
            summary["remaining_qty_total"] = summary.get("remaining_qty_total", 0)
            summary["remaining_cost_amount"] = summary.get("remaining_cost_amount", 0)

            today_display = _date_display(_kst_now().strftime("%Y%m%d"))
            
            if selected_date == today_display and summary.get("valuation_available", False):
                daily_loss = _engine().daily_loss_status(requested_seed=0, market=market)
                unrealized_pnl = summary.get("remaining_unrealized_pnl", 0)
                summary["unrealized_profit"] = unrealized_pnl
                summary["total_pnl"] = summary.get("pnl_net", 0) + unrealized_pnl
                summary["halt_new_buys"] = daily_loss.get("halt_new_buys", False)
                loss_limit = daily_loss.get("daily_loss_limit_krw", 0)
                summary["remaining_buffer"] = max(0, (loss_limit or 0) + summary["total_pnl"]) if loss_limit else 0
                summary["daily_loss_limit_krw"] = daily_loss.get("daily_loss_limit_krw", 0)
            else:
                summary["total_pnl"] = summary.get("pnl_net", 0)

    except Exception as e:
        _dump_error("daily_log_refactored", e)
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, summary=summary)


def period_summary():
    date_from = wiz.request.query("date_from", "")
    date_to = wiz.request.query("date_to", "")
    try:
        result = _engine().period_trade_summary(date_from=date_from, date_to=date_to)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, result=result)


def run_auto_cycle():
    seed = float(wiz.request.query("seed", "5000000"))
    try:
        result = _engine().auto_cycle(requested_seed=seed)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, result=result)


def toggle_auto_enabled():
    enabled_param = wiz.request.query("enabled", "")
    trading = _get_struct().trading
    try:
        if enabled_param == "":
            # 현재 상태 반전 (캐시에서 읽음)
            current = str(trading.get_config("daytrade_auto_enabled", "false")).lower() == "true"
            new_value = not current
        else:
            new_value = enabled_param.lower() in ("true", "1", "yes")
        # DB 쓰기 + 캐시 즉시 갱신. OFF는 자동청산 감시까지 함께 꺼야 자동 매도가 남지 않는다.
        trading.set_config("daytrade_auto_enabled", str(new_value).lower(), description="단타 자동매매 활성화")
        trading.set_config("daytrade_exit_watch_enabled", str(new_value).lower(), description="국장 단타 자동청산 감시 활성화")
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200,
        auto_enabled=new_value,
        exit_watch_enabled=new_value,
        worker_status=_get_struct().trading.worker_status())


def toggle_ignore_reserve():
    trading = _get_struct().trading
    try:
        current = str(trading.get_config("daytrade_ignore_reserve", "false")).lower() == "true"
        new_value = not current
        trading.set_config("daytrade_ignore_reserve", str(new_value).lower(), description="단타 무한매수 예약금 무시")
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, ignore_reserve=new_value)


def get_auto_status():
    try:
        engine = _engine()
        auto_enabled = engine.auto_enabled()
        budget_status = engine.shared_budget_status(requested_seed=0)
        daily_loss = engine.daily_loss_status(requested_seed=0, market="KS")
        active_positions = engine.active_positions()
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200,
        auto_enabled=auto_enabled,
        budget_status=budget_status,
        daily_loss=daily_loss,
        active_positions=active_positions,
    )


# =============================================================================
# 미장(US) 전용 API
# =============================================================================

def us_candidate_universe():
    try:
        candidates = _daytrade().us_candidate_universe()
    except Exception as e:
        wiz.response.status(500, message=str(e))
    wiz.response.status(200, candidates=candidates)


def us_search_symbols():
    query = wiz.request.query("query", "")
    limit = int(wiz.request.query("limit", "12"))
    try:
        results = _daytrade().search_symbols(query=query, limit=limit, market="US")
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, results=results)


def us_bootstrap():
    """미장 전용 부트스트랩: US 기본 심볼/전략/후보 로드 (경량화 — signal_status 제거)"""
    try:
        requested_seed = float(wiz.request.query("seed", "0") or 0)
        service = _daytrade()
        engine = _engine()
        us_candidates = service.us_candidate_universe()
        us_strategy_options = service.us_strategy_options()
        us_profile = service.us_profile()
        # 기본값: TQQQ, us_premarket 전략
        default_symbol = "TQQQ"
        default_strategy = "us_premarket"
        default_name = "ProShares UltraPro QQQ"
        seed = requested_seed if requested_seed > 0 else 5000.0
        # KIS API 호출 없이 state DB에서만 US 포지션 확인 (고속)
        try:
            active_positions = engine.active_positions_from_state(market_filter="US")
        except Exception:
            active_positions = []
        if active_positions:
            first = active_positions[0]
            default_symbol = first.get("symbol", default_symbol)
            default_name = first.get("name", default_name)
            default_strategy = first.get("strategy_id", default_strategy)
        # signal_status 제거 → 프론트에서 usLoadLiveStatus() 별도 호출로 분리
        kis_status = engine.check_kis_connection()
    except Exception as e:
        wiz.response.status(500, message=str(e))
    wiz.response.status(200,
        defaults={
            "symbol": default_symbol,
            "market": "US",
            "strategy": default_strategy,
            "seed": seed,
            "name": default_name,
        },
        us_candidates=us_candidates,
        us_strategy_options=us_strategy_options,
        us_profile=us_profile,
        active_positions=active_positions,
        status=None,
        kis_status=kis_status,
    )


def us_live_status():
    """미장 종목의 실시간 신호 상태 조회 (12초 캐싱 적용)"""
    symbol = wiz.request.query("symbol", "TQQQ")
    strategy = wiz.request.query("strategy", "us_premarket")
    seed = float(wiz.request.query("seed", "5000"))
    force_refresh = wiz.request.query("force_refresh", "false").lower() in ("true", "1")
    cache_key = f"US:{symbol}:{strategy}:{round(seed, 2)}"
    cached_entry = _live_status_cache.get(cache_key)
    if not force_refresh and isinstance(cached_entry, dict):
        cache_age = _time.monotonic() - float(cached_entry.get("ts", 0) or 0)
        if cache_age < _LIVE_STATUS_CACHE_TTL_SEC:
            payload = _copy.deepcopy(cached_entry.get("payload", {}))
            payload["cached"] = True
            payload["cache_age_sec"] = round(cache_age, 2)
            wiz.response.status(200, **payload)
    try:
        engine = _engine()
        name = ""
        for c in _daytrade().us_candidate_universe():
            if c.get("symbol") == symbol:
                name = c.get("name", "")
                break
        status = engine.signal_status(symbol=symbol, market="US", seed=seed, name=name, strategy_id=strategy)
    except Exception as e:
        if isinstance(cached_entry, dict):
            payload = _copy.deepcopy(cached_entry.get("payload", {}))
            payload["cached"] = True
            payload["degraded"] = True
            wiz.response.status(200, **payload)
        wiz.response.status(400, message=str(e))
    payload = {"status": status, "cached": False}
    _live_status_cache[cache_key] = {"ts": _time.monotonic(), "payload": _copy.deepcopy(payload)}
    wiz.response.status(200, **payload)


def us_execute_live():
    """미장 종목 실시간 주문 실행"""
    symbol = wiz.request.query("symbol", "TQQQ")
    strategy = wiz.request.query("strategy", "us_premarket")
    seed = float(wiz.request.query("seed", "5000"))
    try:
        engine = _engine()
        result = engine.execute_live(
            symbol=symbol, market="US", seed=seed,
            name="",
            strategy_id=strategy,
            force=False,
        )
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, result=result)


def us_toggle_auto():
    """미장 자동매매 On/Off 토글"""
    enabled_param = wiz.request.query("enabled", "")
    trading = _get_struct().trading
    try:
        if enabled_param == "":
            current = str(trading.get_config("daytrade_us_auto_enabled", "false")).lower() == "true"
            new_value = not current
        else:
            new_value = enabled_param.lower() in ("true", "1", "yes")
        trading.set_config("daytrade_us_auto_enabled", str(new_value).lower(), description="미장 단타 자동매매 활성화")
        trading.set_config("daytrade_us_exit_watch_enabled", str(new_value).lower(), description="미장 단타 자동청산 감시 활성화")
        
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, us_auto_enabled=new_value, us_exit_watch_enabled=new_value)


def us_get_auto_status():
    """미장 자동매매 상태 조회"""
    try:
        engine = _engine()
        us_auto_enabled = engine.auto_enabled(market="US")
        active_positions = [p for p in (engine.active_positions() or []) if str(p.get("market", "KS")).upper() in ("US", "NASD", "NYSE")]
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200,
        us_auto_enabled=us_auto_enabled,
        active_positions=active_positions,
    )


def us_daily_log():
    """미장 일별 거래 일지 (US 포지션 기준 체결 내역)"""
    date = wiz.request.query("date", "")
    try:
        today = _session_date_9am()
        target_date = _date_compact(date) or today
        summary = _load_daily_trade_summary(
            target_date=target_date,
            include_valuation=False,
            fallback_fast=(target_date == today),
        )
        if isinstance(summary, dict):
            # US 거래만 필터링
            us_trades = [t for t in (summary.get("trades", []) or []) if str(t.get("market", "KS")).upper() in ("US", "NASD", "NYSE")]
            us_positions = [p for p in (summary.get("remaining_positions", []) or []) if str(p.get("market", "KS")).upper() in ("US", "NASD", "NYSE")]
            summary = {
                "session_date": _date_display(target_date),
                "trades": us_trades,
                "trade_count": len(us_trades),
                "remaining_positions": us_positions,
                "remaining_position_count": len(us_positions),
            }
        else:
            summary = {"session_date": _date_display(target_date), "trades": [], "trade_count": 0, "remaining_positions": [], "remaining_position_count": 0}
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, summary=summary)


def us_verify_runtime():
    """미장 자동매매 런타임 검증 (주문 전송 없이 상태 점검만 수행)"""
    symbol = wiz.request.query("symbol", "TQQQ")
    strategy = wiz.request.query("strategy", "us_premarket")
    seed = float(wiz.request.query("seed", "5000") or 5000)
    date = wiz.request.query("date", "")
    try:
        engine = _engine()
        service = _daytrade()

        kis_status = engine.check_kis_connection()
        us_auto_enabled = engine.auto_enabled(market="US")

        status = engine.signal_status(symbol=symbol, market="US", seed=seed, name="", strategy_id=strategy)

        target_date = _date_compact(date) or _session_date_9am()
        summary = _load_daily_trade_summary(
            target_date=target_date,
            include_valuation=False,
            fallback_fast=(target_date == _session_date_9am()),
        )
        us_trades = [t for t in (summary.get("trades", []) or []) if str(t.get("market", "KS")).upper() in ("US", "NASD", "NYSE")]
        us_positions = [p for p in (summary.get("remaining_positions", []) or []) if str(p.get("market", "KS")).upper() in ("US", "NASD", "NYSE")]

        wins = 0
        losses = 0
        for item in us_trades:
            pnl_candidates = [
                item.get("pnl_net"), item.get("realized_pnl"), item.get("pnl_amount"),
                item.get("pnl"), item.get("profit"),
            ]
            pnl = 0.0
            for value in pnl_candidates:
                try:
                    pnl = float(value)
                    break
                except Exception:
                    continue
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1

        total_decision = wins + losses
        win_rate = round((wins / total_decision) * 100, 2) if total_decision > 0 else 0.0
        us_candidates = service.us_candidate_universe() or []

        checks = [
            {
                "key": "kis_connection",
                "label": "KIS 연결",
                "ok": bool(kis_status.get("connected", False)),
                "message": kis_status.get("message", ""),
            },
            {
                "key": "candidate_universe",
                "label": "후보 유니버스",
                "ok": len(us_candidates) > 0,
                "message": f"후보 {len(us_candidates)}개",
            },
            {
                "key": "signal_runtime",
                "label": "실시간 신호",
                "ok": isinstance(status, dict),
                "message": (status or {}).get("signal", {}).get("reason", ""),
            },
            {
                "key": "daily_log",
                "label": "일일 로그",
                "ok": isinstance(summary, dict),
                "message": f"체결 {len(us_trades)}건 · 잔여포지션 {len(us_positions)}건",
            },
        ]

        overall_ok = all([bool(item.get("ok", False)) for item in checks])
    except Exception as e:
        wiz.response.status(400, message=str(e))

    budget = {}
    try:
        budget = engine.shared_budget_status(requested_seed=seed)
    except Exception:
        budget = {}

    tradable_cash = float(budget.get("available_for_daytrade", 0) or 0)
    runtime_logs = []
    try:
        runtime_logs = engine._load_runtime_logs(market="US")[-30:]
    except Exception:
        runtime_logs = []

    checks.append({
        "key": "seed_budget",
        "label": "실주문 가능 시드",
        "ok": tradable_cash > 0,
        "message": f"가용 KRW {round(tradable_cash, 2):,.0f}",
    })
    checks.append({
        "key": "auto_toggle",
        "label": "자동매매 토글",
        "ok": bool(us_auto_enabled),
        "message": "활성" if us_auto_enabled else "비활성 (수동 실행만 가능)",
    })

    hard_fail_keys = ["kis_connection", "candidate_universe", "signal_runtime", "seed_budget"]
    hard_fails = [item for item in checks if item.get("key") in hard_fail_keys and bool(item.get("ok", False)) is False]
    overall_ok = len(hard_fails) == 0

    wiz.response.status(200,
        ok=overall_ok,
        checks=checks,
        hard_fails=hard_fails,
        metrics={
            "session_date": _date_display(target_date),
            "trade_count": len(us_trades),
            "remaining_position_count": len(us_positions),
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "us_auto_enabled": us_auto_enabled,
            "available_for_daytrade_krw": round(tradable_cash, 2),
        },
        kis_status=kis_status,
        status=status,
        recent_logs=runtime_logs,
    )


def us_model_ranking():
    """미장 전략별 승률/수익률 랭킹 분석"""
    seed = float(wiz.request.query("seed", "5000") or 5000)
    period = wiz.request.query("period", "10d")
    interval = wiz.request.query("interval", "5m")
    max_symbols = int(wiz.request.query("max_symbols", "8") or 8)
    try:
        service = _daytrade()
        options = service.us_strategy_options() or []
        candidates = (service.us_candidate_universe() or [])[:max(3, min(max_symbols, 20))]

        rankings = []
        for opt in options:
            strategy_id = str(opt.get("id", "") or "").strip()
            if strategy_id == "":
                continue
            rows = []
            failures = []
            for cand in candidates:
                symbol = str(cand.get("symbol", "") or "").strip().upper()
                if symbol == "":
                    continue
                try:
                    result = service.backtest(
                        symbol,
                        market="US",
                        period=period,
                        interval=interval,
                        seed=seed,
                        strategy_id=strategy_id,
                    ) or {}
                    summary = result.get("summary", {}) or {}
                    rows.append({
                        "symbol": symbol,
                        "name": cand.get("name", ""),
                        "total_return": float(summary.get("total_return", 0) or 0),
                        "win_rate": float(summary.get("win_rate", 0) or 0),
                        "max_drawdown": float(summary.get("max_drawdown", 0) or 0),
                        "score": float(summary.get("score", 0) or 0),
                    })
                except Exception as e:
                    failures.append({"symbol": symbol, "message": str(e)})

            tested = len(rows)
            avg_return = sum(x.get("total_return", 0) for x in rows) / tested if tested > 0 else 0.0
            avg_win = sum(x.get("win_rate", 0) for x in rows) / tested if tested > 0 else 0.0
            avg_mdd = sum(x.get("max_drawdown", 0) for x in rows) / tested if tested > 0 else 0.0
            avg_score = sum(x.get("score", 0) for x in rows) / tested if tested > 0 else 0.0
            rank_score = (avg_return * 0.55) + (avg_win * 0.35) - (abs(avg_mdd) * 0.10)

            explanation = f"평균 수익률 {avg_return:.2f}%, 승률 {avg_win:.2f}%, 최대낙폭 {avg_mdd:.2f}% 기준"
            rankings.append({
                "strategy_id": strategy_id,
                "strategy_name": opt.get("name", strategy_id),
                "tested_symbols": tested,
                "avg_return": round(avg_return, 4),
                "avg_win_rate": round(avg_win, 2),
                "avg_max_drawdown": round(avg_mdd, 2),
                "avg_score": round(avg_score, 4),
                "rank_score": round(rank_score, 4),
                "top_symbols": sorted(rows, key=lambda x: x.get("total_return", -999999), reverse=True)[:3],
                "failures": failures[:5],
                "explanation": explanation,
            })

        rankings.sort(key=lambda x: x.get("rank_score", -999999), reverse=True)
        for idx, row in enumerate(rankings):
            row["rank"] = idx + 1
    except Exception as e:
        wiz.response.status(400, message=str(e))

    wiz.response.status(200,
        seed=seed,
        period=period,
        interval=interval,
        symbol_count=len(candidates),
        rankings=rankings,
    )


def us_manual_sell():
    """미장 종목 수동 즉시 매도"""
    symbol = wiz.request.query("symbol", "TQQQ")
    strategy = wiz.request.query("strategy", "us_premarket")
    seed = float(wiz.request.query("seed", "5000"))
    try:
        engine = _engine()
        result = engine.manual_sell(
            symbol=symbol,
            market="US",
            seed=seed,
            name="",
            strategy_id=strategy,
        )
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, result=result)


def us_auto_cycle():
    """미장 자동순환 실행 (포지션 청산감시 + 신규 진입)"""
    seed = float(wiz.request.query("seed", "5000"))
    try:
        result = _engine().us_auto_cycle(requested_seed=seed)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, result=result)


def us_execute_exit_watch():
    """미장 포지션 자동청산 감시 실행"""
    seed = float(wiz.request.query("seed", "5000"))
    try:
        result = _engine().us_execute_exit_watch(requested_seed=seed)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, result=result)
