"""Per-trade verification (11-04): every KIS order is checked against the broker.

Every regular KIS order request (domestic order-cash, US order) is recorded at
the broker boundary (KisApi._request), whichever engine sent it: KS/US day
trading, infinite buy, manual orders. A read-only pass then checks each order
against KIS and stores one verdict per order:

1. 접수: KIS returned an order number, or an unclear send is found in the
   KIS order list (a rejection is recorded as "거절", nothing was accepted).
2. 주문 내용: KIS's record has the same symbol, side and quantity.
3. 체결 확정: the order is filled or cancelled, or its session ended.
4. 체결가: a fill respects the limit (buy <= limit, sell >= limit).
5. 잔고 반영: a filled buy is in the KIS holdings (minus later sells).
6. 로컬 기록: trade_log / cycle_trade hold the same filled quantity.

A mismatch, or KIS lookups failing for 30 minutes, puts the symbol on hold:
new BUY orders for it are refused at the broker boundary until the check
passes again or the user acknowledges it on the dashboard. Sells, cancels and
exits are never blocked by a hold. The pass only reads (GET); it never sends,
cancels or corrects an order, so an OFF switch stays a no-op.

Reservations (order-resv) keep their own durable receipt check
(KisApi._reservation_write and the LOC verification) and are not recorded
here. Toss and Upbit orders are outside this KIS ledger.

Pure Python with a JSON ledger file per account, so it is unit-tested
without the WIZ runtime.
"""
import datetime
import json
import os
import sys
import tempfile
import threading
import time
import uuid

KST = datetime.timezone(datetime.timedelta(hours=9))

ORDER_PATHS = {
    "/uapi/domestic-stock/v1/trading/order-cash": "KS",
    "/uapi/overseas-stock/v1/trading/order": "US",
}
BUY_TR_IDS = {
    "TTTC0012U", "VTTC0012U",  # KS buy
    "TTTT1002U", "VTTT1002U",  # US buy
    "TTTT3014U", "VTTT3014U",  # US reservation buy (hold check only)
}
SELL_TR_IDS = {"TTTC0011U", "VTTC0011U", "TTTT1006U", "VTTT1001U"}

MAX_RECORDS = 400
FIRST_CHECK_SEC = 20          # give KIS a moment to list the order
RECHECK_SEC = 60
SLOW_RECHECK_SEC = 300        # an order still open after 10 min (US LOC etc.)
NOT_LISTED_SEC = 600          # an order number missing from KIS after 10 min
LOOKUP_FAIL_SEC = 1800        # lookups failing this long -> 확인 불가
FAIL_RECHECK_SEC = 600
FAIL_RECHECK_MAX_SEC = 3 * 86400
LOCAL_GRACE_SEC = {"KS": 900, "US": 26 * 3600}  # US fills sync the next morning
US_SESSION_SEC = 18 * 3600
KS_DAY_END_HHMM = 2010        # NXT closes 20:00
PRICE_TOL = 0.002

PENDING, PASS, FAIL = "PENDING", "PASS", "FAIL"
UNCONFIRMED, REJECTED, NOT_ACCEPTED = "UNCONFIRMED", "REJECTED", "NOT_ACCEPTED"
HOLD_STATUSES = (FAIL, UNCONFIRMED)
FINAL_STATUSES = (PASS, REJECTED, NOT_ACCEPTED)
STATUS_LABELS = {
    PENDING: "검증 대기", PASS: "정상", FAIL: "불일치", UNCONFIRMED: "확인 불가",
    REJECTED: "거절 확인", NOT_ACCEPTED: "미접수 확인",
}
SIDE_LABELS = {"BUY": "매수", "SELL": "매도"}

_LOCKS = sys.__dict__.setdefault("_stock8_trade_verifier_locks", {})
_LOCKS_GUARD = sys.__dict__.setdefault("_stock8_trade_verifier_guard", threading.Lock())


def _path_lock(path):
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(os.path.abspath(path), threading.RLock())


def norm_order_no(value):
    text = str(value or "").strip()
    stripped = text.lstrip("0")
    return stripped or ("0" if text else "")


def norm_symbol(value):
    return str(value or "").strip().upper()


def _int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _side_from_tr_id(tr_id):
    tr_id = str(tr_id or "").upper()
    if tr_id in BUY_TR_IDS:
        return "BUY"
    if tr_id in SELL_TR_IDS:
        return "SELL"
    return ""


def is_order_request(method, path):
    return str(method or "").upper() == "POST" and str(path or "") in ORDER_PATHS


def is_buy_request(method, tr_id):
    return str(method or "").upper() == "POST" and str(tr_id or "").upper() in BUY_TR_IDS


def build_record(path, tr_id, body, data=None, sent=True, error=None, now=None, lane=""):
    """One ledger record for an order request; None when it is not a regular order."""
    market = ORDER_PATHS.get(str(path or ""))
    if not market:
        return None
    body = body if isinstance(body, dict) else {}
    now = now or time.time()
    symbol = norm_symbol(body.get("PDNO") or body.get("OVRS_PDNO"))
    qty = _int(body.get("ORD_QTY") or body.get("OVRS_ORD_QTY") or body.get("FT_ORD_QTY"))
    price = _float(body.get("ORD_UNPR") if market == "KS" else body.get("OVRS_ORD_UNPR"))
    if error is not None:
        if not sent:
            return None  # stopped before transmission: nothing to verify
        outcome, message, order_no = "UNKNOWN", "전송 후 응답 불명", ""
    elif not isinstance(data, dict):
        outcome, message, order_no = "UNKNOWN", "응답 없음", ""
    elif str(data.get("rt_cd", "")) == "0":
        output = data.get("output") or {}
        order_no = str(output.get("ODNO") or output.get("odno") or "")
        outcome = "ACCEPTED" if order_no else "UNKNOWN"
        message = str(data.get("msg1", "") or "")[:200] if order_no else "접수번호 누락"
    else:
        outcome, order_no = "REJECTED", ""
        message = " ".join(str(data.get(k, "") or "") for k in ("msg_cd", "msg1")).strip()[:200]
    stamp = datetime.datetime.fromtimestamp(now, KST)
    return {
        "id": uuid.uuid4().hex[:16],
        "ts": now,
        "at": stamp.strftime("%Y-%m-%d %H:%M:%S"),
        "market": market,
        "symbol": symbol,
        "side": _side_from_tr_id(tr_id),
        "qty": qty,
        "price": price,
        "ord_dvsn": str(body.get("ORD_DVSN", "") or ""),
        "exchange": str(body.get("OVRS_EXCG_CD") or body.get("EXCG_ID_DVSN_CD") or ""),
        "tr_id": str(tr_id or ""),
        "lane": str(lane or ""),
        "outcome": outcome,
        "broker_message": message,
        "order_no": order_no,
        "status": REJECTED if outcome == "REJECTED" else PENDING,
        "checks": [],
        "next_check_ts": now + FIRST_CHECK_SEC,
        "attempts": 0,
    }


def session_over(record, now):
    if record.get("market") == "US":
        return now - _float(record.get("ts")) >= US_SESSION_SEC
    placed = datetime.datetime.fromtimestamp(_float(record.get("ts")), KST)
    current = datetime.datetime.fromtimestamp(now, KST)
    if current.date() > placed.date():
        return True
    return current.hour * 100 + current.minute >= KS_DAY_END_HHMM


def aggregate_order(rows, order_no):
    """KIS's view of one order (rows with that number), or None."""
    key = norm_order_no(order_no)
    if not key:
        return None
    matched = [r for r in rows or [] if norm_order_no(r.get("order_no")) == key]
    if not matched:
        return None
    ord_qty = max(_int(r.get("ord_qty", r.get("order_qty"))) for r in matched)
    fills = [(_int(r.get("filled_qty")), _float(r.get("filled_price"))) for r in matched]
    filled = sum(q for q, _ in fills)
    if ord_qty and filled > ord_qty:
        # Repeated cumulative rows (not separate fills): keep the largest.
        fills = [max(fills)]
        filled = fills[0][0]
    amount = sum(q * p for q, p in fills)
    statuses = {str(r.get("status", "") or "").upper() for r in matched}
    if (ord_qty and filled >= ord_qty) or (not ord_qty and statuses == {"FILLED"}):
        status = "FILLED"
    elif statuses & {"OPEN", "PENDING", "PARTIAL"}:
        status = "PARTIAL" if filled else "OPEN"
    elif statuses & {"CANCELLED", "CANCELED", "REJECTED"}:
        status = "CANCELLED"  # final; a partial fill before the cancel stays counted
    else:
        status = "PARTIAL" if filled else "OPEN"
    first = matched[0]
    return {
        "order_no": str(first.get("order_no", "")),
        "symbol": norm_symbol(first.get("symbol")),
        "side": str(first.get("side") or first.get("action") or "").upper(),
        "ord_qty": ord_qty,
        "filled_qty": filled,
        "filled_price": round(amount / filled, 4) if filled else 0.0,
        "status": status,
    }


def find_unclaimed(rows, record, claimed):
    """For an unclear send: a KIS order with the same symbol/side/qty that no
    other ledger record owns."""
    for row in rows or []:
        number = norm_order_no(row.get("order_no"))
        if not number or number in claimed:
            continue
        if norm_symbol(row.get("symbol")) != record["symbol"]:
            continue
        if str(row.get("side") or row.get("action") or "").upper() != record["side"]:
            continue
        if _int(row.get("ord_qty", row.get("order_qty"))) != _int(record.get("qty")):
            continue
        return str(row.get("order_no"))
    return ""


def _check(key, label, ok, detail=""):
    return {"key": key, "label": label, "ok": ok, "detail": detail}


def evaluate(record, lookup, now, claimed=()):
    """Verdict for one record from one round of broker/local reads.

    lookup: {"orders": rows|None, "orders_error": str, "holdings": int|None,
             "holdings_error": str, "later_sells": int, "local": int|None,
             "local_configured": bool, "local_error": str}
    Returns the record fields to update (status, checks, ...).
    """
    update = {"checks": [], "attempts": _int(record.get("attempts")) + 1, "last_check_ts": now}
    checks = update["checks"]
    age = now - _float(record.get("ts"))

    def lookup_failed(detail):
        first = _float(record.get("first_error_ts")) or now
        update["first_error_ts"] = first
        checks.append(_check("lookup", "브로커 조회", None, detail))
        if now - first >= LOOKUP_FAIL_SEC:
            update["status"] = UNCONFIRMED
            update["reason"] = f"KIS 조회가 {int((now - first) // 60)}분째 실패: {detail}"
        else:
            update["status"] = PENDING
            update["reason"] = "KIS 조회 실패, 재시도 예정"
        return update

    if record.get("outcome") == "REJECTED":
        checks.append(_check("accepted", "접수", True, f"KIS 거절 — 접수되지 않음 ({record.get('broker_message', '')})"))
        update.update(status=REJECTED, reason="KIS가 주문을 거절했습니다 (보유·잔고 변화 없음)")
        return update

    rows = lookup.get("orders")
    if rows is None:
        return lookup_failed(lookup.get("orders_error") or "주문내역 조회 실패")
    update["first_error_ts"] = 0

    order_no = record.get("order_no", "")
    if not order_no:
        adopted = find_unclaimed(rows, record, claimed)
        if adopted:
            order_no = adopted
            update["order_no"] = adopted
            update["outcome"] = "ACCEPTED"
            checks.append(_check("accepted", "접수", True, f"응답 불명 → KIS 주문내역에서 접수 확인 ({adopted})"))
        elif age < NOT_LISTED_SEC:
            checks.append(_check("accepted", "접수", None, "응답 불명 — KIS 주문내역 반영 대기"))
            update.update(status=PENDING, reason="응답이 불명확한 주문을 KIS 주문내역에서 찾는 중")
            return update
        else:
            checks.append(_check("accepted", "접수", True, "응답 불명 주문이 KIS 주문내역에 없음 — 접수되지 않음"))
            update.update(status=NOT_ACCEPTED, reason="응답이 불명확했던 주문이 KIS 주문내역에 없어 미접수로 확정했습니다")
            return update
    else:
        checks.append(_check("accepted", "접수", True, f"접수번호 {order_no}"))

    order = aggregate_order(rows, order_no)
    if order is None:
        if age < NOT_LISTED_SEC:
            checks.append(_check("listed", "주문 내용", None, "KIS 주문내역 반영 대기"))
            update.update(status=PENDING, reason="KIS 주문내역 반영 대기")
        else:
            checks.append(_check("listed", "주문 내용", False, f"접수번호 {order_no}가 KIS 주문내역에 없습니다"))
            update.update(status=FAIL, reason=f"접수번호 {order_no}가 KIS 주문내역에 없습니다")
        return update

    problems = []
    if order["symbol"] and order["symbol"] != record["symbol"]:
        problems.append(f"종목 {record['symbol']}→KIS {order['symbol']}")
    if order["side"] in ("BUY", "SELL") and record.get("side") and order["side"] != record["side"]:
        problems.append(f"구분 {SIDE_LABELS.get(record['side'], record['side'])}→KIS {SIDE_LABELS.get(order['side'], order['side'])}")
    if order["ord_qty"] and order["ord_qty"] != _int(record.get("qty")):
        problems.append(f"수량 {record.get('qty')}주→KIS {order['ord_qty']}주")
    if problems:
        checks.append(_check("listed", "주문 내용", False, " / ".join(problems)))
        update.update(status=FAIL, reason="KIS 주문 내용 불일치: " + " / ".join(problems))
        return update
    checks.append(_check("listed", "주문 내용", True, f"{record['symbol']} {SIDE_LABELS.get(record.get('side'), '')} {record.get('qty')}주"))

    filled = order["filled_qty"]
    update.update(filled_qty=filled, filled_price=order["filled_price"], broker_status=order["status"])
    final = order["status"] in ("FILLED", "CANCELLED") or session_over(record, now)
    if not final:
        checks.append(_check("final", "체결 확정", None, f"{order['status']} · 체결 {filled}/{order['ord_qty'] or record.get('qty')}주"))
        update.update(status=PENDING, reason="체결·취소 확정 대기")
        return update
    final_ts = _float(record.get("final_ts")) or now
    update["final_ts"] = final_ts
    checks.append(_check("final", "체결 확정", True, f"{order['status']} · 체결 {filled}주"
                         + (f" @ {order['filled_price']:g}" if filled else "")))

    failures = []
    pending = []
    limit = _float(record.get("price"))
    if filled and limit > 0:
        fill_price = order["filled_price"]
        if record.get("side") == "BUY" and fill_price > limit * (1 + PRICE_TOL):
            failures.append(f"매수 체결가 {fill_price:g} > 지정가 {limit:g}")
            checks.append(_check("price", "체결가", False, failures[-1]))
        elif record.get("side") == "SELL" and fill_price < limit * (1 - PRICE_TOL):
            failures.append(f"매도 체결가 {fill_price:g} < 지정가 {limit:g}")
            checks.append(_check("price", "체결가", False, failures[-1]))
        else:
            checks.append(_check("price", "체결가", True, f"{fill_price:g} (지정가 {limit:g})"))

    if record.get("side") == "BUY" and filled:
        held = lookup.get("holdings")
        if held is None:
            return lookup_failed(lookup.get("holdings_error") or "잔고 조회 실패")
        expected = max(0, filled - _int(lookup.get("later_sells")))
        if held < expected:
            failures.append(f"KIS 보유 {held}주 < 체결 후 예상 {expected}주 (외부 매도·잔고 미반영 확인 필요)")
            checks.append(_check("holdings", "잔고 반영", False, failures[-1]))
        else:
            checks.append(_check("holdings", "잔고 반영", True, f"KIS 보유 {held}주 ≥ {expected}주"))

    local = lookup.get("local")
    if lookup.get("local_error"):
        pending.append("로컬 기록 조회 재시도")
        checks.append(_check("local", "로컬 기록", None, f"조회 실패: {lookup['local_error']}"))
    elif lookup.get("local_configured") and local is None:
        # The order number was only just found: compare on the next pass.
        pending.append("로컬 기록 대조 대기")
        checks.append(_check("local", "로컬 기록", None, "접수번호 확인 후 다음 검증에서 대조"))
    elif local is not None:
        if local == filled:
            checks.append(_check("local", "로컬 기록", True, f"기록 {local}주 = KIS {filled}주"))
        elif now - final_ts < LOCAL_GRACE_SEC.get(record.get("market"), 900):
            pending.append("로컬 기록 반영 대기")
            checks.append(_check("local", "로컬 기록", None, f"기록 {local}주 / KIS {filled}주 — 동기화 대기"))
        else:
            failures.append(f"로컬 기록 {local}주 ≠ KIS 체결 {filled}주")
            checks.append(_check("local", "로컬 기록", False, failures[-1]))

    if failures:
        update.update(status=FAIL, reason=" / ".join(failures))
    elif pending:
        update.update(status=PENDING, reason=" / ".join(pending))
    else:
        update.update(status=PASS, reason="모든 검증 통과")
    return update


class Ledger:
    """JSON ledger of one account: records (newest last) and acknowledgements."""

    def __init__(self, path):
        self.path = path
        self.lock = _path_lock(path)

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return {"records": [], "last_run": {}}
        except (OSError, ValueError):
            # A corrupt ledger must not look like "nothing to verify":
            # keep the file for inspection and start a fresh one.
            try:
                os.replace(self.path, self.path + ".corrupt")
            except OSError:
                pass
            return {"records": [], "last_run": {}, "corrupt_at": time.time()}
        if not isinstance(data, dict) or not isinstance(data.get("records"), list):
            return {"records": [], "last_run": {}}
        return data

    def save(self, data):
        folder = os.path.dirname(self.path) or "."
        os.makedirs(folder, exist_ok=True)
        data["records"] = list(data.get("records") or [])[-MAX_RECORDS:]
        fd, tmp = tempfile.mkstemp(prefix=".trade_verification.", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def holds_from(records):
    holds = {}
    for record in records:
        if record.get("status") in HOLD_STATUSES and not record.get("acknowledged"):
            holds.setdefault(record.get("symbol"), {
                "symbol": record.get("symbol"), "market": record.get("market"),
                "reason": record.get("reason", ""), "record_id": record.get("id"),
                "at": record.get("at"), "order_no": record.get("order_no", ""),
            })
    return holds


def describe(record):
    side = SIDE_LABELS.get(record.get("side"), record.get("side") or "주문")
    number = f" #{record.get('order_no')}" if record.get("order_no") else ""
    return f"{record.get('market')} {record.get('symbol')} {side} {record.get('qty')}주{number}"


class Verifier:
    """Ledger + broker/local readers + alert callback for one account."""

    def __init__(self, path, broker=None, local=None, notify=None, clock=None):
        self.ledger = Ledger(path)
        self.broker = broker
        self.local = local
        self.notify = notify
        self.clock = clock or time.time

    # ---------------------------------------------------------- recording
    def record(self, path, tr_id, body, data=None, sent=True, error=None, lane=""):
        record = build_record(path, tr_id, body, data=data, sent=sent, error=error, now=self.clock(), lane=lane)
        if record is None:
            return None
        with self.ledger.lock:
            state = self.ledger.load()
            state["records"].append(record)
            self.ledger.save(state)
        return record

    def hold_for(self, symbol):
        symbol = norm_symbol(symbol)
        if not symbol:
            return None
        with self.ledger.lock:
            records = self.ledger.load()["records"]
        return holds_from(records).get(symbol)

    def assert_buy_allowed(self, symbol):
        hold = self.hold_for(symbol)
        if hold:
            raise RuntimeError(
                f"{hold['symbol']}: 거래 검증 불일치로 신규 매수를 보류합니다 ({hold['reason']}). "
                "대시보드 '거래 검증'에서 확인 후 해제하세요.")

    # ---------------------------------------------------------- verifying
    def _due(self, records, now):
        due = []
        for record in records:
            status = record.get("status")
            if status in FINAL_STATUSES or record.get("acknowledged"):
                continue
            if status in HOLD_STATUSES and now - _float(record.get("ts")) > FAIL_RECHECK_MAX_SEC:
                continue
            if now >= _float(record.get("next_check_ts")):
                due.append(record)
        return due

    def verify_due(self, limit=20):
        """One read-only pass over records that are due. Returns a summary."""
        now = self.clock()
        with self.ledger.lock:
            state = self.ledger.load()
            due = self._due(state["records"], now)[:limit]
            claimed = {norm_order_no(r.get("order_no")) for r in state["records"] if r.get("order_no")}
            snapshot = {r["id"]: dict(r) for r in state["records"]}
        if not due:
            return {"checked": 0, "changes": []}

        cache = {}
        updates = {}
        for record in due:
            lookup = self._lookup(record, snapshot, cache)
            update = evaluate(record, lookup, now, claimed=claimed)
            if update.get("order_no"):
                claimed.add(norm_order_no(update["order_no"]))
            status = update.get("status")
            if status in HOLD_STATUSES:
                update["next_check_ts"] = now + FAIL_RECHECK_SEC
            elif now - _float(record.get("ts")) >= NOT_LISTED_SEC:
                update["next_check_ts"] = now + SLOW_RECHECK_SEC
            else:
                update["next_check_ts"] = now + RECHECK_SEC
            if status in FINAL_STATUSES or status in HOLD_STATUSES:
                update["verified_at"] = datetime.datetime.fromtimestamp(now, KST).strftime("%Y-%m-%d %H:%M:%S")
            updates[record["id"]] = update

        changes = []
        with self.ledger.lock:
            state = self.ledger.load()
            for record in state["records"]:
                update = updates.get(record.get("id"))
                if not update:
                    continue
                before = record.get("status")
                record.update(update)
                if before != record.get("status"):
                    changes.append((before, dict(record)))
            state["last_run"] = {"ts": now, "checked": len(updates),
                                 "at": datetime.datetime.fromtimestamp(now, KST).strftime("%Y-%m-%d %H:%M:%S")}
            self.ledger.save(state)
        self._alert(changes)
        return {"checked": len(updates), "changes": [(b, r.get("status"), r.get("id")) for b, r in changes]}

    def _lookup(self, record, snapshot, cache):
        result = {"orders": None, "orders_error": "", "holdings": None, "holdings_error": "",
                  "later_sells": 0, "local": None}
        if record.get("outcome") == "REJECTED" or self.broker is None:
            if self.broker is None:
                result["orders_error"] = "브로커 연결 없음"
            return result
        key = ("orders", record["market"], record["symbol"], record.get("at", "")[:10])
        if key not in cache:
            try:
                cache[key] = (self.broker.orders(record["market"], record["symbol"], record["ts"]), "")
            except Exception as exc:
                cache[key] = (None, str(exc)[:160])
        result["orders"], result["orders_error"] = cache[key]
        if record.get("side") == "BUY":
            hkey = ("holdings", record["market"])
            if hkey not in cache:
                try:
                    cache[hkey] = (self.broker.holdings(record["market"]), "")
                except Exception as exc:
                    cache[hkey] = (None, str(exc)[:160])
            holdings, result["holdings_error"] = cache[hkey]
            if holdings is not None:
                result["holdings"] = _int(holdings.get(record["symbol"], 0))
            later = 0
            for other in snapshot.values():
                if (other.get("symbol") == record["symbol"] and other.get("market") == record["market"]
                        and other.get("side") == "SELL" and _float(other.get("ts")) > _float(record.get("ts"))
                        and other.get("status") not in (REJECTED, NOT_ACCEPTED)):
                    later += _int(other.get("filled_qty")) if other.get("final_ts") else _int(other.get("qty"))
            result["later_sells"] = later
        order_no = record.get("order_no") or ""
        if self.local is not None:
            result["local_configured"] = True
            if order_no:
                try:
                    result["local"] = _int(self.local(order_no))
                except Exception as exc:
                    result["local_error"] = str(exc)[:160] or "조회 실패"
        return result

    def _alert(self, changes):
        if self.notify is None:
            return
        for before, record in changes:
            status = record.get("status")
            text = ""
            if status in HOLD_STATUSES:
                text = (f"⚠️ 거래 검증 {STATUS_LABELS[status]} · {describe(record)} · {record.get('reason', '')}"
                        f" → {record.get('symbol')} 신규 매수 보류")
            elif status == NOT_ACCEPTED:
                text = f"ℹ️ 거래 검증 · {describe(record)} · {record.get('reason', '')}"
            elif status == PASS and before in HOLD_STATUSES:
                text = f"✅ 거래 검증 복구 · {describe(record)} · 다시 일치합니다"
            if text:
                try:
                    self.notify(text)
                except Exception:
                    pass  # an alert must never break verification

    # ---------------------------------------------------------- user view
    def acknowledge(self, symbol="", record_id="", user=""):
        symbol = norm_symbol(symbol)
        stamp = datetime.datetime.fromtimestamp(self.clock(), KST).strftime("%Y-%m-%d %H:%M:%S")
        count = 0
        with self.ledger.lock:
            state = self.ledger.load()
            for record in state["records"]:
                if record.get("status") not in HOLD_STATUSES or record.get("acknowledged"):
                    continue
                if (record_id and record.get("id") == record_id) or (symbol and record.get("symbol") == symbol):
                    record["acknowledged"] = {"at": stamp, "user": str(user or "")}
                    count += 1
            if count:
                self.ledger.save(state)
        return count

    def summary(self, limit=40):
        with self.ledger.lock:
            state = self.ledger.load()
        records = state["records"]
        counts = {}
        for record in records:
            counts[record.get("status")] = counts.get(record.get("status"), 0) + 1
        recent = []
        for record in reversed(records[-limit:]):
            item = {k: record.get(k) for k in (
                "id", "at", "market", "symbol", "side", "qty", "price", "order_no", "status", "reason",
                "filled_qty", "filled_price", "broker_status", "verified_at", "lane", "acknowledged", "checks")}
            item["status_label"] = STATUS_LABELS.get(record.get("status"), record.get("status"))
            item["side_label"] = SIDE_LABELS.get(record.get("side"), record.get("side"))
            recent.append(item)
        return {
            "holds": list(holds_from(records).values()),
            "counts": counts,
            "total": len(records),
            "recent": recent,
            "last_run": state.get("last_run") or {},
        }


class KisReader:
    """Read-only KIS lookups used by the verifier."""

    def __init__(self, kis):
        self.kis = kis

    def orders(self, market, symbol, ts):
        placed = datetime.datetime.fromtimestamp(_float(ts), KST)
        if market == "KS":
            rows = self.kis.get_domestic_fills_for_day(placed.strftime("%Y%m%d"), symbol=symbol)
        else:
            start = (placed - datetime.timedelta(days=1)).strftime("%Y%m%d")
            end = (placed + datetime.timedelta(days=1)).strftime("%Y%m%d")
            rows = self.kis.get_overseas_order_history(start_date=start, end_date=end, symbol=symbol, strict=True)
        return [r for r in rows or [] if not symbol or norm_symbol(r.get("symbol")) in ("", norm_symbol(symbol))]

    def holdings(self, market):
        balance = self.kis.get_domestic_balance() if market == "KS" else self.kis.get_balance()
        totals = {}
        for row in (balance or {}).get("holdings", []) or []:
            symbol = norm_symbol(row.get("symbol"))
            totals[symbol] = totals.get(symbol, 0) + _int(row.get("qty"))
        return totals


def local_filled_reader(trade_log, cycle_trade):
    """order_no -> filled qty recorded locally (daytrade trade_log or
    infinite-buy cycle_trade, whichever holds the order)."""
    def read(order_no):
        variants = {str(order_no), norm_order_no(order_no)}
        variants.discard("")
        log_qty = 0
        cycle_qty = 0
        seen = set()
        for number in variants:
            for row in (trade_log.rows(order_no=number) if trade_log is not None else []) or []:
                if row.get("id") in seen:
                    continue
                seen.add(row.get("id"))
                action = str(row.get("action", "") or "").upper()
                event = str(row.get("event_type", "") or "").upper()
                if action in ("PENDING", "ERROR", "") or event.endswith(("_PENDING", "_ERROR")):
                    continue
                log_qty += _int(row.get("filled_qty"))
            for row in (cycle_trade.rows(broker_order_no=number) if cycle_trade is not None else []) or []:
                if row.get("id") in seen:
                    continue
                seen.add(row.get("id"))
                cycle_qty += _int(row.get("filled_qty"))
        return max(log_qty, cycle_qty)
    return read


class TradeVerifier:
    Verifier = Verifier
    Ledger = Ledger
    KisReader = KisReader
    local_filled_reader = staticmethod(local_filled_reader)
    evaluate = staticmethod(evaluate)
    build_record = staticmethod(build_record)
    is_order_request = staticmethod(is_order_request)
    is_buy_request = staticmethod(is_buy_request)
    norm_order_no = staticmethod(norm_order_no)
    STATUS_LABELS = STATUS_LABELS


Model = TradeVerifier
