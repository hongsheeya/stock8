"""Outbound alerts (10-24): Discord webhook messages and healthchecks.io pings.

Sending never blocks or breaks the caller: messages go through one daemon
thread per process, errors are kept for the page, identical messages within
DEDUPE_SEC are dropped. Only the official Discord webhook hosts and
hc-ping.com are accepted (the URLs carry secrets; stored encrypted).
"""
import json
import queue
import sys
import threading
import time
import urllib.error
import urllib.request

DISCORD_PREFIXES = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/",
                    "https://canary.discord.com/api/webhooks/", "https://ptb.discord.com/api/webhooks/")
HC_PREFIX = "https://hc-ping.com/"
DEDUPE_SEC = 60
TIMEOUT_SEC = 6
MAX_LEN = 1900  # Discord content limit is 2000
STATE = sys.__dict__.setdefault("_stock8_notifier_state", {"last_sent": 0, "last_error": "", "last_error_at": 0,
                                                           "last_ping": 0, "last_ping_error": "", "sent": 0})


def valid_discord(url):
    url = str(url or "").strip()
    return url.startswith(DISCORD_PREFIXES) and len(url) < 300 and not any(ch.isspace() for ch in url)


def valid_hc(url):
    url = str(url or "").strip()
    return url.startswith(HC_PREFIX) and len(url) < 200 and not any(ch.isspace() for ch in url)


def mask(url):
    url = str(url or "")
    return (url[:32] + "…" + url[-4:]) if len(url) > 40 else ("설정됨" if url else "")


def _post(url, payload=None, timeout=TIMEOUT_SEC):
    data = json.dumps(payload).encode("utf-8") if payload is not None else b""
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "stock8-alerts/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.status


class Notifier:
    def __init__(self, post=None, clock=None):
        self.post = post or _post
        self.clock = clock or time.time
        self.queue = queue.Queue(maxsize=200)
        self.recent = {}
        self.lock = threading.Lock()
        self.thread = None

    # ------------------------------------------------------------ public
    def discord(self, url, text):
        """Queue a Discord message; returns False when dropped (bad URL, duplicate, full)."""
        if not valid_discord(url):
            return False
        text = str(text or "")[:MAX_LEN]
        now = self.clock()
        with self.lock:
            self.recent = {k: t for k, t in self.recent.items() if now - t < DEDUPE_SEC}
            if text in self.recent:
                return False
            self.recent[text] = now
        return self._put(("discord", url, text))

    def ping(self, url, fail=False):
        if not valid_hc(url):
            return False
        return self._put(("ping", url.rstrip("/") + ("/fail" if fail else ""), None))

    def send_now(self, url, text):
        """Synchronous send for the page's test button: (ok, message)."""
        if not valid_discord(url):
            return False, "디스코드 웹훅 주소 형식이 아닙니다 (https://discord.com/api/webhooks/...)."
        try:
            self.post(url, {"content": str(text)[:MAX_LEN]})
            STATE.update(last_sent=int(self.clock()), sent=STATE.get("sent", 0) + 1)
            return True, "보냈습니다."
        except urllib.error.HTTPError as exc:
            return False, f"디스코드가 거절했습니다 (HTTP {exc.code}). 웹훅 주소를 확인하세요."
        except Exception as exc:
            return False, f"보내지 못했습니다: {str(exc)[:120]}"

    def ping_now(self, url):
        if not valid_hc(url):
            return False, "healthchecks.io 주소 형식이 아닙니다 (https://hc-ping.com/...)."
        try:
            self.post(url, None)
            STATE.update(last_ping=int(self.clock()), last_ping_error="")
            return True, "신호를 보냈습니다."
        except Exception as exc:
            return False, f"신호를 보내지 못했습니다: {str(exc)[:120]}"

    # ------------------------------------------------------------ worker
    def _put(self, item):
        self._ensure_thread()
        try:
            self.queue.put_nowait(item)
            return True
        except queue.Full:
            return False

    def _ensure_thread(self):
        if self.thread is not None and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, daemon=True, name="stock8-notifier")
        self.thread.start()

    def _run(self):
        while True:
            kind, url, text = self.queue.get()
            self.deliver(kind, url, text)

    def deliver(self, kind, url, text):
        for attempt in range(3):
            try:
                if kind == "discord":
                    self.post(url, {"content": text})
                    STATE.update(last_sent=int(self.clock()), sent=STATE.get("sent", 0) + 1)
                else:
                    self.post(url, None)
                    STATE.update(last_ping=int(self.clock()), last_ping_error="")
                return True
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 2:
                    time.sleep(2 + attempt * 3)
                    continue
                err = f"HTTP {exc.code}"
            except Exception as exc:
                err = str(exc)[:120]
                if attempt < 2:
                    time.sleep(1 + attempt)
                    continue
            if kind == "discord":
                STATE.update(last_error=err, last_error_at=int(self.clock()))
            else:
                STATE.update(last_ping_error=err)
            return False
        return False


def shared():
    """One notifier (one sender thread) per process."""
    inst = sys.__dict__.get("_stock8_notifier")
    if inst is None:
        inst = Notifier()
        sys.__dict__["_stock8_notifier"] = inst
    return inst


class NotifierModel:
    Notifier = Notifier
    shared = staticmethod(shared)
    valid_discord = staticmethod(valid_discord)
    valid_hc = staticmethod(valid_hc)
    mask = staticmethod(mask)
    STATE = STATE


Model = NotifierModel
