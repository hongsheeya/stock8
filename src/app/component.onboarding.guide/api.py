"""Quest-style first-run guide: progress is detected from the user's own setup.

Every check reads only the signed-in user's scoped data (API keys, FireGate
link, cycles, order policy) and returns booleans, never the values.
"""
import json

_KEY = "onboarding_progress"
_VISIT_KEYS = ("dashboard", "history")


def _trading():
    session = wiz.model('portal/season/session').use()
    if not session.get('id'):
        wiz.response.status(401, message='로그인이 필요합니다.')
    return wiz.model('struct').trading


def _load(trading):
    try:
        data = json.loads(trading.get_config(_KEY, "{}") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(trading, data):
    trading.set_config(_KEY, json.dumps(data, ensure_ascii=False), description="Onboarding guide progress")


def _api_ready(trading):
    try:
        broker = getattr(trading, 'broker_api', None) or trading.kis_api
        return bool(str(getattr(broker, 'app_key', '') or '').strip() and str(getattr(broker, 'account_no', '') or '').strip())
    except Exception:
        return False


def _firegate_ready(trading):
    try:
        cfg = json.loads(trading.get_config("fire_gate_bridge", "{}") or "{}")
        return bool(isinstance(cfg, dict) and cfg.get("email") and (cfg.get("id_token") or cfg.get("refresh_token")))
    except Exception:
        return False


def _has_cycle(trading):
    try:
        db = trading.db("trading_cycle")
        for status in ("ACTIVE", "HOLDING", "PENDING_EXTENSION"):
            if db.get(status=status):
                return True
    except Exception:
        pass
    return False


def _auto_on(trading):
    try:
        return trading.order_policy.status().get("infinite_buy") is True
    except Exception:
        return False


def progress():
    trading = _trading()
    data = _load(trading)
    visited = data.get("visited") if isinstance(data.get("visited"), dict) else {}
    api = _api_ready(trading)
    cycle = _has_cycle(trading)
    auto = _auto_on(trading)
    steps = {
        "account": True,
        "api": api,
        # A running cycle or automation already proves the connection works.
        "connection": api and (bool(data.get("connection_ok")) or cycle or auto),
        "firegate": _firegate_ready(trading),
        "cycle": cycle,
        "auto": auto,
        "explore": all(visited.get(key) for key in _VISIT_KEYS),
    }
    wiz.response.status(200, steps=steps, visited=visited, dismissed=bool(data.get("dismissed")))


def mark():
    key = str(wiz.request.query("key", "") or "")
    if key not in _VISIT_KEYS:
        wiz.response.status(400, message="알 수 없는 항목입니다.")
    trading = _trading()
    data = _load(trading)
    visited = data.get("visited") if isinstance(data.get("visited"), dict) else {}
    if not visited.get(key):
        visited[key] = True
        data["visited"] = visited
        _save(trading, data)
    wiz.response.status(200, visited=visited)


def dismiss():
    trading = _trading()
    data = _load(trading)
    data["dismissed"] = str(wiz.request.query("value", "true")).lower() == "true"
    _save(trading, data)
    wiz.response.status(200, dismissed=data["dismissed"])
