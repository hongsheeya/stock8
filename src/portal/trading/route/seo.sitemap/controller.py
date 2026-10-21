# 10-21 pre-launch: the public pages search engines may list.
import os
from flask import request

origin = str(os.environ.get("STOCK8_PUBLIC_ORIGIN", "") or "").strip().rstrip("/")
if not origin:
    proto = str(request.headers.get("X-Forwarded-Proto", "") or request.scheme or "http").split(",")[0].strip()
    origin = f"{proto}://{request.host}"

PUBLIC_PAGES = ["/access"]
urls = "".join(f"<url><loc>{origin}{path}</loc></url>" for path in PUBLIC_PAGES)
body = ('<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
wiz.response.send(body, content_type="application/xml; charset=utf-8")
