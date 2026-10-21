import os

secret_key = os.environ.get("WIZ_SECRET_KEY", "").strip()
if not secret_key:
    raise RuntimeError("WIZ_SECRET_KEY must be set in the production environment")

def _load_web_hooks():
    # deploy/web_hooks.py is installed next to this file (the WIZ config dir).
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_hooks.py")
    spec = importlib.util.spec_from_file_location("stock8_web_hooks", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_web_hooks = _load_web_hooks()
_web_hooks.load_into(globals())


def bootstrap(app, config):
    _web_hooks.apply_flask_settings(app.flask)


_public_origin = os.environ.get("STOCK8_PUBLIC_ORIGIN", "").strip().rstrip("/")

socketio = {
    "async_mode": "threading",
    # Same-origin only unless the public origin is configured.
    "cors_allowed_origins": [_public_origin] if _public_origin else None,
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

