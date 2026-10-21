"""Request hooks shared by deploy/boot.py (public) and boot-local-paper.py.

10-21, pre-launch checks:
- The WIZ IDE (/wiz, /wiz/ide/...) edits and runs project code. Its ACL in
  a fresh `wiz create` workspace allows everyone, and its ?dev= / ?project=
  switches run before the ACL. It is served only to direct loopback
  requests (never through the reverse proxy) unless STOCK8_IDE_ENABLED=false.
- Basic security headers on every response.
- og:image / og:url need absolute URLs; index.html carries relative ones and
  they are completed here from STOCK8_PUBLIC_ORIGIN or the request host.
"""
import os

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_RELATIVE_OG = (
    ('property="og:image" content="/', 'property="og:image" content="{origin}/'),
    ('name="twitter:image" content="/', 'name="twitter:image" content="{origin}/'),
    ('property="og:url" content="/', 'property="og:url" content="{origin}/'),
)


def _truthy(name, default=""):
    return str(os.environ.get(name, default) or "").strip().lower() in ("1", "true", "yes", "on")


def is_direct_loopback(request):
    if request.headers.get("X-Forwarded-For") or request.headers.get("X-Real-IP") or request.headers.get("Forwarded"):
        return False
    return str(request.remote_addr or "") in _LOOPBACK


def ide_allowed(request):
    if str(os.environ.get("STOCK8_IDE_ENABLED", "") or "").strip().lower() in ("0", "false", "no", "off"):
        return False
    return is_direct_loopback(request)


def is_ide_path(path):
    path = str(path or "")
    return path == "/wiz" or path == "/wiz/" or path == "/wiz/ide" or path.startswith("/wiz/ide/")


def public_origin(request):
    origin = str(os.environ.get("STOCK8_PUBLIC_ORIGIN", "") or "").strip().rstrip("/")
    if origin:
        return origin
    proto = str(request.headers.get("X-Forwarded-Proto", "") or request.scheme or "http").split(",")[0].strip()
    return f"{proto}://{request.host}"


def before_request(wiz):
    from flask import request
    from werkzeug.exceptions import NotFound
    if is_ide_path(request.path) and not ide_allowed(request):
        raise NotFound()


def after_request(wiz, response):
    from flask import request
    headers = response.headers
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if response.status_code == 200 and response.mimetype == "text/html" and not request.path.startswith("/wiz"):
        try:
            response.direct_passthrough = False
            html = response.get_data(as_text=True)
            if 'content="/' in html and "og:" in html:
                origin = public_origin(request)
                for old, new in _RELATIVE_OG:
                    html = html.replace(old, new.format(origin=origin))
                response.set_data(html)
        except Exception:
            pass
    return response


def apply_flask_settings(flask_app):
    flask_app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_truthy("STOCK8_COOKIE_SECURE"),
    )


def persistent_secret(name):
    """A random value kept in ~/.stock8/<name> (created once, never printed)."""
    import secrets
    path = os.path.join(os.path.expanduser("~"), ".stock8", name)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                handle.write(secrets.token_urlsafe(48))
        except FileExistsError:
            pass
    with open(path, encoding="ascii") as handle:
        return handle.read().strip()


def load_into(namespace):
    """boot.py: register the hooks in WIZ's boot `event` config."""
    event = dict(namespace.get("event") or {})
    event["before_request"] = before_request
    event["after_request"] = after_request
    namespace["event"] = event
