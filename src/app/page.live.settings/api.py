import os
from flask import request

def _context():
    session = wiz.model("portal/season/session").use()
    uid = session.get("id")
    if not uid:
        wiz.response.status(401, message="로그인이 필요합니다.")
    root = wiz.model("struct")
    user = root.user.get(id=uid) or {}
    return root.trading, str(user.get("role", "")).lower() == "admin"

def _state(trading, admin):
    live = os.environ.get("TRADING_MODE", "PAPER").upper() == "LIVE"
    unlocked = os.environ.get("STOCK8_LIVE_TRADING_UNLOCK", "") == "I_UNDERSTAND_LIVE_TRADING"
    row = trading.db("trading_config").get(key="live_orders_enabled") or {}
    enabled = live and unlocked and str(row.get("value", "false")).lower() == "true"
    return {"orders_enabled": enabled, "can_enable": live and unlocked and admin,
            "is_admin": admin, "runtime_mode": "LIVE" if live else "PAPER"}

def status():
    trading, admin = _context()
    wiz.response.status(200, _state(trading, admin))

def save():
    wiz.response.status(410, message='전략별 자동매매 제어에서 경고를 확인하고 설정하세요.')
    if request.method != "POST":
        wiz.response.status(405, message="POST 요청만 허용됩니다.")
    trading, admin = _context()
    if not admin:
        wiz.response.status(403, message="관리자만 실투자 주문 설정을 변경할 수 있습니다.")
    enabled = str(wiz.request.query("enabled", "false")).lower() == "true"
    state = _state(trading, admin)
    if enabled and not state["can_enable"]:
        wiz.response.status(409, message="현재는 모의투자 서버입니다. 분리된 실투자 서버 연결 전에는 활성화할 수 없습니다.")
    if enabled and str(wiz.request.query("confirmation", "")) != "실투자 거래 활성화":
        wiz.response.status(400, message="확인 문구를 정확히 입력하세요.")
    trading.set_config("live_orders_enabled", "true" if enabled else "false",
                       description="실투자 주문 명시적 허용; 기본 OFF")
    wiz.response.status(200, _state(trading, admin))
