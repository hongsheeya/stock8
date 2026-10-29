import traceback as _tb
import os as _os
import time as _time
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
_LIVE_STATUS_CACHE_TTL_SEC = 12.0
_live_status_cache = {}
_ACTIVE_POSITIONS_CACHE_TTL_SEC = 4.0
_active_positions_cache = {}
_ACTIVE_POSITION_QUOTE_TTL_SEC = 4.0
_active_position_quote_cache = {}
_BROKER_SYNC_LOOKBACK_DAYS = 7
_TRADING_MODE = str(_os.environ.get("TRADING_MODE", "PAPER") or "PAPER").strip().upper()
_DAYTRADE_HARD_LOCKED = str(_os.environ.get("STOCK8_DAYTRADE_HARD_LOCK", "false")).lower() in ("1", "true", "yes", "on")
_PAPER_DAYTRADE_FULL_ACCESS = _TRADING_MODE == "PAPER" and not _DAYTRADE_HARD_LOCKED
_DAYTRADE_LOCK_MESSAGE = "단타 기능은 현재 운영 안정화를 위해 완전히 봉인되어 있습니다."

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


def _daytrade():
    return _get_struct().trading.daytrade


def _engine():
    return _get_struct().trading.daytrade_engine


def _get_config(key, default=""):
    trading = _get_struct().trading
    getter = getattr(trading, "get_config", None)
    if callable(getter):
        return getter(key, default)
    row = trading.db("trading_config").get(key=key)
    return row.get("value", default) if row else default


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "y", "on")


def _is_admin_user(user):
    role = str((user or {}).get("role", "") or "").lower()
    email = str((user or {}).get("email", "") or "").strip().lower()
    return role == "admin" or email == "gigukbyun@gmail.com"


def _session_user():
    session = wiz.model("portal/season/session").use()
    user_id = session.get("id")
    if not user_id:
        wiz.response.status(401, message="로그인이 필요합니다.")
    user = _get_struct().user.get(id=user_id)
    if not user:
        wiz.response.status(404, message="사용자 정보를 찾을 수 없습니다.")
    return user


def _daytrade_access_payload():
    user = _session_user()
    is_admin = _is_admin_user(user)
    feature_enabled = not _DAYTRADE_HARD_LOCKED and (_TRADING_MODE == "LIVE" or _PAPER_DAYTRADE_FULL_ACCESS or _truthy(_get_config("daytrade_feature_enabled", "false")))
    authorized = is_admin and not _DAYTRADE_HARD_LOCKED
    confirmed = is_admin and not _DAYTRADE_HARD_LOCKED
    return {
        "is_admin": is_admin,
        "daytrade_feature_enabled": feature_enabled,
        "daytrade_user_authorized": authorized,
        "daytrade_user_confirmed": confirmed,
        "daytrade_access_enabled": False if _DAYTRADE_HARD_LOCKED else feature_enabled and authorized and confirmed,
        "daytrade_hard_locked": _DAYTRADE_HARD_LOCKED,
        "message": _DAYTRADE_LOCK_MESSAGE if _DAYTRADE_HARD_LOCKED else "",
    }


def _require_daytrade_access():
    payload = _daytrade_access_payload()
    payload.pop('message', None)
    if payload.get("daytrade_hard_locked"):
        wiz.response.status(403, message=_DAYTRADE_LOCK_MESSAGE, **payload)
    if payload.get("daytrade_feature_enabled") is False:
        wiz.response.status(403, message="단타 기능이 관리자 설정에서 비활성화되어 있습니다.", **payload)
    if payload.get("daytrade_user_authorized") is False:
        wiz.response.status(403, message="관리자 인증을 받은 사용자만 단타 기능을 사용할 수 있습니다.", **payload)
    if payload.get("daytrade_user_confirmed") is False:
        wiz.response.status(403, message="단타 위험 확인 문구 입력이 필요합니다.", **payload)
    return payload


def _page_budget_status(engine, seed, force=False):
    budget = engine.shared_budget_status(requested_seed=seed, use_cache_only=not force)
    if not force and (budget.get('budget_status') == 'unavailable' or budget.get('source') == 'cache_miss'):
        # A cold cache is not a zero balance. Warm it on the first page read;
        # subsequent polls use the existing engine TTL rather than refetching.
        # 10-18: LIVE was excluded, and with LIVE day trading OFF nothing else
        # fills the cache, so the LIVE page showed a ₩0 seed. The warm-up is a
        # read-only balance query.
        with engine._broker().request_options(timeout=8, retries=0):
            budget = engine.shared_budget_status(requested_seed=seed, use_cache_only=False)
    return budget


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
    engine = _engine()
    market_key = str(market or "KS").upper().strip()
    cache_key = f"{market_key}:{'quotes' if refresh_quotes else 'state'}"
    cached = _active_positions_cache.get(cache_key)
    if isinstance(cached, dict):
        age = _time.monotonic() - float(cached.get("ts", 0) or 0)
        if age < _ACTIVE_POSITIONS_CACHE_TTL_SEC:
            return [row for row in _copy.deepcopy(cached.get("payload", [])) if engine.analysis_allowed(row.get('symbol', ''))]

    engine = _engine()
    rows = []
    for row in (engine.active_positions_from_state() or []):
        if not engine.analysis_allowed(row.get('symbol', '')):
            continue
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
        configured_seed = float(
            _get_struct().trading.get_config(
                "daytrade_default_seed",
                defaults.get("seed", 5000000),
            ) or defaults.get("seed", 5000000)
        )
        seed = requested_seed if requested_seed > 0 else configured_seed
        kis_status = engine.check_kis_connection()
        budget_status = _page_budget_status(engine, seed)
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
        daily_loss = engine.daily_loss_status(requested_seed=defaults["seed"], use_live_price=False, use_cache_only=True)
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
        budget_status = _page_budget_status(engine, seed, force=force_refresh)
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
            daily_loss = engine.daily_loss_status(requested_seed=seed, use_live_price=force_refresh, use_cache_only=(force_refresh is False))
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
                daily_loss = _engine().daily_loss_status(requested_seed=0)
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
        engine = _engine()
        # A manual "즉시 점검" must never spend its request budget on
        # discovery/backtests while an existing position needs an exit.
        exit_result = engine.kr_execute_exit_watch(requested_seed=seed)
        if exit_result.get("executed") or exit_result.get("submitted"):
            result = {
                **exit_result,
                "message": exit_result.get("message", "청산 주문을 우선 처리했습니다."),
                "exit_priority": True,
            }
        else:
            result = engine.auto_cycle(requested_seed=seed)
            result["exit_watch"] = exit_result
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


def _guard_daytrade_api(name):
    original = globals().get(name)
    if not callable(original):
        return

    def _wrapped(*args, **kwargs):
        _require_daytrade_access()
        return original(*args, **kwargs)

    globals()[name] = _wrapped


for _daytrade_api_name in [
    "bootstrap",
    "active_positions_snapshot",
    "recommend",
    "sync_seed",
    "train_symbol",
    "live_status",
    "execute_live",
    "update_trade_settings",
    "manual_sell",
    "search_symbols",
    "daily_log",
    "period_summary",
    "run_auto_cycle",
    "toggle_auto_enabled",
]:
    _guard_daytrade_api(_daytrade_api_name)


def kis_call_stats():
    """Admin: KIS gateway calls by TR id over the last N minutes (no parameters or replies)."""
    import sys as _sys
    if not _is_admin_user(_session_user()):
        wiz.response.status(403, message="관리자만 볼 수 있습니다.")
    minutes = max(1, min(240, int(float(wiz.request.query("minutes", "10") or 10))))
    cutoff = _time.time() - minutes * 60
    rows = [row for row in list(_sys.__dict__.get("_stock8_kis_call_log") or []) if row[0] >= cutoff]
    by_key = {}
    for ts, tr_id, path, waited, outcome, thread in rows:
        item = by_key.setdefault(f"{tr_id} {path.rsplit('/', 1)[-1]}", {"calls": 0, "wait_sec": 0.0, "timeouts": 0, "threads": {}})
        item["calls"] += 1
        item["wait_sec"] = round(item["wait_sec"] + waited, 1)
        item["timeouts"] += outcome == "timeout"
        item["threads"][thread] = item["threads"].get(thread, 0) + 1
    span = max(60.0, min(minutes * 60.0, _time.time() - (rows[0][0] if rows else _time.time())))
    wiz.response.status(200, minutes=minutes, calls=len(rows), calls_per_min=round(len(rows) / span * 60, 1),
                        timeouts=sum(1 for r in rows if r[4] == "timeout"),
                        avg_wait_sec=round(sum(r[3] for r in rows) / len(rows), 2) if rows else 0.0,
                        max_wait_sec=round(max((r[3] for r in rows), default=0.0), 2),
                        cache_hits_total=(_sys.__dict__.get("_stock8_kis_cache_hits") or {}).get("hits", 0),
                        by_call=[{"call": k, **v} for k, v in sorted(by_key.items(), key=lambda kv: -kv[1]["calls"])[:25]])


def ks_minute_backfill():
    """Admin: start (action=start) or read the one-year KS minute-bar backfill."""
    import sys as _sys
    import threading as _threading
    if not _is_admin_user(_session_user()):
        wiz.response.status(403, message="관리자만 실행할 수 있습니다.")
    state = _sys.__dict__.setdefault("_stock8_ks_backfill", {"running": False})
    if str(wiz.request.query("action", "") or "") == "start" and not state.get("running"):
        owner = str(_session_user().get("id") or "")
        days_back = max(1, min(400, int(float(wiz.request.query("days", "370") or 370))))
        state["running"] = True  # claim before the thread starts

        def job():
            # Broker keys are per user: run under the starting admin's session.
            import flask
            with wiz.server.app.flask.test_request_context('/'):
                flask.session['id'] = owner
                state["running"] = False
                try:
                    _engine().backfill_ks_minute_archive(days_back=days_back)
                except Exception as exc:
                    state.update(running=False, last_error=str(exc)[:200])

        _threading.Thread(target=job, daemon=True, name="stock8-ks-backfill").start()
    wiz.response.status(200, **{k: v for k, v in state.items()})

