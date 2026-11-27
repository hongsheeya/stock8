"""Daily operations report (11-27): what each feature did today, and why.

The user believed everything was running while LIVE KS entries were blocked
all day, LIVE SOXL reservations had been held since 11-22, PAPER US orders
failed 41 times and the coin policy did not exist. This report puts each lane
(KS/US day trading, infinite buy, coin, PAPER US trend hold) of both accounts
on one page with one status and its reason.

Read-only by construction:
- SQLite is opened with `?mode=ro` and `PRAGMA query_only`, for the server's
  own mode as well as the other one (same files the trading ORM uses). The
  ORM is not used: its get_config() may write a user-scoped copy of a legacy
  key for an admin, and trade_verifier.Ledger.load() renames a corrupt file.
- Runtime JSON files are read in one call and closed before parsing
  (read_json_file). On Windows any open handle, even one shared for
  delete, makes an engine's atomic save (os.replace) fail with WinError 5,
  so the handle is held only for the read itself.
- No KIS, Upbit or FireGate call, no config write, no order path.

A read failure or a missing file is reported as "확인 불가", never as zero
or as normal. Pure Python (no wiz) so it is unit-tested with temp files.
"""
import contextlib
import datetime
import errno
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import sys
import threading

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - the runtime image has zoneinfo
    ZoneInfo = None

KST = datetime.timezone(datetime.timedelta(hours=9))
MODES = ("LIVE", "PAPER")
HISTORY_DAYS = 14

RUNNING, WAITING, BLOCKED, OFF, UNKNOWN = "running", "waiting", "blocked", "off", "unknown"
STATUS_LABELS = {RUNNING: "동작", WAITING: "대기", BLOCKED: "막힘", OFF: "꺼짐", UNKNOWN: "확인 불가"}
STATUS_ORDER = (BLOCKED, UNKNOWN, RUNNING, WAITING, OFF)
LANE_LABELS = {
    "daytrade_ks": "국내 단타", "daytrade_us": "미국 단타", "infinite_buy": "무한매수",
    "coin": "코인", "us_trend_hold": "미국 추세보유",
}

# A same-message *_ERROR this many times in a day is the day's block.
REPEATED_ERROR_MIN = 3
# "신규 진입 차단" this many times is a block even on a day with buys.
ENTRY_BLOCK_MIN = 3
ENTRY_BLOCK_PREFIX = "단타 신규 진입 차단"
ACCOUNT_HALT_MARKER = "계좌 주문을 거부"
RUNTIME_LOG_FILES = {"daytrade_ks": "runtime_logs_ks.json", "daytrade_us": "runtime_logs_us.json"}
# A worker or runtime log silent this long inside its active window is
# reported as 확인 불가 (the PAPER loop ticks every ~15 s, LIVE jobs every
# 15-30 s, the engines log a cycle about every 5 min).
WORKER_STALE_SEC = 15 * 60
MAX_LIST = 200
# One user's trade_log rows of one day (noise excluded). More than this and
# the mode is 확인 불가 instead of a silently cut list.
MAX_DAY_ROWS = 5000

# Keys the engines read with struct.get_config(): stored as user:<uid>:<key>,
# and an admin falls back to the legacy global key. A test checks this is a
# subset of struct.USER_SCOPED_CONFIG_KEYS.
USER_SCOPED_KEYS = frozenset({
    "daytrade_feature_enabled", "daytrade_auto_enabled", "daytrade_exit_watch_enabled",
    "daytrade_us_auto_enabled", "us_daytrade_auto_enabled",
    "daytrade_us_exit_watch_enabled", "us_daytrade_exit_watch_enabled",
    "broker_provider", "kis_live_account_no", "kis_paper_account_no",
    "kis_live_token_expires", "kis_paper_token_expires", "kis_paper_readiness_verified_at",
    "kis_paper_account_unavailable_at", "kis_paper_account_unavailable_reason",
    "kis_reservation_pending", "auto_trade_enabled", "loc_auto_schedule_enabled",
    "loc_reservation_verified_date", "loc_reservation_verified_complete",
    "loc_reservation_verified_failure_reason", "loc_reservation_rebuild_cooldown_until_ts",
    "loc_reservation_rebuild_cooldown_reason",
})

DT_EVENT_LABELS = {
    "BUY": "매수", "BUY1": "1차 매수", "BUY2": "2차 매수", "SELL_FULL": "전량 매도",
    "SELL_STOP_LOSS": "손절 매도", "PRE_SELL_JACKPOT": "목표가 매도", "SELL_DELEVERAGE": "노출 축소 매도",
    "SELL_MANUAL": "수동 매도", "SELL_MANUAL_NOW": "수동 매도", "SELL_PARTIAL": "분할 매도",
    "SELL_RESCUE": "구조 매도", "SELL_RECENT": "매도",
}
# Infinite buy: reservations the engine refused to place or verify.
IB_HARD_BLOCK_EVENTS = {
    "IB_LOC_BUY_FIREGATE_AUTHORITY_BLOCKED": "LOC 매수 예약 보류 (FireGate 권한 차단)",
    "IB_LOC_SELL_FIREGATE_AUTHORITY_BLOCKED": "LOC 매도 예약 보류 (FireGate 권한 차단)",
    "IB_FIREGATE_LINK_MISMATCH": "FireGate 연결 사이클 불일치",
}
IB_FILL_EVENTS = {"IB_BUY_FILLED": "BUY", "IB_SELL_FILLED": "SELL", "IB_PARTIAL_SELL_FILLED": "SELL"}
IB_ORDER_EVENTS = {
    "IB_LOC_BUY_SCHEDULED": "LOC 매수 예약", "IB_LOC_SELL_SCHEDULED": "LOC 매도 예약",
    "IB_LOC_BUY_ALREADY_SCHEDULED": "LOC 매수 예약 유지", "IB_LOC_SELL_ALREADY_SCHEDULED": "LOC 매도 예약 유지",
    "IB_PAPER_LOC_SUBMITTED": "모의 LOC 주문", "IB_DAILY_ORDER_SUBMITTED": "주문 제출",
    "IB_REVERSE_MOC_SUBMITTED": "리버스 MOC 주문", "IB_PENDING_EXTENSION": "미체결 연장",
}
IB_FILL_LABELS = {"IB_BUY_FILLED": "매수 체결", "IB_SELL_FILLED": "매도 체결", "IB_PARTIAL_SELL_FILLED": "분할매도 체결"}
COIN_FILL_EVENTS = {"COIN_BUY": "BUY", "COIN_SELL": "SELL", "COIN_EXTERNAL_SELL": "SELL",
                    "COIN_SHADOW_BUY": "BUY", "COIN_SHADOW_SELL": "SELL"}
COIN_STATE_EVENTS = ("COIN_HALT", "COIN_RESUME", "COIN_ORDER_CANCELLED")
USTH_EVENTS = ("USTH_FILL", "USTH_ORDER")
# trade_log events the report reads: day-trade rows, named fill/order/block
# events and *_ERROR rows. Run/skip noise (IB_LOC_AUTOMATION_RUN ...) is not
# read row by row (it only feeds the aggregated liveness query).
_NAMED_EVENTS = tuple(IB_FILL_EVENTS) + tuple(IB_ORDER_EVENTS) + tuple(IB_HARD_BLOCK_EVENTS) \
    + tuple(COIN_FILL_EVENTS) + COIN_STATE_EVENTS + USTH_EVENTS
_LOG_EVENT_SQL = ("(substr(event_type, 1, 3) = 'DT_' OR event_type IN (%s) "
                  "OR (substr(event_type, -6) = '_ERROR' AND substr(event_type, 1, 3) IN ('IB_', 'COI', 'UST')))"
                  % ",".join("?" for _ in _NAMED_EVENTS))
# Long message/raw_response are cut in SQL; only the JSON fields used are read.
_LOG_COLUMNS = ("id, symbol, event_type, action, order_no, order_price, order_qty, filled_price, filled_qty, created, "
                "substr(message, 1, 600) AS message, "
                "CASE WHEN json_valid(raw_response) THEN json_extract(raw_response, '$.repeat') END AS repeat, "
                "CASE WHEN json_valid(raw_response) THEN json_extract(raw_response, '$.last_at') END AS last_at, "
                "CASE WHEN json_valid(raw_response) THEN json_extract(raw_response, '$.runtime.realized') END AS rt_realized")
# Job names: PAPER worker_status.json result key, LIVE policy-worker job.
LANE_JOBS = {
    "daytrade_ks": (("auto_cycle", "entry_ks", "진입"), ("exit_watch", "exit_ks", "청산 감시")),
    "daytrade_us": (("us_auto_cycle", "entry_us", "진입"), ("us_exit_watch", "exit_us", "청산 감시")),
    "infinite_buy": (("loc_automation", "loc", "LOC 예약"), ("external_cycle_sync", "sync", "체결 동기화"),
                     ("firegate_sync", "", "FireGate 동기화")),
}
PAPER_RESULT_KEYS = frozenset({"auto_cycle", "exit_watch", "us_auto_cycle", "us_exit_watch", "loc_automation",
                               "firegate_sync", "external_cycle_sync", "maintenance"})
ACTIVE_CYCLE_STATUSES = ("ACTIVE", "HOLDING", "PENDING_EXTENSION")
US_EXCHANGES = ("US", "NAS", "NASD", "NYS", "NYSE", "AMS", "AMEX")
WEEKDAYS = "월화수목금토일"
# Past days: struct._trim_trade_logs keeps only the first and last row of a
# repeated error/noise line, and deletes *MISMATCH* rows after 14 days
# (3 days when the log is large).
TRIM_NOTE = ("지난 날짜는 로그 정리로 같은 오류의 처음·마지막 기록만 남아 횟수가 실제보다 적을 수 있고, "
             "FireGate 연결 불일치(MISMATCH) 기록은 14일(기록이 많으면 3일)이 지나면 지워집니다")


class Unavailable(Exception):
    """A source could not be read; shown as 확인 불가 with this message."""


# --------------------------------------------------------------- small helpers
def _int(value, default=0):
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return default


def _float(value, default=None):
    try:
        text = str(value if value is not None else "").replace(",", "").strip()
        return float(text) if text != "" else default
    except (TypeError, ValueError):
        return default


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "y", "on")


def _json(value):
    try:
        data = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _json_object(raw):
    """(dict, ok) of a stored JSON object; ok is False when it is damaged."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}, False
    return (data, True) if isinstance(data, dict) else ({}, False)


def _parse_ts(value):
    text = str(value or "").strip().replace("T", " ")
    if not text:
        return None
    if re.fullmatch(r"\d{9,11}(?:\.\d+)?", text):  # epoch seconds (token expiry)
        try:
            return datetime.datetime.fromtimestamp(float(text), KST).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    for fmt, size in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.datetime.strptime(text[:size], fmt)
        except ValueError:
            continue
    return None


def _hhmm(value):
    ts = _parse_ts(value)
    return ts.strftime("%H:%M") if ts else ""


def _hhmmss(value):
    ts = _parse_ts(value)
    return ts.strftime("%H:%M:%S") if ts else ""


def _stamp(ts, now):
    return ts.strftime("%H:%M") if ts.date() == now.date() else ts.strftime("%m-%d %H:%M")


def _mmdd(day):
    return f"{day.month}/{day.day}"


def _day_label(day):
    return f"{_mmdd(day)}({WEEKDAYS[day.weekday()]})"


_PARAM_GROUP = re.compile(r"\s*\((?=[^)]*(?:rt_cd|CANO|ACNT_PRDT_CD|tr_id|ord_dvsn|is_real|exchange=|qty=|price=))[^)]*\)")
_PARAM_TAIL = re.compile(r"\s*\((?:rt_cd|CANO|ACNT_PRDT_CD|tr_id|exchange=)[^)]*$")
# kis_api account errors quote the raw account: "(원본: '...', CANO: ...)".
_RAW_ACCOUNT = re.compile(r"\s*\(원본:.*?(?:\)|$)")


def clean_message(text):
    """The message users see and errors are grouped by: request parameters
    (rt_cd, qty=, price=...), raw-account quotes and countdowns removed, and
    long digit runs (account, order and portfolio numbers) masked."""
    text = str(text or "").strip()
    text = _RAW_ACCOUNT.sub("", text)
    text = _PARAM_GROUP.sub("", text)
    text = _PARAM_TAIL.sub("", text)
    text = re.sub(r"\s*\|\s*symbol=.*$", "", text)
    text = re.sub(r"\(\d+초\)", "(…초)", text)
    text = re.sub(r"\d{8,}", "****", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:240]


def _money_after(text, label):
    match = re.search(rf"{label}\s*[:=]?\s*[$₩]?\s*([+-]?[0-9][0-9,]*(?:\.[0-9]+)?)", str(text or ""))
    return _float(match.group(1)) if match else None


def account_scope(provider, account):
    """struct.live_data_scope: per-account folder of LIVE day-trade files."""
    return hashlib.sha256((str(provider) + ":" + str(account or "")).encode()).hexdigest()[:24]


def policy_key(provider, account):
    """order_policy.Policy._key() for this account, or "" without one."""
    account = str(account or "").strip()
    if not account:
        return ""
    return "order_policy_v1:" + hashlib.sha256((str(provider) + ":" + account).encode()).hexdigest()[:40]


def verification_scope(kis_account):
    """struct._trade_verification_path(): ledger file name of a KIS account."""
    account = str(kis_account or "").strip()
    if not account:
        return ""
    return hashlib.sha256(("kis:" + account).encode()).hexdigest()[:24]


def coin_owner_scope(owner):
    """coin_engine.owner_scope: per-owner folder of the coin ledger."""
    return hashlib.sha256(str(owner or "").encode("utf-8")).hexdigest()[:16]


def mode_db_path(server_root, mode):
    """Same resolution as dbbase trading_database_path / paper_subscription."""
    mode = str(mode).upper()
    rel = os.environ.get("STOCK8_" + mode + "_DB_PATH", "project/main/data/" + mode.lower() + "/trading.db")
    return os.path.realpath(os.path.join(str(server_root), rel))


# --------------------------------------------------------------- file reading
_WIN = {}


def _win_api():
    if "api" not in _WIN:
        try:
            import ctypes
            import msvcrt
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # private copy: argtypes stay local
            create = kernel32.CreateFileW
            create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                               wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            create.restype = wintypes.HANDLE
            close = kernel32.CloseHandle
            close.argtypes = [wintypes.HANDLE]
            close.restype = wintypes.BOOL
            _WIN["api"] = (ctypes, msvcrt, create, close)
        except Exception:
            _WIN["api"] = None
    return _WIN["api"]


def open_shared(path):
    """Windows: a read-only fd opened with FILE_SHARE_READ|WRITE|DELETE, so
    the report never blocks another process from writing or deleting the
    file. None when the Win32 call is unavailable (other OS)."""
    if os.name != "nt":
        return None
    api = _win_api()
    if api is None:
        return None
    ctypes, msvcrt, create, close = api
    handle = create(str(path), 0x80000000, 0x1 | 0x2 | 0x4, None, 3, 0x80, None)  # GENERIC_READ, OPEN_EXISTING
    if not handle or handle == ctypes.c_void_p(-1).value:
        code = ctypes.get_last_error()
        if code in (2, 3):
            raise FileNotFoundError(errno.ENOENT, "file not found")
        raise OSError(errno.EACCES, f"CreateFileW failed ({code})")
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except Exception:
        close(handle)
        raise


def _read_bytes(path):
    """All bytes in one call; the handle is closed before anything is parsed."""
    try:
        fd = open_shared(path)
    except FileNotFoundError:
        raise
    except OSError:
        fd = None  # fall back to a plain read below
    if fd is not None:
        with os.fdopen(fd, "rb") as handle:
            return handle.read()
    with open(path, "rb") as handle:
        return handle.read()


def _decode_json(raw):
    return json.loads(raw.decode("utf-8-sig"))


def _ledger_lock(path):
    """The trade_verifier lock of this ledger when the verifier lives in this
    process, so a save there never meets this read (other processes can only
    be helped by the short read)."""
    locks = sys.__dict__.get("_stock8_trade_verifier_locks")
    guard = sys.__dict__.get("_stock8_trade_verifier_guard")
    if not isinstance(locks, dict) or guard is None:
        return None
    with guard:
        return locks.setdefault(os.path.abspath(path), threading.RLock())


def read_json_file(path, lock=None):
    """(data, state): state is ok | missing | error. Never creates, moves or
    locks a file; a missing file is not 'empty'."""
    if not path:
        return None, "missing"
    held = lock.acquire(timeout=2) if lock is not None else False
    try:
        raw = _read_bytes(path)
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "error"
    finally:
        if held:
            lock.release()
    try:
        return _decode_json(raw), "ok"
    except ValueError:
        return None, "error"


def date_options(today, days=HISTORY_DAYS):
    return [(today - datetime.timedelta(days=i)).isoformat() for i in range(days)]


def parse_day(value, today):
    """The report date: today (KST) by default, else one of the last 14 days."""
    text = str(value or "").strip()
    if not text:
        return today
    try:
        day = datetime.date.fromisoformat(text[:10])
    except ValueError:
        raise ValueError("날짜 형식이 올바르지 않습니다 (YYYY-MM-DD).")
    if day > today or (today - day).days >= HISTORY_DAYS:
        raise ValueError(f"최근 {HISTORY_DAYS}일 안의 날짜만 볼 수 있습니다.")
    return day


# ------------------------------------------------------------- market calendar
def _us_dst(et_day):
    if ZoneInfo is not None:
        try:
            noon = datetime.datetime(et_day.year, et_day.month, et_day.day, 12, tzinfo=ZoneInfo("America/New_York"))
            return bool(noon.dst())
        except Exception:
            pass
    march = datetime.date(et_day.year, 3, 1)
    start = march + datetime.timedelta(days=(6 - march.weekday()) % 7 + 7)
    november = datetime.date(et_day.year, 11, 1)
    end = november + datetime.timedelta(days=(6 - november.weekday()) % 7)
    return start <= et_day < end


def _et_to_kst(et_day, hhmm):
    hour, minute = (int(x) for x in hhmm.split(":"))
    offset = 13 if _us_dst(et_day) else 14
    return datetime.datetime(et_day.year, et_day.month, et_day.day, hour, minute) + datetime.timedelta(hours=offset)


def _kst_to_et(now):
    if ZoneInfo is not None:
        try:
            return now.replace(tzinfo=ZoneInfo("Asia/Seoul")).astimezone(ZoneInfo("America/New_York")).replace(tzinfo=None)
        except Exception:
            pass
    guess = now - datetime.timedelta(hours=14)
    return now - datetime.timedelta(hours=13 if _us_dst(guess.date()) else 14)


def _at(day, hour, minute=0):
    return datetime.datetime(day.year, day.month, day.day, hour, minute)


class Calendar:
    """KRX/US trading days from domestic_market.KRX_HOLIDAYS and
    KisApi.US_MARKET_HOLIDAYS / US_EARLY_CLOSES (passed in by the caller)."""

    def __init__(self, krx_holidays=(), us_holidays=None, us_early_closes=None):
        self.krx_holidays = set(krx_holidays or ())
        self.us_holidays = dict(us_holidays or {})
        self.us_early_closes = dict(us_early_closes or {})

    def krx_closed_reason(self, day):
        if day.weekday() >= 5:
            return "주말"
        if day.isoformat() in self.krx_holidays:
            return "KRX 휴장일"
        return ""

    def us_closed_reason(self, et_day):
        if et_day.weekday() >= 5:
            return "주말"
        name = self.us_holidays.get(et_day.isoformat(), "")
        return f"미국 휴장일 ({name})" if name else ""

    def us_close(self, et_day):
        text = str(self.us_early_closes.get(et_day.isoformat(), "") or "")
        return text if re.fullmatch(r"1[0-5]:[0-5]\d", text) else "16:00"

    def krx_day(self, day):
        reason = self.krx_closed_reason(day)
        entry = {"date": day.isoformat(), "label": _day_label(day), "open": not reason, "reason": reason}
        if not reason:
            entry.update(hours="09:00~15:30 KST", nxt="NXT 08:00~20:00")
        return entry

    def us_day(self, et_day):
        reason = self.us_closed_reason(et_day)
        entry = {"date": et_day.isoformat(), "label": _day_label(et_day), "open": not reason, "reason": reason}
        if not reason:
            close = self.us_close(et_day)
            start, end, pre = _et_to_kst(et_day, "09:30"), _et_to_kst(et_day, close), _et_to_kst(et_day, "04:00")
            entry.update(
                hours_et=f"09:30~{close} ET", early_close=close != "16:00",
                hours_kst=f"{_mmdd(start.date())} {start:%H:%M} ~ {_mmdd(end.date())} {end:%H:%M} KST",
                premarket_kst=f"프리마켓 {_mmdd(pre.date())} {pre:%H:%M} KST부터",
                dst=_us_dst(et_day))
        return entry

    def next_krx_day(self, day):
        for i in range(1, 15):
            nxt = day + datetime.timedelta(days=i)
            if not self.krx_closed_reason(nxt):
                return nxt
        return None

    def next_us_day(self, et_day):
        for i in range(1, 15):
            nxt = et_day + datetime.timedelta(days=i)
            if not self.us_closed_reason(nxt):
                return nxt
        return None

    def schedule(self, day):
        """KRX: the day and the next trading day. US: the ET session that
        ends on the KST morning (day-1), the one that opens that night (day)
        and the next trading day after it."""
        krx = [self.krx_day(day)]
        nxt = self.next_krx_day(day)
        if nxt:
            krx.append({**self.krx_day(nxt), "next": True})
        us = [self.us_day(day - datetime.timedelta(days=1)), self.us_day(day)]
        nxt = self.next_us_day(day)
        if nxt:
            us.append({**self.us_day(nxt), "next": True})
        return {"krx": krx, "us": us}

    def _us_session(self, et_day):
        """KST (start, end) of one ET day's premarket-to-close, or None."""
        if self.us_closed_reason(et_day):
            return None
        return _et_to_kst(et_day, "04:00"), _et_to_kst(et_day, self.us_close(et_day))

    def active_window(self, lane_name, now):
        """KST (start, end) of the lane's window that contains `now`, or None:
        KRX 09:00-15:30, US premarket to close, LOC reservations 10:00 to
        23:20 (22:20 in US summer time) on a US trading day."""
        day = now.date()
        window = None
        if lane_name == "daytrade_ks":
            if not self.krx_closed_reason(day):
                window = (_at(day, 9), _at(day, 15, 30))
        elif lane_name in ("daytrade_us", "us_trend_hold"):
            for et_day in (day - datetime.timedelta(days=1), day):
                session = self._us_session(et_day)
                if session and session[0] <= now < session[1]:
                    window = session
        elif lane_name == "infinite_buy":
            if not self.us_closed_reason(day):
                window = (_at(day, 10), _at(day, 22, 20) if _us_dst(day) else _at(day, 23, 20))
        if window and window[0] <= now < window[1]:
            return window
        return None

    def log_expected_since(self, lane_name, now):
        """From when a day-trade runtime log should have entries today."""
        day = now.date()
        if lane_name == "daytrade_ks":
            return None if self.krx_closed_reason(day) else _at(day, 9)
        prev = self._us_session(day - datetime.timedelta(days=1))
        if prev and prev[1] > _at(day, 0):
            return _at(day, 0)
        today = self._us_session(day)
        return today[0] if today else None

    def ks_waiting_reason(self, day, now, is_today):
        closed = self.krx_closed_reason(day)
        if closed:
            return f"휴장 ({closed})"
        if not is_today:
            return "체결 없음 (진입 신호 없음)"
        hhmm = now.hour * 100 + now.minute
        if hhmm < 900:
            return "장 시작 전"
        if hhmm < 1530:
            return "장중 · 진입 신호 대기"
        return "장 마감 · 체결 없음 (진입 신호 없음)"

    def us_closed_all_day(self, day):
        """Neither US session touching this KST day trades (ET day-1 and day)."""
        a = self.us_closed_reason(day - datetime.timedelta(days=1))
        b = self.us_closed_reason(day)
        return (b or a) if (a and b) else ""

    def us_waiting_reason(self, day, now, is_today):
        closed = self.us_closed_all_day(day)
        if closed:
            return f"휴장 ({closed})"
        if not is_today:
            return "체결 없음 (진입 신호 없음)"
        et = _kst_to_et(now)
        reason = self.us_closed_reason(et.date())
        if reason:
            return f"장외 · {reason}"
        minutes = et.hour * 60 + et.minute
        close_h, close_m = (int(x) for x in self.us_close(et.date()).split(":"))
        if minutes < 4 * 60:
            return "장외 · 프리마켓 시작 전"
        if minutes < 9 * 60 + 30:
            return "프리마켓 · 진입 신호 대기"
        if minutes < close_h * 60 + close_m:
            return "장중 · 진입 신호 대기"
        return "장 마감 · 체결 없음 (진입 신호 없음)"


# ------------------------------------------------------------------ DB access
def _db_error(exc):
    """A message without server paths: sqlite's own text, else the type only."""
    if isinstance(exc, sqlite3.Error):
        return f"{type(exc).__name__}: {str(exc)[:80]}"
    return type(exc).__name__


class ModeDb:
    """One mode's trading.db, read-only, scoped to one user.

    Rows: user_id = uid, plus legacy '' rows for an admin (_UserScopedDb).
    Config: user:<uid>:<key> for user-scoped keys, admin falls back to the
    legacy global key (struct.get_config)."""

    def __init__(self, path, uid, is_admin, decrypt=None):
        self.path = path
        self.uid = str(uid or "").strip()
        self.is_admin = bool(is_admin)
        self.decrypt = decrypt or (lambda value: value)
        self.conn = None

    def open(self):
        if not self.path or not os.path.exists(self.path):
            raise Unavailable("DB 파일이 없습니다")
        try:
            uri = pathlib.Path(self.path).resolve().as_uri() + "?mode=ro"
            self.conn = sqlite3.connect(uri, uri=True, timeout=3)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA query_only = ON")
            self.conn.execute("SELECT 1 FROM trading_config LIMIT 1").fetchall()
        except Exception as exc:
            self.close()
            raise Unavailable(f"DB를 읽지 못했습니다 ({_db_error(exc)})")
        return self

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
        self.conn = None

    def query(self, sql, params=()):
        try:
            return [dict(row) for row in self.conn.execute(sql, tuple(params)).fetchall()]
        except Exception as exc:
            raise Unavailable(f"DB 조회 실패 ({_db_error(exc)})")

    def _raw(self, key):
        rows = self.query("SELECT value FROM trading_config WHERE key = ? LIMIT 1", (key,))
        return rows[0]["value"] if rows else None

    def value(self, key):
        """(value, readable) of one stored key; readable is False when an
        encrypted value could not be decrypted."""
        raw = self._raw(key)
        if raw is None:
            return None, True
        text = str(raw)
        if text.startswith("enc:v1:"):
            plain = self.decrypt(text)
            return (plain if plain else None), bool(plain)
        return text, True

    def cfg(self, key, default=None):
        value, _readable = self.cfg_checked(key)
        return default if value is None else value

    def cfg_checked(self, key):
        if key in USER_SCOPED_KEYS:
            if not self.uid:
                return None, True
            value, readable = self.value(f"user:{self.uid}:{key}")
            if value is not None or not readable:
                return value, readable
            if self._raw(f"user:{self.uid}:{key}") is None and self.is_admin:
                return self.value(key)
            return None, True
        return self.value(key)

    def scoped_users(self):
        return [self.uid, ""] if self.is_admin else [self.uid]

    def scoped_rows(self, table, where, params=(), columns="*", order="created", limit=None):
        limit = MAX_DAY_ROWS if limit is None else limit
        users = self.scoped_users()
        marks = ",".join("?" for _ in users)
        sql = f'SELECT {columns} FROM "{table}" WHERE user_id IN ({marks})'
        if where:
            sql += f" AND ({where})"
        if order:
            sql += f" ORDER BY {order}"
        rows = self.query(sql + f" LIMIT {int(limit) + 1}", list(users) + list(params))
        if len(rows) > limit:
            raise Unavailable(f"하루 기록이 {limit}건을 넘어 모두 읽지 못했습니다 (기록 과다)")
        return rows


# --------------------------------------------------------------- mode facts
def _day_bounds(day):
    start = day.isoformat()
    end = (day + datetime.timedelta(days=1)).isoformat()
    return start, end


def _switch(db, key, default="false"):
    return str(db.cfg(key, default) or default).strip().lower() == "true"


def _us_auto_switch(db):
    modern = str(db.cfg("daytrade_us_auto_enabled", "") or "").strip().lower()
    legacy = str(db.cfg("us_daytrade_auto_enabled", "") or "").strip().lower()
    if modern in ("true", "false"):
        return modern == "true"
    if legacy in ("true", "false"):
        return legacy == "true"
    return False


def _us_exit_switch(db):
    modern = str(db.cfg("daytrade_us_exit_watch_enabled", "") or "").strip().lower()
    legacy = str(db.cfg("us_daytrade_exit_watch_enabled", "") or "").strip().lower()
    if modern in ("true", "false"):
        return modern == "true"
    return legacy == "true"


def collect_mode(mode, db_path, data_dir, uid, is_admin, day, decrypt=None, hard_locked=False):
    """Everything the report needs from one mode, read once."""
    facts = {"mode": mode, "ok": False, "error": "", "account": {}, "switches": {}, "policy": None,
             "policy_error": "", "foreign": False, "logs": [], "cycles": [], "runtime": {}, "state": None,
             "state_status": "", "verification": None, "old_ledgers": [], "worker": None, "coin": None,
             "usth": None, "paper_unavailable": None, "connection": {}, "ib_block_days": [], "worker_note": "",
             "hard_locked": bool(hard_locked), "dt_root": ""}
    db = ModeDb(db_path, uid, is_admin, decrypt)
    try:
        db.open()
    except Unavailable as exc:
        facts["error"] = str(exc)
        return facts
    try:
        _collect_db(facts, db, mode, data_dir, uid, is_admin, day)
        facts["ok"] = True
    except Unavailable as exc:
        facts["error"] = str(exc)
        facts["ok"] = False
    finally:
        db.close()
    return facts


def _collect_db(facts, db, mode, data_dir, uid, is_admin, day):
    live = mode == "LIVE"
    provider = "kis"
    if live:
        provider = str(db.cfg("broker_provider", "kis") or "kis").strip().lower()
        if provider not in ("kis", "toss"):
            provider = "kis"
    account_key = "kis_live_account_no" if live else "kis_paper_account_no"
    kis_account, readable = db.cfg_checked(account_key)
    kis_account = str(kis_account or "")
    broker_account = kis_account if provider == "kis" else ""  # TossApi has no account_no
    # An encrypted account that does not decrypt is configured but unknown.
    account = {"provider": provider, "configured": bool(kis_account.strip()) or not readable, "readable": readable,
               "scope": "", "policy_key": "", "verification_scope": ""}
    if readable and (kis_account.strip() or provider != "kis"):
        account["scope"] = account_scope(provider, broker_account)
        account["policy_key"] = policy_key(provider, broker_account)
    if readable and kis_account.strip():
        account["verification_scope"] = verification_scope(kis_account)
    facts["account"] = account

    sw = {
        "daytrade_feature": live is False or _truthy(db.cfg("daytrade_feature_enabled", "false")),
        "daytrade_ks": _switch(db, "daytrade_auto_enabled"),
        "daytrade_ks_exit": _switch(db, "daytrade_exit_watch_enabled"),
        "daytrade_us": _us_auto_switch(db),
        "daytrade_us_exit": _us_exit_switch(db),
        "auto_trade": _switch(db, "auto_trade_enabled"),
        "loc_schedule": _switch(db, "loc_auto_schedule_enabled", "true"),
    }
    facts["switches"] = sw

    if account["policy_key"]:
        raw = db._raw(account["policy_key"])
        if raw is not None:
            policy, ok = _json_object(raw)
            owner = str(policy.get("owner_user_id", "") or "") if ok else ""
            if ok and owner and owner != uid:
                # The broker account's policy belongs to another user: its
                # lanes, files, worker state and ledger are not this user's.
                facts["foreign"] = True
            elif not ok or not isinstance(policy.get("symbols"), dict):
                facts["policy_error"] = "주문 권한 데이터 오류: 엔진이 이 계좌의 주문을 차단합니다."
            else:
                facts["policy"] = {lane: policy.get(lane) is True for lane in ("infinite_buy", "daytrade_ks", "daytrade_us")}
        else:
            facts["policy"] = {"infinite_buy": False, "daytrade_ks": False, "daytrade_us": False, "missing": True}

    start, end = _day_bounds(day)
    facts["logs"] = db.scoped_rows("trade_log", f"created >= ? AND created < ? AND {_LOG_EVENT_SQL}",
                                   [start, end] + list(_NAMED_EVENTS), columns=_LOG_COLUMNS)
    # No IB heartbeat from trade_log: IB_LOC_AUTOMATION_RUN is written only
    # when a day's reservations are first attempted, verified or forced; a
    # healthy day's later passes end as "already scheduled" without a row.
    facts["cycles"] = db.scoped_rows(
        "trading_cycle", "status IN ('ACTIVE', 'HOLDING', 'PENDING_EXTENSION')", (),
        columns="symbol, status, cycle_number, current_round, division_count, total_qty, avg_price, updated",
        order="symbol")
    since = (day - datetime.timedelta(days=HISTORY_DAYS - 1)).isoformat()
    marks = ",".join("?" for _ in IB_HARD_BLOCK_EVENTS)
    facts["ib_block_days"] = [row["d"] for row in db.scoped_rows(
        "trade_log", f"created >= ? AND created < ? AND event_type IN ({marks})", [since, end] + list(IB_HARD_BLOCK_EVENTS),
        columns="DISTINCT substr(created, 1, 10) AS d", order="d")]

    ib = {"reservation_pending": str(db.cfg("kis_reservation_pending", "") or "").strip(),
          "verified_date": str(db.cfg("loc_reservation_verified_date", "") or ""),
          "verified_complete": _truthy(db.cfg("loc_reservation_verified_complete", "")),
          "failure_reason": str(db.cfg("loc_reservation_verified_failure_reason", "") or ""),
          "cooldown_until": _float(db.cfg("loc_reservation_rebuild_cooldown_until_ts", ""), 0.0) or 0.0,
          "cooldown_reason": str(db.cfg("loc_reservation_rebuild_cooldown_reason", "") or "")}
    facts["ib"] = ib

    prefix = "kis_live" if live else "kis_paper"
    facts["connection"] = {"token_expires": str(db.cfg(prefix + "_token_expires", "") or ""),
                           "readiness_verified_at": "" if live else str(db.cfg("kis_paper_readiness_verified_at", "") or "")}
    if not live:
        since_text = str(db.cfg("kis_paper_account_unavailable_at", "") or "").strip()
        facts["paper_unavailable"] = ({"since": since_text,
                                       "reason": clean_message(db.cfg("kis_paper_account_unavailable_reason", ""))[:200]}
                                      if since_text else {})

    data_root = os.path.join(str(data_dir), mode.lower())
    if not facts["foreign"]:
        # Day-trade files: LIVE per account, PAPER one shared folder that only
        # admins may read (daytrade_engine._daytrade_state_visible).
        dt_root = ""
        if is_admin and not facts["hard_locked"]:
            if live and account["scope"]:
                dt_root = os.path.join(data_root, "daytrade", account["scope"])
            elif not live:
                dt_root = os.path.join(data_root, "daytrade")
        facts["dt_root"] = dt_root
        if dt_root:
            for lane, name in RUNTIME_LOG_FILES.items():
                data, status = read_json_file(os.path.join(dt_root, name))
                if status == "ok" and not isinstance(data, list):
                    data, status = None, "error"
                facts["runtime"][lane] = {"entries": data or [], "status": status}
            state, status = read_json_file(os.path.join(dt_root, "live_state.json"))
            if status == "ok" and not isinstance(state, dict):
                state, status = None, "error"
            facts["state"], facts["state_status"] = state, status

        if account["verification_scope"]:
            facts["verification"] = _read_verification(
                os.path.join(data_root, "trade_verification", account["verification_scope"] + ".json"))
    # Ledgers of this user's earlier accounts (order policies they own).
    for row in db.query("SELECT key, value FROM trading_config WHERE key LIKE 'order_policy_v1:%'"):
        policy, ok = _json_object(row["value"])
        scope = str(row["key"]).split(":", 1)[1][:24]
        if not ok or str(policy.get("owner_user_id", "") or "") != uid:
            continue
        if not re.fullmatch(r"[0-9a-f]{24}", scope) or scope == account["verification_scope"]:
            continue
        ledger = _read_verification(os.path.join(data_root, "trade_verification", scope + ".json"))
        if ledger.get("status") == "ok":
            facts["old_ledgers"].append(ledger)

    if not live:
        # One shared file that every PAPER owner's worker overwrites: only a
        # snapshot stamped with this user as owner describes this user's
        # worker. Anything else is a note, never a status (it could turn
        # someone else's error into 막힘, or hide a stopped worker as 대기).
        data, status = read_json_file(os.path.join(data_root, "daytrade", "worker_status.json"))
        owner = str(data.get("owner_user_id", "") or "") if isinstance(data, dict) else ""
        if status == "ok" and isinstance(data, dict) and owner == uid:
            facts["worker"] = {"status": "ok", "data": data}
        elif status == "missing":
            facts["worker_note"] = "워커 상태 확인 불가 (worker_status.json 없음)"
        elif status != "ok" or not isinstance(data, dict):
            facts["worker_note"] = "워커 상태 확인 불가 (worker_status.json 읽기 실패)"
        elif owner:
            facts["worker_note"] = "워커 상태 확인 불가 (다른 사용자 워커 기록)"
        else:
            facts["worker_note"] = "워커 상태 확인 불가 (소유자 표시가 없는 예전 워커 기록 — 다른 사용자 것일 수 있음)"

    if live:
        raw = db._raw("coin_policy_v1")
        policy, ok = _json_object(raw) if raw is not None else ({}, True)
        coin = {"exists": raw is not None, "corrupt": not ok, "policy": policy, "ledger": None, "ledger_status": ""}
        mode_name = str(policy.get("mode", "off") or "off").lower()
        owner = str(policy.get("owner_user_id", "") or "")
        if ok and mode_name in ("shadow", "live") and owner == uid:
            ledger, status = read_json_file(os.path.join(data_root, "coin", coin_owner_scope(owner), f"state_{mode_name}.json"))
            coin["ledger"], coin["ledger_status"] = (ledger if isinstance(ledger, dict) else None), status
        facts["coin"] = coin
    else:
        raw = db._raw("us_trend_hold_policy_v1")
        policy, ok = _json_object(raw) if raw is not None else ({}, True)
        usth = {"enabled": policy.get("enabled") is True, "owner": str(policy.get("owner_user_id", "") or ""),
                "corrupt": not ok, "ledger": None, "ledger_status": ""}
        if usth["enabled"] and usth["owner"] == uid:
            ledger, status = read_json_file(os.path.join(data_root, "us_trend_hold", "state.json"))
            usth["ledger"], usth["ledger_status"] = (ledger if isinstance(ledger, dict) else None), status
        facts["usth"] = usth


def _read_verification(path):
    """Per-account trade_verifier ledger, read directly (Ledger.load would
    rename a corrupt file). Holds as on the dashboard: one per symbol with
    an unacknowledged FAIL/UNCONFIRMED record."""
    data, status = read_json_file(path, lock=_ledger_lock(path))
    result = {"status": status, "file": os.path.basename(path)}
    if status != "ok" or not isinstance(data, dict) or not isinstance(data.get("records"), list):
        if status == "ok":
            result["status"] = "error"
        return result
    records = data["records"]
    holds = {}
    counts = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        counts[record.get("status")] = counts.get(record.get("status"), 0) + 1
        if record.get("status") in ("FAIL", "UNCONFIRMED") and not record.get("acknowledged"):
            holds.setdefault(record.get("symbol"), {
                "symbol": record.get("symbol"), "market": record.get("market"), "at": record.get("at"),
                "reason": clean_message(record.get("reason"))[:160], "status": record.get("status"), "records": 0})
            holds[record.get("symbol")]["records"] += 1
    result.update(holds=sorted(holds.values(), key=lambda h: str(h.get("at") or ""), reverse=True),
                  hold_records=sum(h["records"] for h in holds.values()),
                  counts=counts, total=len(records), last_run=str((data.get("last_run") or {}).get("at", "") or ""))
    return result


# ------------------------------------------------------------ log analysis
def _repeat(row):
    """(count, last_at) of a row; IB repeats are compressed into one row."""
    if "repeat" in row or "last_at" in row:
        count, last_at = row.get("repeat"), row.get("last_at")
    else:
        raw = _json(row.get("raw_response"))
        count, last_at = raw.get("repeat"), raw.get("last_at")
    return (max(1, _int(count, 1)) if count is not None else 1), str(last_at or "")


def group_errors(rows, source="거래 기록", past=False):
    """*_ERROR rows grouped by message: count (repeats included), first, last.

    past: a finished day may have been trimmed to the first and last row of
    each repeated line (same event, symbol and message before " | "); its
    counts are minimums, and a line left with exactly two rows is treated as
    repeated."""
    groups = {}
    for row in rows:
        message = clean_message(row.get("message")) or str(row.get("event_type", ""))
        count, last_at = _repeat(row)
        created = str(row.get("created", "") or "")
        group = groups.setdefault(message, {"message": message, "count": 0, "first": created, "last": created,
                                            "events": set(), "symbols": set(), "source": source, "level": "error",
                                            "count_is_min": bool(past), "maybe_trimmed": False, "_lines": {}})
        group["count"] += count
        group["first"] = min(group["first"], created)
        group["last"] = max(group["last"], created, last_at or created)
        group["events"].add(str(row.get("event_type", "")))
        if row.get("symbol"):
            group["symbols"].add(str(row.get("symbol")))
        line = (str(row.get("event_type", "")), str(row.get("symbol") or ""), str(row.get("message") or "").split(" | ")[0])
        group["_lines"][line] = group["_lines"].get(line, 0) + 1
    for group in groups.values():
        lines = group.pop("_lines")
        group["maybe_trimmed"] = bool(past) and any(n == 2 for n in lines.values())
    return _finish_groups(groups)


def _finish_groups(groups):
    result = []
    for group in groups.values():
        group["events"] = sorted(group["events"])
        group["symbols"] = sorted(group["symbols"])
        group["first_hhmm"], group["last_hhmm"] = _hhmm(group["first"]), _hhmm(group["last"])
        group.setdefault("count_is_min", False)
        group.setdefault("maybe_trimmed", False)
        result.append(group)
    result.sort(key=lambda g: (-g["count"], g["first"]))
    return result


def group_text(group):
    span = group["first_hhmm"] if group["first_hhmm"] == group["last_hhmm"] else f"{group['first_hhmm']}~{group['last_hhmm']}"
    count = f"최소 {group['count']}회" if group.get("count_is_min") else f"×{group['count']}"
    return f"{group['message']} {count} ({span})"


def runtime_window(entries, day):
    """How the runtime log covers the day: full | partial | rotated | idle | empty.

    The engine keeps the last 300 entries, so a busy log starts mid-day and
    a past date is usually rotated out."""
    stamps = [ts for ts in (_parse_ts((e or {}).get("timestamp")) for e in entries or []) if ts]
    if not stamps:
        return "empty", ""
    start = datetime.datetime.combine(day, datetime.time.min)
    end = start + datetime.timedelta(days=1)
    first, last = min(stamps), max(stamps)
    if first >= end:
        return "rotated", first.strftime("%m-%d %H:%M")
    if last < start:
        return "idle", last.strftime("%m-%d %H:%M")
    if first > start:
        return "partial", first.strftime("%H:%M")
    return "full", ""


def runtime_last(entries):
    stamps = [ts for ts in (_parse_ts((e or {}).get("timestamp")) for e in entries or [] if isinstance(e, dict)) if ts]
    return max(stamps) if stamps else None


def runtime_problems(entries, day):
    """Warnings/errors of the day grouped by message."""
    groups = {}
    prefix = day.isoformat()
    for entry in entries or []:
        if not isinstance(entry, dict) or not str(entry.get("timestamp", "")).startswith(prefix):
            continue
        level = str(entry.get("level", "") or "").lower()
        if level not in ("warning", "error"):
            continue
        message = clean_message(entry.get("message"))
        stamp = str(entry.get("timestamp"))
        group = groups.setdefault((level, message), {"message": message, "count": 0, "first": stamp, "last": stamp,
                                                     "events": set(), "symbols": set(), "source": "런타임 로그",
                                                     "level": level})
        group["count"] += 1
        group["first"], group["last"] = min(group["first"], stamp), max(group["last"], stamp)
        if entry.get("symbol"):
            group["symbols"].add(str(entry.get("symbol")))
    return _finish_groups(groups)


# ------------------------------------------------------------- worker state
def worker_view(facts, lane_name, process=None):
    """The lane's worker state: display rows, errors (-> 막힘), unknown
    states (-> 확인 불가 inside the window) and the latest heartbeat.

    Sources: PAPER data/paper/daytrade/worker_status.json (only a snapshot
    stamped with this user as owner_user_id), and on the LIVE server its own
    per-account job registry (process["rows"]). Without either, known is
    False, `note` says why, and the status is not changed by worker state
    (day-trade lanes still check their own runtime log)."""
    view = {"rows": [], "known": False, "errors": [], "unknown": [], "heartbeat": None, "source": "", "note": ""}
    jobs = LANE_JOBS.get(lane_name, ())
    worker = facts.get("worker")
    if facts["mode"] == "PAPER":
        if worker is None:
            view["note"] = facts.get("worker_note") or "워커 상태 확인 불가"
        else:
            data = worker["data"]
            result = data.get("result") if isinstance(data.get("result"), dict) else {}
            at = str(data.get("last_run_at", "") or "")
            view.update(known=True, source="PAPER 워커", heartbeat=_parse_ts(at))
            if result.get("message") and not (PAPER_RESULT_KEYS & set(result)):
                # The loop itself raised (struct._background_worker_loop).
                message = clean_message(result.get("message"))[:200]
                view["rows"].append({"job": "PAPER 워커", "status": "error", "message": message, "at": at})
                view["errors"].append(f"PAPER 워커 오류: {message}")
            for result_key, _job, label in jobs:
                item = result.get(result_key)
                if not isinstance(item, dict) or not item:
                    continue
                status = str(item.get("status", "") or "")
                message = clean_message(item.get("message"))[:200]
                view["rows"].append({"job": label, "status": status, "message": message, "at": at})
                if status == "error":
                    view["errors"].append(f"PAPER 워커 {label} 오류: {message or '상세 없음'}")
    if facts["mode"] == "LIVE" and process is not None and not facts.get("foreign"):
        key = (facts.get("account") or {}).get("policy_key")
        mine = [item for item in process.get("rows") or [] if key and item.get("policy_key") == key]
        view.update(known=True, source="LIVE 워커")
        found = False
        for _result_key, job, label in jobs:
            for item in mine:
                if not job or item.get("job") != job:
                    continue
                found = True
                status = str(item.get("status", "") or "")
                error = clean_message(item.get("error"))[:200]
                at = str(item.get("last_check", "") or "")[:19]
                view["rows"].append({"job": label, "status": status, "message": error or clean_message(item.get("message"))[:200], "at": at})
                stamp = _parse_ts(at)
                if stamp and (view["heartbeat"] is None or stamp > view["heartbeat"]):
                    view["heartbeat"] = stamp
                if status == "error":
                    view["errors"].append(f"LIVE 워커 {label} 오류: {error or '상세 없음'}")
                elif status == "account_changed":
                    view["unknown"].append(f"계좌가 바뀌어 LIVE 워커({label})가 멈췄습니다")
        if not found:
            view["unknown"].append("LIVE 워커가 이 레인을 실행하고 있지 않습니다")
        if process.get("error"):
            view["unknown"].append("LIVE 워커 배정 오류: " + clean_message(process["error"])[:160])
    elif facts["mode"] == "LIVE" and not facts.get("foreign"):
        view["note"] = "LIVE 워커 상태는 LIVE 서버(3001)의 일일 보고에서 확인하세요"
    return view


def silence(seen, window, now):
    """Minutes a source has been silent inside the active window (measured
    from the later of its last record and the window start), when that is
    more than WORKER_STALE_SEC; None when fine or outside the window."""
    if not window:
        return None
    start, end = window
    if not (start <= now < end):
        return None
    since = max(seen, start) if seen else start
    seconds = (now - since).total_seconds()
    return int(seconds // 60) if seconds > WORKER_STALE_SEC else None


def _quiet(kind, seen, minutes, now, source=""):
    """Reason text for a silent source (see silence)."""
    if minutes is None:
        return ""
    last = _stamp(seen, now) if seen else ""
    if kind == "worker":
        return (f"{source} 응답 없음 — 마지막 기록 {last}, 장중 {minutes}분째 기록 없음" if seen
                else f"{source} 기록이 없습니다 (장중 {minutes}분째)")
    return (f"런타임 로그가 {last} 이후 끊겼습니다 (장중 {minutes}분째 기록 없음) — 워커가 멈췄을 수 있습니다" if seen
            else f"런타임 로그 기록이 없습니다 (장중 {minutes}분째)")


def _stale_note(view, now):
    beat = view.get("heartbeat")
    if view.get("known") and beat and (now - beat).total_seconds() > WORKER_STALE_SEC:
        return f"{view['source']} 마지막 기록 {_stamp(beat, now)} ({int((now - beat).total_seconds() // 60)}분 전)"
    return ""


# ------------------------------------------------------------ lane builders
def _new_lane(lane, mode, currency="KRW"):
    return {"key": f"{lane}:{mode}", "lane": lane, "lane_label": LANE_LABELS[lane], "mode": mode,
            "status": UNKNOWN, "status_label": STATUS_LABELS[UNKNOWN], "reason": "",
            "buys": None, "sells": None, "realized": None, "realized_missing": 0, "currency": currency,
            "notes": [], "fills": [], "orders": [], "problems": [], "positions": [], "pending": [],
            "worker": [], "sources": {}}


def _set(lane, status, reason):
    lane["status"], lane["status_label"], lane["reason"] = status, STATUS_LABELS[status], reason
    return lane


FOREIGN_REASON = "이 계좌의 주문 정책은 다른 사용자 소유입니다 — 이 계정으로는 확인할 수 없습니다"


def _paper_unavailable_block(facts, day):
    """PAPER: KIS said the mock account is not registered (kis_api flag). It is
    the current flag, so it covers every day since it was set."""
    flag = facts.get("paper_unavailable") or {}
    since = _parse_ts(flag.get("since"))
    if not since or since.date() > day:
        return ""
    reason = clean_message(flag.get("reason")) or "모의투자 신청내역을 확인하세요"
    return f"모의계좌 사용 불가 ({since:%m-%d %H:%M}부터): {reason}"


def _dt_fills(facts, prefix):
    fills, orders, errors = [], [], []
    seen = set()
    for row in facts["logs"]:
        event = str(row.get("event_type", "") or "").upper()
        if not event.startswith(prefix):
            continue
        if event.endswith("_ERROR"):
            errors.append(row)
            continue
        body = event[len(prefix):]
        pending = body.endswith("_PENDING")
        body = body[:-8] if pending else body
        action = str(row.get("action", "") or body).upper()
        side = "BUY" if (action.startswith("BUY") or body.startswith("BUY")) else (
            "SELL" if (action.startswith(("SELL", "PRE_SELL")) or body.startswith(("SELL", "PRE_SELL"))) else "")
        item = {"time": _hhmmss(row.get("created")), "symbol": row.get("symbol", ""), "side": side,
                "label": DT_EVENT_LABELS.get(body, body) + (" 접수" if pending else ""),
                "qty": _int(row.get("filled_qty") if not pending else row.get("order_qty")),
                "price": _float(row.get("filled_price")) if not pending else _float(row.get("order_price")),
                "realized": None, "status": "접수" if pending else "체결",
                "message": clean_message(row.get("message"))[:160]}
        if pending or _int(row.get("filled_qty")) <= 0 or not side:
            if pending:
                orders.append(item)
            continue
        order_no = str(row.get("order_no", "") or "").strip()
        if order_no:
            if (order_no, side) in seen:
                continue
            seen.add((order_no, side))
        if side == "SELL":
            item["realized"] = _money_after(row.get("message"), "순손익")
            if item["realized"] is None:
                if "rt_realized" in row:
                    item["realized"] = _float(row.get("rt_realized"))
                else:
                    runtime = _json(row.get("raw_response")).get("runtime") or {}
                    item["realized"] = _float(runtime.get("realized")) if isinstance(runtime, dict) else None
        fills.append(item)
    return fills, orders, errors


def _count_fills(lane, fills):
    lane["fills"] = fills[:MAX_LIST]
    lane["buys"] = sum(1 for f in fills if f["side"] == "BUY")
    lane["sells"] = sum(1 for f in fills if f["side"] == "SELL")
    sells = [f for f in fills if f["side"] == "SELL"]
    known = [f["realized"] for f in sells if f.get("realized") is not None]
    lane["realized"] = round(sum(known), 2) if known else None
    lane["realized_missing"] = len(sells) - len(known)


def _repeated_error_blocks(groups):
    return [g for g in groups if g["count"] >= REPEATED_ERROR_MIN]


def _trimmed_groups(groups):
    """Past-day lines left with exactly two rows: two real failures, or the
    first and last of many after the log trim. Not decidable, so not 막힘."""
    return [g for g in groups if g.get("maybe_trimmed") and g["count"] < REPEATED_ERROR_MIN]


def _trimmed_reason(groups):
    trimmed = _trimmed_groups(groups)
    return f"로그 정리로 반복 횟수를 알 수 없습니다: {group_text(trimmed[0])}" if trimmed else ""


def _dt_positions(facts, market):
    positions, pending = [], []
    state = facts.get("state") or {}
    for key, item in state.items():
        if not isinstance(item, dict):
            continue
        item_market = str(item.get("market") or str(key).rsplit(".", 1)[-1] or "").upper()
        is_us = item_market in US_EXCHANGES
        if (market == "US") != is_us:
            continue
        symbol = str(item.get("symbol") or str(key).rsplit(".", 1)[0])
        qty = _int(item.get("position_qty"))
        if qty > 0:
            positions.append({"symbol": symbol, "name": str(item.get("name", "") or ""), "qty": qty,
                              "avg_price": _float(item.get("avg_price")),
                              "carried_overnight": bool(item.get("carried_overnight")),
                              "unmanaged_qty": _int(item.get("broker_unmanaged_qty")),
                              "halt_reason": clean_message(item.get("halt_reason"))[:160]})
        for field, value in item.items():
            match = re.fullmatch(r"pending_(\w+?)_order_no", str(field))
            if match and str(value or "").strip():
                kind = match.group(1)
                pending.append({"symbol": symbol, "kind": "매수" if "buy" in kind else ("매도" if "sell" in kind else kind),
                                "order_no": str(value), "qty": _int(item.get(f"pending_{kind}_qty")),
                                "price": _float(item.get(f"pending_{kind}_price")),
                                "placed_at": str(item.get(f"pending_{kind}_placed_at", "") or "")[:19]})
    return positions, pending


def _off_reason(facts, lane_name):
    """Account and LIVE order-policy reasons a lane cannot trade at all."""
    mode = facts["mode"]
    if not facts["account"].get("configured"):
        return "실계좌가 설정되지 않았습니다" if mode == "LIVE" else "모의계좌가 설정되지 않았습니다"
    if mode != "LIVE":
        return ""
    policy = facts.get("policy")
    if policy is None:
        return "LIVE 주문 정책을 찾을 계좌 정보가 없습니다"
    if policy.get("missing"):
        return "LIVE 주문 정책이 없습니다 (전략 스위치를 켠 적 없음)"
    if not policy.get(lane_name):
        return f"LIVE 주문 정책의 {LANE_LABELS[lane_name]} 레인이 꺼져 있습니다 ({lane_name}=false)"
    return ""


def _us_holiday_notes(groups, calendar):
    """US orders that failed while the US market was closed for a holiday."""
    notes = []
    for group in groups:
        for stamp in (group["first"], group["last"]):
            ts = _parse_ts(stamp)
            if not ts:
                continue
            et_day = _kst_to_et(ts).date()
            name = calendar.us_holidays.get(et_day.isoformat(), "")
            note = f"오류가 난 시각은 미국 동부 {_mmdd(et_day)}로, 미국 휴장일({name})이었습니다" if name else ""
            if note and note not in notes:
                notes.append(note)
    return notes


def build_daytrade_lane(facts, market, day, now, is_today, calendar, is_admin, process=None):
    """Status of one day-trade lane. Rules (first match wins):

    1. 확인 불가  the mode's DB could not be read, the account does not
                 decrypt, or the account's order policy belongs to another
                 user.
    2. 꺼짐      not an admin (day trading is admin only), daytrade hard lock,
                 feature flag OFF (LIVE), LIVE order policy lane false or
                 missing, or the auto switch OFF.
    3. 막힘      PAPER mock account unavailable flag; runtime "계좌 주문을
                 거부" (account halt); the same *_ERROR message >= 3 times;
                 runtime "단타 신규 진입 차단" >= 3 times, or at least once
                 on a day without buys; today, a worker job in error.
    4. 확인 불가  a past day's error line left with two rows (the log trim
                 keeps first and last, so 2 or many is unknown); today: the
                 runtime log is missing/unreadable, or has nothing today
                 although the market opened 15+ min ago; inside the session
                 the worker heartbeat (own worker state only) or the runtime
                 log has been silent for 15+ min, or a LIVE job is
                 missing/account_changed. Fills do not override this.
                 Unreadable worker state (other user's snapshot, the other
                 server) is a note only. A past date whose log was rotated
                 out is 확인 불가 only without fills on a trading day.
    5. 동작      at least one fill that day.
    6. 대기      market closed / holiday / before open, or no signal.
    """
    lane_name = "daytrade_us" if market == "US" else "daytrade_ks"
    mode = facts["mode"]
    lane = _new_lane(lane_name, mode, "USD" if market == "US" else "KRW")
    if not facts["ok"]:
        return _set(lane, UNKNOWN, f"{mode} 데이터를 확인할 수 없습니다: {facts['error']}")
    sw = facts["switches"]
    if not is_admin:
        return _set(lane, OFF, "단타는 관리자 전용 기능입니다")
    if facts.get("hard_locked"):
        return _set(lane, OFF, "단타 기능이 봉인되어 있습니다 (STOCK8_DAYTRADE_HARD_LOCK)")
    if facts.get("foreign"):
        return _set(lane, UNKNOWN, FOREIGN_REASON)

    prefix = "DT_US_" if market == "US" else "DT_KS_"
    fills, orders, error_rows = _dt_fills(facts, prefix)
    _count_fills(lane, fills)
    lane["orders"] = orders[:MAX_LIST]
    error_groups = group_errors(error_rows, past=not is_today)
    runtime = facts["runtime"].get(lane_name) or {"entries": [], "status": "missing"}
    rt_groups = runtime_problems(runtime["entries"], day) if runtime["status"] == "ok" else []
    window, window_at = runtime_window(runtime["entries"], day) if runtime["status"] == "ok" else (runtime["status"], "")
    lane["sources"]["runtime_log"] = window
    if window == "partial":
        # The engine keeps the last 300 entries: earlier ones of the day are gone.
        for group in rt_groups:
            group["count_is_min"] = True
        lane["notes"].append(f"런타임 로그는 {window_at} 이후만 남아 있습니다 (최근 300건 보관)")
    lane["problems"] = (error_groups + rt_groups)[:MAX_LIST]
    lane["positions"], lane["pending"] = _dt_positions(facts, market)
    view = worker_view(facts, lane_name, process)
    lane["worker"] = view["rows"]
    if lane["realized_missing"]:
        lane["notes"].append(f"매도 {lane['realized_missing']}건의 손익을 기록에서 찾지 못했습니다")
    if not is_today and error_groups:
        lane["notes"].append(TRIM_NOTE)

    switch_on = sw["daytrade_us"] if market == "US" else sw["daytrade_ks"]
    exit_on = sw["daytrade_us_exit"] if market == "US" else sw["daytrade_ks_exit"]
    if not facts["account"].get("readable", True):
        return _set(lane, UNKNOWN, "계좌번호를 복호화하지 못해 주문 정책·런타임 파일을 확인할 수 없습니다")
    if mode == "LIVE" and facts.get("policy_error"):
        return _set(lane, BLOCKED, facts["policy_error"])
    off_reason = _off_reason(facts, lane_name)
    if not off_reason and mode == "LIVE" and not sw["daytrade_feature"]:
        off_reason = "단타 기능 스위치(daytrade_feature_enabled)가 꺼져 있습니다"
    if not off_reason and not switch_on:
        off_reason = "자동매매 스위치가 꺼져 있습니다"
    if off_reason:
        if exit_on and lane["positions"]:
            lane["notes"].append("신규 진입은 꺼져 있지만 청산 감시는 켜져 있습니다")
        if fills:
            lane["notes"].append(f"이날 체결 {len(fills)}건 (스위치·정책은 현재 값 기준)")
        return _set(lane, OFF, off_reason)
    if is_today and view["note"]:
        lane["notes"].append(view["note"])

    blocks = []
    unavailable = _paper_unavailable_block(facts, day) if mode == "PAPER" else ""
    if unavailable:
        blocks.append(unavailable)
    halt = [g for g in rt_groups if ACCOUNT_HALT_MARKER in g["message"]]
    if halt:
        blocks.append("KIS 계좌 거부로 자동 주문 정지: " + group_text(halt[0]))
    repeated = _repeated_error_blocks(error_groups)
    blocks.extend(group_text(g) for g in repeated)
    if market == "US":
        lane["notes"].extend(_us_holiday_notes(repeated + _trimmed_groups(error_groups), calendar))
    entry_blocks = [g for g in rt_groups if g["message"].startswith(ENTRY_BLOCK_PREFIX)]
    entry_total = sum(g["count"] for g in entry_blocks)
    if entry_blocks and (entry_total >= ENTRY_BLOCK_MIN or lane["buys"] == 0):
        blocks.append(group_text(entry_blocks[0]))
    elif entry_blocks:
        lane["notes"].append(f"신규 진입 차단 {entry_total}회 (일시적)")
    if is_today:
        blocks.extend(view["errors"])
    if blocks:
        if fills:
            lane["notes"].append(f"차단 사유가 있는 날에도 체결 {len(fills)}건이 있었습니다")
        lane["notes"].extend(f"추가 차단 사유: {b}" for b in blocks[1:3])
        return _set(lane, BLOCKED, blocks[0])
    trimmed = _trimmed_reason(error_groups)
    if trimmed:
        return _set(lane, UNKNOWN, trimmed)

    if not facts.get("dt_root"):
        return _set(lane, UNKNOWN, "런타임 파일 위치(계좌 해시)를 확인하지 못했습니다")
    closed = calendar.us_closed_all_day(day) if market == "US" else calendar.krx_closed_reason(day)
    fill_note = f"체결 {len(fills)}건은 거래 기록으로 확인했습니다" if fills else ""
    if is_today:
        expected = calendar.log_expected_since(lane_name, now)
        opened = expected is not None and (now - expected).total_seconds() > WORKER_STALE_SEC
        what = ""
        if window in ("missing", "error"):
            what = "런타임 로그 파일이 없습니다" if window == "missing" else "런타임 로그를 읽지 못했습니다"
        elif window in ("idle", "empty") and opened:
            what = (f"오늘 런타임 로그 기록이 없습니다 (마지막 {window_at})" if window == "idle"
                    else "런타임 로그가 비어 있습니다")
        if what:
            if fill_note:
                lane["notes"].append(fill_note)
            return _set(lane, UNKNOWN, what + " — 차단 여부를 확인할 수 없습니다")
        active = calendar.active_window(lane_name, now)
        reasons = list(view["unknown"]) if active else []
        if view["known"]:
            beat = view["heartbeat"]
            reasons.append(_quiet("worker", beat, silence(beat, active, now), now, view["source"]))
        last = runtime_last(runtime["entries"])
        reasons.append(_quiet("runtime", last, silence(last, active, now), now))
        reasons = [r for r in reasons if r]
        if reasons:
            if fill_note:
                lane["notes"].append(fill_note)
            lane["notes"].extend(reasons[1:3])
            return _set(lane, UNKNOWN, reasons[0])
        stale = _stale_note(view, now)
        if stale:
            lane["notes"].append(stale)
    elif window in ("rotated", "missing", "error", "idle", "empty"):
        lane["notes"].append("이 날짜의 런타임 로그는 보관 범위 밖이라 거래 기록(trade_log)만으로 판단했습니다")
        if not fills and not closed:
            return _set(lane, UNKNOWN, "체결 없음 · 런타임 로그가 남아 있지 않아 차단 여부를 알 수 없습니다")
    if fills:
        return _set(lane, RUNNING, f"매수 {lane['buys']} · 매도 {lane['sells']} 체결")
    reason = calendar.us_waiting_reason(day, now, is_today) if market == "US" else calendar.ks_waiting_reason(day, now, is_today)
    return _set(lane, WAITING, reason)


def _ib_fill(row):
    event = str(row.get("event_type", "") or "").upper()
    message = str(row.get("message", "") or "")
    match = re.search(r"(\d+)(?:/\d+)?주\s*@\s*\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)", message)
    return {"time": _hhmmss(row.get("created")), "symbol": row.get("symbol", ""), "side": IB_FILL_EVENTS[event],
            "label": IB_FILL_LABELS.get(event, event), "qty": _int(match.group(1)) if match else None,
            "price": _float(match.group(2)) if match else None,
            "realized": _money_after(message, "실현수익") if IB_FILL_EVENTS[event] == "SELL" else None,
            "status": "체결", "message": clean_message(message)[:160]}


def _ib_order(row):
    event = str(row.get("event_type", "") or "").upper()
    side = "BUY" if "_BUY_" in event else ("SELL" if "_SELL_" in event or str(row.get("action", "")).upper() == "SELL" else "")
    return {"time": _hhmmss(row.get("created")), "symbol": row.get("symbol", ""), "side": side,
            "label": IB_ORDER_EVENTS[event], "qty": _int(row.get("order_qty")) or None,
            "price": _float(row.get("order_price")) or None, "status": "예약·주문",
            "message": clean_message(row.get("message"))[:160]}


def build_infinite_buy_lane(facts, day, now, is_today, calendar, process=None):
    """Infinite buy. Rules (first match wins):

    1. 확인 불가  DB unreadable, account does not decrypt, or the account's
                 order policy belongs to another user.
    2. 꺼짐      LIVE order policy infinite_buy false/missing, auto_trade_enabled
                 OFF, or loc_auto_schedule_enabled OFF (LIVE and PAPER).
    3. 막힘      FireGate authority/link block events that day, reservation
                 receipt unknown (kis_reservation_pending, today), PAPER mock
                 account unavailable, the same IB_*_ERROR message >= 3 times,
                 or today a worker job in error (PAPER loc_automation, LIVE
                 loc/sync).
    4. 확인 불가  a past day's error line left with two rows (log trim);
                 today with an active cycle, inside the LOC window (10:00 to
                 23:20/22:20 KST on a US trading day): the own worker state's
                 heartbeat is silent 15+ min, or a LIVE job is missing /
                 account_changed. Without own worker state (the other server,
                 another user's PAPER snapshot) only a note is added: trade_log
                 has no heartbeat (IB_LOC_AUTOMATION_RUN is written only on a
                 day's first attempt, verification or a forced run).
    5. 동작      a fill logged that day (IB_*_FILLED).
    6. 대기      no active cycle, US holiday, or no fill yet (reservations
                 placed/kept are shown in the reason).
    """
    mode = facts["mode"]
    lane = _new_lane("infinite_buy", mode, "USD")
    if not facts["ok"]:
        return _set(lane, UNKNOWN, f"{mode} 데이터를 확인할 수 없습니다: {facts['error']}")
    if facts.get("foreign"):
        return _set(lane, UNKNOWN, FOREIGN_REASON)
    sw, ib = facts["switches"], facts.get("ib") or {}
    rows = [r for r in facts["logs"] if str(r.get("event_type", "") or "").upper().startswith("IB_")]
    fills = [_ib_fill(r) for r in rows if str(r.get("event_type", "")).upper() in IB_FILL_EVENTS]
    _count_fills(lane, fills)
    lane["orders"] = [_ib_order(r) for r in rows if str(r.get("event_type", "")).upper() in IB_ORDER_EVENTS][:MAX_LIST]
    error_groups = group_errors([r for r in rows if str(r.get("event_type", "")).upper().endswith("_ERROR")], past=not is_today)
    block_groups = group_errors([r for r in rows if str(r.get("event_type", "")).upper() in IB_HARD_BLOCK_EVENTS],
                                source="차단 이벤트", past=not is_today)
    for group in block_groups:
        group["level"] = "block"
    lane["problems"] = (block_groups + error_groups)[:MAX_LIST]
    lane["positions"] = [{"symbol": c.get("symbol"), "name": f"{_int(c.get('cycle_number'))}번째 사이클 · {c.get('status')}",
                          "qty": _int(c.get("total_qty")), "avg_price": _float(c.get("avg_price")),
                          "round": f"{_int(c.get('current_round'))}/{_int(c.get('division_count'))}회차"}
                         for c in facts.get("cycles") or []]
    view = worker_view(facts, "infinite_buy", process)
    lane["worker"] = view["rows"]
    if ib.get("failure_reason") and is_today:
        lane["notes"].append("최근 예약 검증 실패 사유: " + clean_message(ib["failure_reason"])[:200])
    if lane["realized_missing"]:
        lane["notes"].append(f"매도 {lane['realized_missing']}건의 실현수익을 기록에서 찾지 못했습니다")
    if not is_today:
        lane["notes"].append(TRIM_NOTE)

    if not facts["account"].get("readable", True):
        return _set(lane, UNKNOWN, "계좌번호를 복호화하지 못해 주문 정책을 확인할 수 없습니다")
    if mode == "LIVE" and facts.get("policy_error"):
        return _set(lane, BLOCKED, facts["policy_error"])
    off_reason = _off_reason(facts, "infinite_buy")
    if not off_reason and not sw["auto_trade"]:
        off_reason = "무한매수 매매 스위치(auto_trade_enabled)가 꺼져 있습니다"
    if not off_reason and not sw["loc_schedule"]:
        off_reason = "LOC 자동 예약(loc_auto_schedule_enabled)이 꺼져 있습니다"
    if off_reason:
        if fills:
            lane["notes"].append(f"이날 체결 {len(fills)}건 (스위치·정책은 현재 값 기준)")
        return _set(lane, OFF, off_reason)
    if is_today and view["note"]:
        lane["notes"].append(view["note"])

    blocks = []
    unavailable = _paper_unavailable_block(facts, day) if mode == "PAPER" else ""
    if unavailable:
        blocks.append(unavailable)
    if block_groups:
        events = {e for g in block_groups for e in g["events"]}
        labels = []
        if {"IB_LOC_BUY_FIREGATE_AUTHORITY_BLOCKED", "IB_LOC_SELL_FIREGATE_AUTHORITY_BLOCKED"} <= events:
            labels.append("LOC 매수·매도 예약 보류 (FireGate 권한 차단)")
            events -= {"IB_LOC_BUY_FIREGATE_AUTHORITY_BLOCKED", "IB_LOC_SELL_FIREGATE_AUTHORITY_BLOCKED"}
        labels.extend(IB_HARD_BLOCK_EVENTS[e] for e in IB_HARD_BLOCK_EVENTS if e in events)
        symbols = sorted({s for g in block_groups for s in g["symbols"]})
        text = f"{', '.join(symbols) + ' ' if symbols else ''}{' · '.join(labels)}"
        days = [d for d in facts.get("ib_block_days") or [] if d <= day.isoformat()]
        if len(days) > 1:
            text += f" — 최근 {HISTORY_DAYS}일 중 최소 {len(days)}일 발생 (처음 {days[0][5:].replace('-', '/')})"
        blocks.append(text)
    if is_today and ib.get("reservation_pending"):
        blocks.append("예약 접수 여부를 확인하지 못해 새 예약을 멈췄습니다 (kis_reservation_pending) — 대조 필요")
    blocks.extend(group_text(g) for g in _repeated_error_blocks(error_groups))
    cooldown = is_today and ib.get("cooldown_until") and ib["cooldown_until"] > now.replace(tzinfo=KST).timestamp()
    if cooldown:
        lane["notes"].append("예약 재구성 대기 중: " + clean_message(ib.get("cooldown_reason"))[:160])
    if is_today:
        blocks.extend(view["errors"])
    if blocks:
        lane["notes"].extend(f"추가 차단 사유: {b}" for b in blocks[1:3])
        return _set(lane, BLOCKED, blocks[0])
    trimmed = _trimmed_reason(error_groups)  # any block event is already 막힘 above
    if trimmed:
        return _set(lane, UNKNOWN, trimmed)
    if is_today and facts.get("cycles") and not cooldown and view["known"]:
        active = calendar.active_window("infinite_buy", now)
        reasons = list(view["unknown"]) if active else []
        beat = view["heartbeat"]
        reasons.append(_quiet("worker", beat, silence(beat, active, now), now, view["source"]))
        reasons = [r for r in reasons if r]
        if reasons:
            if fills:
                lane["notes"].append(f"체결 {len(fills)}건은 거래 기록으로 확인했습니다")
            lane["notes"].extend(reasons[1:3])
            return _set(lane, UNKNOWN, reasons[0])
        stale = _stale_note(view, now)
        if stale:
            lane["notes"].append(stale)
    if fills:
        return _set(lane, RUNNING, f"매수 {lane['buys']} · 매도 {lane['sells']} 체결")
    if not facts.get("cycles"):
        return _set(lane, WAITING, "운영 중인 사이클이 없습니다")
    closed = calendar.us_closed_reason(day)
    if closed:
        return _set(lane, WAITING, f"휴장 ({closed})")
    if lane["orders"]:
        return _set(lane, WAITING, f"예약·주문 {len(lane['orders'])}건 · 체결 없음")
    if ib.get("verified_date") == day.isoformat() and ib.get("verified_complete"):
        return _set(lane, WAITING, "LOC 예약 검증 완료 · 체결 없음")
    return _set(lane, WAITING, "체결·예약 기록 없음")


def build_coin_lane(facts, day, now, is_today, coin_hard_locked=False, hard_lock_known=True):
    """Coin (LIVE only, admin only). Rules (first match wins):

    1. 확인 불가  LIVE DB unreadable, or coin_policy_v1 is damaged.
    2. 꺼짐      no coin_policy_v1, mode off, another owner, or hard lock.
    3. 막힘      COIN_HALT that day without a later COIN_RESUME, or the same
                 COIN_*_ERROR / cancel message >= 3 times.
    4. 동작      a fill that day (shadow fills are virtual and say so).
    5. 대기      no signal.
    """
    lane = _new_lane("coin", "LIVE")
    if not facts["ok"]:
        return _set(lane, UNKNOWN, f"LIVE 데이터를 확인할 수 없습니다: {facts['error']}")
    coin = facts.get("coin") or {}
    if not hard_lock_known:
        lane["notes"].append("PAPER 서버에서는 LIVE 서버의 코인 봉인(STOCK8_COIN_HARD_LOCK) 설정을 알 수 없습니다")
    if coin.get("corrupt"):
        return _set(lane, UNKNOWN, "코인 정책(coin_policy_v1) 데이터가 손상되어 확인할 수 없습니다")
    policy = coin.get("policy") or {}
    mode_name = str(policy.get("mode", "off") or "off").lower()
    rows = [r for r in facts["logs"] if str(r.get("event_type", "") or "").upper().startswith("COIN_")]
    fills = []
    for row in rows:
        event = str(row.get("event_type", "")).upper()
        if event in COIN_FILL_EVENTS:
            side = COIN_FILL_EVENTS[event]
            fills.append({"time": _hhmmss(row.get("created")), "symbol": row.get("symbol", ""), "side": side,
                          "label": ("[섀도] " if "SHADOW" in event else "") + ("매수" if side == "BUY" else "매도"),
                          "qty": None, "price": _float(row.get("filled_price")),
                          "realized": _money_after(row.get("message"), "순손익") if side == "SELL" else None,
                          "status": "가상 체결" if "SHADOW" in event else "체결",
                          "message": clean_message(row.get("message"))[:160]})
    _count_fills(lane, fills)
    error_rows = [r for r in rows if str(r.get("event_type", "")).upper().endswith("_ERROR")
                  or str(r.get("event_type", "")).upper() == "COIN_ORDER_CANCELLED"]
    error_groups = group_errors(error_rows, past=not is_today)
    lane["problems"] = error_groups[:MAX_LIST]
    ledger = coin.get("ledger") or {}
    for market, sleeve in (ledger.get("sleeves") or {}).items():
        if not isinstance(sleeve, dict):
            continue
        if sleeve.get("long"):
            lane["positions"].append({"symbol": market, "name": "", "qty": _float(sleeve.get("volume")),
                                      "avg_price": _float(sleeve.get("entry_px"))})
        if sleeve.get("pending"):
            pend = sleeve["pending"] if isinstance(sleeve["pending"], dict) else {}
            lane["pending"].append({"symbol": market, "kind": "매수" if pend.get("side") == "bid" else "매도",
                                    "order_no": str(pend.get("uuid", "") or ""), "qty": None, "price": None,
                                    "placed_at": ""})
    if coin.get("ledger_status") in ("missing", "error") and mode_name in ("shadow", "live"):
        lane["notes"].append("코인 장부 파일 " + ("없음" if coin["ledger_status"] == "missing" else "읽기 실패") + " — 보유 내역 확인 불가")

    if coin_hard_locked:
        return _set(lane, OFF, "코인 기능이 봉인되어 있습니다 (STOCK8_COIN_HARD_LOCK)")
    if not coin.get("exists"):
        return _set(lane, OFF, "코인 정책(coin_policy_v1)이 LIVE DB에 없습니다")
    if mode_name not in ("shadow", "live"):
        return _set(lane, OFF, "코인 정책이 꺼짐(off) 상태입니다")
    if str(policy.get("owner_user_id", "") or "") != str(facts.get("uid") or ""):
        return _set(lane, OFF, "코인 정책의 소유자가 이 계정이 아닙니다")
    if mode_name == "shadow":
        lane["notes"].append("섀도 모드: 실주문 없이 가상 체결만 기록합니다")
    blocks = []
    halts = [r for r in rows if str(r.get("event_type", "")).upper() == "COIN_HALT"]
    resumes = [r for r in rows if str(r.get("event_type", "")).upper() == "COIN_RESUME"]
    if halts and (not resumes or max(str(r.get("created")) for r in resumes) < max(str(r.get("created")) for r in halts)):
        last = max(halts, key=lambda r: str(r.get("created")))
        blocks.append(f"신규 진입 중단 ({_hhmm(last.get('created'))}): {clean_message(last.get('message'))[:160]}")
    blocks.extend(group_text(g) for g in _repeated_error_blocks(error_groups))
    if blocks:
        return _set(lane, BLOCKED, blocks[0])
    trimmed = _trimmed_reason(error_groups)
    if trimmed:
        return _set(lane, UNKNOWN, trimmed)
    if fills:
        return _set(lane, RUNNING, f"{'섀도 ' if mode_name == 'shadow' else ''}매수 {lane['buys']} · 매도 {lane['sells']}")
    return _set(lane, WAITING, "섀도 모드 · 진입 신호 대기" if mode_name == "shadow" else "진입 신호 대기")


def build_usth_lane(facts, day, now, is_today, calendar):
    """PAPER US trend hold (shown only while enabled). Rules:
    확인 불가 (DB, damaged policy) > 막힘 (mock account unavailable, same
    USTH_ERROR >= 3) > 동작 (USTH_FILL that day) > 대기 (US holiday / no
    rebalance)."""
    lane = _new_lane("us_trend_hold", "PAPER", "USD")
    if not facts["ok"]:
        return _set(lane, UNKNOWN, f"PAPER 데이터를 확인할 수 없습니다: {facts['error']}")
    usth = facts.get("usth") or {}
    if usth.get("corrupt"):
        return _set(lane, UNKNOWN, "추세보유 정책(us_trend_hold_policy_v1) 데이터가 손상되어 확인할 수 없습니다")
    rows = [r for r in facts["logs"] if str(r.get("event_type", "") or "").upper().startswith("USTH_")]
    fills = []
    for row in rows:
        event = str(row.get("event_type", "")).upper()
        side = "BUY" if str(row.get("action", "")).upper().startswith("BUY") else ("SELL" if str(row.get("action", "")).upper().startswith("SELL") else "")
        item = {"time": _hhmmss(row.get("created")), "symbol": row.get("symbol", ""), "side": side,
                "label": "체결" if event == "USTH_FILL" else ("주문" if event == "USTH_ORDER" else event),
                "qty": _int(row.get("filled_qty") or row.get("order_qty")) or None,
                "price": _float(row.get("filled_price") or row.get("order_price")) or None, "realized": None,
                "status": "체결" if event == "USTH_FILL" else "주문", "message": clean_message(row.get("message"))[:160]}
        if event == "USTH_FILL" and side:
            fills.append(item)
        elif event == "USTH_ORDER":
            lane["orders"].append(item)
    _count_fills(lane, fills)
    lane["realized"] = None
    error_groups = group_errors([r for r in rows if str(r.get("event_type", "")).upper().endswith("_ERROR")], past=not is_today)
    lane["problems"] = error_groups
    ledger = usth.get("ledger") or {}
    for etf, sleeve in (ledger.get("sleeves") or {}).items():
        if not isinstance(sleeve, dict):
            continue
        if _int(sleeve.get("qty")) > 0:
            lane["positions"].append({"symbol": etf, "name": str(sleeve.get("index", "") or ""), "qty": _int(sleeve.get("qty")),
                                      "avg_price": (_float(sleeve.get("cost_usd"), 0) / _int(sleeve.get("qty"))) if _int(sleeve.get("qty")) else None})
        if isinstance(sleeve.get("pending"), dict):
            pend = sleeve["pending"]
            lane["pending"].append({"symbol": etf, "kind": "매수" if pend.get("side") == "BUY" else "매도",
                                    "order_no": str(pend.get("order_no", "") or ""), "qty": _int(pend.get("qty")),
                                    "price": _float(pend.get("limit")), "placed_at": ""})
    if usth.get("ledger_status") in ("missing", "error"):
        lane["notes"].append("추세보유 장부 파일 " + ("없음" if usth["ledger_status"] == "missing" else "읽기 실패") + " — 보유 내역 확인 불가")
    blocks = []
    unavailable = _paper_unavailable_block(facts, day)
    if unavailable:
        blocks.append(unavailable)
    blocks.extend(group_text(g) for g in _repeated_error_blocks(error_groups))
    if blocks:
        return _set(lane, BLOCKED, blocks[0])
    trimmed = _trimmed_reason(error_groups)
    if trimmed:
        return _set(lane, UNKNOWN, trimmed)
    if fills:
        return _set(lane, RUNNING, f"매수 {lane['buys']} · 매도 {lane['sells']} 체결")
    closed = calendar.us_closed_all_day(day)
    if closed:
        return _set(lane, WAITING, f"휴장 ({closed})")
    return _set(lane, WAITING, "리밸런싱 없음 (보유 유지)")


# ------------------------------------------------------------ safety section
def build_safety(facts, now, connection_cache=None):
    mode = facts["mode"]
    safety = {"mode": mode, "ok": facts["ok"], "error": facts.get("error", ""), "verification": None,
              "old_ledgers": [], "paper_unavailable": None, "connection": {}, "account": {}}
    if not facts["ok"]:
        return safety
    account = facts.get("account") or {}
    safety["account"] = {"configured": bool(account.get("configured")), "readable": bool(account.get("readable", True)),
                         "provider": account.get("provider", "")}
    if not account.get("configured"):
        safety["verification"] = {"status": "not_configured"}
    elif not account.get("readable", True):
        safety["verification"] = {"status": "error", "message": "계좌번호를 복호화하지 못했습니다"}
    elif facts.get("foreign"):
        safety["verification"] = {"status": "foreign", "message": "다른 사용자 소유 계좌"}
    else:
        # The ledger file name is an account hash: not sent to the browser.
        safety["verification"] = {k: v for k, v in (facts.get("verification") or {"status": "missing"}).items() if k != "file"}
    safety["old_ledgers"] = [{"holds": len(l.get("holds") or []), "hold_records": l.get("hold_records", 0),
                              "symbols": [h.get("symbol") for h in (l.get("holds") or [])][:30],
                              "last_run": l.get("last_run", "")} for l in facts.get("old_ledgers") or [] if l.get("holds")]
    if mode == "PAPER":
        safety["paper_unavailable"] = facts.get("paper_unavailable")
    conn = dict(facts.get("connection") or {})
    expires = _parse_ts(conn.get("token_expires"))
    conn["token_state"] = "" if not expires else ("만료됨 (다음 호출 때 재발급)" if expires < now else "유효")
    conn["cache"] = connection_cache
    safety["connection"] = conn
    return safety


# ------------------------------------------------------------------ report
def build_report(uid, day, *, now, is_admin, server_mode, db_paths, data_dir, decrypt=None,
                 krx_holidays=(), us_holidays=None, us_early_closes=None, process=None,
                 daytrade_hard_locked=False, coin_hard_locked=False):
    """The whole report for one user and one KST date. Read-only.

    process (this server's memory, optional): connection_cache (dashboard
    KIS status) and, on LIVE, live_workers {"rows": [...], "error": ""}."""
    uid = str(uid or "").strip()
    if not uid:
        raise ValueError("로그인이 필요합니다.")
    server_mode = str(server_mode or "PAPER").upper()
    today = now.date()
    is_today = day == today
    process = process or {}
    calendar = Calendar(krx_holidays, us_holidays, us_early_closes)
    paths = dict(db_paths or {})
    same = paths.get("LIVE") and paths.get("PAPER") and os.path.normcase(os.path.realpath(paths["LIVE"])) == os.path.normcase(os.path.realpath(paths["PAPER"]))
    facts = {}
    for mode in MODES:
        if same and mode != server_mode:
            facts[mode] = {"mode": mode, "ok": False, "error": "LIVE와 PAPER DB 경로가 같습니다", "uid": uid}
            continue
        facts[mode] = collect_mode(mode, paths.get(mode), data_dir, uid, is_admin, day, decrypt,
                                   hard_locked=daytrade_hard_locked if mode == server_mode else False)
        facts[mode]["uid"] = uid
    workers = process.get("live_workers") if server_mode == "LIVE" else None

    lanes = []
    for market in ("KS", "US"):
        for mode in MODES:
            lanes.append(build_daytrade_lane(facts[mode], market, day, now, is_today, calendar, is_admin,
                                             workers if mode == "LIVE" else None))
    for mode in MODES:
        lanes.append(build_infinite_buy_lane(facts[mode], day, now, is_today, calendar,
                                             workers if mode == "LIVE" else None))
    if is_admin:
        lanes.append(build_coin_lane(facts["LIVE"], day, now, is_today,
                                     coin_hard_locked=coin_hard_locked if server_mode == "LIVE" else False,
                                     hard_lock_known=server_mode == "LIVE"))
        usth = facts["PAPER"].get("usth") or {}
        if not facts["PAPER"].get("ok") or usth.get("corrupt") or (usth.get("enabled") and usth.get("owner") == uid):
            lanes.append(build_usth_lane(facts["PAPER"], day, now, is_today, calendar))

    counts = {status: 0 for status in STATUS_ORDER}
    for lane in lanes:
        counts[lane["status"]] = counts.get(lane["status"], 0) + 1
    cache = process.get("connection_cache")
    safety = {mode: build_safety(facts[mode], now, cache if mode == server_mode else None) for mode in MODES}
    notes = []
    if not is_today:
        notes.append("지난 날짜는 거래 기록(trade_log)의 기록 시각 기준입니다. 스위치·주문 정책·보유·미체결은 지금 값입니다.")
    for mode in MODES:
        if not facts[mode].get("ok"):
            notes.append(f"{mode} 데이터를 읽지 못해 {mode} 항목은 '확인 불가'로 표시합니다: {facts[mode].get('error', '')}")
    return {
        "date": day.isoformat(), "today": today.isoformat(), "is_today": is_today,
        "dates": date_options(today), "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "server_mode": server_mode, "is_admin": bool(is_admin),
        "lanes": lanes, "counts": counts,
        "safety": safety, "market": calendar.schedule(day),
        "sources": {mode: {"ok": bool(facts[mode].get("ok")), "error": facts[mode].get("error", ""),
                           "own": mode == server_mode} for mode in MODES},
        "notes": notes,
    }


class DailyReport:
    build_report = staticmethod(build_report)
    parse_day = staticmethod(parse_day)
    date_options = staticmethod(date_options)
    mode_db_path = staticmethod(mode_db_path)
    clean_message = staticmethod(clean_message)
    group_errors = staticmethod(group_errors)
    STATUS_LABELS = STATUS_LABELS
    HISTORY_DAYS = HISTORY_DAYS


Model = DailyReport
