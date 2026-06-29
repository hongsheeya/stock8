import json
import datetime
import time
import re

_TIME = wiz.model("portal/trading/kst")

_STRUCT_CACHE = {"obj": None, "error": None, "error_at": 0.0}
_STRUCT_ERROR_TTL_SEC = 5.0
_ACCOUNT_NO_RE = re.compile(r"^\d{8}-\d{2}$")
_TOSS_ACCOUNT_SUFFIX_RE = re.compile(r"^0\d{1,5}$")
_BROKER_OPTIONS = [
    {
        "id": "kis",
        "name": "한국투자증권",
        "logo": "KIS",
        "status": "지원",
        "enabled": True,
        "summary": "현재 운영 중인 기본 브로커입니다. 해외 ETF LOC 예약, 잔고, 주문가능금액, 체결 동기화를 지원합니다.",
    },
    {
        "id": "toss",
        "name": "토스증권",
        "logo": "TOSS",
        "status": "지원",
        "enabled": True,
        "summary": "토스증권 API로 해외 ETF 현재가, 보유, 주문가능금액, LOC 주문, 주문 조회를 지원합니다.",
    },
]
_BROKER_PROVIDERS = {item["id"] for item in _BROKER_OPTIONS if item.get("enabled")}
_DAYTRADE_HARD_LOCKED = True
_DAYTRADE_LOCK_MESSAGE = "단타 기능은 현재 운영 안정화를 위해 완전히 봉인되어 있습니다."
_DEFAULT_WATCHLIST_ITEMS = [
    {
        "symbol": "TQQQ",
        "name": "ProShares UltraPro QQQ",
        "exchange": "NASD",
        "total_investment": 10000.0,
    },
    {
        "symbol": "SOXL",
        "name": "Direxion Daily Semiconductor Bull 3X Shares",
        "exchange": "AMEX",
        "total_investment": 15000.0,
    },
]


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


def _normalize_broker_provider(value):
    provider = str(value or "kis").strip().lower()
    return provider if provider in _BROKER_PROVIDERS else "kis"


def _broker_option(provider):
    provider = str(provider or "").strip().lower()
    for item in _BROKER_OPTIONS:
        if item.get("id") == provider:
            return item
    return _BROKER_OPTIONS[0]


def _selected_broker_api(trading=None):
    trading = trading or _trading()
    return getattr(trading, "broker_api", None) or trading.kis_api


_API_SETTING_QUERY_KEYS = (
    "broker_provider",
    "app_key",
    "app_secret",
    "account_no",
    "toss_client_id",
    "toss_client_secret",
    "toss_account_seq",
    "is_mock",
)


def _query_text(key, default=""):
    return str(wiz.request.query(key, default) or "").strip()


def _query_present(key):
    return wiz.request.query(key, None) is not None


def _api_settings_request_present():
    for key in _API_SETTING_QUERY_KEYS:
        if _query_present(key):
            return True
    return False


def _api_settings_payload_from_request():
    use_request_values = _api_settings_request_present()

    def request_or_saved(query_key, config_key="", default=""):
        if use_request_values:
            return _query_text(query_key, "")
        return _get_config(config_key or query_key, default)

    broker_provider_raw = request_or_saved("broker_provider", "broker_provider", "kis").lower()
    requested_broker = _broker_option(broker_provider_raw)
    if broker_provider_raw not in _BROKER_PROVIDERS:
        wiz.response.status(400, message=f"{requested_broker.get('name', broker_provider_raw)} API는 아직 무한매수 실주문 지원이 검증되지 않았습니다.")

    is_real = _get_config("kis_is_real", "false")
    default_is_mock = "false" if str(is_real).lower() == "true" else "true"
    return {
        "broker_provider": _normalize_broker_provider(broker_provider_raw),
        "app_key": request_or_saved("app_key", "kis_app_key", ""),
        "app_secret": request_or_saved("app_secret", "kis_app_secret", ""),
        "account_no": _normalize_account_no(request_or_saved("account_no", "kis_account_no", "")),
        "toss_client_id": request_or_saved("toss_client_id", "toss_client_id", ""),
        "toss_client_secret": request_or_saved("toss_client_secret", "toss_client_secret", ""),
        "toss_account_seq": request_or_saved("toss_account_seq", "toss_account_seq", ""),
        "is_mock": wiz.request.query("is_mock", "false") if use_request_values else default_is_mock,
        "_input_source": "screen" if use_request_values else "saved",
    }


def _validate_api_settings_payload(payload):
    broker_provider = payload["broker_provider"]
    if broker_provider == "kis":
        if payload["app_key"] == "":
            wiz.response.status(400, message="한국투자증권 앱 키를 입력해주세요.")
        if payload["app_secret"] == "":
            wiz.response.status(400, message="한국투자증권 앱 시크릿을 입력해주세요.")
        if payload["account_no"] == "":
            wiz.response.status(400, message="한국투자증권 계좌번호를 입력해주세요.")
        if _validate_account_no(payload["account_no"]) is False:
            wiz.response.status(400, message="한국투자증권 계좌번호는 12345678-01 형식으로 입력해주세요.")
    elif broker_provider == "toss":
        if payload["toss_client_id"] == "":
            wiz.response.status(400, message="토스증권 클라이언트 ID를 입력해주세요.")
        if payload["toss_client_secret"] == "":
            wiz.response.status(400, message="토스증권 클라이언트 비밀키를 입력해주세요.")
        if payload["toss_client_id"].startswith("tssk_") or payload["toss_client_secret"].startswith("tsck_"):
            wiz.response.status(400, message="토스증권 키 입력 위치가 반대로 보입니다. api key(tsck_...)는 첫 번째 칸, secret key(tssk_...)는 두 번째 칸에 입력해주세요.")
        if not payload["toss_client_id"].startswith("tsck_"):
            wiz.response.status(400, message="토스증권 API key 칸에는 api key(tsck_...) 값을 입력해야 합니다.")
        if not payload["toss_client_secret"].startswith("tssk_"):
            wiz.response.status(400, message="토스증권 Secret key 칸에는 secret key(tssk_...) 값을 입력해야 합니다.")
        if payload["toss_account_seq"] and re.match(r"^\d+$", payload["toss_account_seq"]) is None:
            wiz.response.status(400, message="토스증권 계좌 일련번호(accountSeq)는 숫자만 입력해야 합니다. 일반 계좌번호는 입력하지 말고 비워둔 뒤 연결 테스트를 누르면 자동 선택됩니다.")
        if payload["toss_account_seq"] and _TOSS_ACCOUNT_SUFFIX_RE.match(payload["toss_account_seq"]):
            wiz.response.status(400, message="토스증권 accountSeq는 계좌 뒷번호가 아닙니다. 이 칸은 비워둔 뒤 연결 테스트를 누르세요. 연결이 성공하면 토스 계좌 목록에서 accountSeq를 자동 조회해 저장합니다.")


def _persist_api_settings(payload):
    # is_mock → is_real로 변환하여 kis_is_real 키에 저장 (kis_api.py와 키 통일)
    is_real = "false" if payload["is_mock"] in ["true", "True", "1", True] else "true"

    _set_config("broker_provider", payload["broker_provider"], "선택한 증권사")
    _set_config("kis_app_key", payload["app_key"], "한국투자증권 앱 키", True)
    _set_config("kis_app_secret", payload["app_secret"], "한국투자증권 앱 시크릿", True)
    _set_config("kis_account_no", payload["account_no"], "한국투자증권 계좌번호", True)
    _set_config("kis_is_real", is_real, "실전투자 여부")
    _set_config("toss_client_id", payload["toss_client_id"], "토스증권 클라이언트 ID", True)
    _set_config("toss_client_secret", payload["toss_client_secret"], "토스증권 클라이언트 비밀키", True)
    _set_config("toss_account_seq", payload["toss_account_seq"], "토스증권 계좌 일련번호", True)

    trading = _trading()
    config_db = trading.db("trading_config")
    old_suffix = config_db.get(key="kis_account_suffix")
    if old_suffix:
        config_db.delete(id=old_suffix["id"])
    old_mock = config_db.get(key="kis_is_mock")
    if old_mock:
        config_db.delete(id=old_mock["id"])

    # 브로커/키/계좌를 바꾼 뒤에는 반드시 새 토큰으로 검증한다.
    _set_config("kis_access_token", "", "한국투자증권 접근 토큰", True)
    _set_config("kis_token_expires", "0", "한국투자증권 토큰 만료시각")
    _set_config("toss_access_token", "", "토스증권 접근 토큰", True)
    _set_config("toss_token_expires", "0", "토스증권 토큰 만료시각")
    try:
        setattr(trading, "_toss_credential_source", payload.get("_input_source", "screen"))
    except Exception:
        pass
    return trading, is_real


def _api_settings_response(payload, result, is_real, saved=False):
    success = result.get("success", False)
    message = result.get("message", "")
    if success is False and not message:
        message = "증권사 API 연결에 실패했습니다."
    wiz.response.status(200,
        saved=saved,
        success=success,
        message=message,
        broker_provider=payload["broker_provider"],
        account_no=payload["account_no"],
        toss_account_no=result.get("account_no", ""),
        is_mock=is_real != "true",
        toss_account_seq=_get_config("toss_account_seq", payload["toss_account_seq"]),
        diagnostics=result.get("diagnostics", []),
    )


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "y", "on")


def _is_admin_user(user):
    role = str((user or {}).get("role", "") or "").lower()
    email = str((user or {}).get("email", "") or "").strip().lower()
    return role == "admin" or email == "gigukbyun@gmail.com"


def _csv_items(value):
    text = str(value or "")
    items = []
    for token in re.split(r"[\s,;\n]+", text):
        token = token.strip()
        if token:
            items.append(token)
    return items


def _daytrade_user_authorized(user):
    user_id = str((user or {}).get("id", "") or "").strip()
    email = str((user or {}).get("email", "") or "").strip().lower()
    ids = {str(item).strip() for item in _csv_items(_get_config("daytrade_authorized_user_ids", ""))}
    emails = {str(item).strip().lower() for item in _csv_items(_get_config("daytrade_authorized_user_emails", ""))}
    return (user_id and user_id in ids) or (email and email in emails)


def _daytrade_user_confirmed(user):
    user_id = str((user or {}).get("id", "") or "").strip()
    email = str((user or {}).get("email", "") or "").strip().lower()
    ids = {str(item).strip() for item in _csv_items(_get_config("daytrade_confirmed_user_ids", ""))}
    emails = {str(item).strip().lower() for item in _csv_items(_get_config("daytrade_confirmed_user_emails", ""))}
    return (user_id and user_id in ids) or (email and email in emails)


def _append_config_list(key, value):
    value = str(value or "").strip()
    if value == "":
        return
    items = _csv_items(_get_config(key, ""))
    if value not in items:
        items.append(value)
    _set_config(key, "\n".join(items), f"{key} list")

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


def _normalize_order_method(value, default="firegate", allow_market=False):
    method = str(value or default).strip().lower()
    if method == "loc":
        return "loc"
    if allow_market and method == "market":
        return "market"
    return "firegate"


def _ensure_default_watchlist_items(trading):
    watchlist_db = trading.db("etf_watchlist")
    now = _TIME.now()
    default_division = _safe_int(_get_config("default_division_count", "40"), 40)
    default_target = _safe_float(_get_config("default_target_profit", "10"), 10)
    for item in _DEFAULT_WATCHLIST_ITEMS:
        symbol = item["symbol"]
        if watchlist_db.get(symbol=symbol):
            continue
        watchlist_db.insert({
            "symbol": symbol,
            "name": item["name"],
            "exchange": item["exchange"],
            "total_investment": item["total_investment"],
            "division_count": default_division,
            "target_profit": default_target,
            "cycle_mode": "auto",
            "is_active": False,
            "memo": "기본 관심종목 - 사용자가 활성화해야 자동 운용됩니다.",
            "created": now,
            "updated": now,
        })


def load_settings():
    """설정 전체 로드"""
    try:
        _, _, user = _session_user()
        trading = _trading()
        watchlist_db = trading.db("etf_watchlist")

        broker_provider = _normalize_broker_provider(_get_config("broker_provider", "kis"))
        app_key = _get_config("kis_app_key")
        app_secret = _get_config("kis_app_secret")
        toss_client_id = _get_config("toss_client_id", "")
        toss_client_secret = _get_config("toss_client_secret", "")
        toss_account_seq = _get_config("toss_account_seq", "")
        account_raw = _get_config("kis_account_no")
        # 레거시 호환: 하이픈 없는 8자리면 suffix와 합치기
        if account_raw and "-" not in account_raw:
            suffix = _get_config("kis_account_suffix", "01")
            if suffix:
                account_raw = f"{account_raw}-{suffix}"
                _set_config("kis_account_no", account_raw, "한국투자증권 계좌번호", True)
        account_no = account_raw

        is_real = _get_config("kis_is_real", "false")
        division_count = _get_config("default_division_count", "40")
        target_profit = _get_config("default_target_profit", "10")
        auto_trade = _get_config("auto_trade_enabled", "false")
        buy_commission_rate = _get_config("buy_commission_rate", "0.25")
        sell_commission_rate = _get_config("sell_commission_rate", "0.25")
        tax_rate = _get_config("tax_rate", "0")

        sell_strategy = _get_config("sell_strategy", "firegate")
        if sell_strategy not in ["firegate", "full", "partial"]:
            sell_strategy = "firegate"
        crash_buy_enabled = _get_config("crash_buy_enabled", "false")
        crash_buy_drop_pct = _get_config("crash_buy_drop_pct", "5")
        crash_buy_ma_drop_pct = _get_config("crash_buy_ma_drop_pct", "10")
        crash_buy_ratio = _get_config("crash_buy_ratio", "10")
        crash_buy_max_per_cycle = _get_config("crash_buy_max_per_cycle", "3")
        buy_method = _normalize_order_method(_get_config("buy_method", "firegate"), "firegate", allow_market=True)
        sell_method = _normalize_order_method(_get_config("sell_method", "firegate"), "firegate")
        daytrade_default_seed = _get_config("daytrade_default_seed", "5000000")
        daytrade_us_default_seed = _get_config("daytrade_us_default_seed", daytrade_default_seed or "5000000")
        daytrade_feature_enabled = "false" if _DAYTRADE_HARD_LOCKED else _get_config("daytrade_feature_enabled", "false")
        daytrade_authorized_user_ids = _get_config("daytrade_authorized_user_ids", "")
        daytrade_authorized_user_emails = _get_config("daytrade_authorized_user_emails", "")
        daytrade_auto_enabled = _get_config("daytrade_auto_enabled", "false")
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
        user_email = user.get("email", "")
        login_id = user_email.split("@", 1)[0] if "@" in user_email else user_email
        is_admin = _is_admin_user(user)
        daytrade_user_authorized = is_admin or _daytrade_user_authorized(user)
        daytrade_user_confirmed = is_admin or _daytrade_user_confirmed(user)
        if _DAYTRADE_HARD_LOCKED:
            daytrade_user_authorized = False
            daytrade_user_confirmed = False

        try:
            _ensure_default_watchlist_items(trading)
            watchlist = watchlist_db.rows(orderby="created", order="ASC") or []
        except Exception:
            watchlist = []
    except Exception as e:
        wiz.response.status(500, message=f"load_settings failed: {e}")

    wiz.response.status(200,
        app_key=app_key,
        app_secret=app_secret,
        broker_provider=broker_provider,
        broker_options=_BROKER_OPTIONS,
        selected_broker_option=_broker_option(broker_provider),
        toss_client_id=toss_client_id,
        toss_client_secret=toss_client_secret,
        toss_account_seq=toss_account_seq,
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
        buy_method=buy_method,
        sell_method=sell_method,
        daytrade_default_seed=_safe_float(daytrade_default_seed, 5000000),
        daytrade_us_default_seed=_safe_float(daytrade_us_default_seed, _safe_float(daytrade_default_seed, 5000000)),
        daytrade_auto_enabled=False if _DAYTRADE_HARD_LOCKED else str(daytrade_auto_enabled).lower() == "true",
        daytrade_us_auto_enabled=False if _DAYTRADE_HARD_LOCKED else str(daytrade_us_auto_enabled).lower() == "true",
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
        is_admin=is_admin,
        daytrade_feature_enabled=False if _DAYTRADE_HARD_LOCKED else _truthy(daytrade_feature_enabled),
        daytrade_hard_locked=_DAYTRADE_HARD_LOCKED,
        daytrade_lock_message=_DAYTRADE_LOCK_MESSAGE,
        daytrade_authorized_user_ids=daytrade_authorized_user_ids,
        daytrade_authorized_user_emails=daytrade_authorized_user_emails,
        daytrade_user_authorized=daytrade_user_authorized,
        daytrade_user_confirmed=daytrade_user_confirmed,
        daytrade_access_enabled=False if _DAYTRADE_HARD_LOCKED else _truthy(daytrade_feature_enabled) and daytrade_user_authorized and daytrade_user_confirmed,
        daytrade_confirmation_phrase="확인했습니다",
        account_user_id=user.get("id", ""),
        account_login_id=login_id,
        account_email=user_email,
        watchlist=watchlist,
    )

def save_api_settings():
    """API 설정 저장"""
    _session_user()
    payload = _api_settings_payload_from_request()
    _validate_api_settings_payload(payload)
    trading, is_real = _persist_api_settings(payload)

    try:
        result = _selected_broker_api(trading).test_connection()
    except Exception as e:
        result = {"success": False, "message": f"증권사 API 연결 테스트 중 오류가 발생했습니다: {e}"}

    _api_settings_response(payload, result, is_real, saved=True)

def test_connection():
    """API 연결 테스트"""
    _session_user()
    if _api_settings_request_present():
        payload = _api_settings_payload_from_request()
        _validate_api_settings_payload(payload)
        trading, is_real = _persist_api_settings(payload)
        try:
            result = _selected_broker_api(trading).test_connection()
        except Exception as e:
            result = {"success": False, "message": f"증권사 API 연결 테스트 중 오류가 발생했습니다: {e}"}
        _api_settings_response(payload, result, is_real, saved=True)

    trading = _trading()
    try:
        result = _selected_broker_api(trading).test_connection()
    except Exception as e:
        wiz.response.status(200, success=False, message=f"증권사 API 연결 테스트 중 오류가 발생했습니다: {e}")
    if result.get("success", False) is False:
        wiz.response.status(200, success=False, message=result.get("message", "증권사 API 연결에 실패했습니다."))
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
        wiz.response.status(400, message=f"{symbol} 종목은 이미 관심종목에 등록되어 있습니다.")

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
        wiz.response.status(404, message=f"{symbol} 종목을 찾지 못했습니다.")

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
    _set_config("default_target_profit", target_profit, "기본 목표 수익률")
    _set_config("auto_trade_enabled", auto_trade, "Auto trade enabled")
    _set_config("buy_commission_rate", buy_commission_rate, "Buy commission rate %")
    _set_config("sell_commission_rate", sell_commission_rate, "Sell commission rate %")
    _set_config("tax_rate", tax_rate, "Sell tax rate %")

    # Strategy params
    sell_strategy = wiz.request.query("sell_strategy", "firegate")
    if sell_strategy not in ["firegate", "full", "partial"]:
        sell_strategy = "firegate"
    crash_buy_enabled = wiz.request.query("crash_buy_enabled", "false")
    crash_buy_drop_pct = wiz.request.query("crash_buy_drop_pct", "5")
    crash_buy_ma_drop_pct = wiz.request.query("crash_buy_ma_drop_pct", "10")
    crash_buy_ratio = wiz.request.query("crash_buy_ratio", "10")
    crash_buy_max_per_cycle = wiz.request.query("crash_buy_max_per_cycle", "3")
    daytrade_default_seed = max(100000.0, min(1000000000.0, _safe_float(wiz.request.query("daytrade_default_seed", "5000000"), 5000000)))
    daytrade_us_default_seed = max(100000.0, min(1000000000.0, _safe_float(wiz.request.query("daytrade_us_default_seed", str(daytrade_default_seed)), daytrade_default_seed)))
    daytrade_auto_enabled = wiz.request.query("daytrade_auto_enabled", "false")
    daytrade_us_auto_enabled = wiz.request.query("daytrade_us_auto_enabled", "false")
    if _DAYTRADE_HARD_LOCKED or _truthy(_get_config("daytrade_feature_enabled", "false")) is False:
        daytrade_auto_enabled = "false"
        daytrade_us_auto_enabled = "false"
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

    buy_method = _normalize_order_method(wiz.request.query("buy_method", "firegate"), "firegate", allow_market=True)
    sell_method = _normalize_order_method(wiz.request.query("sell_method", "firegate"), "firegate")
    _set_config("buy_method", buy_method, "Buy method: firegate, loc or legacy market")
    _set_config("sell_method", sell_method, "Sell method: firegate or loc")
    _set_config("sell_strategy", sell_strategy, "Sell strategy: firegate, full or partial")
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
    _set_config("loc_auto_schedule_enabled", loc_auto_schedule_enabled, "Auto LOC reservation scheduling from 10:00 KST")

    wiz.response.status(200)


def save_daytrade_admin_settings():
    """관리자 단타 기능 전역 노출/인증 설정."""
    _, _, user = _session_user()
    if _is_admin_user(user) is False:
        wiz.response.status(403, message="관리자만 변경할 수 있습니다.")

    if _DAYTRADE_HARD_LOCKED:
        _set_config("daytrade_feature_enabled", "false", "Daytrade feature hard locked")
        _set_config("daytrade_auto_enabled", "false", "Domestic daytrade auto rotation enabled")
        _set_config("daytrade_exit_watch_enabled", "false", "Domestic daytrade auto exit watch enabled")
        _set_config("daytrade_us_auto_enabled", "false", "US daytrade auto rotation enabled")
        _set_config("daytrade_us_exit_watch_enabled", "false", "US daytrade auto exit watch enabled")
        wiz.response.status(200,
            daytrade_feature_enabled=False,
            daytrade_authorized_user_ids="",
            daytrade_authorized_user_emails="",
            daytrade_hard_locked=True,
            message=_DAYTRADE_LOCK_MESSAGE,
        )

    feature_enabled = wiz.request.query("daytrade_feature_enabled", "false")
    authorized_user_ids = wiz.request.query("daytrade_authorized_user_ids", "")
    authorized_user_emails = wiz.request.query("daytrade_authorized_user_emails", "")

    enabled = _truthy(feature_enabled)
    _set_config("daytrade_feature_enabled", "true" if enabled else "false", "Daytrade feature globally visible")
    _set_config("daytrade_authorized_user_ids", "\n".join(_csv_items(authorized_user_ids)), "Daytrade authorized user ids")
    _set_config("daytrade_authorized_user_emails", "\n".join([item.lower() for item in _csv_items(authorized_user_emails)]), "Daytrade authorized user emails")

    if enabled is False:
        _set_config("daytrade_auto_enabled", "false", "Domestic daytrade auto rotation enabled")
        _set_config("daytrade_exit_watch_enabled", "false", "Domestic daytrade auto exit watch enabled")
        _set_config("daytrade_us_auto_enabled", "false", "US daytrade auto rotation enabled")
        _set_config("daytrade_us_exit_watch_enabled", "false", "US daytrade auto exit watch enabled")

    try:
        _trading().refresh_config_cache()
    except Exception:
        pass

    wiz.response.status(200,
        daytrade_feature_enabled=enabled,
        daytrade_authorized_user_ids="\n".join(_csv_items(authorized_user_ids)),
        daytrade_authorized_user_emails="\n".join([item.lower() for item in _csv_items(authorized_user_emails)]),
        message="단타 관리자 설정이 저장되었습니다.",
    )


def confirm_daytrade_warning():
    """일반 사용자가 단타 위험 문구를 직접 입력해 확인."""
    _, _, user = _session_user()
    if _DAYTRADE_HARD_LOCKED:
        wiz.response.status(403, message=_DAYTRADE_LOCK_MESSAGE, daytrade_hard_locked=True)
    if _truthy(_get_config("daytrade_feature_enabled", "false")) is False:
        wiz.response.status(403, message="단타 기능이 관리자 설정에서 비활성화되어 있습니다.")
    if _is_admin_user(user) is False and _daytrade_user_authorized(user) is False:
        wiz.response.status(403, message="관리자 인증을 받은 사용자만 단타 기능을 확인할 수 있습니다.")

    phrase = str(wiz.request.query("phrase", "") or "").strip()
    required = "확인했습니다"
    if phrase != required:
        wiz.response.status(400, message=f"'{required}' 문구를 정확히 입력해주세요.")

    user_id = str(user.get("id", "") or "").strip()
    email = str(user.get("email", "") or "").strip().lower()
    _append_config_list("daytrade_confirmed_user_ids", user_id)
    _append_config_list("daytrade_confirmed_user_emails", email)
    wiz.response.status(200, confirmed=True, message="단타 위험 확인 문구가 저장되었습니다.")


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
    """종목 검색 — 선택한 증권사 API로 심볼을 여러 거래소에서 조회하여 검증"""
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
        kis = _selected_broker_api(trading)
        test = kis.test_connection()
        if not test.get("success", False):
            wiz.response.status(200, results=[], connected=False, message="선택한 증권사 API가 연결되지 않았습니다.")
    except Exception:
        wiz.response.status(200, results=[], connected=False, message="선택한 증권사 API를 사용할 수 없습니다.")

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
