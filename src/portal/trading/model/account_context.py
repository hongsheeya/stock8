"""Deployment-bound account context. Never mutate process mode per request."""
import os
from urllib.parse import urlsplit

def context():
    mode = os.environ.get("TRADING_MODE", "PAPER").upper()
    if mode not in ("LIVE", "PAPER"):
        raise RuntimeError("Invalid account context")
    live = os.environ.get("STOCK8_LIVE_ORIGIN", "http://127.0.0.1:3001").rstrip("/")
    paper = os.environ.get("STOCK8_PAPER_ORIGIN", "http://127.0.0.1:3002").rstrip("/")
    for origin in (live, paper):
        parsed = urlsplit(origin)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.path or parsed.query or parsed.fragment:
            raise RuntimeError("Invalid configured account origin")
    if live == paper:
        raise RuntimeError("Account environments must have separate origins")
    return {"mode": mode, "is_mock": mode == "PAPER", "data_scope": mode.lower(),
            "live_url": live + "/dashboard", "paper_url": paper + "/dashboard",
            "live_settings_url": live + "/settings", "paper_settings_url": paper + "/settings"}

class AccountContext:
    context = staticmethod(context)

Model = AccountContext()
