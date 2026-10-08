import os

secret_key = os.environ.get("WIZ_SECRET_KEY", "").strip()
if not secret_key:
    raise RuntimeError("WIZ_SECRET_KEY must be set in the production environment")

socketio = {
    "async_mode": "threading",
    "cors_allowed_origins": "*",
    "async_handlers": True,
    "always_connect": False,
    "manage_session": True,
}

run = {
    "allow_unsafe_werkzeug": True,
    "host": "0.0.0.0",
    "port": int(os.environ.get("PORT", "3000")),
    "use_reloader": False,
    "debug": False,
}

