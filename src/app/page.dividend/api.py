"""배당 관리 page API (10-22). Every logged-in user, own account only.

Holdings (KIS/Toss balance) and dividend data (KIS on real accounts,
yfinance otherwise) are refreshed in a background thread under the user's
session; requests only read the cached results, so the page stays fast and
the KIS call budget is not spent on polling (holdings: 5 calls / 10 min).
"""
import datetime as _dt
import json as _json
import os as _os
import re as _re
import sys as _sys
import threading as _threading
import time as _time

_TRADING_MODE = str(_os.environ.get("TRADING_MODE", "PAPER") or "PAPER").strip().upper()
_STATE = _sys.__dict__.setdefault("_stock8_dividend_state", {})  # uid -> holdings, fx, refresh flags
_HOLDINGS_TTL_SEC = 600
_WATCH_KEY = "dividend_watchlist"
_MAX_WATCH = 40
_FX_FALLBACK = 1400.0
_US_SYMBOL = _re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_KR_SYMBOL = _re.compile(r"^[0-9A-Z]{6}$")


def _trading():
    return wiz.model("struct").trading


def _uid():
    uid = str(wiz.session.get("id") or "")
    if not uid:
        wiz.response.status(401, message="로그인이 필요합니다.")
    return uid


def _models():
    return wiz.model("portal/trading/dividend"), wiz.model("portal/trading/dividend_data")


def _cache_dir():
    return wiz.project.fs().abspath(f"data/{'live' if _TRADING_MODE == 'LIVE' else 'paper'}/dividend/cache")


def _today():
    return wiz.model("portal/trading/kst").now().date()


def _watchlist(trading, uid):
    raw = trading._lookup_config_value(trading._user_config_key(uid, _WATCH_KEY), "")
    try:
        rows = _json.loads(raw or "[]")
    except (TypeError, ValueError):
        rows = []
    return [r for r in rows if isinstance(r, dict) and r.get("symbol") and r.get("market")][:_MAX_WATCH]


def _save_watchlist(trading, uid, rows):
    trading._write_config_value(trading._user_config_key(uid, _WATCH_KEY), _json.dumps(rows[:_MAX_WATCH], ensure_ascii=False),
                                "Dividend watchlist", False)


def _jsonable(value):
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _fetch_holdings(trading):
    broker = getattr(trading, "broker_api", None) or trading.kis_api
    holdings, errors, fx = [], [], 0.0
    domestic = getattr(broker, "get_domestic_balance", None)
    if callable(domestic):
        try:
            for h in (domestic() or {}).get("holdings", []) or []:
                holdings.append({"symbol": str(h.get("symbol", "")), "market": h.get("market") or "KS", "name": h.get("name", ""),
                                 "qty": float(h.get("qty") or 0), "avg_price": float(h.get("avg_price") or 0),
                                 "current_price": float(h.get("current_price") or 0)})
        except Exception as exc:
            errors.append(f"국내 잔고: {str(exc)[:120]}")
    overseas = getattr(broker, "get_balance", None)
    if callable(overseas):
        try:
            for h in (overseas() or {}).get("holdings", []) or []:
                holdings.append({"symbol": str(h.get("symbol", "")).upper(), "market": "US", "name": h.get("name", ""),
                                 "qty": float(h.get("qty") or 0), "avg_price": float(h.get("avg_price") or 0),
                                 "current_price": float(h.get("current_price") or 0)})
        except Exception as exc:
            errors.append(f"해외 잔고: {str(exc)[:120]}")
    present = getattr(broker, "get_present_balance", None)
    if callable(present):
        try:
            fx = float((present() or {}).get("usd_krw") or 0)
        except Exception as exc:
            errors.append(f"환율: {str(exc)[:80]}")
    holdings = [h for h in holdings if h["symbol"] and h["qty"] > 0]
    return holdings, fx, errors


def _refresh_job(uid, refresh_holdings=True, only=None, force=False):
    import flask
    state = _STATE.setdefault(uid, {})
    try:
        with wiz.server.app.flask.test_request_context("/"):
            flask.session["id"] = uid
            trading = _trading()
            if refresh_holdings:
                holdings, fx, errors = _fetch_holdings(trading)
                state.update(holdings=holdings, holdings_at=_time.time(), holdings_errors=errors)
                if fx > 0:
                    state["fx"] = fx
            import yfinance as yf
            dividend, data_cls = _models()
            data = data_cls(_cache_dir(), dividend, yf=yf)
            kis = getattr(trading, "kis_api", None)
            if not callable(getattr(kis, "get_domestic_dividend_schedule", None)):
                kis = None
            symbols = only or ([(h["symbol"], h["market"]) for h in state.get("holdings") or []] +
                               [(w["symbol"], w["market"]) for w in _watchlist(trading, uid)])
            seen = set()
            for symbol, market in symbols:
                if (symbol, market) in seen:
                    continue
                seen.add((symbol, market))
                if force or data.stale(symbol, market):
                    data.refresh(symbol, market, kis=kis, today=_today())
            state["error"] = ""
    except Exception as exc:
        state["error"] = str(exc)[:200]
    finally:
        state["refreshing"] = False
        state["refreshed_at"] = _time.time()


def _start_refresh(uid, **kwargs):
    state = _STATE.setdefault(uid, {})
    if state.get("refreshing"):
        return False
    state["refreshing"] = True  # claimed before the thread starts
    _threading.Thread(target=_refresh_job, args=(uid,), kwargs=kwargs, daemon=True, name="stock8-dividend-refresh").start()
    return True


def _alerts(rows, watch_rows, fin, today):
    out = []
    for r in rows + watch_rows:
        name = r.get("name") or r["symbol"]
        if r.get("cut"):
            out.append({"level": "danger", "text": f"{name}: 최근 배당이 1년 전보다 {abs(r['cut']['pct']):.1f}% 줄었습니다."})
        if r.get("missed"):
            out.append({"level": "warn", "text": f"{name}: 예정 주기가 지났는데 새 배당 기록이 없습니다 (중단·지연 확인)."})
    for r in rows:
        ex = r.get("next_ex_date")
        if ex and 0 <= (ex - today).days <= 7:
            hint = "팔 계획이면 배당락 전에 파는 편이 평균적으로 나았습니다." if r["market"] == "US" else \
                "팔 계획이면 배당을 받고 배당락일 시가에 파는 편이 평균적으로 나았습니다."
            out.append({"level": "info", "text": f"{r.get('name') or r['symbol']} 배당락 {ex.isoformat()} (D-{(ex - today).days}). {hint}"})
    for r in watch_rows:
        by = r.get("buy_by")
        if by and 0 <= (by - today).days <= 7:
            out.append({"level": "info", "text": f"관심 {r.get('name') or r['symbol']}: 이번 배당을 받으려면 {by.isoformat()} 장 마감까지 보유해야 합니다. "
                                                 "배당만 노린 매수는 세금·수수료 때문에 평균 손해였습니다."})
    if fin["used_pct"] >= 70:
        out.append({"level": "warn" if fin["used_pct"] < 100 else "danger",
                    "text": f"올해 배당(세전) 추정 ₩{fin['total_krw']:,}로 금융소득 종합과세 기준(₩20,000,000)의 {fin['used_pct']:.0f}%입니다. 이자소득도 합산됩니다."})
    return out


def overview():
    uid = _uid()
    trading = _trading()
    state = _STATE.setdefault(uid, {})
    force = str(wiz.request.query("force", "false") or "false").lower() == "true"
    stale = _time.time() - float(state.get("holdings_at") or 0) > _HOLDINGS_TTL_SEC
    if force or stale:
        _start_refresh(uid, refresh_holdings=True, force=force)
    dividend, data_cls = _models()
    data = data_cls(_cache_dir(), dividend)  # reads the cache only
    today = _today()
    fx = float(state.get("fx") or 0)
    fx_estimated = fx <= 0
    fx = fx if fx > 0 else _FX_FALLBACK
    rows, items, pending = [], [], 0
    for h in state.get("holdings") or []:
        entry = data.cached(h["symbol"], h["market"])
        if entry is None:
            pending += 1
        profile = dividend.analyze(data_cls.parse_events(entry), today)
        holding = dict(h)
        if not holding.get("current_price") and entry:
            holding["current_price"] = float(entry.get("price") or 0)
        view = dividend.holding_view(holding, profile, today, fx)
        view.update(name=h.get("name") or h["symbol"], has_data=bool(profile.get("events")), errors=(entry or {}).get("errors", []),
                    sources=(entry or {}).get("sources", []), avg_price=h.get("avg_price"), current_price=holding.get("current_price"))
        rows.append(view)
        items.append((holding, profile, fx))
    watch_rows = []
    for w in _watchlist(trading, uid):
        entry = data.cached(w["symbol"], w["market"])
        if entry is None:
            pending += 1
        profile = dividend.analyze(data_cls.parse_events(entry), today)
        view = dividend.holding_view({**w, "qty": 0, "current_price": float((entry or {}).get("price") or 0)}, profile, today, fx)
        tax = dividend.tax_rate(w["market"])
        view.update(name=w.get("name") or w["symbol"], has_data=bool(profile.get("events")),
                    net_per_share=round(float(view.get("next_amount") or 0) * (1 - tax), 6), errors=(entry or {}).get("errors", []))
        watch_rows.append(view)
    rows.sort(key=lambda r: -(r.get("annual_net_krw") or 0))
    cashflow = dividend.monthly_cashflow(items, today)
    fin = dividend.financial_income_year(items, today)
    payload = {
        "mode": _TRADING_MODE, "today": today, "fx": fx, "fx_estimated": fx_estimated,
        "holdings": rows, "watchlist": watch_rows, "cashflow": cashflow, "financial_income": fin,
        "totals": {"annual_net_krw": sum(r.get("annual_net_krw") or 0 for r in rows),
                   "annual_gross_krw": sum(r.get("annual_gross_krw") or 0 for r in rows),
                   "next12_net_krw": sum(b["net_krw"] for b in cashflow),
                   "this_month_net_krw": cashflow[0]["net_krw"] if cashflow else 0},
        "alerts": _alerts(rows, watch_rows, fin, today),
        "refreshing": bool(state.get("refreshing")), "pending": pending,
        "holdings_at": state.get("holdings_at"), "holdings_errors": state.get("holdings_errors", []),
        "error": state.get("error", ""),
        "kis_dividend_api": _TRADING_MODE == "LIVE",
    }
    wiz.response.status(200, **_jsonable(payload))


def add_watch():
    uid = _uid()
    trading = _trading()
    symbol = str(wiz.request.query("symbol", "") or "").strip().upper()
    market = str(wiz.request.query("market", "US") or "US").strip().upper()
    name = str(wiz.request.query("name", "") or "").strip()[:40]
    if market not in ("US", "KS", "KQ"):
        wiz.response.status(400, message="시장은 미국·코스피·코스닥 중에서 고르세요.")
    if not (_US_SYMBOL if market == "US" else _KR_SYMBOL).match(symbol):
        wiz.response.status(400, message="종목코드 형식이 올바르지 않습니다. (미국: SCHD, 한국: 033780)")
    rows = [r for r in _watchlist(trading, uid) if not (r["symbol"] == symbol and r["market"] == market)]
    if len(rows) >= _MAX_WATCH:
        wiz.response.status(400, message=f"관심 종목은 {_MAX_WATCH}개까지입니다.")
    rows.append({"symbol": symbol, "market": market, "name": name})
    _save_watchlist(trading, uid, rows)
    _start_refresh(uid, refresh_holdings=False, only=[(symbol, market)])
    wiz.response.status(200, watchlist=rows)


def remove_watch():
    uid = _uid()
    trading = _trading()
    symbol = str(wiz.request.query("symbol", "") or "").strip().upper()
    market = str(wiz.request.query("market", "") or "").strip().upper()
    rows = [r for r in _watchlist(trading, uid) if not (r["symbol"] == symbol and r["market"] == market)]
    _save_watchlist(trading, uid, rows)
    wiz.response.status(200, watchlist=rows)
