import copy as _copy
import datetime as _datetime
import sys as _sys
import threading as _threading
import time as _time

_STRUCT_CACHE = {"obj": None, "error": None, "error_at": 0.0}
_STRUCT_ERROR_TTL_SEC = 5.0
_BROKER_SYNC_LOOKBACK_DAYS = 7
_US_LIVE_STATUS_CACHE = {}
_US_DAILY_LOG_CACHE = {}
_US_VERIFY_CACHE = {}
_US_AUTO_STATUS_CACHE = {}
_US_SNAPSHOT_CACHE = {}
_US_BOOTSTRAP_CACHE = {}
_US_MODEL_RANKING_CACHE = {}
_SINGLEFLIGHT_EVENTS = {}
_SINGLEFLIGHT_LOCK = _threading.Lock()
_US_LIVE_STATUS_TTL_SEC = 12.0
_US_DAILY_LOG_TTL_SEC = 20.0
_US_VERIFY_TTL_SEC = 20.0
_US_AUTO_STATUS_TTL_SEC = 12.0
_US_SNAPSHOT_TTL_SEC = 12.0
_US_BOOTSTRAP_TTL_SEC = 10.0
_US_MODEL_RANKING_TTL_SEC = 900.0
_US_DEFAULT_SEED_KRW = 5000000.0
_US_DEFAULT_RANKING_SYMBOLS = 12
_US_MAX_RANKING_SYMBOLS = 18
_US_MIN_TRADABLE_WIN_RATE = 35.0
_US_MIN_TRADABLE_VALIDATION_WIN_RATE = 30.0
_US_MIN_TRADABLE_RETURN = 0.5
_US_MAX_TRADABLE_MDD = 18.0
_US_MIN_TRADABLE_AVG_TRADES = 0.6

_TIME = wiz.model("portal/trading/kst")


def _kst_now():
    return _TIME.now()


def _session_date_9am(now=None):
    now = now or _kst_now()
    if now.hour < 9:
        now = now - _datetime.timedelta(days=1)
    return now.strftime("%Y%m%d")


def _date_compact(value=""):
    return str(value or "").strip().replace("-", "")[:8]


def _date_display(value=""):
    text = _date_compact(value)
    if len(text) != 8:
        return str(value or "")
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def _cache_get(store, key, ttl_sec):
    entry = store.get(key)
    if isinstance(entry, dict) is False:
        return None, None
    age = _time.monotonic() - float(entry.get("ts", 0.0) or 0.0)
    if age >= ttl_sec:
        return None, None
    return _copy.deepcopy(entry.get("payload", {})), round(age, 2)


def _cache_set(store, key, payload):
    store[key] = {
        "ts": _time.monotonic(),
        "payload": _copy.deepcopy(payload),
    }


def _singleflight(key, builder, timeout_sec=60.0):
    leader = False
    with _SINGLEFLIGHT_LOCK:
        event = _SINGLEFLIGHT_EVENTS.get(key)
        if event is None:
            event = _threading.Event()
            _SINGLEFLIGHT_EVENTS[key] = event
            leader = True
    if leader:
        try:
            return builder(), True
        finally:
            with _SINGLEFLIGHT_LOCK:
                event.set()
                _SINGLEFLIGHT_EVENTS.pop(key, None)
    event.wait(timeout=timeout_sec)
    return None, False


def _quality_gate(rankings):
    usable = []
    warnings = []
    for row in rankings or []:
        tested = int(row.get("tested_symbols", 0) or 0)
        avg_return = float(row.get("avg_return", 0) or 0)
        avg_validation_return = float(row.get("avg_validation_return", avg_return) or 0)
        avg_win = float(row.get("avg_win_rate", 0) or 0)
        avg_validation_win = float(row.get("avg_validation_win_rate", avg_win) or 0)
        avg_trades = float(row.get("avg_trades", 0) or 0)
        avg_validation_trades = float(row.get("avg_validation_trades", avg_trades) or 0)
        avg_mdd = abs(float(row.get("avg_max_drawdown", 0) or 0))
        avg_robustness = float(row.get("avg_robustness", 0) or 0)
        avg_overfit_gap = abs(float(row.get("avg_overfit_gap", 0) or 0))
        is_usable = tested >= 3 and avg_return >= _US_MIN_TRADABLE_RETURN and avg_validation_return >= 0 and avg_win >= _US_MIN_TRADABLE_WIN_RATE and avg_validation_win >= _US_MIN_TRADABLE_VALIDATION_WIN_RATE and avg_trades >= _US_MIN_TRADABLE_AVG_TRADES and avg_validation_trades >= _US_MIN_TRADABLE_AVG_TRADES and avg_mdd <= _US_MAX_TRADABLE_MDD and avg_robustness > 0 and avg_overfit_gap <= 12.0
        row["tradable"] = is_usable
        if is_usable:
            usable.append(row)
            continue
        issues = []
        if tested < 3:
            issues.append(f"표본 부족({tested})")
        if avg_return < _US_MIN_TRADABLE_RETURN:
            issues.append(f"수익률 {avg_return:.2f}%")
        if avg_validation_return < 0:
            issues.append(f"검증수익 {avg_validation_return:.2f}%")
        if avg_win < _US_MIN_TRADABLE_WIN_RATE:
            issues.append(f"승률 {avg_win:.2f}%")
        if avg_validation_win < _US_MIN_TRADABLE_VALIDATION_WIN_RATE:
            issues.append(f"검증승률 {avg_validation_win:.2f}%")
        if avg_trades < _US_MIN_TRADABLE_AVG_TRADES:
            issues.append(f"거래빈도 {avg_trades:.2f}/day")
        if avg_validation_trades < _US_MIN_TRADABLE_AVG_TRADES:
            issues.append(f"검증빈도 {avg_validation_trades:.2f}/day")
        if avg_mdd > _US_MAX_TRADABLE_MDD:
            issues.append(f"MDD {avg_mdd:.2f}%")
        if avg_robustness <= 0:
            issues.append(f"견고성 {avg_robustness:.2f}")
        if avg_overfit_gap > 12.0:
            issues.append(f"과최적화 {avg_overfit_gap:.2f}")
        row["quality_note"] = ", ".join(issues)
    if len(rankings or []) == 0:
        warnings.append("랭킹 결과가 없습니다.")
    if len(usable) == 0:
        warnings.append("현재 기준으로는 실거래 권장 전략이 없습니다.")
    return {
        "tradable_count": len(usable),
        "best_tradable": usable[0] if len(usable) > 0 else None,
        "min_win_rate": _US_MIN_TRADABLE_WIN_RATE,
        "min_validation_win_rate": _US_MIN_TRADABLE_VALIDATION_WIN_RATE,
        "min_return": _US_MIN_TRADABLE_RETURN,
        "min_avg_trades": _US_MIN_TRADABLE_AVG_TRADES,
        "max_drawdown": _US_MAX_TRADABLE_MDD,
        "warning_message": " ".join(warnings).strip(),
    }


def us_search_symbols():
    query = wiz.request.query("query", "")
    limit = int(wiz.request.query("limit", "12") or 12)
    try:
        results = _daytrade().search_symbols(query=query, limit=limit, market="US")
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, results=results)


def _get_struct():
    shared = getattr(_sys, "_page_daytrade_us_struct_obj", None)
    if shared is not None:
        _STRUCT_CACHE["obj"] = _refresh_trading_runtime(shared)
        _STRUCT_CACHE["error"] = None
        _STRUCT_CACHE["error_at"] = 0.0
        return _STRUCT_CACHE["obj"]
    cached = _STRUCT_CACHE.get("obj")
    if cached is not None:
        return _refresh_trading_runtime(cached)
    err = _STRUCT_CACHE.get("error")
    if err is not None and (_time.monotonic() - float(_STRUCT_CACHE.get("error_at", 0.0) or 0.0)) < _STRUCT_ERROR_TTL_SEC:
        raise err
    try:
        _STRUCT_CACHE["obj"] = _refresh_trading_runtime(wiz.model("struct"))
        setattr(_sys, "_page_daytrade_us_struct_obj", _STRUCT_CACHE["obj"])
        _STRUCT_CACHE["error"] = None
        _STRUCT_CACHE["error_at"] = 0.0
    except Exception as e:
        _STRUCT_CACHE["obj"] = None
        _STRUCT_CACHE["error"] = e
        _STRUCT_CACHE["error_at"] = _time.monotonic()
        raise
    return _STRUCT_CACHE["obj"]


def _refresh_trading_runtime(shared):
    try:
        trading = getattr(shared, "trading", None)
        if trading is None:
            return shared

        daytrade_engine_model = wiz.model("portal/trading/struct/daytrade_engine")
        cached_daytrade_engine_model = getattr(trading, "_DaytradeEngine", None)
        if cached_daytrade_engine_model is not daytrade_engine_model or hasattr(daytrade_engine_model, "_us_auto_buy_window"):
            trading._DaytradeEngine = daytrade_engine_model

        engine_model = wiz.model("portal/trading/struct/engine")
        if getattr(trading, "_Engine", None) is not engine_model:
            trading._Engine = engine_model
            trading._engine_obj = None

        kis_api_model = wiz.model("portal/trading/struct/kis_api")
        cached_kis_api_obj = getattr(trading, "_kis_api_obj", None)
        if getattr(trading, "_KisApi", None) is not kis_api_model:
            trading._KisApi = kis_api_model
            trading._kis_api_obj = None
        elif cached_kis_api_obj is not None and hasattr(cached_kis_api_obj, "us_auto_exchange_window") is False:
            trading._kis_api_obj = None
    except Exception:
        return shared
    return shared


def _daytrade():
    return _get_struct().trading.daytrade


def _engine():
    return _get_struct().trading.daytrade_engine


def _normalized_us_seed(seed=0.0, service=None):
    service = service or _daytrade()
    try:
        defaults = service.us_defaults() or {}
    except Exception:
        defaults = {}
    default_seed = float(defaults.get("seed", _US_DEFAULT_SEED_KRW) or _US_DEFAULT_SEED_KRW)
    try:
        return float(service._normalized_seed(seed, default_seed))
    except Exception:
        try:
            seed = float(seed or 0)
        except Exception:
            seed = 0.0
        if seed <= 0:
            seed = default_seed
        return max(100000.0, seed)


def _parse_us_seed(name="seed", default=0.0, service=None):
    raw = wiz.request.query(name, str(default or 0))
    try:
        value = float(raw or 0)
    except Exception:
        value = 0.0
    return _normalized_us_seed(value, service=service)


def _select_us_ranking_candidates(candidates, max_symbols, focus_symbol=""):
    items = [dict(item) for item in (candidates or []) if str(item.get("symbol", "") or "").strip() != ""]
    if len(items) <= max_symbols:
        return items
    selected = []
    seen = set()

    def _add(item):
        symbol = str(item.get("symbol", "") or "").strip().upper()
        if symbol == "" or symbol in seen:
            return
        selected.append(item)
        seen.add(symbol)

    focus_symbol = str(focus_symbol or "").strip().upper()
    if focus_symbol != "":
        for item in items:
            if str(item.get("symbol", "") or "").strip().upper() == focus_symbol:
                _add(item)
                break

    core_symbols = ["TQQQ", "SOXL", "SPXL", "UPRO", "NVDA", "AVGO", "TSLA", "PLTR", "MSTR", "COIN"]
    for symbol in core_symbols:
        for item in items:
            if str(item.get("symbol", "") or "").strip().upper() == symbol:
                _add(item)
                break
        if len(selected) >= max_symbols:
            return selected[:max_symbols]

    remaining = [item for item in items if str(item.get("symbol", "") or "").strip().upper() not in seen]
    slots = max(0, max_symbols - len(selected))
    if slots <= 0:
        return selected[:max_symbols]
    if slots >= len(remaining):
        for item in remaining:
            _add(item)
        return selected[:max_symbols]

    if slots == 1:
        _add(remaining[0])
    else:
        used_indexes = set()
        last_index = len(remaining) - 1
        for idx in range(slots):
            picked_index = int(round((last_index * idx) / (slots - 1)))
            used_indexes.add(picked_index)
            _add(remaining[picked_index])
        if len(selected) < max_symbols:
            for idx, item in enumerate(remaining):
                if idx in used_indexes:
                    continue
                _add(item)
                if len(selected) >= max_symbols:
                    break
    return selected[:max_symbols]


def _load_daily_trade_summary(target_date="", include_valuation=False):
    session_date = _date_compact(target_date) or _session_date_9am()
    engine = _engine()
    try:
        return engine.period_trade_summary(
            date_from=session_date,
            date_to=session_date,
            sync_broker=True,
            broker_lookback_days=_BROKER_SYNC_LOOKBACK_DAYS,
            include_valuation=include_valuation,
        )
    except Exception:
        return engine.daily_trade_summary(
            session_date=session_date,
            sync_broker=False,
            include_valuation=include_valuation,
        )


def _build_us_daily_payload(target_date=""):
    session_date = _date_compact(target_date) or _session_date_9am()
    cached_payload, _ = _cache_get(_US_DAILY_LOG_CACHE, session_date, _US_DAILY_LOG_TTL_SEC)
    if isinstance(cached_payload, dict):
        return cached_payload
    summary = _load_daily_trade_summary(target_date=session_date, include_valuation=False)
    if isinstance(summary, dict):
        us_trades = [t for t in (summary.get("trades", []) or []) if str(t.get("market", "KS")).upper() in ("US", "NASD", "NYSE")]
        us_positions = [p for p in (summary.get("remaining_positions", []) or []) if str(p.get("market", "KS")).upper() in ("US", "NASD", "NYSE")]
        wins = len([x for x in us_trades if float(x.get("pnl_net", 0) or 0) > 0])
        losses = len([x for x in us_trades if float(x.get("pnl_net", 0) or 0) < 0])
        decisions = wins + losses
        win_rate = round((wins / decisions) * 100, 2) if decisions > 0 else 0.0
        normalized = {
            "session_date": _date_display(session_date),
            "trades": us_trades,
            "trade_count": len(us_trades),
            "remaining_positions": us_positions,
            "remaining_position_count": len(us_positions),
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
        }
    else:
        normalized = {
            "session_date": _date_display(session_date),
            "trades": [],
            "trade_count": 0,
            "remaining_positions": [],
            "remaining_position_count": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
        }
    payload = {"summary": normalized, "cached": False}
    _cache_set(_US_DAILY_LOG_CACHE, session_date, payload)
    return payload


def _build_us_auto_status_payload(engine=None, trading=None):
    cache_key = "default"
    cached_payload, _ = _cache_get(_US_AUTO_STATUS_CACHE, cache_key, _US_AUTO_STATUS_TTL_SEC)
    if isinstance(cached_payload, dict):
        return cached_payload
    engine = engine or _engine()
    trading = trading or _get_struct().trading
    us_auto_enabled = engine.auto_enabled(market="US")
    active_positions = [p for p in (engine.active_positions() or []) if str(p.get("market", "KS")).upper() in ("US", "NASD", "NYSE")]
    worker_status = trading.worker_status() or {}
    kis_status = engine.check_kis_connection()
    market_open = bool(engine._us_market_open())
    premarket_open = bool(engine._us_premarket_open())
    auto_buy_window = engine._us_auto_buy_window()
    last_result = worker_status.get("last_result", {}) or {}
    us_auto_cycle = last_result.get("us_auto_cycle", {}) or {}
    us_exit_watch = last_result.get("us_exit_watch", {}) or {}

    if bool(worker_status.get("started", False)) is False:
        state_label = "STOPPED"
        state_reason = "백그라운드 자동매매 워커가 꺼져 있습니다."
        state_tone = "danger"
    elif us_auto_enabled is False:
        state_label = "STOPPED"
        state_reason = "미장 자동매매 토글이 꺼져 있습니다."
        state_tone = "muted"
    elif bool(kis_status.get("connected", False)) is False:
        state_label = "STOPPED"
        state_reason = str(kis_status.get("message", "KIS 연결이 필요합니다.") or "KIS 연결이 필요합니다.")
        state_tone = "danger"
    elif (market_open or premarket_open) and auto_buy_window.get("ready", False) is False:
        state_label = "READY"
        state_reason = str(auto_buy_window.get("message", "미국 프리마켓/본장 전이라 원화 자동환전 매수 대기 중입니다.") or "미국 프리마켓/본장 전이라 원화 자동환전 매수 대기 중입니다.")
        state_tone = "warning"
    elif market_open or premarket_open:
        state_label = "RUNNING"
        state_reason = str(us_auto_cycle.get("message", "프리마켓/본장 자동매매 감시 중입니다.") or "프리마켓/본장 자동매매 감시 중입니다.")
        state_tone = "success"
    else:
        state_label = "READY"
        state_reason = str(us_auto_cycle.get("message", "미국 주식 시장이 닫혀 있어 대기 중입니다.") or "미국 주식 시장이 닫혀 있어 대기 중입니다.")
        state_tone = "warning"

    payload = {
        "us_auto_enabled": us_auto_enabled,
        "active_positions": active_positions,
        "worker_status": worker_status,
        "kis_status": kis_status,
        "market_open": market_open,
        "premarket_open": premarket_open,
        "auto_buy_window": auto_buy_window,
        "state_label": state_label,
        "state_reason": state_reason,
        "state_tone": state_tone,
        "last_us_auto_cycle": us_auto_cycle,
        "last_us_exit_watch": us_exit_watch,
        "cached": False,
    }
    _cache_set(_US_AUTO_STATUS_CACHE, cache_key, payload)
    return payload


def _enrich_budget_status(engine, budget_status, market="US"):
    budget = dict(budget_status or {})
    portfolio = budget.get("portfolio", {}) or {}
    existing_used = float(budget.get("used_seed_krw", 0) or 0)
    market_used = float(budget.get("market_used_seed_krw", portfolio.get("active_entry_seed_krw", portfolio.get("active_cost_krw", existing_used))) or 0)
    cross_market_used = budget.get("cross_market_used_seed_krw", None)
    if cross_market_used is None:
        cross_market_used = market_used
        if str(market or "").upper() == "US":
            try:
                shared_portfolio = engine.portfolio_usage(use_live_price=True) or {}
                cross_market_used = float(shared_portfolio.get("active_entry_seed_krw", shared_portfolio.get("active_cost_krw", market_used)) or market_used)
            except Exception:
                cross_market_used = market_used
    cross_market_used = float(cross_market_used or 0)
    used_seed = market_used
    total_seed = float(budget.get("total_seed_krw", 0) or 0)
    if total_seed > 0:
        budget["remaining_seed_krw"] = round(max(0.0, total_seed - used_seed), 2)
        budget["seed_usage_pct"] = round((used_seed / total_seed * 100), 2) if total_seed > 0 else 0.0
    budget["market_used_seed_krw"] = round(market_used, 2)
    budget["cross_market_used_seed_krw"] = round(cross_market_used, 2)
    budget["used_seed_krw"] = round(used_seed, 2)
    budget["lane_isolated"] = True
    budget["budget_lane"] = budget.get("budget_lane") or "US_DAYTRADE"
    return budget


def _build_us_verify_payload(symbol="TQQQ", strategy="us_premarket", seed=_US_DEFAULT_SEED_KRW, engine=None, service=None, daily_payload=None, auto_payload=None, us_candidates=None, force_refresh=False):
    target_date = _session_date_9am()
    engine = engine or _engine()
    service = service or _daytrade()
    seed = _normalized_us_seed(seed, service=service)
    auto_payload = auto_payload or _build_us_auto_status_payload(engine=engine, trading=_get_struct().trading)
    current_auto_enabled = bool(auto_payload.get("us_auto_enabled", False))
    cache_key = f"{symbol}:{strategy}:{round(seed, 2)}:{target_date}:{1 if current_auto_enabled else 0}"
    cached_payload, _ = _cache_get(_US_VERIFY_CACHE, cache_key, _US_VERIFY_TTL_SEC)
    if force_refresh is False and isinstance(cached_payload, dict):
        return cached_payload

    kis_status = auto_payload.get("kis_status", {}) or engine.check_kis_connection()
    us_auto_enabled = current_auto_enabled
    live_payload, _ = _cache_get(_US_LIVE_STATUS_CACHE, f"{symbol}:{strategy}:{round(seed, 2)}", _US_LIVE_STATUS_TTL_SEC)
    if isinstance(live_payload, dict):
        status = live_payload.get("status", {})
    else:
        status = engine.signal_status(symbol=symbol, market="US", seed=seed, name="", strategy_id=strategy)
        _cache_set(_US_LIVE_STATUS_CACHE, f"{symbol}:{strategy}:{round(seed, 2)}", {"status": status, "cached": False})

    daily_payload = daily_payload or _build_us_daily_payload(target_date=target_date)
    summary = daily_payload.get("summary", {}) if isinstance(daily_payload, dict) else {}
    us_trades = summary.get("trades", []) or []
    us_positions = summary.get("remaining_positions", []) or []
    wins = int(summary.get("wins", 0) or 0)
    losses = int(summary.get("losses", 0) or 0)
    total_decision = wins + losses
    win_rate = round((wins / total_decision) * 100, 2) if total_decision > 0 else 0.0
    us_candidates = us_candidates if isinstance(us_candidates, list) else (service.us_candidate_universe() or [])
    budget = _enrich_budget_status(engine, engine.shared_budget_status(requested_seed=seed, market="US"), market="US")
    tradable_cash = float(budget.get("actual_orderable_seed_krw", budget.get("available_for_daytrade", 0)) or 0)
    tradable_usd = float(budget.get("us_combined_orderable_amount_usd", budget.get("us_orderable_amount_usd", 0)) or 0)
    executable_usd = float(budget.get("us_orderable_amount_usd", 0) or 0)

    checks = [
        {"key": "kis_connection", "label": "KIS 연결", "ok": bool(kis_status.get("connected", False)), "message": kis_status.get("message", "")},
        {"key": "candidate_universe", "label": "후보 유니버스", "ok": len(us_candidates) > 0, "message": f"후보 {len(us_candidates)}개"},
        {"key": "signal_runtime", "label": "실시간 신호", "ok": isinstance(status, dict), "message": (status or {}).get("signal", {}).get("reason", "")},
        {"key": "daily_log", "label": "일일 로그", "ok": isinstance(summary, dict), "message": f"체결 {len(us_trades)}건 · 잔여포지션 {len(us_positions)}건"},
        {"key": "seed_budget", "label": "실주문 가능 시드", "ok": tradable_cash > 0 and tradable_usd > 0, "message": f"가용 KRW {round(tradable_cash, 2):,.0f} · 통합 USD {round(tradable_usd, 2):,.2f} (실주문 USD {round(executable_usd, 2):,.2f})"},
        {"key": "auto_toggle", "label": "자동매매 토글", "ok": bool(us_auto_enabled), "message": "활성" if us_auto_enabled else "비활성 (수동 실행만 가능)"},
    ]
    hard_fail_keys = ["kis_connection", "candidate_universe", "signal_runtime", "seed_budget"]
    hard_fails = [item for item in checks if item.get("key") in hard_fail_keys and bool(item.get("ok", False)) is False]
    overall_ok = len(hard_fails) == 0
    try:
        recent_logs = engine._load_runtime_logs(market="US")[-30:]
    except Exception:
        recent_logs = []

    payload = {
        "ok": overall_ok,
        "checks": checks,
        "hard_fails": hard_fails,
        "metrics": {
            "session_date": _date_display(target_date),
            "trade_count": len(us_trades),
            "remaining_position_count": len(us_positions),
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "us_auto_enabled": us_auto_enabled,
            "available_for_daytrade_krw": round(tradable_cash, 2),
            "combined_orderable_usd": round(tradable_usd, 2),
            "executable_orderable_usd": round(executable_usd, 2),
        },
        "kis_status": kis_status,
        "status": status,
        "recent_logs": recent_logs,
        "budget_status": budget,
        "cached": False,
    }
    _cache_set(_US_VERIFY_CACHE, cache_key, payload)
    return payload


def _build_us_snapshot_payload(symbol="TQQQ", strategy="us_premarket", seed=_US_DEFAULT_SEED_KRW, force_refresh=False, engine=None, service=None, trading=None, us_candidates=None):
    service = service or _daytrade()
    seed = _normalized_us_seed(seed, service=service)
    cache_key = f"{symbol}:{strategy}:{round(seed, 2)}"
    cached_payload, _ = _cache_get(_US_SNAPSHOT_CACHE, cache_key, _US_SNAPSHOT_TTL_SEC)
    if force_refresh is False and isinstance(cached_payload, dict):
        return cached_payload

    def _builder():
        resolved_engine = engine or _engine()
        resolved_service = service or _daytrade()
        resolved_trading = trading or _get_struct().trading
        auto_payload = _build_us_auto_status_payload(engine=resolved_engine, trading=resolved_trading)
        daily_payload = _build_us_daily_payload()
        verify_payload = _build_us_verify_payload(
            symbol=symbol,
            strategy=strategy,
            seed=seed,
            engine=resolved_engine,
            service=resolved_service,
            daily_payload=daily_payload,
            auto_payload=auto_payload,
            us_candidates=us_candidates,
            force_refresh=force_refresh,
        )
        budget_status = _enrich_budget_status(resolved_engine, resolved_engine.shared_budget_status(requested_seed=seed, market="US"), market="US")
        live_payload, _ = _cache_get(_US_LIVE_STATUS_CACHE, cache_key, _US_LIVE_STATUS_TTL_SEC)
        if isinstance(live_payload, dict):
            status_payload = live_payload
        else:
            status_payload = {"status": resolved_engine.signal_status(symbol=symbol, market="US", seed=seed, name="", strategy_id=strategy), "cached": False}
            _cache_set(_US_LIVE_STATUS_CACHE, cache_key, status_payload)

        payload = {
            "status": status_payload.get("status", {}),
            "daily": daily_payload.get("summary", {}),
            "auto_status": auto_payload,
            "verify": verify_payload,
            "budget_status": budget_status,
            "cached": False,
        }
        _cache_set(_US_SNAPSHOT_CACHE, cache_key, payload)
        return payload

    payload, is_leader = _singleflight(f"snapshot:{cache_key}", _builder)
    if is_leader:
        return payload
    cached_payload, _ = _cache_get(_US_SNAPSHOT_CACHE, cache_key, _US_SNAPSHOT_TTL_SEC)
    if isinstance(cached_payload, dict):
        return cached_payload
    return _builder()


def us_bootstrap():
    persist_seed = str(wiz.request.query("persist_seed", "false") or "false").lower() in ("true", "1", "yes")
    symbol = wiz.request.query("symbol", "TQQQ")
    strategy = wiz.request.query("strategy", "us_premarket")
    requested_seed = _parse_us_seed("seed", 0)
    cache_key = f"{round(requested_seed, 2)}:{1 if persist_seed else 0}:{symbol}:{strategy}"
    cached_payload, cache_age = _cache_get(_US_BOOTSTRAP_CACHE, cache_key, _US_BOOTSTRAP_TTL_SEC)
    if persist_seed is False and isinstance(cached_payload, dict):
        cached_payload["cached"] = True
        cached_payload["cache_age_sec"] = cache_age
        wiz.response.status(200, **cached_payload)
    def _builder():
        try:
            service = _daytrade()
            engine = _engine()
            trading = _get_struct().trading
            defaults = service.us_defaults()
            us_candidates = service.us_candidate_universe()
            universe_policy = service.us_candidate_universe_policy()
            us_strategy_options = service.us_strategy_options()
            us_profile = service.us_profile()
            default_symbol = "TQQQ"
            default_strategy = "us_premarket"
            default_name = "ProShares UltraPro QQQ"
            seed = requested_seed if requested_seed > 0 else _normalized_us_seed(defaults.get("seed", _US_DEFAULT_SEED_KRW), service=service)
            if persist_seed and seed > 0:
                trading.set_config("daytrade_us_default_seed", round(seed, 2), description="미장 단타 기본 요청 시드")
                defaults = service.us_defaults()
                seed = _normalized_us_seed(defaults.get("seed", seed), service=service)
            try:
                active_positions = engine.active_positions_from_state(market_filter="US")
            except Exception:
                active_positions = []
            if active_positions:
                first = active_positions[0]
                default_symbol = first.get("symbol", default_symbol)
                default_name = first.get("name", default_name)
                default_strategy = first.get("strategy_id", default_strategy)
            kis_status = engine.check_kis_connection()
            budget_status = _enrich_budget_status(engine, engine.shared_budget_status(requested_seed=seed, use_cache_only=(persist_seed is False), market="US"), market="US")
            snapshot = _build_us_snapshot_payload(
                symbol=symbol or default_symbol,
                strategy=strategy or default_strategy,
                seed=seed,
                force_refresh=persist_seed,
                engine=engine,
                service=service,
                trading=trading,
                us_candidates=us_candidates,
            )
        except Exception as e:
            wiz.response.status(500, message=str(e))
        payload = {
            "defaults": {
                "symbol": default_symbol,
                "market": "US",
                "strategy": default_strategy,
                "seed": seed,
                "name": default_name,
            },
            "us_candidates": us_candidates,
            "universe_policy": universe_policy,
            "us_strategy_options": us_strategy_options,
            "us_profile": us_profile,
            "active_positions": active_positions,
            "kis_status": kis_status,
            "budget_status": budget_status,
            "persisted_seed": persist_seed,
            "snapshot": snapshot,
            "cached": False,
        }
        _cache_set(_US_BOOTSTRAP_CACHE, cache_key, payload)
        return payload

    payload, is_leader = _singleflight(f"bootstrap:{cache_key}", _builder, timeout_sec=90.0)
    if is_leader is False:
        cached_payload, cache_age = _cache_get(_US_BOOTSTRAP_CACHE, cache_key, _US_BOOTSTRAP_TTL_SEC)
        if isinstance(cached_payload, dict):
            cached_payload["cached"] = True
            cached_payload["cache_age_sec"] = cache_age
            wiz.response.status(200, **cached_payload)
        payload = _builder()
    wiz.response.status(200, **payload)


def us_live_status():
    symbol = wiz.request.query("symbol", "TQQQ")
    strategy = wiz.request.query("strategy", "us_premarket")
    seed = _parse_us_seed("seed", 0)
    force_refresh = wiz.request.query("force_refresh", "false").lower() in ("true", "1")
    cache_key = f"{symbol}:{strategy}:{round(seed, 2)}"
    cached_payload, cache_age = _cache_get(_US_LIVE_STATUS_CACHE, cache_key, _US_LIVE_STATUS_TTL_SEC)
    if force_refresh is False and isinstance(cached_payload, dict):
        cached_payload["cached"] = True
        cached_payload["cache_age_sec"] = cache_age
        wiz.response.status(200, **cached_payload)
    try:
        engine = _engine()
        status = engine.signal_status(symbol=symbol, market="US", seed=seed, name="", strategy_id=strategy)
    except Exception as e:
        if isinstance(cached_payload, dict):
            cached_payload["cached"] = True
            cached_payload["degraded"] = True
            cached_payload["cache_age_sec"] = cache_age
            wiz.response.status(200, **cached_payload)
        wiz.response.status(400, message=str(e))
    payload = {"status": status, "cached": False}
    _cache_set(_US_LIVE_STATUS_CACHE, cache_key, payload)
    wiz.response.status(200, **payload)


def us_daily_log():
    date = wiz.request.query("date", "")
    target_date = _date_compact(date) or _session_date_9am()
    cached_payload, cache_age = _cache_get(_US_DAILY_LOG_CACHE, target_date, _US_DAILY_LOG_TTL_SEC)
    if isinstance(cached_payload, dict):
        cached_payload["cached"] = True
        cached_payload["cache_age_sec"] = cache_age
        wiz.response.status(200, **cached_payload)
    try:
        payload = _build_us_daily_payload(target_date=target_date)
    except Exception as e:
        if isinstance(cached_payload, dict):
            cached_payload["cached"] = True
            cached_payload["degraded"] = True
            cached_payload["cache_age_sec"] = cache_age
            wiz.response.status(200, **cached_payload)
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, **payload)


def us_verify_runtime():
    symbol = wiz.request.query("symbol", "TQQQ")
    strategy = wiz.request.query("strategy", "us_premarket")
    seed = _parse_us_seed("seed", 0)
    try:
        current_auto_enabled = _build_us_auto_status_payload().get("us_auto_enabled", False)
    except Exception:
        current_auto_enabled = False
    target_date = _session_date_9am()
    cache_key = f"{symbol}:{strategy}:{round(seed, 2)}:{target_date}:{1 if current_auto_enabled else 0}"
    cached_payload, cache_age = _cache_get(_US_VERIFY_CACHE, cache_key, _US_VERIFY_TTL_SEC)
    if isinstance(cached_payload, dict):
        cached_payload["cached"] = True
        cached_payload["cache_age_sec"] = cache_age
        wiz.response.status(200, **cached_payload)
    try:
        payload = _build_us_verify_payload(symbol=symbol, strategy=strategy, seed=seed)
    except Exception as e:
        if isinstance(cached_payload, dict):
            cached_payload["cached"] = True
            cached_payload["degraded"] = True
            cached_payload["cache_age_sec"] = cache_age
            wiz.response.status(200, **cached_payload)
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, **payload)


def us_snapshot():
    symbol = wiz.request.query("symbol", "TQQQ")
    strategy = wiz.request.query("strategy", "us_premarket")
    seed = _parse_us_seed("seed", 0)
    force_refresh = wiz.request.query("force_refresh", "false").lower() in ("true", "1")
    try:
        payload = _build_us_snapshot_payload(symbol=symbol, strategy=strategy, seed=seed, force_refresh=force_refresh)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, **payload)


def us_model_ranking():
    seed = _parse_us_seed("seed", 0)
    period = wiz.request.query("period", "10d")
    interval = wiz.request.query("interval", "5m")
    focus_symbol = str(wiz.request.query("symbol", "") or "").strip().upper()
    max_symbols = int(wiz.request.query("max_symbols", str(_US_DEFAULT_RANKING_SYMBOLS)) or _US_DEFAULT_RANKING_SYMBOLS)
    force_refresh = wiz.request.query("force_refresh", "false").lower() in ("true", "1")
    capped_symbols = max(6, min(max_symbols, _US_MAX_RANKING_SYMBOLS))
    cache_key = f"{round(seed, 2)}:{period}:{interval}:{capped_symbols}:{focus_symbol}"
    cached_payload, cache_age = _cache_get(_US_MODEL_RANKING_CACHE, cache_key, _US_MODEL_RANKING_TTL_SEC)
    if force_refresh is False and isinstance(cached_payload, dict):
        cached_payload["cached"] = True
        cached_payload["cache_age_sec"] = cache_age
        wiz.response.status(200, **cached_payload)
    try:
        service = _daytrade()
        options = service.us_strategy_options() or []
        all_candidates = service.us_candidate_universe() or []
        candidates = _select_us_ranking_candidates(all_candidates, capped_symbols, focus_symbol=focus_symbol)
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
                    result = service.backtest(symbol, market="US", period=period, interval=interval, seed=seed, strategy_id=strategy_id) or {}
                    summary = result.get("summary", {}) or {}
                    validation = result.get("validation", {}) or {}
                    validation_summary = validation.get("validation", {}) or {}
                    rows.append({
                        "symbol": symbol,
                        "name": cand.get("name", ""),
                        "total_return": float(summary.get("total_return", 0) or 0),
                        "win_rate": float(summary.get("win_rate", 0) or 0),
                        "max_drawdown": float(summary.get("max_drawdown", 0) or 0),
                        "score": float(summary.get("score", 0) or 0),
                        "avg_trades": float(summary.get("avg_trades", 0) or 0),
                        "validation_return": float(validation_summary.get("total_return", 0) or 0),
                        "validation_win_rate": float(validation_summary.get("win_rate", 0) or 0),
                        "validation_avg_trades": float(validation_summary.get("avg_trades", 0) or 0),
                        "robustness": float(validation.get("robustness_score", 0) or 0),
                        "overfit_gap": float(validation.get("overfit_gap", 0) or 0),
                    })
                except Exception as e:
                    failures.append({"symbol": symbol, "message": str(e)})
            tested = len(rows)
            avg_return = sum(x.get("total_return", 0) for x in rows) / tested if tested > 0 else 0.0
            avg_win = sum(x.get("win_rate", 0) for x in rows) / tested if tested > 0 else 0.0
            avg_mdd = sum(x.get("max_drawdown", 0) for x in rows) / tested if tested > 0 else 0.0
            avg_score = sum(x.get("score", 0) for x in rows) / tested if tested > 0 else 0.0
            avg_validation_return = sum(x.get("validation_return", 0) for x in rows) / tested if tested > 0 else 0.0
            avg_validation_win = sum(x.get("validation_win_rate", 0) for x in rows) / tested if tested > 0 else 0.0
            avg_trades = sum(x.get("avg_trades", 0) for x in rows) / tested if tested > 0 else 0.0
            avg_validation_trades = sum(x.get("validation_avg_trades", 0) for x in rows) / tested if tested > 0 else 0.0
            avg_robustness = sum(x.get("robustness", 0) for x in rows) / tested if tested > 0 else 0.0
            avg_overfit_gap = sum(abs(x.get("overfit_gap", 0)) for x in rows) / tested if tested > 0 else 0.0
            rank_score = (avg_validation_return * 0.35) + (avg_return * 0.20) + (avg_robustness * 0.20) + (avg_win * 0.10) + (avg_validation_win * 0.10) - (abs(avg_mdd) * 0.05) - (avg_overfit_gap * 0.10)
            best_symbol = sorted(rows, key=lambda x: (x.get("validation_return", 0), x.get("robustness", 0), x.get("total_return", 0), x.get("win_rate", 0)), reverse=True)[:1]
            rankings.append({
                "strategy_id": strategy_id,
                "strategy_name": opt.get("name", strategy_id),
                "strategy_summary": opt.get("summary", ""),
                "entry": list(opt.get("entry", []) or []),
                "exit": list(opt.get("exit", []) or []),
                "tested_symbols": tested,
                "avg_return": round(avg_return, 4),
                "avg_validation_return": round(avg_validation_return, 4),
                "avg_win_rate": round(avg_win, 2),
                "avg_validation_win_rate": round(avg_validation_win, 2),
                "avg_trades": round(avg_trades, 2),
                "avg_validation_trades": round(avg_validation_trades, 2),
                "avg_max_drawdown": round(avg_mdd, 2),
                "avg_robustness": round(avg_robustness, 4),
                "avg_overfit_gap": round(avg_overfit_gap, 4),
                "avg_score": round(avg_score, 4),
                "rank_score": round(rank_score, 4),
                "best_symbol": best_symbol[0] if len(best_symbol) > 0 else None,
                "top_symbols": sorted(rows, key=lambda x: (x.get("validation_return", -999999), x.get("total_return", -999999)), reverse=True)[:3],
                "failures": failures[:5],
                "explanation": f"검증수익 {avg_validation_return:.2f}%, 견고성 {avg_robustness:.2f}, 평균수익 {avg_return:.2f}%, 승률 {avg_win:.2f}%, 검증승률 {avg_validation_win:.2f}%, 거래빈도 {avg_trades:.2f}/day 기준",
            })
        rankings.sort(key=lambda x: x.get("rank_score", -999999), reverse=True)
        for idx, row in enumerate(rankings):
            row["rank"] = idx + 1
        quality_gate = _quality_gate(rankings)
        low_win_count = len([row for row in rankings if float(row.get("avg_win_rate", 0) or 0) < _US_MIN_TRADABLE_WIN_RATE])
        low_validation_win_count = len([row for row in rankings if float(row.get("avg_validation_win_rate", 0) or 0) < _US_MIN_TRADABLE_VALIDATION_WIN_RATE])
        sparse_trade_count = len([row for row in rankings if float(row.get("avg_trades", 0) or 0) < _US_MIN_TRADABLE_AVG_TRADES or float(row.get("avg_validation_trades", 0) or 0) < _US_MIN_TRADABLE_AVG_TRADES])
        research_summary = {
            "top_strategy": rankings[0] if len(rankings) > 0 else None,
            "analysis": {
                "low_win_count": low_win_count,
                "low_validation_win_count": low_validation_win_count,
                "sparse_trade_count": sparse_trade_count,
                "message": f"최근 미장 랭킹은 {len(candidates)}종목을 넓게 테스트한 결과, 저승률 전략 {low_win_count}개, 검증 승률 미달 {low_validation_win_count}개, 거래 빈도 부족 {sparse_trade_count}개가 겹쳐 승률이 약해진 상태입니다.",
            },
            "working_strategies": [
                {
                    "strategy_id": row.get("strategy_id"),
                    "strategy_name": row.get("strategy_name"),
                    "best_symbol": row.get("best_symbol"),
                    "avg_validation_return": row.get("avg_validation_return", 0),
                    "avg_robustness": row.get("avg_robustness", 0),
                    "note": row.get("explanation", ""),
                }
                for row in rankings if row.get("tradable") is True
            ],
            "blocked_strategies": [
                {
                    "strategy_id": row.get("strategy_id"),
                    "strategy_name": row.get("strategy_name"),
                    "reason": row.get("quality_note", row.get("explanation", "")),
                    "avg_validation_return": row.get("avg_validation_return", 0),
                    "avg_robustness": row.get("avg_robustness", 0),
                }
                for row in rankings if row.get("tradable") is not True
            ],
        }
    except Exception as e:
        if isinstance(cached_payload, dict):
            cached_payload["cached"] = True
            cached_payload["degraded"] = True
            cached_payload["cache_age_sec"] = cache_age
            wiz.response.status(200, **cached_payload)
        wiz.response.status(400, message=str(e))

    payload = {
        "seed": seed,
        "period": period,
        "interval": interval,
        "symbol_count": len(candidates),
        "focus_symbol": focus_symbol,
        "rankings": rankings,
        "quality_gate": quality_gate,
        "recommended_pair": ((quality_gate or {}).get("best_tradable") or {}).get("best_symbol"),
        "research_summary": research_summary,
        "generated_at": _kst_now().strftime("%Y-%m-%d %H:%M:%S"),
        "cached": False,
    }
    _cache_set(_US_MODEL_RANKING_CACHE, cache_key, payload)
    wiz.response.status(200, **payload)


def us_execute_live():
    symbol = wiz.request.query("symbol", "TQQQ")
    strategy = wiz.request.query("strategy", "us_premarket")
    seed = _parse_us_seed("seed", 0)
    try:
        engine = _engine()
        result = engine.execute_live(
            symbol=symbol,
            market="US",
            seed=seed,
            name="",
            strategy_id=strategy,
            force=False,
        )
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, result=result)


def us_toggle_auto():
    enabled_param = wiz.request.query("enabled", "")
    trading = _get_struct().trading
    pending_sell_cancel = {}
    try:
        if enabled_param == "":
            current = str(trading.get_config("daytrade_us_auto_enabled", "false")).lower() == "true"
            new_value = not current
        else:
            new_value = enabled_param.lower() in ("true", "1", "yes")

        if new_value is False:
            pending_sell_cancel = _engine().cancel_pending_auto_sells(market="US", reason="미장 단타 자동매매 OFF")
        trading.set_config("daytrade_us_auto_enabled", str(new_value).lower(), description="미장 단타 자동매매 활성화")
        trading.set_config("daytrade_us_exit_watch_enabled", str(new_value).lower(), description="미장 단타 자동청산 감시 활성화")
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, us_auto_enabled=new_value, us_exit_watch_enabled=new_value, pending_sell_cancel=pending_sell_cancel)


def us_get_auto_status():
    try:
        payload = _build_us_auto_status_payload()
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, **payload)


def us_manual_sell():
    symbol = wiz.request.query("symbol", "TQQQ")
    strategy = wiz.request.query("strategy", "us_premarket")
    seed = _parse_us_seed("seed", 0)
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
    seed = _parse_us_seed("seed", 0)
    try:
        result = _engine().us_auto_cycle(requested_seed=seed)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, result=result)


def us_execute_exit_watch():
    seed = _parse_us_seed("seed", 0)
    try:
        result = _engine().us_execute_exit_watch(requested_seed=seed)
    except Exception as e:
        wiz.response.status(400, message=str(e))
    wiz.response.status(200, result=result)
