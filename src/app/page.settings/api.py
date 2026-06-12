import json
import datetime
import time
import re

_TIME = wiz.model("portal/trading/kst")

_STRUCT_CACHE = {"obj": None, "error": None, "error_at": 0.0}
_STRUCT_ERROR_TTL_SEC = 5.0
_ACCOUNT_NO_RE = re.compile(r"^\d{8}-\d{2}$")


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

def _session_user():
    session = wiz.model("portal/season/session").use()
    user_id = session.get("id")
    if not user_id:
        wiz.response.status(401, message="로그인이 필요합니다.")
    struct = _get_struct()
    user = struct.user.get(id=user_id)
    if user is None:
        wiz.response.status(404, message="사용자 정보를 찾을 수 없습니다.")
    return struct, session, user

def _validate_email(email):
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str(email or "")) is not None


def _normalize_account_no(account_no):
    text = re.sub(r"\s+", "", str(account_no or ""))
    if text == "":
        return ""
    if re.match(r"^\d{10}$", text):
        return f"{text[:8]}-{text[8:]}"
    return text


def _validate_account_no(account_no):
    return _ACCOUNT_NO_RE.match(str(account_no or "")) is not None

def _get_config(key, default=""):
    trading = _trading()
    getter = getattr(trading, "get_config", None)
    if callable(getter):
        return getter(key, default)

    config_db = trading.db("trading_config")
    row = config_db.get(key=key)
    if row:
        return row.get("value", default)
    return default

def _set_config(key, value, description="", is_secret=False):
    trading = _trading()
    setter = getattr(trading, "set_config", None)
    if callable(setter):
        setter(key, str(value), description=description, is_secret=is_secret)
        return

    config_db = trading.db("trading_config")
    existing = config_db.get(key=key)
    now = _TIME.now()
    if existing:
        config_db.update({"value": str(value), "updated": now}, id=existing["id"])
    else:
        config_db.insert({
            "key": key,
            "value": str(value),
            "description": description,
            "is_secret": is_secret,
            "created": now,
            "updated": now,
        })

def _get_partial_sell_stages():
    trading = _trading()
    strategy_mod = trading.strategy
    defaults = strategy_mod.get("DEFAULT_PARAMS", {})
    return defaults.get("partial_sell_stages", [])


def _safe_int(value, default=0):
    try:
        text = str(value if value is not None else "").strip()
        if text == "":
            return int(default)
        return int(float(text))
    except Exception:
        return int(default)


def _safe_float(value, default=0.0):
    try:
        text = str(value if value is not None else "").strip()
        if text == "":
            return float(default)
        return float(text)
    except Exception:
        return float(default)

def load_settings():
    """설정 전체 로드"""
    try:
        trading = _trading()
        watchlist_db = trading.db("etf_watchlist")

        app_key = _get_config("kis_app_key")
        app_secret = _get_config("kis_app_secret")
        account_raw = _get_config("kis_account_no")
        # 레거시 호환: 하이픈 없는 8자리면 suffix와 합치기
        if account_raw and "-" not in account_raw:
            suffix = _get_config("kis_account_suffix", "01")
            if suffix:
                account_raw = f"{account_raw}-{suffix}"
                _set_config("kis_account_no", account_raw, "KIS Account Number", True)
        account_no = account_raw

        is_real = _get_config("kis_is_real", "false")
        division_count = _get_config("default_division_count", "40")
        target_profit = _get_config("default_target_profit", "10")
        auto_trade = _get_config("auto_trade_enabled", "false")
        buy_commission_rate = _get_config("buy_commission_rate", "0.25")
        sell_commission_rate = _get_config("sell_commission_rate", "0.25")
        tax_rate = _get_config("tax_rate", "0")

        sell_strategy = _get_config("sell_strategy", "full")
        crash_buy_enabled = _get_config("crash_buy_enabled", "false")
        crash_buy_drop_pct = _get_config("crash_buy_drop_pct", "5")
        crash_buy_ma_drop_pct = _get_config("crash_buy_ma_drop_pct", "10")
        crash_buy_ratio = _get_config("crash_buy_ratio", "10")
        crash_buy_max_per_cycle = _get_config("crash_buy_max_per_cycle", "3")
        sell_method = _get_config("sell_method", "market")
        daytrade_default_seed = _get_config("daytrade_default_seed", "5000000")
        daytrade_us_default_seed = _get_config("daytrade_us_default_seed", daytrade_default_seed or "5000000")
        daytrade_auto_enabled = _get_config("daytrade_auto_enabled", "true")
        daytrade_us_auto_enabled = _get_config("daytrade_us_auto_enabled", "false")
        daytrade_daily_loss_limit_krw = _get_config("daytrade_daily_loss_limit_krw", "50000")
        daytrade_auto_max_symbols = _get_config("daytrade_auto_max_symbols", "16")
        daytrade_entry_aggressiveness = _get_config("daytrade_entry_aggressiveness", "balanced")
        daytrade_probe_entry_enabled = _get_config("daytrade_probe_entry_enabled", "true")
        daytrade_probe_entry_ratio = _get_config("daytrade_probe_entry_ratio", "0.35")
        daytrade_jackpot_take_profit_pct = _get_config("daytrade_jackpot_take_profit_pct", "2.0")
        daytrade_jackpot_pre_sell_gap_pct = _get_config("daytrade_jackpot_pre_sell_gap_pct", "0.5")
        daytrade_us_jackpot_take_profit_pct = _get_config("daytrade_us_jackpot_take_profit_pct", "3.0")
        daytrade_us_jackpot2_take_profit_pct = _get_config("daytrade_us_jackpot2_take_profit_pct", "5.0")
        loc_auto_schedule_enabled = _get_config("loc_auto_schedule_enabled", "true")
        _, _, user = _session_user()
        user_email = user.get("email", "")
        login_id = user_email.split("@", 1)[0] if "@" in user_email else user_email

        try:
            watchlist = watchlist_db.rows(orderby="created", order="ASC") or []
        except Exception:
            watchlist = []
    except Exception as e:
        wiz.response.status(500, message=f"load_settings failed: {e}")

    wiz.response.status(200,
        app_key=app_key,
        app_secret=app_secret,
        account_no=account_no,
        is_mock=is_real != "true",
        division_count=_safe_int(division_count, 40),
        target_profit=_safe_float(target_profit, 10),
        auto_trade=str(auto_trade).lower() == "true",
        buy_commission_rate=_safe_float(buy_commission_rate, 0.25),
        sell_commission_rate=_safe_float(sell_commission_rate, 0.25),
        tax_rate=_safe_float(tax_rate, 0),
        sell_strategy=sell_strategy,
        partial_sell_stages=_get_partial_sell_stages(),
        crash_buy_enabled=str(crash_buy_enabled).lower() == "true",
        crash_buy_drop_pct=_safe_float(crash_buy_drop_pct, 5),
        crash_buy_ma_drop_pct=_safe_float(crash_buy_ma_drop_pct, 10),
        crash_buy_ratio=_safe_float(crash_buy_ratio, 10),
        crash_buy_max_per_cycle=_safe_int(crash_buy_max_per_cycle, 3),
        sell_method=sell_method,
        daytrade_default_seed=_safe_float(daytrade_default_seed, 5000000),
        daytrade_us_default_seed=_safe_float(daytrade_us_default_seed, _safe_float(daytrade_default_seed, 5000000)),
        daytrade_auto_enabled=str(daytrade_auto_enabled).lower() == "true",
        daytrade_us_auto_enabled=str(daytrade_us_auto_enabled).lower() == "true",
        daytrade_daily_loss_limit_krw=_safe_float(daytrade_daily_loss_limit_krw, 50000),
        daytrade_auto_max_symbols=_safe_int(daytrade_auto_max_symbols, 16),
        daytrade_entry_aggressiveness=daytrade_entry_aggressiveness,
        daytrade_probe_entry_enabled=str(daytrade_probe_entry_enabled).lower() == "true",
        daytrade_probe_entry_ratio=_safe_float(daytrade_probe_entry_ratio, 0.35),
        daytrade_jackpot_take_profit_pct=_safe_float(daytrade_jackpot_take_profit_pct, 2.0),
        daytrade_jackpot_pre_sell_gap_pct=_safe_float(daytrade_jackpot_pre_sell_gap_pct, 0.5),
        daytrade_us_jackpot_take_profit_pct=_safe_float(daytrade_us_jackpot_take_profit_pct, 3.0),
        daytrade_us_jackpot2_take_profit_pct=_safe_float(daytrade_us_jackpot2_take_profit_pct, 5.0),
        loc_auto_schedule_enabled=str(loc_auto_schedule_enabled).lower() == "true",
        account_user_id=user.get("id", ""),
        account_login_id=login_id,
        account_email=user_email,
        watchlist=watchlist,
    )

def save_api_settings():
    """API 설정 저장"""
    app_key = wiz.request.query("app_key", "").strip()
    app_secret = wiz.request.query("app_secret", "").strip()
    account_no = _normalize_account_no(wiz.request.query("account_no", ""))  # 12345678-01 형태
    is_mock = wiz.request.query("is_mock", "true")

    if app_key == "":
        wiz.response.status(400, message="App Key를 입력해주세요.")
    if app_secret == "":
        wiz.response.status(400, message="App Secret을 입력해주세요.")
    if account_no == "":
        wiz.response.status(400, message="계좌번호를 입력해주세요.")
    if _validate_account_no(account_no) is False:
        wiz.response.status(400, message="계좌번호는 12345678-01 형식으로 입력해주세요.")

    # is_mock → is_real로 변환하여 kis_is_real 키에 저장 (kis_api.py와 키 통일)
    is_real = "false" if is_mock in ["true", "True", "1", True] else "true"

    _set_config("kis_app_key", app_key, "KIS App Key", True)
    _set_config("kis_app_secret", app_secret, "KIS App Secret", True)
    _set_config("kis_account_no", account_no, "KIS Account Number", True)
    _set_config("kis_is_real", is_real, "Real Trading Mode")

    # 레거시 kis_account_suffix 키 삭제 (통합됨)
    trading = _trading()
    config_db = trading.db("trading_config")
    old_suffix = config_db.get(key="kis_account_suffix")
    if old_suffix:
        config_db.delete(id=old_suffix["id"])

    # 기존 kis_is_mock 키가 있으면 삭제 (키 중복 방지)
    trading = _trading()
    config_db = trading.db("trading_config")
    old_mock = config_db.get(key="kis_is_mock")
    if old_mock:
        config_db.delete(id=old_mock["id"])

    # 토큰 초기화 (키 변경 시 재발급 필요)
    _set_config("kis_access_token", "", "Access Token", True)
    _set_config("kis_token_expires", "0", "Token Expiry")

    try:
        result = trading.kis_api.test_connection()
    except Exception as e:
        result = {"success": False, "message": str(e)}

    wiz.response.status(200,
        saved=True,
        success=result.get("success", False),
        message=result.get("message", ""),
        account_no=account_no,
        is_mock=is_real != "true",
    )

def test_connection():
    """API 연결 테스트"""
    trading = _trading()
    try:
        result = trading.kis_api.test_connection()
    except Exception as e:
        wiz.response.status(200, success=False, message=str(e))
    if result.get("success", False) is False:
        wiz.response.status(200, success=False, message=result.get("message", "API 연결 실패"))
    wiz.response.status(200, **result)

def add_watchlist():
    """종목 추가"""
    symbol = wiz.request.query("symbol", True)
    name = wiz.request.query("name", "")
    investment = float(wiz.request.query("investment", "5000"))
    exchange = wiz.request.query("exchange", "NASD")

    # 유효한 거래소 코드 확인
    if exchange not in ("NASD", "NYSE", "AMEX"):
        exchange = "NASD"

    default_division = int(_get_config("default_division_count", "40"))
    default_target = float(_get_config("default_target_profit", "10"))

    trading = _trading()
    watchlist_db = trading.db("etf_watchlist")

    existing = watchlist_db.get(symbol=symbol)
    if existing:
        wiz.response.status(400, message=f"Symbol {symbol} already exists")

    now = _TIME.now()
    watchlist_db.insert({
        "symbol": symbol,
        "name": name,
        "exchange": exchange,
        "total_investment": investment,
        "division_count": default_division,
        "target_profit": default_target,
        "cycle_mode": "auto",
        "is_active": True,
        "created": now,
        "updated": now,
    })

    watchlist = watchlist_db.rows(orderby="created", order="ASC")
    wiz.response.status(200, watchlist=watchlist)

def remove_watchlist():
    """종목 삭제"""
    id = wiz.request.query("id", True)
    trading = _trading()
    watchlist_db = trading.db("etf_watchlist")
    watchlist_db.delete(id=id)
    watchlist = watchlist_db.rows(orderby="created", order="ASC")
    wiz.response.status(200, watchlist=watchlist)

def update_watchlist_item():
    """종목 개별 설정 업데이트"""
    symbol = wiz.request.query("symbol", True)
    trading = _trading()
    watchlist_db = trading.db("etf_watchlist")

    existing = watchlist_db.get(symbol=symbol)
    if not existing:
        wiz.response.status(404, message=f"Symbol {symbol} not found")

    update_data = {"updated": _TIME.now()}

    investment = wiz.request.query("investment", "")
    if investment:
        update_data["total_investment"] = float(investment)

    division_count = wiz.request.query("division_count", "")
    if division_count:
        update_data["division_count"] = int(division_count)

    target_profit = wiz.request.query("target_profit", "")
    if target_profit:
        update_data["target_profit"] = float(target_profit)

    cycle_mode = wiz.request.query("cycle_mode", "")
    if cycle_mode:
        update_data["cycle_mode"] = cycle_mode

    is_active = wiz.request.query("is_active", "")
    if is_active != "":
        update_data["is_active"] = is_active in ["true", "1", "True"]

    watchlist_db.update(update_data, id=existing["id"])
    watchlist = watchlist_db.rows(orderby="created", order="ASC")
    wiz.response.status(200, watchlist=watchlist)

def save_params():
    """매매 파라미터 + 전략 설정 저장"""
    division_count = wiz.request.query("division_count", "40")
    target_profit = wiz.request.query("target_profit", "10")
    auto_trade = wiz.request.query("auto_trade", "false")
    buy_commission_rate = wiz.request.query("buy_commission_rate", "0.25")
    sell_commission_rate = wiz.request.query("sell_commission_rate", "0.25")
    tax_rate = wiz.request.query("tax_rate", "0")

    _set_config("default_division_count", division_count, "Default division count")
    _set_config("default_target_profit", target_profit, "Default target profit %")
    _set_config("auto_trade_enabled", auto_trade, "Auto trade enabled")
    _set_config("buy_commission_rate", buy_commission_rate, "Buy commission rate %")
    _set_config("sell_commission_rate", sell_commission_rate, "Sell commission rate %")
    _set_config("tax_rate", tax_rate, "Sell tax rate %")

    # Strategy params
    sell_strategy = wiz.request.query("sell_strategy", "full")
    crash_buy_enabled = wiz.request.query("crash_buy_enabled", "false")
    crash_buy_drop_pct = wiz.request.query("crash_buy_drop_pct", "5")
    crash_buy_ma_drop_pct = wiz.request.query("crash_buy_ma_drop_pct", "10")
    crash_buy_ratio = wiz.request.query("crash_buy_ratio", "10")
    crash_buy_max_per_cycle = wiz.request.query("crash_buy_max_per_cycle", "3")
    daytrade_default_seed = max(100000.0, min(1000000000.0, _safe_float(wiz.request.query("daytrade_default_seed", "5000000"), 5000000)))
    daytrade_us_default_seed = max(100000.0, min(1000000000.0, _safe_float(wiz.request.query("daytrade_us_default_seed", str(daytrade_default_seed)), daytrade_default_seed)))
    daytrade_auto_enabled = wiz.request.query("daytrade_auto_enabled", "true")
    daytrade_us_auto_enabled = wiz.request.query("daytrade_us_auto_enabled", "false")
    daytrade_daily_loss_limit_krw = max(0.0, min(10000000.0, _safe_float(wiz.request.query("daytrade_daily_loss_limit_krw", "50000"), 50000)))
    daytrade_auto_max_symbols = max(1, min(40, _safe_int(wiz.request.query("daytrade_auto_max_symbols", "16"), 16)))
    daytrade_entry_aggressiveness = str(wiz.request.query("daytrade_entry_aggressiveness", "balanced") or "balanced").strip().lower()
    if daytrade_entry_aggressiveness not in ["defensive", "balanced", "aggressive"]:
        daytrade_entry_aggressiveness = "balanced"
    daytrade_probe_entry_enabled = wiz.request.query("daytrade_probe_entry_enabled", "true")
    daytrade_probe_entry_ratio = max(0.05, min(0.8, _safe_float(wiz.request.query("daytrade_probe_entry_ratio", "0.35"), 0.35)))
    daytrade_jackpot_take_profit_pct = max(0.1, min(20.0, _safe_float(wiz.request.query("daytrade_jackpot_take_profit_pct", "2.0"), 2.0)))
    daytrade_jackpot_pre_sell_gap_pct = max(0.0, min(5.0, _safe_float(wiz.request.query("daytrade_jackpot_pre_sell_gap_pct", "0.5"), 0.5)))
    daytrade_us_jackpot_take_profit_pct = max(0.1, min(50.0, _safe_float(wiz.request.query("daytrade_us_jackpot_take_profit_pct", "3.0"), 3.0)))
    daytrade_us_jackpot2_take_profit_pct = max(daytrade_us_jackpot_take_profit_pct, min(100.0, _safe_float(wiz.request.query("daytrade_us_jackpot2_take_profit_pct", "5.0"), 5.0)))
    loc_auto_schedule_enabled = wiz.request.query("loc_auto_schedule_enabled", "true")

    sell_method = wiz.request.query("sell_method", "market")
    _set_config("sell_method", sell_method, "Sell method: market or loc")
    _set_config("sell_strategy", sell_strategy, "Sell strategy: full or partial")
    _set_config("crash_buy_enabled", crash_buy_enabled, "Crash buy enabled")
    _set_config("crash_buy_drop_pct", crash_buy_drop_pct, "Crash buy daily drop threshold %")
    _set_config("crash_buy_ma_drop_pct", crash_buy_ma_drop_pct, "Crash buy MA5 drop threshold %")
    _set_config("crash_buy_ratio", crash_buy_ratio, "Crash buy investment ratio %")
    _set_config("crash_buy_max_per_cycle", crash_buy_max_per_cycle, "Max crash buys per cycle")
    _set_config("daytrade_default_seed", round(daytrade_default_seed, 2), "Domestic daytrade default requested seed")
    _set_config("daytrade_us_default_seed", round(daytrade_us_default_seed, 2), "US daytrade default requested seed")
    _set_config("daytrade_auto_enabled", daytrade_auto_enabled, "Domestic daytrade auto rotation enabled")
    _set_config("daytrade_exit_watch_enabled", daytrade_auto_enabled, "Domestic daytrade auto exit watch enabled")
    _set_config("daytrade_us_auto_enabled", daytrade_us_auto_enabled, "US daytrade auto rotation enabled")
    _set_config("daytrade_us_exit_watch_enabled", daytrade_us_auto_enabled, "US daytrade auto exit watch enabled")
    _set_config("daytrade_daily_loss_limit_krw", round(daytrade_daily_loss_limit_krw), "Domestic daytrade daily loss limit KRW")
    _set_config("daytrade_auto_max_symbols", daytrade_auto_max_symbols, "Domestic daytrade max monitored symbols")
    _set_config("daytrade_entry_aggressiveness", daytrade_entry_aggressiveness, "Domestic daytrade entry aggressiveness")
    _set_config("daytrade_probe_entry_enabled", daytrade_probe_entry_enabled, "Allow small probe entries near trigger")
    _set_config("daytrade_probe_entry_ratio", daytrade_probe_entry_ratio, "Probe entry budget ratio")
    _set_config("daytrade_jackpot_take_profit_pct", daytrade_jackpot_take_profit_pct, "Domestic daytrade jackpot take profit pct")
    _set_config("daytrade_jackpot_pre_sell_gap_pct", daytrade_jackpot_pre_sell_gap_pct, "Domestic jackpot limit pre-sell gap pct")
    _set_config("daytrade_us_jackpot_take_profit_pct", daytrade_us_jackpot_take_profit_pct, "US daytrade first take profit pct")
    _set_config("daytrade_us_jackpot2_take_profit_pct", daytrade_us_jackpot2_take_profit_pct, "US daytrade second take profit pct")
    _set_config("loc_auto_schedule_enabled", loc_auto_schedule_enabled, "Auto LOC sell scheduling at 17:40 KST")

    wiz.response.status(200)


def save_account_profile():
    struct, session, user = _session_user()
    email = wiz.request.query("email", "").strip().lower()
    login_id = wiz.request.query("login_id", "").strip()

    current_email = str(user.get("email", "") or "")
    if email == "" and login_id != "":
        domain = current_email.split("@", 1)[1] if "@" in current_email else ""
        if domain:
            email = f"{login_id}@{domain}".lower()

    if email == "":
        wiz.response.status(400, message="이메일을 입력해주세요.")
    if _validate_email(email) is False:
        wiz.response.status(400, message="올바른 이메일 형식을 입력해주세요.")

    user_db = struct.orm.use("user")
    exists = user_db.get(email=email)
    if exists and str(exists.get("id", "")) != str(user.get("id", "")):
        wiz.response.status(409, message="이미 사용 중인 이메일입니다.")

    struct.user.update_profile(user.get("id"), email=email)
    session.set(email=email)

    updated = struct.user.get(id=user.get("id"))
    updated_email = updated.get("email", "") if updated else email
    updated_login_id = updated_email.split("@", 1)[0] if "@" in updated_email else updated_email

    wiz.response.status(200,
        user_id=user.get("id", ""),
        login_id=updated_login_id,
        email=updated_email,
    )


def change_account_password():
    struct, _, user = _session_user()
    current_password = wiz.request.query("current_password", "")
    new_password = wiz.request.query("new_password", "")

    if not current_password:
        wiz.response.status(400, message="현재 비밀번호를 입력해주세요.")
    if not new_password:
        wiz.response.status(400, message="새 비밀번호를 입력해주세요.")
    if len(new_password) < 8:
        wiz.response.status(400, message="새 비밀번호는 8자 이상이어야 합니다.")

    ok = struct.user.change_password(user.get("id"), current_password, new_password)
    if not ok:
        wiz.response.status(400, message="현재 비밀번호가 올바르지 않습니다.")

    wiz.response.status(200)


def search_symbol():
    """종목 검색 — KIS API로 심볼을 여러 거래소에서 조회하여 검증"""
    symbol = wiz.request.query("symbol", True).upper().strip()
    if not symbol:
        wiz.response.status(400, message="Symbol required")

    trading = _trading()
    results = []

    # 거래소 코드 매핑: 시세조회(3글자) → 주문(4글자)
    exchanges = [
        {"price": "NAS", "order": "NASD", "label": "NASDAQ"},
        {"price": "NYS", "order": "NYSE", "label": "NYSE"},
        {"price": "AMS", "order": "AMEX", "label": "AMEX"},
    ]

    try:
        kis = trading.kis_api
        test = kis.test_connection()
        if not test.get("success", False):
            wiz.response.status(200, results=[], connected=False, message="KIS API not connected")
    except Exception:
        wiz.response.status(200, results=[], connected=False, message="KIS API not available")

    for ex in exchanges:
        try:
            price_data = kis.get_current_price(symbol, exchange=ex["price"])
            if price_data and price_data.get("price", 0) > 0:
                results.append({
                    "symbol": symbol,
                    "name": price_data.get("name", symbol),
                    "exchange": ex["order"],
                    "exchange_label": ex["label"],
                    "price": price_data.get("price", 0),
                    "prev_close": price_data.get("prev_close", 0),
                    "change_rate": price_data.get("change_rate", 0),
                })
        except Exception:
            pass

    wiz.response.status(200, results=results, connected=True)
