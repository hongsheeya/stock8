"""Coin automation page API (admin only via controller "coin"; 10-22).

The worker (struct._ensure_live_coin_worker) owns the ledger and every Upbit
order. This API only edits the policy row and the encrypted keys, runs a
read-only connection test, and reads status. Keys are never sent back.
"""
import json as _json
import os as _os
import sys as _sys
import time as _time

_TRADING_MODE = str(_os.environ.get("TRADING_MODE", "PAPER") or "PAPER").strip().upper()
_LIVE_ORIGIN = str(_os.environ.get("STOCK8_LIVE_ORIGIN", "http://127.0.0.1:3001") or "").rstrip("/")
# Last successful read-only key test per owner (live needs one within 30 min).
_CONN = _sys.__dict__.setdefault("_stock8_coin_connection", {})
_LIVE_CONFIRM_TEXT = "실거래 시작"
_ERROR_HINTS = {
    "no_authorization_ip": "업비트에 등록한 허용 IP와 이 PC의 공인 IP가 다릅니다. 업비트 Open API 관리에서 허용 IP를 확인하세요.",
    "invalid_access_key": "Access Key가 올바르지 않습니다.",
    "jwt_verification": "Secret Key가 올바르지 않습니다.",
    "expired_access_key": "만료된 키입니다. 업비트에서 새로 발급하세요.",
    "out_of_scope": "키 권한이 부족합니다. 자산조회·주문조회·주문하기 권한을 켜세요.",
    "too_many_requests": "요청이 너무 많습니다. 잠시 뒤 다시 시도하세요.",
}


def _trading():
    return wiz.model("struct").trading


def _uid():
    return str(wiz.session.get("id") or "")


def _engine_cls():
    return wiz.model("portal/trading/coin_engine")


def _require_live():
    if _TRADING_MODE != "LIVE":
        wiz.response.status(409, message="코인 자동매매는 실투자 서버에서만 설정합니다.", live_url=_LIVE_ORIGIN + "/coin")


def _key_status(trading, uid):
    access, secret = trading.coin_keys(uid)
    return {"configured": bool(access and secret), "access_hint": ("…" + access[-4:]) if len(access) >= 8 else ""}


def _read_state(trading, owner, mode):
    state_dir, _candles, _root = trading.coin_data_dirs(owner)
    try:
        with open(_os.path.join(state_dir, f"state_{mode}.json"), encoding="utf-8") as handle:
            return _json.load(handle)
    except (OSError, ValueError):
        return None


def _ledger_summary(state):
    if not isinstance(state, dict):
        return None
    sleeves = state.get("sleeves") or {}
    return {
        "equity": state.get("equity", 0), "peak_equity": state.get("peak_equity", 0), "seed_krw": state.get("seed_krw", 0),
        "halted": bool(state.get("halted")), "halt_reason": state.get("halt_reason", ""),
        "open_positions": [m for m, s in sleeves.items() if s.get("long")],
        "trades": sum(int(s.get("trades") or 0) for s in sleeves.values()),
        "realized_krw": sum(float(s.get("realized_krw") or 0) for s in sleeves.values()),
    }


def _events(trading):
    rows = trading.db("trade_log").rows(event_type__startswith="COIN_", orderby="created", order="DESC", dump=40) or []
    return [{"created": str(r.get("created", ""))[:19], "symbol": r.get("symbol", ""), "event_type": r.get("event_type", ""),
             "action": r.get("action", ""), "message": r.get("message", "")} for r in rows]


def status():
    trading = _trading()
    uid = _uid()
    engine_cls = _engine_cls()
    policy = trading.coin_policy_read()
    live_process = _TRADING_MODE == "LIVE"
    payload = {
        "available": live_process,
        "live_url": _LIVE_ORIGIN + "/coin",
        "policy": {k: policy[k] for k in ("mode", "seed_krw", "markets", "max_order_krw", "live_confirmed_at", "updated_at")},
        "all_markets": list(engine_cls.ALL_MARKETS),
        "default_markets": list(engine_cls.DEFAULT_MARKETS),
        "seed_limits": [engine_cls.SEED_MIN, engine_cls.SEED_MAX],
        "keys": _key_status(trading, uid),
        "connection": {k: v for k, v in (_CONN.get(uid) or {}).items() if k != "fingerprint"},
        "worker": trading.coin_worker_status() if live_process else {},
        "live_confirm_text": _LIVE_CONFIRM_TEXT,
        "engine": {},
        "ledgers": {},
        "events": [],
        "server_time": int(_time.time()),
    }
    if live_process:
        snap = dict(engine_cls.STATUS)
        if snap and snap.get("mode") == policy["mode"] and _time.time() - float(snap.get("updated_at") or 0) < 120:
            payload["engine"] = snap
        owner = policy["owner_user_id"] or uid
        payload["ledgers"] = {mode: _ledger_summary(_read_state(trading, owner, mode)) for mode in ("shadow", "live")}
        payload["events"] = _events(trading)
        try:
            payload["shadow_progress"] = trading.coin_shadow_progress(owner)
        except Exception as exc:
            payload["shadow_progress"] = {"error": str(exc)[:200]}
    wiz.response.status(200, **payload)


def save_keys():
    _require_live()
    access = str(wiz.request.query("access_key", "") or "").strip()
    secret = str(wiz.request.query("secret_key", "") or "").strip()
    for label, value in (("Access Key", access), ("Secret Key", secret)):
        if not (20 <= len(value) <= 128) or any(ch.isspace() for ch in value):
            wiz.response.status(400, message=f"{label} 형식이 올바르지 않습니다.")
    trading = _trading()
    uid = _uid()
    trading.coin_save_keys(uid, access, secret)
    _CONN.pop(uid, None)
    policy = trading.coin_policy_read()
    if policy["mode"] == "live":
        # New keys = possibly another account: live needs a fresh approval.
        trading.coin_policy_write({"mode": "off", "account_fp": ""})
    wiz.response.status(200, keys=_key_status(trading, uid), mode_reset=policy["mode"] == "live")


def delete_keys():
    _require_live()
    trading = _trading()
    uid = _uid()
    policy = trading.coin_policy_read()
    if policy["mode"] == "live":
        trading.coin_policy_write({"mode": "off", "account_fp": ""})
    trading.coin_save_keys(uid, "", "")
    _CONN.pop(uid, None)
    wiz.response.status(200, keys=_key_status(trading, uid))


def test_connection():
    _require_live()
    trading = _trading()
    uid = _uid()
    access, secret = trading.coin_keys(uid)
    if not (access and secret):
        wiz.response.status(400, message="먼저 업비트 API 키를 저장하세요.")
    api_cls = wiz.model("portal/trading/upbit_api")
    api = api_cls(access, secret)  # no order guard: this client cannot order
    result, error = None, None
    try:
        balances = api.balances()
        coins = [{"currency": c, "balance": v["balance"] + v["locked"], "avg_buy_price": v["avg_buy_price"]}
                 for c, v in balances.items() if c != "KRW" and (v["balance"] + v["locked"]) > 0]
        result = {"ok": True, "at": int(_time.time()), "krw": (balances.get("KRW") or {}).get("balance", 0),
                  "krw_locked": (balances.get("KRW") or {}).get("locked", 0), "coins": coins[:20],
                  "fingerprint": wiz.model("portal/trading/coin_engine").account_fingerprint(access)}
    except Exception as exc:
        name = str(getattr(exc, "name", "") or "")
        error = _ERROR_HINTS.get(name) or f"연결 실패: {str(exc)[:160]}"
    if error:
        _CONN[uid] = {"ok": False, "at": int(_time.time()), "message": error}
        wiz.response.status(400, message=error)
    _CONN[uid] = result
    wiz.response.status(200, connection={k: v for k, v in result.items() if k != "fingerprint"})


def save_settings():
    _require_live()
    trading = _trading()
    engine_cls = _engine_cls()
    try:
        seed = int(float(wiz.request.query("seed_krw", "0") or 0))
        max_order = int(float(wiz.request.query("max_order_krw", "0") or 0))
    except (TypeError, ValueError):
        wiz.response.status(400, message="금액은 숫자로 입력하세요.")
    markets = [m.strip() for m in str(wiz.request.query("markets", "") or "").split(",") if m.strip()]
    if not markets or any(m not in engine_cls.ALL_MARKETS for m in markets):
        wiz.response.status(400, message="운용할 코인을 1개 이상 고르세요.")
    if not (engine_cls.SEED_MIN <= seed <= engine_cls.SEED_MAX):
        wiz.response.status(400, message=f"시드는 ₩{engine_cls.SEED_MIN:,} ~ ₩{engine_cls.SEED_MAX:,} 사이로 입력하세요.")
    if seed // len(markets) < 10000:
        wiz.response.status(400, message="코인 1개당 시드가 ₩10,000 이상이어야 합니다 (업비트 최소 주문 ₩5,000).")
    if max_order and max_order < 5000:
        wiz.response.status(400, message="1회 주문 한도는 ₩5,000 이상이어야 합니다.")
    policy = trading.coin_policy_write({"seed_krw": seed, "markets": markets, "max_order_krw": max_order})
    wiz.response.status(200, policy={k: policy[k] for k in ("mode", "seed_krw", "markets", "max_order_krw")})


def set_mode():
    _require_live()
    trading = _trading()
    uid = _uid()
    mode = str(wiz.request.query("mode", "") or "").lower()
    if mode not in ("off", "shadow", "live"):
        wiz.response.status(400, message="알 수 없는 모드입니다.")
    current = trading.coin_policy_read()
    updates = {"mode": mode}
    if mode == "live":
        access, secret = trading.coin_keys(uid)
        if not (access and secret):
            wiz.response.status(400, message="업비트 API 키를 먼저 저장하세요.")
        conn = _CONN.get(uid) or {}
        engine_cls = _engine_cls()
        fp = engine_cls.account_fingerprint(access)
        if not conn.get("ok") or _time.time() - float(conn.get("at") or 0) > 1800 or conn.get("fingerprint") != fp:
            wiz.response.status(400, message="실거래 전에 '연결 테스트'를 다시 통과해야 합니다 (30분 이내).")
        if str(wiz.request.query("confirm", "") or "").strip() != _LIVE_CONFIRM_TEXT:
            wiz.response.status(400, message=f"확인 문구 '{_LIVE_CONFIRM_TEXT}'를 정확히 입력하세요.")
        updates.update(account_fp=fp, live_confirmed_at=_time.strftime("%Y-%m-%d %H:%M:%S"))
    elif current["mode"] == "live":
        updates["account_fp"] = ""  # leaving live always needs a new approval
    policy = trading.coin_policy_write(updates)
    wiz.response.status(200, policy={k: policy[k] for k in ("mode", "seed_krw", "markets", "max_order_krw", "live_confirmed_at")})


def resume():
    _require_live()
    policy = _trading().coin_policy_write({"resume_at": _time.strftime("%Y-%m-%d %H:%M:%S")})
    wiz.response.status(200, policy={"mode": policy["mode"]})
