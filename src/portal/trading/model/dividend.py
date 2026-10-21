"""Dividend management math (10-22). Pure functions, no WIZ or network.

Research behind the page (2015-01..2026-10, yfinance unadjusted prices):
- Buying the day before the ex-date and selling on it loses for a Korean
  resident: US stocks -0.04% per event after the 15% withholding alone,
  -0.28% with 0.07% commissions; Korean stocks +0.01% after 15.4% tax and
  the 0.20% sell tax. The page therefore manages dividends (calendar,
  after-tax cash flow, 20M KRW financial-income threshold, cuts) and does
  not trade the ex-date.
- Small timing rules that held up: in the US avoid buying on the day
  before the ex-date (-0.26% vs buying on the ex-date close) and, if
  selling anyway, sell before the ex-date; in Korea sell at the ex-date
  open after collecting the dividend (+0.34% vs selling the day before).

Dates are datetime.date. Amounts are per share in the listing currency.
"""
import datetime
import statistics

US_TAX = 0.15      # Korea-US treaty withholding on US dividends
KR_TAX = 0.154     # 14% income tax + 1.4% local tax on Korean dividends
FIN_INCOME_LIMIT_KRW = 20000000  # comprehensive taxation threshold (interest + dividends, pre-tax)

# NYSE closures (same table as kis_api.US_MARKET_HOLIDAYS).
US_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
    "2026-09-07", "2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26",
    "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}
# KRX closures incl. substitute holidays and the year-end close.
KR_HOLIDAYS = {
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-02", "2026-05-01", "2026-05-05",
    "2026-05-25", "2026-06-03", "2026-08-17", "2026-09-24", "2026-09-25", "2026-10-05", "2026-10-09",
    "2026-12-25", "2026-12-31",
    "2027-01-01", "2027-02-08", "2027-02-09", "2027-03-01", "2027-05-05", "2027-05-13", "2027-08-16",
    "2027-09-14", "2027-09-15", "2027-09-16", "2027-10-04", "2027-10-11", "2027-12-27", "2027-12-31",
}


def is_us(market):
    return str(market or "").upper() in ("US", "NASD", "NYSE", "AMEX", "NAS", "NYS", "AMS")


def tax_rate(market):
    return US_TAX if is_us(market) else KR_TAX


def is_business_day(market, day):
    if day.weekday() >= 5:
        return False
    return day.isoformat() not in (US_HOLIDAYS if is_us(market) else KR_HOLIDAYS)


def prev_business_day(market, day):
    day = day - datetime.timedelta(days=1)
    while not is_business_day(market, day):
        day -= datetime.timedelta(days=1)
    return day


def ex_date_from_record(market, record_date):
    """US (T+1 since 2024-05-28): ex-date = record date. Korea (T+2):
    ex-date = the business day before the record date."""
    if is_us(market):
        return record_date
    return prev_business_day(market, record_date)


def buy_deadline(market, ex_date):
    """Last trading day whose CLOSE still carries the dividend."""
    return prev_business_day(market, ex_date)


def _frequency(intervals):
    if not intervals:
        return 1, "연 1회"
    gap = statistics.median(intervals)
    if gap <= 45:
        return 12, "매월"
    if gap <= 110:
        return 4, "분기"
    if gap <= 220:
        return 2, "반기"
    return 1, "연 1회"


def _seasonal_amount(history, per_year, ex, last_amount):
    """Last amount scaled by the same slot a year earlier vs the payment a
    year before the last one: keeps growth, restores seasonal patterns
    (e.g. a larger year-end dividend). Monthly payers use the last amount."""
    regular = [h for h in history or [] if not h.get("special")]
    if not regular or per_year not in (1, 2, 4) or last_amount <= 0:
        return last_amount

    def near(day):
        best = min(regular, key=lambda h: abs((h["ex_date"] - day).days))
        return float(best["amount"]) if abs((best["ex_date"] - day).days) <= 45 else 0.0

    slot = near(ex - datetime.timedelta(days=365))
    base = near(regular[-1]["ex_date"] - datetime.timedelta(days=365))
    if slot > 0 and base > 0:
        return round(last_amount * slot / base, 6)
    return last_amount


def analyze(events, today):
    """events: [{"ex_date", "amount", "pay_date"?, "record_date"?, "confirmed"?,
    "special"?}] in any order. Returns the dividend profile used by the page."""
    rows = sorted([e for e in events or [] if e.get("ex_date") and float(e.get("amount") or 0) > 0],
                  key=lambda e: e["ex_date"])
    past = [e for e in rows if e["ex_date"] < today and not e.get("special")]
    upcoming = [e for e in rows if e["ex_date"] >= today]
    out = {"per_year": 0, "frequency": "-", "ttm_dps": 0.0, "last_ex": None, "last_amount": 0.0,
           "next": None, "cut": None, "variable": False, "history": [], "events": len(rows)}
    if not past and not upcoming:
        return out
    dates = [e["ex_date"] for e in past[-7:]]
    intervals = [(b - a).days for a, b in zip(dates, dates[1:])]
    per_year, label = _frequency(intervals)
    out.update(per_year=per_year, frequency=label)
    year_ago = today - datetime.timedelta(days=365)
    out["ttm_dps"] = round(sum(float(e["amount"]) for e in past if e["ex_date"] >= year_ago), 6)
    if past:
        out["last_ex"] = past[-1]["ex_date"]
        out["last_amount"] = float(past[-1]["amount"])
    lags = [(e["pay_date"] - e["ex_date"]).days for e in past[-8:] if e.get("pay_date")]
    lag = int(statistics.median(lags)) if lags else None
    recent = [float(e["amount"]) for e in past[-12:]]
    if len(recent) >= 4 and statistics.mean(recent) > 0:
        cv = statistics.pstdev(recent) / statistics.mean(recent)
        out["variable"] = per_year == 12 and cv > 0.15  # covered-call style payouts
    # Cut: the latest payment vs the one about a year earlier, both
    # annualised at their own cadence, so a switch from quarterly to monthly
    # payments (HDV 2026) is reported as a frequency change, not a cut.
    if len(past) >= 3:
        last = past[-1]
        target = last["ex_date"] - datetime.timedelta(days=365)
        prior = min(past[:-1], key=lambda e: abs((e["ex_date"] - target).days))
        if abs((prior["ex_date"] - target).days) <= 60:
            # cadence at that time: only payments up to the prior one
            near = [e["ex_date"] for e in past if 0 <= (prior["ex_date"] - e["ex_date"]).days <= 200]
            if len(near) >= 2:
                prior_per_year, prior_label = _frequency([(b - a).days for a, b in zip(near, near[1:])])
            else:
                prior_per_year, prior_label = per_year, label
            recent_per_year, _label = _frequency(intervals[-3:])
            latest_rate = float(last["amount"]) * recent_per_year
            prior_rate = float(prior["amount"]) * prior_per_year
            if prior_per_year != recent_per_year:
                out["frequency_changed"] = {"from": prior_label, "to": _label}
            if prior_rate > 0 and latest_rate < prior_rate * 0.9 and not out["variable"]:
                out["cut"] = {"pct": round((latest_rate / prior_rate - 1) * 100, 1), "vs": prior["ex_date"]}
    if upcoming:
        nxt = upcoming[0]
        out["next"] = {"ex_date": nxt["ex_date"], "amount": float(nxt["amount"]),
                       "pay_date": nxt.get("pay_date") or (nxt["ex_date"] + datetime.timedelta(days=lag) if lag else None),
                       "record_date": nxt.get("record_date"), "confirmed": bool(nxt.get("confirmed", True)), "projected": False,
                       "amount_estimated": bool(nxt.get("amount_estimated"))}
    elif past:
        gap = statistics.median(intervals) if intervals else 365
        ex = past[-1]["ex_date"] + datetime.timedelta(days=round(gap))
        while ex < today:
            ex += datetime.timedelta(days=round(gap))
        history = [{"ex_date": e["ex_date"], "amount": float(e["amount"]), "special": bool(e.get("special"))} for e in rows]
        last_amount = float(past[-1]["amount"])
        skipped = ex - datetime.timedelta(days=round(gap))
        if skipped > past[-1]["ex_date"] + datetime.timedelta(days=round(gap * 0.5)):
            pay = skipped + datetime.timedelta(days=lag if lag is not None else 21)
            if pay >= today:
                out["pending"] = {"ex_date": skipped, "pay_date": pay, "amount": _seasonal_amount(history, per_year, skipped, last_amount),
                                  "confirmed": False, "projected": True, "unannounced": True}
        out["next"] = {"ex_date": ex, "amount": _seasonal_amount(history, per_year, ex, last_amount),
                       "pay_date": ex + datetime.timedelta(days=lag) if lag else None,
                       "record_date": None, "confirmed": False, "projected": True}
        # Expected payment missing for more than a full cycle and a month.
        if (today - past[-1]["ex_date"]).days > gap + 45:
            out["missed"] = True
    out["history"] = [{"ex_date": e["ex_date"], "amount": float(e["amount"]), "pay_date": e.get("pay_date"),
                       "special": bool(e.get("special"))} for e in rows[-12:]]
    out["lag_days"] = lag
    out["interval_days"] = round(statistics.median(intervals)) if intervals else None
    return out


def schedule(profile, today, months=12):
    """Payments still to come within `months`: ex-dates already passed but
    not yet paid, an unannounced payment the cadence expects, then the next
    announced or projected ex-date repeated at the usual interval."""
    end = today + datetime.timedelta(days=round(months * 30.44))
    gap = profile.get("interval_days") or round(365 / max(1, profile.get("per_year") or 1))
    lag = profile.get("lag_days")
    default_lag = lag if lag is not None else 21
    out = []
    for h in profile.get("history") or []:
        if h["ex_date"] < today:
            pay = h.get("pay_date") or (h["ex_date"] + datetime.timedelta(days=default_lag))
            if today <= pay <= end:
                out.append({"ex_date": h["ex_date"], "pay_date": pay, "amount": float(h["amount"]), "confirmed": True})
    pending = profile.get("pending")
    if pending and pending["pay_date"] <= end:
        out.append({"ex_date": pending["ex_date"], "pay_date": pending["pay_date"], "amount": float(pending["amount"]),
                    "confirmed": False, "unannounced": True})
    nxt = profile.get("next")
    if not nxt:
        return out
    ex, amount, pay = nxt["ex_date"], float(nxt["amount"]), nxt.get("pay_date")
    first = True
    while ex <= end:
        pay_day = pay if first and pay else ex + datetime.timedelta(days=default_lag)
        confirmed = bool(first and nxt.get("confirmed") and not nxt.get("projected"))
        out.append({"ex_date": ex, "pay_date": pay_day, "amount": amount, "confirmed": confirmed})
        first = False
        ex = ex + datetime.timedelta(days=gap)
        amount = _seasonal_amount(profile.get("history"), profile.get("per_year") or 0, ex,
                                  float(profile.get("last_amount") or amount) if not confirmed else amount)
    return out


def holding_view(holding, profile, today, fx=1.0):
    """Per-holding dividend figures. holding: {symbol, market, qty, avg_price, current_price}."""
    market = holding.get("market") or "KS"
    qty = float(holding.get("qty") or 0)
    tax = tax_rate(market)
    krw = float(fx or 1.0) if is_us(market) else 1.0
    ttm = float(profile.get("ttm_dps") or 0)
    price = float(holding.get("current_price") or 0)
    avg = float(holding.get("avg_price") or 0)
    nxt = profile.get("next") or {}
    view = {
        "symbol": holding.get("symbol"), "market": market, "name": holding.get("name", ""), "qty": qty,
        "frequency": profile.get("frequency", "-"), "per_year": profile.get("per_year", 0),
        "last_amount": profile.get("last_amount", 0), "ttm_dps": ttm,
        "yield_pct": round(ttm / price * 100, 2) if price > 0 and ttm > 0 else None,
        "yoc_pct": round(ttm / avg * 100, 2) if avg > 0 and ttm > 0 else None,
        "annual_gross_krw": round(ttm * qty * krw),
        "annual_net_krw": round(ttm * qty * krw * (1 - tax)),
        "tax_pct": round(tax * 100, 1),
        "next_ex_date": nxt.get("ex_date"), "next_pay_date": nxt.get("pay_date"), "next_amount": nxt.get("amount"),
        "next_confirmed": bool(nxt.get("confirmed")) and not nxt.get("projected"),
        "next_amount_estimated": bool(nxt.get("amount_estimated")) or bool(nxt.get("projected")),
        "next_net_krw": round(float(nxt.get("amount") or 0) * qty * krw * (1 - tax)) if nxt else 0,
        "buy_by": buy_deadline(market, nxt["ex_date"]) if nxt.get("ex_date") else None,
        "cut": profile.get("cut"), "variable": profile.get("variable", False), "missed": profile.get("missed", False),
        "frequency_changed": profile.get("frequency_changed"),
        "pending": profile.get("pending"),
    }
    return view


def monthly_cashflow(items, today, months=12):
    """items: [(holding, profile, fx)] -> 12 monthly buckets of net KRW."""
    buckets = []
    start = today.replace(day=1)
    for i in range(months):
        y, m = start.year + (start.month - 1 + i) // 12, (start.month - 1 + i) % 12 + 1
        buckets.append({"month": f"{y}-{m:02d}", "net_krw": 0.0, "gross_krw": 0.0, "confirmed_krw": 0.0, "items": []})
    index = {b["month"]: b for b in buckets}
    for holding, profile, fx in items:
        market = holding.get("market") or "KS"
        qty = float(holding.get("qty") or 0)
        krw = float(fx or 1.0) if is_us(market) else 1.0
        for pay in schedule(profile, today, months):
            day = pay["pay_date"] or pay["ex_date"]
            key = f"{day.year}-{day.month:02d}"
            if key not in index:
                continue
            gross = pay["amount"] * qty * krw
            net = gross * (1 - tax_rate(market))
            bucket = index[key]
            bucket["gross_krw"] += gross
            bucket["net_krw"] += net
            if pay["confirmed"]:
                bucket["confirmed_krw"] += net
            bucket["items"].append({"symbol": holding.get("symbol"), "net_krw": round(net), "confirmed": pay["confirmed"],
                                    "pay_date": day.isoformat()})
    for b in buckets:
        for k in ("net_krw", "gross_krw", "confirmed_krw"):
            b[k] = round(b[k])
    return buckets


def financial_income_year(items, today):
    """Pre-tax dividend income for the calendar year: paid so far (history x
    current quantity, an estimate) plus what is still expected."""
    year = today.year
    received = expected = 0.0
    for holding, profile, fx in items:
        market = holding.get("market") or "KS"
        qty = float(holding.get("qty") or 0)
        krw = float(fx or 1.0) if is_us(market) else 1.0
        lag = profile.get("lag_days") or 21
        for e in profile.get("history") or []:
            pay = e.get("pay_date") or (e["ex_date"] + datetime.timedelta(days=lag))
            if pay.year == year and pay < today:
                received += float(e["amount"]) * qty * krw
        for pay in schedule(profile, today, 12):
            day = pay["pay_date"] or pay["ex_date"]
            if day.year == year and day >= today:
                expected += pay["amount"] * qty * krw
    total = received + expected
    return {"year": year, "received_krw": round(received), "expected_krw": round(expected), "total_krw": round(total),
            "limit_krw": FIN_INCOME_LIMIT_KRW, "used_pct": round(total / FIN_INCOME_LIMIT_KRW * 100, 1)}


class Dividend:
    US_TAX = US_TAX
    KR_TAX = KR_TAX
    FIN_INCOME_LIMIT_KRW = FIN_INCOME_LIMIT_KRW
    is_us = staticmethod(is_us)
    tax_rate = staticmethod(tax_rate)
    prev_business_day = staticmethod(prev_business_day)
    ex_date_from_record = staticmethod(ex_date_from_record)
    buy_deadline = staticmethod(buy_deadline)
    analyze = staticmethod(analyze)
    schedule = staticmethod(schedule)
    holding_view = staticmethod(holding_view)
    monthly_cashflow = staticmethod(monthly_cashflow)
    financial_income_year = staticmethod(financial_income_year)


Model = Dividend
