# WIZ IDE access control (installed as config/ide.py).
# 10-21: a fresh `wiz create` workspace allows everyone into the IDE, which
# can edit and run project code. Only direct loopback requests get in (the
# boot hooks also hide /wiz/ide from proxied and remote requests).


def acl(wiz):
    import os
    from flask import request
    if str(os.environ.get("STOCK8_IDE_ENABLED", "") or "").strip().lower() in ("0", "false", "no", "off"):
        wiz.response.abort(404)
    proxied = request.headers.get("X-Forwarded-For") or request.headers.get("X-Real-IP") or request.headers.get("Forwarded")
    if proxied or str(request.remote_addr or "") not in ("127.0.0.1", "::1"):
        wiz.response.abort(404)
