import re
import time

_STRUCT_CACHE = {"obj": None, "error": None, "error_at": 0.0}
_STRUCT_ERROR_TTL_SEC = 5.0
_DAYTRADE_HARD_LOCKED = True
_DAYTRADE_LOCK_MESSAGE = "단타 기능은 현재 운영 안정화를 위해 완전히 봉인되어 있습니다."


def _get_struct():
    cached = _STRUCT_CACHE.get("obj")
    if cached is not None:
        return cached

    cached_error = _STRUCT_CACHE.get("error")
    if cached_error is not None:
        if time.monotonic() - float(_STRUCT_CACHE.get("error_at", 0.0) or 0.0) < _STRUCT_ERROR_TTL_SEC:
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


def _get_config(key, default=""):
    trading = _get_struct().trading
    getter = getattr(trading, "get_config", None)
    if callable(getter):
        return getter(key, default)
    row = trading.db("trading_config").get(key=key)
    return row.get("value", default) if row else default


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "y", "on")


def _csv_items(value):
    return [token.strip() for token in re.split(r"[\s,;\n]+", str(value or "")) if token.strip()]


def _is_admin_user(user):
    role = str((user or {}).get("role", "") or "").lower()
    email = str((user or {}).get("email", "") or "").strip().lower()
    return role == "admin" or email == "gigukbyun@gmail.com"


def _session_user():
    session = wiz.model("portal/season/session").use()
    user_id = session.get("id")
    if not user_id:
        return None
    try:
        return _get_struct().user.get(id=user_id)
    except Exception:
        return None


def _listed_user(user, id_key, email_key):
    user_id = str((user or {}).get("id", "") or "").strip()
    email = str((user or {}).get("email", "") or "").strip().lower()
    ids = {str(item).strip() for item in _csv_items(_get_config(id_key, ""))}
    emails = {str(item).strip().lower() for item in _csv_items(_get_config(email_key, ""))}
    return (user_id and user_id in ids) or (email and email in emails)


def daytrade_access_status():
    user = _session_user()
    if not user:
        return wiz.response.status(200,
            logged_in=False,
            is_admin=False,
            daytrade_feature_enabled=False,
            daytrade_user_authorized=False,
            daytrade_user_confirmed=False,
            daytrade_access_enabled=False,
            daytrade_hard_locked=_DAYTRADE_HARD_LOCKED,
            message=_DAYTRADE_LOCK_MESSAGE if _DAYTRADE_HARD_LOCKED else "",
        )

    is_admin = _is_admin_user(user)
    feature_enabled = False if _DAYTRADE_HARD_LOCKED else _truthy(_get_config("daytrade_feature_enabled", "false"))
    authorized = False if _DAYTRADE_HARD_LOCKED else is_admin or _listed_user(user, "daytrade_authorized_user_ids", "daytrade_authorized_user_emails")
    confirmed = False if _DAYTRADE_HARD_LOCKED else is_admin or _listed_user(user, "daytrade_confirmed_user_ids", "daytrade_confirmed_user_emails")

    wiz.response.status(200,
        logged_in=True,
        is_admin=is_admin,
        daytrade_feature_enabled=feature_enabled,
        daytrade_user_authorized=authorized,
        daytrade_user_confirmed=confirmed,
        daytrade_access_enabled=False if _DAYTRADE_HARD_LOCKED else feature_enabled and authorized and confirmed,
        daytrade_hard_locked=_DAYTRADE_HARD_LOCKED,
        message=_DAYTRADE_LOCK_MESSAGE if _DAYTRADE_HARD_LOCKED else "",
    )
