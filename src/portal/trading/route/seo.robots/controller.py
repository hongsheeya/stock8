# 10-21 pre-launch: only the public entry (/access) and static assets are
# crawlable; every trading screen, API and the WIZ IDE stay out of search.
import os
from flask import request

origin = str(os.environ.get("STOCK8_PUBLIC_ORIGIN", "") or "").strip().rstrip("/")
if not origin:
    proto = str(request.headers.get("X-Forwarded-Proto", "") or request.scheme or "http").split(",")[0].strip()
    origin = f"{proto}://{request.host}"

body = "\n".join([
    "User-agent: *",
    "Allow: /access",
    "Allow: /assets/",
    "Disallow: /",
    "",
    f"Sitemap: {origin}/sitemap.xml",
    "",
])
wiz.response.send(body, content_type="text/plain; charset=utf-8")
