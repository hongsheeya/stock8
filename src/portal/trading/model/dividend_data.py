"""Dividend data for the 배당 page (10-22): KIS first on real accounts,
yfinance for history and as the fallback (PAPER, Toss, missing rows).

- Korea: KIS 예탁원정보(배당일정) gives record dates, cash dividend per
  share and pay dates; the ex-date is derived (T+2: business day before
  the record date). yfinance adds older history.
- US: KIS 해외주식 권리종합 gives announced ex/record/pay dates; amounts come
  from yfinance (the last regular amount when not yet published).
Per-symbol results are cached on disk for 12 hours; public data, so the
cache is shared by all users of a server.
"""
import datetime
import json
import os
import sys
import threading
import time

CACHE_TTL_SEC = 12 * 3600
_FETCH_LOCK = sys.__dict__.setdefault("_stock8_dividend_fetch_lock", threading.Lock())


def to_date(value):
    text = str(value or "").strip().replace("-", "").replace("/", "")[:8]
    if len(text) != 8 or not text.isdigit() or text == "00000000":
        return None
    try:
        return datetime.date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        return None


def yahoo_symbol(symbol, market):
    symbol = str(symbol or "").strip().upper()
    market = str(market or "").upper()
    if market in ("KS", "KR", "KRX"):
        return f"{symbol}.KS"
    if market in ("KQ", "KOSDAQ"):
        return f"{symbol}.KQ"
    return symbol.replace(".", "-")  # BRK.B -> BRK-B


def is_us(market):
    return str(market or "").upper() in ("US", "NASD", "NYSE", "AMEX", "NAS", "NYS", "AMS")


def yahoo_events(symbol, market, yf, today):
    """(events, last_close, name) from yfinance. Unadjusted prices; the
    Dividends column carries the per-share cash amount on each ex-date."""
    ticker = yf.Ticker(yahoo_symbol(symbol, market))
    hist = ticker.history(period="6y", auto_adjust=False, actions=True)
    events, price = [], 0.0
    if hist is not None and len(hist):
        closes = hist["Close"].dropna()
        price = float(closes.iloc[-1]) if len(closes) else 0.0  # today's row can be NaN
        if "Dividends" in hist:
            for stamp, amount in hist["Dividends"].items():
                if float(amount or 0) > 0:
                    events.append({"ex_date": stamp.date().isoformat(), "amount": round(float(amount), 6),
                                   "source": "yahoo", "confirmed": True})
    try:
        cal = ticker.calendar or {}
    except Exception:
        cal = {}
    ex = cal.get("Ex-Dividend Date") if isinstance(cal, dict) else None
    pay = cal.get("Dividend Date") if isinstance(cal, dict) else None
    if isinstance(ex, datetime.date) and ex >= today and not any(e["ex_date"] == ex.isoformat() for e in events):
        last = events[-1]["amount"] if events else 0.0
        events.append({"ex_date": ex.isoformat(), "amount": last, "pay_date": pay.isoformat() if isinstance(pay, datetime.date) else None,
                       "source": "yahoo_calendar", "confirmed": False, "amount_estimated": True})
    elif isinstance(pay, datetime.date) and events and events[-1]["ex_date"] >= (today - datetime.timedelta(days=60)).isoformat():
        events[-1]["pay_date"] = pay.isoformat()
    return events, price


def kis_kr_events(kis, symbol, today, market="KS"):
    rows = kis.get_domestic_dividend_schedule(symbol, (today - datetime.timedelta(days=800)).strftime("%Y%m%d"),
                                              (today + datetime.timedelta(days=200)).strftime("%Y%m%d"))
    dividend = wiz_dividend()
    out = []
    for row in rows or []:
        if str(row.get("sht_cd", symbol) or symbol).strip() not in ("", str(symbol)):
            continue
        record = to_date(row.get("record_date"))
        amount = float(str(row.get("per_sto_divi_amt", "0") or "0").replace(",", "") or 0)
        if not record or amount <= 0:
            continue
        ex = dividend.ex_date_from_record(market, record)
        out.append({"ex_date": ex.isoformat(), "record_date": record.isoformat(), "amount": amount,
                    "pay_date": to_date(row.get("divi_pay_dt")).isoformat() if to_date(row.get("divi_pay_dt")) else None,
                    "kind": str(row.get("divi_kind", "") or ""), "high_dividend": str(row.get("high_divi_gb", "") or ""),
                    "source": "kis", "confirmed": True})
    return out


def kis_us_events(kis, symbol, today):
    rows = kis.get_overseas_rights_schedule(symbol, (today - datetime.timedelta(days=45)).strftime("%Y%m%d"),
                                            (today + datetime.timedelta(days=120)).strftime("%Y%m%d"))
    out = []
    for row in rows or []:
        title = str(row.get("ca_title", "") or "")
        if title and not any(word in title for word in ("배당", "Dividend", "DIVIDEND", "Cash", "CASH")):
            continue
        ex = to_date(row.get("div_lock_dt"))
        if not ex:
            continue
        out.append({"ex_date": ex.isoformat(), "record_date": (to_date(row.get("record_dt")) or ex).isoformat(),
                    "pay_date": (to_date(row.get("pay_dt")).isoformat() if to_date(row.get("pay_dt")) else None),
                    "title": title, "source": "kis", "confirmed": True, "amount": None})
    return out


_DIVIDEND_MODEL = {}


def wiz_dividend():
    """The math model; injected by DividendData (tests set it directly)."""
    return _DIVIDEND_MODEL["model"]


def merge(market, yahoo, kis_rows):
    """KIS rows win within +/-5 days of a Yahoo ex-date; US KIS rows take
    their amount from the matching Yahoo row or the last Yahoo amount."""
    events = [dict(e) for e in yahoo]
    last_amount = next((e["amount"] for e in reversed(events) if e.get("amount")), 0.0)
    for row in kis_rows:
        ex = to_date(row["ex_date"])
        match = None
        for e in events:
            other = to_date(e["ex_date"])
            if other and abs((other - ex).days) <= 5:
                match = e
                break
        if match is not None:
            amount = row.get("amount") if row.get("amount") else match.get("amount")
            match.update({k: v for k, v in row.items() if v not in (None, "")})
            match["amount"] = amount
            match["confirmed"] = True
        else:
            new = dict(row)
            if not new.get("amount"):
                new["amount"] = last_amount
                new["amount_estimated"] = True
            events.append(new)
    events.sort(key=lambda e: e["ex_date"])
    return events


class DividendData:
    def __init__(self, cache_dir, dividend_model, yf=None, now=None):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        _DIVIDEND_MODEL["model"] = dividend_model
        self.D = dividend_model
        self.yf = yf
        self.now = now or time.time

    def _path(self, symbol, market):
        key = ("US" if is_us(market) else "KR") + "_" + "".join(ch for ch in str(symbol).upper() if ch.isalnum() or ch in "-.")
        return os.path.join(self.cache_dir, f"{key}.json")

    def cached(self, symbol, market):
        try:
            with open(self._path(symbol, market), encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return None

    def stale(self, symbol, market):
        entry = self.cached(symbol, market)
        return entry is None or self.now() - float(entry.get("fetched_at") or 0) > CACHE_TTL_SEC

    def refresh(self, symbol, market, kis=None, today=None):
        today = today or datetime.date.today()
        yahoo, price, errors = [], 0.0, []
        if self.yf is not None:
            try:
                yahoo, price = yahoo_events(symbol, market, self.yf, today)
            except Exception as exc:
                errors.append(f"yahoo: {str(exc)[:120]}")
        kis_rows = []
        if kis is not None:
            try:
                kis_rows = kis_us_events(kis, symbol, today) if is_us(market) else kis_kr_events(kis, symbol, today, market)
            except Exception as exc:
                errors.append(f"kis: {str(exc)[:120]}")
        entry = {"symbol": str(symbol).upper(), "market": market, "fetched_at": self.now(), "price": price,
                 "events": merge(market, yahoo, kis_rows), "sources": sorted({e.get("source", "") for e in yahoo + kis_rows}),
                 "errors": errors}
        if not entry["events"] and errors:
            old = self.cached(symbol, market)
            if old and old.get("events"):
                old["errors"] = errors  # keep the last good data, show the error
                entry = old
        tmp = self._path(symbol, market) + ".tmp"
        with _FETCH_LOCK:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(entry, handle, ensure_ascii=False)
            os.replace(tmp, self._path(symbol, market))
        return entry

    @staticmethod
    def parse_events(entry):
        out = []
        for e in (entry or {}).get("events") or []:
            ex = to_date(e.get("ex_date"))
            if not ex or not e.get("amount"):
                continue
            out.append({"ex_date": ex, "amount": float(e["amount"]), "pay_date": to_date(e.get("pay_date")),
                        "record_date": to_date(e.get("record_date")), "confirmed": bool(e.get("confirmed")),
                        "amount_estimated": bool(e.get("amount_estimated")), "source": e.get("source", "")})
        return out


Model = DividendData
