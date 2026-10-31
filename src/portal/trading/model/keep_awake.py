"""
Keep the LIVE PC awake only while trading needs it (10-31, user chose this).

Windows idle sleep suspended the LIVE server for hours (Kernel-Power 42,
reason 7): a KS day-trade stop ran 30 min late on 10-30, the coin stop
watch sold 1.7% below its stop, and the 10-29 US open was slept through.
This asks Windows for "system required" (SetThreadExecutionState, the same
request a video player makes) during:
- KS: weekdays 08:30-15:40 KST (day trading, 10:00 LOC reservations)
- US: weekdays 09:00-16:30 ET (MOC job, LOC fills, post-close fill sync)
- coin: while a coin is held or an order is pending (Upbit has no
  server-side stop), and from 2 min before to 20 min after each 4h decision
  bar while coin automation is ON.
It changes no Windows setting: closing the lid or choosing Sleep still
sleeps, and the request ends with the process.
Pure functions plus one Windows call, so it can be unit-tested anywhere.
"""

import datetime
import glob
import json
import os
import sys

KST = datetime.timezone(datetime.timedelta(hours=9))
KS_WINDOW = ((8, 30), (15, 40))
US_WINDOW_ET = ((9, 0), (16, 30))
COIN_BAR_SEC = 4 * 3600
COIN_BEFORE_SEC = 120
COIN_AFTER_SEC = 20 * 60

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

STATE = sys.__dict__.setdefault("_stock8_keep_awake", {"awake": False, "reason": "", "since": "", "error": ""})


def _nth_sunday(year, month, nth):
    day = datetime.date(year, month, 1)
    day += datetime.timedelta(days=(6 - day.weekday()) % 7)
    return day + datetime.timedelta(days=7 * (nth - 1))


def us_eastern(now_utc):
    """ET from UTC with the US rule (2nd Sunday of March 2:00 to 1st Sunday
    of November 2:00), so no tz database is needed on Windows."""
    year = now_utc.year
    start = datetime.datetime.combine(_nth_sunday(year, 3, 2), datetime.time(7), tzinfo=datetime.timezone.utc)
    end = datetime.datetime.combine(_nth_sunday(year, 11, 1), datetime.time(6), tzinfo=datetime.timezone.utc)
    offset = -4 if start <= now_utc < end else -5
    return now_utc.astimezone(datetime.timezone(datetime.timedelta(hours=offset)))


def _inside(local, window):
    (h0, m0), (h1, m1) = window
    minutes = local.hour * 60 + local.minute
    return local.weekday() < 5 and h0 * 60 + m0 <= minutes < h1 * 60 + m1


def needed(now_utc, coin_on=False, coin_held=False):
    """(bool, reason) for the given UTC-aware time."""
    if coin_held:
        return True, "코인 보유/주문 중"
    if _inside(now_utc.astimezone(KST), KS_WINDOW):
        return True, "국장 시간"
    if _inside(us_eastern(now_utc), US_WINDOW_ET):
        return True, "미장 시간"
    if coin_on:
        sec = int(now_utc.timestamp())
        into_bar = sec % COIN_BAR_SEC
        if into_bar < COIN_AFTER_SEC or COIN_BAR_SEC - into_bar <= COIN_BEFORE_SEC:
            return True, "코인 4시간봉 판단"
    return False, ""


def coin_held(coin_root):
    """Any sleeve long or with a pending order in the current ledgers
    (state_shadow/state_live/state_probe; archived copies are ignored)."""
    for path in glob.glob(os.path.join(coin_root, "*", "state_*.json")):
        if os.path.basename(path) not in ("state_shadow.json", "state_live.json", "state_probe.json"):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                sleeves = (json.load(handle) or {}).get("sleeves") or {}
        except (OSError, ValueError):
            continue
        if any((s or {}).get("long") or (s or {}).get("pending") for s in sleeves.values()):
            return True
    return False


def apply(awake, setter=None):
    """Must run on the one long-lived thread that owns the request:
    ES_CONTINUOUS state belongs to the calling thread."""
    if setter is None:
        if os.name != "nt":
            return False
        import ctypes
        setter = ctypes.windll.kernel32.SetThreadExecutionState
    flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if awake else 0)
    return bool(setter(flags))


class KeepAwake:
    needed = staticmethod(needed)
    coin_held = staticmethod(coin_held)
    apply = staticmethod(apply)
    us_eastern = staticmethod(us_eastern)
    STATE = STATE


Model = KeepAwake
