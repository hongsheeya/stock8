import os

def account_context():
    wiz.response.status(200, wiz.model('portal/trading/account_context').context())

def status():
    trading = wiz.model("struct").trading
    configured = all(bool(trading.get_config(key, "")) for key in (
        "kis_live_app_key", "kis_live_app_secret", "kis_live_account_no"
    ))
    row = trading.db("trading_config").get(key="live_orders_enabled") or {}
    enabled = (os.environ.get("TRADING_MODE", "PAPER").upper() == "LIVE"
               and os.environ.get("STOCK8_LIVE_TRADING_UNLOCK", "") == "I_UNDERSTAND_LIVE_TRADING"
               and str(row.get("value", "false")).lower() == "true")
    wiz.response.status(200, {
        "mode": "LIVE", "orders_enabled": enabled,
        "credentials_configured": configured,
        "balance_verified": False,
    })
