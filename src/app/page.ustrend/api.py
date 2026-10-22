"""US daily trend hold page API (admin only via controller "coin"; 10-23).

PAPER process only. The worker (struct._ensure_paper_trend_hold_worker) owns
the ledger and every order; this API edits the policy row and reads status.
"""
import os as _os
import time as _time

_TRADING_MODE = str(_os.environ.get("TRADING_MODE", "PAPER") or "PAPER").strip().upper()
_PAPER_ORIGIN = str(_os.environ.get("STOCK8_PAPER_ORIGIN", "http://127.0.0.1:3002") or "").rstrip("/")


def _trading():
    return wiz.model("struct").trading


def _engine_cls():
    return wiz.model("portal/trading/us_trend_hold")


def _require_paper():
    if _TRADING_MODE != "PAPER":
        wiz.response.status(409, message="미장 추세 보유는 모의투자 서버에서만 운용합니다.", paper_url=_PAPER_ORIGIN + "/us-trend")


def _events(trading):
    rows = trading.db("trade_log").rows(event_type__startswith="USTH_", orderby="created", order="DESC", dump=40) or []
    return [{"created": str(r.get("created", ""))[:19], "symbol": r.get("symbol", ""), "event_type": r.get("event_type", ""),
             "action": r.get("action", ""), "message": r.get("message", "")} for r in rows]


def status():
    trading = _trading()
    engine_cls = _engine_cls()
    paper = _TRADING_MODE == "PAPER"
    payload = {"available": paper, "paper_url": _PAPER_ORIGIN + "/us-trend", "policy": {}, "engine": {},
               "worker": {}, "events": [], "seed_limits": [engine_cls.SEED_MIN, engine_cls.SEED_MAX],
               "pairs": [list(p) for p in engine_cls.PAIRS], "server_time": int(_time.time())}
    if paper:
        policy = trading.us_trend_hold_policy_read()
        payload["policy"] = {k: policy[k] for k in ("enabled", "seed_usd", "updated_at")}
        payload["worker"] = trading.us_trend_hold_worker_status()
        snap = dict(engine_cls.STATUS)
        if not snap:
            ledger = trading.us_trend_hold_ledger()
            if ledger:
                snap = {"equity": ledger.get("equity", 0), "peak_equity": ledger.get("peak_equity", 0),
                        "seed_usd": ledger.get("seed_usd", 0), "sleeves": [], "decisions": ledger.get("decisions", [])[-20:],
                        "equity_days": ledger.get("equity_days", [])[-250:], "last_error": ledger.get("last_error", "")}
        payload["engine"] = snap
        payload["events"] = _events(trading)
    wiz.response.status(200, **payload)


def save_settings():
    _require_paper()
    engine_cls = _engine_cls()
    try:
        seed = int(float(wiz.request.query("seed_usd", "0") or 0))
    except (TypeError, ValueError):
        wiz.response.status(400, message="시드는 숫자로 입력하세요.")
    if not (engine_cls.SEED_MIN <= seed <= engine_cls.SEED_MAX):
        wiz.response.status(400, message=f"시드는 ${engine_cls.SEED_MIN:,} ~ ${engine_cls.SEED_MAX:,} 사이로 입력하세요.")
    policy = _trading().us_trend_hold_policy_write({"seed_usd": seed})
    wiz.response.status(200, policy={k: policy[k] for k in ("enabled", "seed_usd")})


def set_enabled():
    _require_paper()
    enabled = str(wiz.request.query("enabled", "") or "").lower() in ("1", "true", "yes", "on")
    policy = _trading().us_trend_hold_policy_write({"enabled": enabled})
    wiz.response.status(200, policy={k: policy[k] for k in ("enabled", "seed_usd")})
