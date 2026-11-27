"""FireGate SOXL 연결 복구 — 기본은 계획만 출력하고, FireGate·KIS·LIVE DB에 쓰지 않는다.

11-27 LIVE: FireGate SOXL 포트폴리오 1780022179464의 sourceCycleId가 10-03 서버
DB의 사이클(tsevwk…)을 가리킨 채 남았다. 11-09에 LIVE DB를 새로 만든 뒤로는 로컬
체결이 FireGate에 하나도 넘어가지 못했다(10-30 이후 거래 없음, 112주 vs KIS 165주).
PR #42 이후로는 이 연결 불일치 때문에 SOXL 예약·리버스 MOC가 모두 보류된다.

두 가지 방식의 계획을 계산한다. 둘 다 FireGate addTransaction 규칙을 그대로 따른다
(firegate_bridge.calculate_v4_t_delta / firegate_operator / apply_v4_transaction 재사용).

- A: 기존 포트폴리오에 빠진 KIS 체결을 시간순으로 넣는다. 그다음 상태 필드와
  sourceCycleId를 한 번의 PATCH로 현재 사이클로 바꾼다. sourceCycleId는 Firestore
  필드라 updateMask PATCH로 바뀐다(10-03 복구 스크립트가 같은 방식으로 이 값을 썼다).
- B: 현재 사이클에 연결한 새 포트폴리오를 만든다. 기존 포트폴리오의 거래와 그 뒤의
  KIS 체결을 처음부터 하나씩 다시 넣은 뒤, 기존 포트폴리오는 보관(stock8Archived)한다.
  삭제하지 않는다.

--apply는 다음이 모두 맞을 때만 쓴다.
- 확인 문구가 정확히 일치한다.
- 최종 FireGate 보유수량이 KIS 보유수량과 같다.
- 대상이 SOXL에서 실행 중인 유일한 관리 포트폴리오다.

쓰기 전에 대상 포트폴리오와 거래 전체를 JSON으로 백업한다. 진행 기록을 남기고,
쓴 뒤 다시 읽어 검증한다. 같은 거래는 고정 문서 ID로 한 번만 들어간다.
키·토큰·계좌번호는 출력하지 않는다.

KIS는 읽기 조회만 쓴다(GET inquire-ccnl / inquire-balance).
캐시된 토큰만 쓰고 새로 발급하지 않는다. 주문 API는 부르지 않는다.
"""
import argparse
import copy
import datetime
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYMBOL = "SOXL"
DEFAULT_PORTFOLIO_ID = 1780022179464
# Method B's new portfolio id is fixed (2026-11-27 00:00 KST in ms, FireGate's
# id style) so the confirm phrase from a plan run stays valid for --apply.
REBUILD_PORTFOLIO_ID = 1795705200000
REPAIR_ID = "soxl-relink-20261127"
CYCLE_STATUSES = ("ACTIVE", "HOLDING", "PENDING_EXTENSION")
STATE_KEYS = ("holdingQty", "avgPrice", "totalBuy", "totalSell", "tValue", "reverseMode", "reverseState",
              "reverseModeStarPrice", "isRunning", "endDate", "sellPrice")
KIS_READ_PATHS = (
    "/uapi/overseas-stock/v1/trading/inquire-ccnl",
    "/uapi/overseas-stock/v1/trading/inquire-balance",
    "/uapi/overseas-stock/v1/trading/order-resv-list",
)
PRICE_TOLERANCE = 0.006
# FireGate's average carries the 0.25% commission KIS leaves out; a missing or
# extra fill moves it much more than that.
AVG_TOLERANCE_PCT = 1.0
DATE_TOLERANCE_DAYS = 3


def _load_module(name, rel_path, wiz_stub=None):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
    module = importlib.util.module_from_spec(spec)
    if wiz_stub is not None:
        module.wiz = wiz_stub
    spec.loader.exec_module(module)
    return module


fg = _load_module("firegate_relink_bridge", "src/portal/trading/model/struct/firegate_bridge.py")


class RelinkRefused(Exception):
    """A guard failed: nothing was written for this step."""


# ---------------------------------------------------------------------------
# 순수 계산 (오프라인 테스트 대상)
# ---------------------------------------------------------------------------

def parse_date(value):
    """FireGate "2026. 10. 30", ISO, or KIS "20261030" -> date (None when unknown)."""
    text = str(value or "").strip()
    for fmt in ("%Y. %m. %d", "%Y-%m-%d", "%Y.%m.%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(text[:12].strip(), fmt).date()
        except ValueError:
            continue
    return None


def _order_key(order_no):
    return str(order_no or "").strip().lstrip("0")


def redact(text):
    """Firestore errors echo document paths (users/<email>/...); a requests
    error echoes the KIS URL with CANO/ACNT_PRDT_CD. Mask those and anything
    shaped like an account number (12345678-01)."""
    text = re.sub(r"[\w.+-]+(?:@|%40)[\w.-]+", "<email>", str(text or ""))
    text = re.sub(r"(CANO|ACNT_PRDT_CD)=[^&\s]*", r"\1=<account>", text)
    return re.sub(r"(?<![0-9])[0-9]{8}-[0-9]{2}(?![0-9])", "<account>", text)


def _safe_id(text):
    return re.sub(r"[^A-Za-z0-9_-]", "-", str(text or ""))[:120]


def normalize_kis_fills(orders, symbol=SYMBOL):
    """KIS order-history rows -> fills (filled quantity only), one per order line."""
    fills = []
    for row in orders or []:
        if str(row.get("symbol", "") or "").upper() != symbol:
            continue
        qty = int(float(row.get("filled_qty", 0) or 0))
        price = float(row.get("filled_price", 0) or 0)
        side = str(row.get("action", row.get("side", "")) or "").upper()
        day = parse_date(row.get("order_date"))
        if qty <= 0 or price <= 0 or side not in ("BUY", "SELL") or day is None:
            continue
        fills.append({
            "date": day.isoformat(),
            "time": str(row.get("order_time", "") or "")[:6],
            "side": "buy" if side == "BUY" else "sell",
            "qty": qty,
            "price": round(price, 4),
            "order_no": str(row.get("order_no", "") or "").strip(),
            "commission": None,
            "local_trade_id": "",
            "local_cycle_id": "",
            "strategy_type": "",
            "source": "kis",
        })
    return sorted(fills, key=lambda f: (f["date"], f["time"], f["order_no"]))


def normalize_local_fills(trades, symbol=SYMBOL):
    fills = []
    for row in trades or []:
        if str(row.get("symbol", "") or "").upper() != symbol:
            continue
        if str(row.get("status", "") or "").upper() != "FILLED" or fg._is_synthetic_trade_row(row):
            continue
        side = str(row.get("action", "") or "").upper()
        qty = int(float(row.get("filled_qty") or row.get("order_qty") or 0))
        price = float(row.get("filled_price") or row.get("order_price") or 0)
        day = parse_date(row.get("trade_date"))
        if side not in ("BUY", "SELL") or qty <= 0 or price <= 0 or day is None:
            continue
        fills.append({
            "date": day.isoformat(),
            "time": "",
            "side": "buy" if side == "BUY" else "sell",
            "qty": qty,
            "price": round(price, 4),
            "order_no": str(row.get("broker_order_no", "") or "").strip(),
            "commission": float(row.get("commission") or 0),
            "local_trade_id": str(row.get("id", "") or ""),
            "local_cycle_id": str(row.get("cycle_id", "") or ""),
            "strategy_type": str(row.get("strategy_type", "") or ""),
            "source": "local",
        })
    return sorted(fills, key=lambda f: (f["date"], f["order_no"]))


def merge_fills(kis_fills, local_fills, window_start):
    """Attach local trade ids/commissions to KIS fills.

    Returns (fills, problems). Every local fill on/after window_start must be in
    KIS: a local row the broker does not show means one side is wrong."""
    fills = [dict(f) for f in kis_fills]
    used = set()
    problems = []
    for local in local_fills:
        if local["date"] < window_start:
            continue
        match = None
        for i, kis in enumerate(fills):
            if i in used or kis["side"] != local["side"] or kis["qty"] != local["qty"]:
                continue
            if local["order_no"] and _order_key(kis["order_no"]) == _order_key(local["order_no"]):
                match = i
                break
        if match is None:
            problems.append(f"로컬 체결이 KIS 체결내역에 없음: {local['date']} {local['side']} {local['qty']}주 "
                            f"@{local['price']} (주문번호 {local['order_no'] or '-'})")
            continue
        used.add(match)
        fills[match].update(commission=local["commission"], local_trade_id=local["local_trade_id"],
                            local_cycle_id=local["local_cycle_id"], strategy_type=local["strategy_type"])
    return fills, problems


def fill_source_trade_id(fill):
    if fill.get("local_trade_id"):
        return fill["local_trade_id"]
    return _safe_id(f"kis-{fill['order_no'] or 'noorder'}-{fill['date']}-{fill['side']}-{fill['qty']}")


def is_pending_relink_tx(tx, portfolio):
    """A tx this repair created that the portfolio state does not include yet."""
    return (str((tx or {}).get("relinkRepairId", "")) == REPAIR_ID
            and str((portfolio or {}).get("relinkRepairId", "")) != REPAIR_ID)


def find_missing_fills(fg_transactions, fills, portfolio=None):
    """KIS fills with no FireGate transaction. A broker/source id match wins; else
    the same side, size and price within a few days (manual entries carry no id)."""
    pool = [tx for tx in fg_transactions or [] if not is_pending_relink_tx(tx, portfolio)]
    used = set()
    missing = []
    for fill in fills:
        found = None
        ids = {fill_source_trade_id(fill), _order_key(fill.get("order_no"))} - {""}
        for i, tx in enumerate(pool):
            if i in used or str(tx.get("type", "")).lower() != fill["side"]:
                continue
            tx_ids = {str(tx.get("sourceTradeId", "") or ""), _order_key(tx.get("brokerOrderNo"))} - {""}
            if ids & tx_ids and int(float(tx.get("size", 0) or 0)) == fill["qty"]:
                found = i
                break
        if found is None:
            day = parse_date(fill["date"])
            for i, tx in enumerate(pool):
                if i in used or str(tx.get("type", "")).lower() != fill["side"]:
                    continue
                tx_day = parse_date(tx.get("date"))
                if (int(float(tx.get("size", 0) or 0)) == fill["qty"]
                        and abs(float(tx.get("price", 0) or 0) - fill["price"]) < PRICE_TOLERANCE
                        and tx_day is not None and day is not None
                        and abs((tx_day - day).days) <= DATE_TOLERANCE_DAYS):
                    found = i
                    break
        if found is None:
            missing.append(fill)
        else:
            used.add(found)
    return missing


def _commission(fill, portfolio):
    if fill.get("commission") is not None:
        return round(float(fill["commission"]), 2), False
    rate = float((portfolio or {}).get("commissionRate", fg.KIS_US_ONLINE_COMMISSION_RATE) or 0)
    return round(fill["price"] * fill["qty"] * rate / 100.0, 2), True


def tx_from_fill(fill, portfolio_id, cycle_id, state):
    """The transaction the app's push would add for this fill, against `state`."""
    commission, unverified = _commission(fill, state)
    tx = {
        "type": fill["side"],
        "ticker": SYMBOL,
        "date": fg.format_firegate_date(fill["date"]),
        "price": fill["price"],
        "size": fill["qty"],
        "portfolioId": fg._safe_int(portfolio_id, portfolio_id),
        "commission": commission,
        "source": fg.INFINITYSTOCK_SOURCE,
        "sourceTradeId": fill_source_trade_id(fill),
        "sourceCycleId": fill.get("local_cycle_id") or cycle_id,
        "brokerOrderNo": fill.get("order_no", ""),
        "orderType": "EXTERNAL",
        "strategyType": fill.get("strategy_type", ""),
        "relinkRepairId": REPAIR_ID,
        "memo": f"KIS 체결 {fill['date']} {fill['side']} {fill['qty']} @ {fill['price']} — FireGate 연결 복구로 추가",
    }
    if unverified:
        tx["commissionUnverified"] = True
    if tx["type"] == "buy":
        tx["tDelta"] = 0 if tx["strategyType"].upper() == "CRASH_BUY" else fg.calculate_v4_t_delta(state, tx)
    tx.update(fg.firegate_operator(state, tx))
    return tx


def _needs_recent_average(state, tx):
    return (tx.get("type") == "sell" and tx.get("reverseMode")
            and float(state.get("reverseModeStarPrice", 0) or 0) <= 0)


def replay(state, txs, recent_average=None):
    """apply_v4_transaction over txs in order; returns (final, warnings)."""
    warnings = []
    for tx in txs:
        if _needs_recent_average(state, tx) and not recent_average:
            warnings.append(f"{tx.get('date')} 리버스 매도: 별 가격이 없는데 최근 5일 평균을 모름 — 별 가격 0으로 남음")
        state = fg.apply_v4_transaction(state, tx, recent_average=recent_average if _needs_recent_average(state, tx) else None)
    return state, warnings


def summarize_state(state):
    keys = ("holdingQty", "avgPrice", "totalBuy", "totalSell", "tValue", "reverseMode", "reverseState",
            "reverseModeStarPrice", "seed", "divisionDate")
    return {key: (state or {}).get(key) for key in keys}


def plan_append(portfolio, missing, cycle_id, recent_average=None):
    """Method A: missing fills appended to the existing portfolio in time order."""
    state = copy.deepcopy(portfolio)
    txs = []
    warnings = []
    for fill in missing:
        tx = tx_from_fill(fill, portfolio["id"], cycle_id, state)
        tx["_doc_id"] = _safe_id(f"relink-{portfolio['id']}-{tx['sourceTradeId']}")
        state, more = replay(state, [tx], recent_average)
        warnings.extend(more)
        txs.append(tx)
    return {"method": "A", "portfolio_id": portfolio["id"], "transactions": txs, "final": state,
            "warnings": warnings}


def a_portfolio_changes(portfolio, plan, cycle_id, local_trade_ids):
    final = plan["final"]
    changes = {key: final.get(key) for key in STATE_KEYS if key in final}
    reconciled = [str(v) for v in (portfolio.get("reconciledSourceTradeIds") or [])]
    reconciled += [tid for tid in local_trade_ids if tid not in reconciled]
    changes.update(
        sourceCycleId=cycle_id,
        relinkedFromSourceCycleId=str(portfolio.get("sourceCycleId", "") or ""),
        relinkRepairId=REPAIR_ID,
        reconciledSourceTradeIds=reconciled,
        stock8Reconciliation=(f"{REPAIR_ID}: KIS 체결 {len(plan['transactions'])}건 추가, "
                              f"보유 {final.get('holdingQty')}주, 사이클 연결 {cycle_id}"),
    )
    return changes


def _original_replay_txs(transactions):
    valid = []
    for tx in transactions or []:
        if fg._is_synthetic_trade_row({"order_type": tx.get("orderType"), "source": tx.get("source"),
                                       "broker_order_no": tx.get("sourceTradeId"), "memo": tx.get("memo", "")}):
            continue
        if str(tx.get("type", "")).lower() in ("buy", "sell") and float(tx.get("price", 0) or 0) > 0 \
                and int(float(tx.get("size", 0) or 0)) > 0:
            valid.append(tx)
    return sorted(valid, key=fg._transaction_sort_key)


def plan_rebuild(portfolio, fg_transactions, missing, cycle_id, new_portfolio_id, recent_average=None):
    """Method B: a new portfolio linked to the cycle, every original transaction and
    then the missing fills re-entered one by one from zero."""
    new = fg.build_v4_portfolio(
        SYMBOL, portfolio.get("seed"),
        division_count=portfolio.get("divisionDate", 20),
        target_profit=portfolio.get("targetProfit", fg.default_target_profit(SYMBOL)),
        nickname=f"{fg.INFINITYSTOCK_PORTFOLIO_GROUP} | {SYMBOL} | 연결 복구 재구성",
        commission_rate=portfolio.get("commissionRate", fg.KIS_US_ONLINE_COMMISSION_RATE),
        include_state=False,
        source=fg.INFINITYSTOCK_SOURCE,
        source_cycle_id=cycle_id,
        portfolio_group=fg.INFINITYSTOCK_PORTFOLIO_GROUP,
        portfolio_category=fg.INFINITYSTOCK_PORTFOLIO_CATEGORY,
    )
    new.update(id=new_portfolio_id, startDate=portfolio.get("startDate", new.get("startDate")),
               isRunning=False, relinkRepairId=REPAIR_ID, rebuiltFromPortfolioId=portfolio["id"])
    state = copy.deepcopy(new)
    txs = []
    warnings = []
    # The original's star was FireGate's 5-day average when its first reverse
    # sell was entered; replaying that history uses the same value.
    historical_star = float(portfolio.get("reverseModeStarPrice", 0) or 0) or None
    # Transactions an interrupted method-A run left behind are fills that are
    # re-entered below from `missing`; replaying them too would count them twice.
    for original in _original_replay_txs([t for t in fg_transactions or [] if not is_pending_relink_tx(t, portfolio)]):
        tx = {key: original[key] for key in ("type", "ticker", "date", "price", "size", "commission", "source",
                                             "sourceTradeId", "sourceCycleId", "brokerOrderNo", "orderType",
                                             "strategyType", "memo", "commissionUnverified", "tDelta")
              if key in original and original[key] is not None}
        tx.update(portfolioId=new_portfolio_id, relinkRepairId=REPAIR_ID,
                  rebuiltFromTransactionId=str(original.get("_doc_id") or original.get("id") or ""))
        if tx["type"] == "buy" and tx.get("tDelta") is None:
            tx["tDelta"] = fg.calculate_v4_t_delta(state, tx)
        tx.update({k: v for k, v in fg.firegate_operator(state, tx).items() if k not in tx or k == "tOperator"})
        tx["_doc_id"] = _safe_id(f"rebuild-{new_portfolio_id}-{tx['rebuiltFromTransactionId'] or len(txs)}")
        state, more = replay(state, [tx], historical_star)
        warnings.extend(more)
        txs.append(tx)
    for fill in missing:
        tx = tx_from_fill(fill, new_portfolio_id, cycle_id, state)
        tx["_doc_id"] = _safe_id(f"rebuild-{new_portfolio_id}-{tx['sourceTradeId']}")
        state, more = replay(state, [tx], recent_average)
        warnings.extend(more)
        txs.append(tx)
    return {"method": "B", "portfolio_id": new_portfolio_id, "new_portfolio": new, "transactions": txs,
            "final": state, "warnings": warnings}


def managed_running(portfolios, symbol=SYMBOL):
    return [p for p in portfolios or []
            if fg._normalize_symbol(p.get("ticker")) == symbol and not p.get("stock8Archived")
            and fg._firegate_running(p) and fg._is_infinitystock_portfolio(p)]


def reconcile_quantities(kis_sources):
    """kis_sources: {label: qty or None}. Returns (qty, problems)."""
    known = {label: int(qty) for label, qty in kis_sources.items() if qty is not None}
    if not known:
        return None, ["KIS 보유수량을 알 수 없음"]
    values = set(known.values())
    if len(values) > 1:
        return None, ["KIS 보유수량 출처끼리 다름: " + ", ".join(f"{k}={v}" for k, v in known.items())]
    return values.pop(), []


def plan_digest(plan):
    """8 hex chars over every transaction and the final state, so a confirm
    phrase copied from one plan run only applies that exact plan."""
    final = plan["final"]
    material = [[t.get("_doc_id"), t.get("type"), t.get("size"), t.get("price"), t.get("tDelta")]
                for t in plan["transactions"]]
    material.append([final.get(k) for k in ("holdingQty", "avgPrice", "totalBuy", "totalSell", "tValue",
                                            "reverseState", "reverseModeStarPrice")])
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:8]


def confirm_phrase(plan, cycle_id):
    return (f"{plan['method']} {SYMBOL} {plan['portfolio_id']} {plan['final'].get('holdingQty')} "
            f"{cycle_id[:6]} {plan_digest(plan)}")


def apply_refusals(plan, context, confirm_text):
    """Every reason --apply must not write. Empty list = allowed."""
    reasons = list(context.get("problems") or [])
    cycle_id = context["cycle_id"]
    kis_qty = context.get("kis_qty")
    if not context.get("kis_qty_verified"):
        reasons.append("이번 실행에서 KIS 잔고·체결을 직접 조회하지 않음(--no-kis-read/--fills-json으로는 적용 불가)")
    if kis_qty is None or int(plan["final"].get("holdingQty", -1)) != int(kis_qty):
        reasons.append(f"최종 FireGate 보유 {plan['final'].get('holdingQty')}주 ≠ KIS 보유 {kis_qty}주")
    kis_avg = context.get("kis_avg")
    final_avg = float(plan["final"].get("avgPrice", 0) or 0)
    if kis_avg and abs(final_avg - kis_avg) / kis_avg * 100 > AVG_TOLERANCE_PCT:
        reasons.append(f"최종 평단 {final_avg} vs KIS {kis_avg}: {AVG_TOLERANCE_PCT}% 넘게 다름")
    kis_only = [t for t in plan["transactions"] if t.get("commissionUnverified") and not t.get("rebuiltFromTransactionId")]
    if kis_only and not context.get("kis_only_covered"):
        reasons.append(f"로컬 기록이 없는 KIS 체결 {len(kis_only)}건: KIS 전체 종목 보기나 예약주문 이력으로 "
                       "빠진 체결이 없는지 확인하지 못함")
    for warning in plan.get("warnings") or []:
        reasons.append(f"재생 경고: {warning}")
    running = managed_running(context["portfolios"])
    target = context["target"]
    if plan["method"] == "A":
        if [p.get("id") for p in running] != [target.get("id")]:
            reasons.append(f"SOXL 실행 중 관리 포트폴리오가 대상 하나가 아님: {[p.get('id') for p in running]}")
    else:
        # A rerun after the new portfolio was activated but before the old one
        # was archived still sees the old one as the only other running record.
        others = [p.get("id") for p in running if str(p.get("id")) != str(plan["portfolio_id"])]
        if others != [target.get("id")]:
            reasons.append(f"SOXL 실행 중 관리 포트폴리오가 대상 하나가 아님: {others}")
        clash = next((p for p in context.get("all_portfolios", context["portfolios"])
                      if str(p.get("id")) == str(plan["portfolio_id"])
                      and str(p.get("relinkRepairId", "")) != REPAIR_ID), None)
        if clash is not None:
            reasons.append(f"새 포트폴리오 ID {plan['portfolio_id']}를 다른 기록이 쓰고 있음")
    link = str(target.get("sourceCycleId", "") or "")
    if link and link != cycle_id and link in context.get("local_cycle_ids", set()):
        reasons.append(f"대상 포트폴리오가 로컬 DB에 있는 다른 사이클({link})에 연결됨 — 옛 연결이 아님")
    if not plan["transactions"] and str(target.get("sourceCycleId", "")) == cycle_id:
        reasons.append("이미 복구됨: 넣을 거래가 없고 연결도 현재 사이클임")
    expected = confirm_phrase(plan, cycle_id)
    if str(confirm_text or "").strip() != expected:
        reasons.append(f"확인 문구 불일치 (필요: \"{expected}\")")
    return reasons


# ---------------------------------------------------------------------------
# FireGate 쓰기 (--apply 전용)
# ---------------------------------------------------------------------------

class GuardedFireGate(fg.FireGateBridge):
    """GET only unless writes are switched on; never DELETE."""

    def __init__(self, email, id_token, refresh_token=""):
        super().__init__(email, id_token)
        self.allow_writes = False
        self.write_log = []
        self._refresh_token = refresh_token

    def ensure_fresh(self, grace_sec=900):
        """Refresh the id token in memory before writing, so a long KIS read
        does not leave the writes to fail half-way on a 401."""
        if self._refresh_token and fg._id_token_expired_or_stale(self.id_token, grace_sec):
            data = fg.refresh_id_token(self._refresh_token)
            self.id_token = data.get("id_token") or data.get("idToken") or self.id_token

    def _request(self, method, url, body=None, params=None):
        method = str(method).upper()
        if method == "DELETE":
            raise RelinkRefused("FireGate 삭제는 이 스크립트에서 금지")
        if method != "GET":
            if not self.allow_writes:
                raise RelinkRefused(f"계획 단계에서 FireGate 쓰기 시도 차단: {method}")
            self.write_log.append({"method": method, "path": redact(url.split("/documents/", 1)[-1].split("?", 1)[0])})
        return super()._request(method, url, body=body, params=params)


def _clean_tx(tx):
    return {k: v for k, v in tx.items() if not k.startswith("_")}


class Progress:
    def __init__(self, path):
        self.path = Path(path) if path else None
        self.steps = []

    def record(self, step, **detail):
        self.steps.append({"at": datetime.datetime.now().isoformat(timespec="seconds"), "step": step, **detail})
        if self.path:
            self.path.write_text(json.dumps(self.steps, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _existing_doc_ids(client):
    return {str(tx.get("_doc_id", "")): tx for tx in client._list_collection("transactions")}


def _create_planned_transactions(client, plan, progress):
    existing = _existing_doc_ids(client)
    for tx in plan["transactions"]:
        doc_id = tx["_doc_id"]
        if doc_id in existing:
            prior = existing[doc_id]
            same = (str(prior.get("type")) == tx["type"] and int(prior.get("size", 0)) == tx["size"]
                    and abs(float(prior.get("price", 0)) - tx["price"]) < 1e-6
                    and str(prior.get("portfolioId")) == str(tx["portfolioId"]))
            if not same:
                raise RelinkRefused(f"같은 문서 ID에 다른 거래가 있음: {doc_id}")
            progress.record("transaction_exists", doc_id=doc_id)
            continue
        client.create_transaction(_clean_tx(tx), doc_id=doc_id)
        progress.record("transaction_created", doc_id=doc_id, type=tx["type"], size=tx["size"], price=tx["price"])
    after = _existing_doc_ids(client)
    absent = [tx["_doc_id"] for tx in plan["transactions"] if tx["_doc_id"] not in after]
    if absent:
        raise RelinkRefused(f"생성 확인 실패: {absent}")


def _verify_state(actual, expected, cycle_id, label):
    problems = []
    for key in ("holdingQty", "tValue", "reverseState"):
        if actual.get(key) != expected.get(key):
            problems.append(f"{key} {actual.get(key)} ≠ {expected.get(key)}")
    if abs(float(actual.get("avgPrice", 0) or 0) - float(expected.get("avgPrice", 0) or 0)) > 1e-6:
        problems.append(f"avgPrice {actual.get('avgPrice')} ≠ {expected.get('avgPrice')}")
    if str(actual.get("sourceCycleId", "")) != cycle_id:
        problems.append(f"sourceCycleId {actual.get('sourceCycleId')} ≠ {cycle_id}")
    if problems:
        raise RelinkRefused(f"{label} 검증 실패: " + "; ".join(problems))


BASE_KEYS = ("holdingQty", "avgPrice", "totalBuy", "totalSell", "tValue", "reverseMode", "reverseState",
             "reverseModeStarPrice", "sourceCycleId", "isRunning", "stock8Archived", "updatedAt")


def _assert_unchanged(client, base, base_tx_ids, planned_ids=()):
    """Re-read right before the state PATCH: the plan was built from a read
    taken before the (minutes-long) KIS queries. A FireGate edit, an app
    auto-exit PATCH or a new transaction since then means the plan is stale."""
    fresh = client.get_portfolio(base["id"])
    changed = [k for k in BASE_KEYS if fresh.get(k) != base.get(k)]
    ids_now = {str(t.get("_doc_id") or t.get("id")) for t in client.list_transactions(base["id"])}
    expected = {str(i) for i in base_tx_ids} | {str(i) for i in planned_ids}
    if changed or ids_now != expected:
        raise RelinkRefused(f"계획 이후 포트폴리오 {base['id']}가 바뀜(필드 {changed}, 거래 "
                            f"+{sorted(ids_now - expected)[:5]} -{sorted(expected - ids_now)[:5]}) — 상태는 쓰지 않음, 다시 실행")


def apply_a(client, plan, context, progress):
    target_id = plan["portfolio_id"]
    base = context["target"]
    base_tx_ids = [t.get("_doc_id") or t.get("id") for t in context["fg_transactions"]]
    changes = a_portfolio_changes(base, plan, context["cycle_id"], context["local_trade_ids"])
    getattr(client, "ensure_fresh", lambda: None)()
    client.allow_writes = True
    try:
        _create_planned_transactions(client, plan, progress)
        _assert_unchanged(client, base, base_tx_ids, [t["_doc_id"] for t in plan["transactions"]])
        # One PATCH: the engine sees the old state with the old link, or the new
        # state with the new link, never a half-updated portfolio.
        client.update_portfolio(target_id, changes)
        progress.record("portfolio_updated", portfolio_id=target_id, fields=sorted(changes))
    finally:
        client.allow_writes = False
    after = client.get_portfolio(target_id)
    _verify_state(after, plan["final"], context["cycle_id"], "A")
    progress.record("verified", portfolio_id=target_id, holdingQty=after.get("holdingQty"))
    return after


def apply_b(client, plan, context, progress):
    new = plan["new_portfolio"]
    new_id = plan["portfolio_id"]
    old_id = context["target"]["id"]
    base_tx_ids = [t.get("_doc_id") or t.get("id") for t in context["fg_transactions"]]
    getattr(client, "ensure_fresh", lambda: None)()
    client.allow_writes = True
    try:
        existing = {str(p.get("id")): p for p in client.list_portfolios()}
        if str(new_id) not in existing:
            # Archived while it is built: the pull, find_portfolio and the
            # running check all skip stock8Archived, so a half-entered history
            # never reaches the local cycle (isRunning=False alone would not).
            client.create_portfolio({**{k: v for k, v in new.items() if not k.startswith("_")},
                                     "stock8Archived": True}, doc_id=new_id)
            progress.record("portfolio_created", portfolio_id=new_id, isRunning=False, stock8Archived=True)
        elif str(existing[str(new_id)].get("relinkRepairId", "")) != REPAIR_ID:
            raise RelinkRefused(f"새 포트폴리오 ID {new_id}가 다른 기록에 쓰이고 있음")
        _create_planned_transactions(client, plan, progress)
        final = plan["final"]
        activate = {key: final.get(key) for key in STATE_KEYS if key in final}
        activate.update(isRunning=True, stock8Archived=False, sourceCycleId=context["cycle_id"],
                        reconciledSourceTradeIds=list(context["local_trade_ids"]),
                        stock8Reconciliation=f"{REPAIR_ID}: 포트폴리오 {old_id} 거래 재입력 + KIS 체결")
        _assert_unchanged(client, context["target"], base_tx_ids)
        # New first, then archive the old one right after: a moment with two
        # running portfolios blocks (ambiguous); a moment with none would not.
        client.update_portfolio(new_id, activate)
        progress.record("new_portfolio_activated", portfolio_id=new_id)
        client.update_portfolio(old_id, {"isRunning": False, "stock8Archived": True,
                                         "archivedIntoPortfolioId": new_id, "relinkRepairId": REPAIR_ID,
                                         "archiveReason": "FireGate 연결 복구(B): 새 포트폴리오로 재구성, 거래 보존"})
        progress.record("old_portfolio_archived", portfolio_id=old_id)
    finally:
        client.allow_writes = False
    after = client.get_portfolio(new_id)
    _verify_state(after, plan["final"], context["cycle_id"], "B")
    old_after = client.get_portfolio(old_id)
    if old_after.get("isRunning") or not old_after.get("stock8Archived"):
        raise RelinkRefused("기존 포트폴리오 보관 확인 실패")
    progress.record("verified", portfolio_id=new_id, holdingQty=after.get("holdingQty"))
    return after


# ---------------------------------------------------------------------------
# LIVE 읽기 (DB는 ?mode=ro, FireGate·KIS는 GET만)
# ---------------------------------------------------------------------------

class ReadOnlyConfig:
    """trading_config reader for KisApi. Writes are dropped and counted, never stored."""

    def __init__(self, db, user_id, box):
        self.db = db
        self.user_id = user_id
        self.box = box
        self.dropped_writes = []
        self.broker_provider = "kis"
        self.order_policy = None
        self.trade_verifier = None

    def _current_user_id(self):
        return self.user_id

    def get_config(self, key, default=""):
        for storage_key in (f"user:{self.user_id}:{key}", key):
            row = self.db.execute("select value from trading_config where key=?", (storage_key,)).fetchone()
            if row is not None:
                return self.box.decrypt(row[0])
        return default

    def set_config(self, key, *args, **kwargs):
        self.dropped_writes.append(str(key))


def open_live_db(path):
    return sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)


def read_local(db):
    db.row_factory = sqlite3.Row
    cycles = [dict(r) for r in db.execute("select * from trading_cycle where symbol=? order by created", (SYMBOL,))]
    current = [c for c in cycles if str(c.get("status", "")).upper() in CYCLE_STATUSES]
    if len(current) != 1:
        raise RelinkRefused(f"진행 중 SOXL 사이클이 하나가 아님: {[c['id'] for c in current]}")
    trades = [dict(r) for r in db.execute("select * from cycle_trade where symbol=? order by created", (SYMBOL,))]
    snap = db.execute("select created, message from trade_log where symbol=? and event_type like '%BROKER_HOLDING_SNAPSHOT%' "
                      "order by created desc limit 1", (SYMBOL,)).fetchone()
    snapshot = None
    if snap:
        m = re.search(r"broker_qty=(\d+)", snap["message"] or "")
        if m:
            snapshot = {"qty": int(m.group(1)), "at": snap["created"][:19]}
    return {"cycle": current[0], "cycles": cycles, "trades": trades, "snapshot": snapshot}


def firegate_client(db, user_id, box):
    raw = ReadOnlyConfig(db, user_id, box).get_config(fg.FIRE_GATE_BRIDGE_CONFIG_KEY, "{}")
    cfg = json.loads(raw or "{}")
    if not cfg.get("email"):
        raise RelinkRefused("FireGate 브리지 설정을 읽지 못함")
    id_token = cfg.get("id_token", "")
    if not id_token or fg._id_token_expired_or_stale(id_token):
        # Refreshed in memory only; the app's stored session is not touched.
        data = fg.refresh_id_token(cfg.get("refresh_token"))
        id_token = data.get("id_token") or data.get("idToken")
    return GuardedFireGate(cfg["email"], id_token, cfg.get("refresh_token", ""))


def kis_reader(db, user_id, box):
    os.environ["TRADING_MODE"] = "LIVE"
    clock_holder = {}
    stub = type("Wiz", (), {"model": lambda self, name: clock_holder["clock"].Model})()
    clock_holder["clock"] = _load_module("firegate_relink_kst", "src/portal/trading/model/kst.py", stub)
    kis = _load_module("firegate_relink_kis", "src/portal/trading/model/struct/kis_api.py", stub)

    class ReadOnlyKis(kis.KisApi):
        def _issue_token(self, *args, **kwargs):
            raise RuntimeError("캐시된 KIS 토큰이 없거나 만료됨 — 새 발급은 하지 않음")

        def _log(self, *args, **kwargs):
            pass

        def _request(self, method, path, *args, **kwargs):
            if str(method).upper() != "GET" or path not in KIS_READ_PATHS:
                raise RelinkRefused(f"KIS 읽기 외 요청 차단: {method} {path}")
            time.sleep(0.6)
            return super()._request(method, path, *args, **kwargs)

    config = ReadOnlyConfig(db, user_id, box)
    return ReadOnlyKis(config), config


class _KisDataChanged(Exception):
    """SYDB0050: orders changed after page 1; the query must start over."""


def _kis_page(api, params, tr_cont, attempts=4):
    """One inquire-ccnl page; a transient failure is retried, never read as empty."""
    last = None
    for attempt in range(attempts):
        try:
            # request_options sets one deadline for its whole block, so each
            # page gets its own budget instead of sharing one for the read.
            with api.request_options(timeout=15, retries=0):
                data = api._request("GET", KIS_READ_PATHS[0], "TTTS3035R", params=params, tr_cont=tr_cont)
        except RelinkRefused:
            raise
        except Exception as exc:  # shared gateway limit with the running LIVE server
            data, last = None, f"{type(exc).__name__}: {str(exc)[:100]}"
        if data and data.get("rt_cd") == "0":
            return data
        if data:
            if str(data.get("msg_cd", "")) == "SYDB0050":
                raise _KisDataChanged(str(data.get("msg1", "")).strip()[:80])
            last = f"{data.get('msg_cd')} {str(data.get('msg1', '')).strip()[:80]}"
        time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"KIS 체결내역 조회 실패({attempts}회): {last}")


def _read_kis_view(api, pdno, exchange, start_ymd, end_ymd, symbol, max_pages):
    found = []
    nk = fk = ""
    seen = set()
    for page in range(max_pages):
        params = {"CANO": api.account_prefix, "ACNT_PRDT_CD": api.account_suffix, "PDNO": pdno,
                  "ORD_STRT_DT": start_ymd, "ORD_END_DT": end_ymd, "SLL_BUY_DVSN": "00",
                  "CCLD_NCCS_DVSN": "00", "OVRS_EXCG_CD": exchange, "SORT_SQN": "DS", "ORD_DT": "",
                  "ORD_GNO_BRNO": "", "ODNO": "", "CTX_AREA_NK200": nk, "CTX_AREA_FK200": fk}
        data = _kis_page(api, params, "N" if (nk or fk) else "")
        page_rows = api._overseas_ccnl_rows(data)
        for item in page_rows:
            order = api._normalize_overseas_ccnl_row(item, exchange, start_ymd)
            if order and str(order.get("symbol", "")).upper() == symbol:
                found.append({k: v for k, v in order.items() if k != "raw"})
        tr_cont = str(data.get("tr_cont", "") or "")
        cursor = (str(data.get("ctx_area_nk200", "") or "").strip(), str(data.get("ctx_area_fk200", "") or "").strip())
        if not tr_cont and len(page_rows) >= 20:
            # Same rule as the app's strict read: a full page without a
            # continuation flag may have more behind it.
            raise RuntimeError(f"KIS 연속조회 완료 정보 누락: {exchange}/{pdno or 'ALL'} {page + 1}페이지")
        if tr_cont not in ("M", "F"):
            return found
        if not any(cursor) or cursor in seen or cursor == (nk.strip(), fk.strip()):
            raise RuntimeError(f"KIS 연속조회 커서 이상: {exchange}/{pdno or 'ALL'} {page + 1}페이지")
        seen.add(cursor)
        nk, fk = cursor
    raise RuntimeError(f"KIS 연속조회 미완료: {exchange}/{pdno or 'ALL'} {max_pages}페이지 초과")


def read_kis_fills(api, start_ymd, end_ymd, symbol=SYMBOL, max_pages=80, restarts=5):
    """Every SOXL fill line in [start, end]. The symbol view must read to its
    end on each US exchange code (else this raises). The all-symbol view (KIS
    sometimes omits reservation-origin fills when PDNO is set) is added when it
    completes; while other orders keep changing the list (SYDB0050) it cannot.
    Then the filled reservations (order-resv-list, which raises on a partial
    read) stand in for it. Returns (orders, notes, covered): covered is False
    when neither the all-symbol view nor the reservation history was read."""
    rows = {}
    notes = []
    all_view_complete = True
    for pdno in (symbol, ""):
        for exchange in ("NASD", "NYSE", "AMEX"):
            found = None
            for attempt in range(restarts):
                try:
                    found = _read_kis_view(api, pdno, exchange, start_ymd, end_ymd, symbol, max_pages)
                    break
                except _KisDataChanged:
                    time.sleep(3.0)
                except RuntimeError:
                    if pdno:
                        raise
                    break
            if found is None:
                if pdno:
                    raise RuntimeError(f"KIS 조회 중 자료 변경이 계속됨(SYDB0050): {exchange}/{pdno}")
                all_view_complete = False
                notes.append(f"KIS 전체 종목 보기({exchange})는 다른 주문 변경으로 끝까지 읽지 못함")
                continue
            for order in found:
                rows.setdefault(_fill_key(order), order)
    covered = all_view_complete
    if not all_view_complete:
        try:
            reservations = _read_filled_reservations(api, start_ymd, end_ymd, symbol)
        except Exception as exc:
            notes.append(f"KIS 예약주문 이력도 읽지 못함: {type(exc).__name__}: {redact(str(exc))[:100]}")
        else:
            covered = True
            # Multiset: three 1-share LOC fills at one close price are three fills.
            have = {}
            for order in rows.values():
                have[_fill_signature(order)] = have.get(_fill_signature(order), 0) + 1
            extra = []
            for order in reservations:
                sig = _fill_signature(order)
                if have.get(sig, 0) > 0:
                    have[sig] -= 1
                else:
                    extra.append(order)
            for order in extra:
                rows.setdefault(_fill_key(order), order)
            notes.append(f"대신 KIS 예약주문 이력(GET order-resv-list)을 끝까지 읽음: 체결 {len(reservations)}건, "
                         f"종목 보기에 없던 체결 {len(extra)}건")
    return list(rows.values()), notes, covered


def _fill_key(order):
    return (_order_key(order.get("order_no")), order.get("action"), order.get("order_date"),
            int(order.get("filled_qty") or 0), round(float(order.get("filled_price") or 0), 4))


def _fill_signature(order):
    """Same fill whatever order number KIS showed (reservation vs order)."""
    return (str(order.get("action", "")).upper(), str(order.get("order_date", ""))[:8],
            int(order.get("filled_qty") or 0), round(float(order.get("filled_price") or 0), 4))


def _read_filled_reservations(api, start_ymd, end_ymd, symbol):
    """Filled reservation-origin rows, normalized like the app's fallback.
    get_overseas_reservation_orders raises on any partial read; the app's
    _overseas_reservation_history_rows would swallow that, so the list is
    read here once and handed to it for the normalization only."""
    reservations = []
    day = datetime.datetime.strptime(start_ymd, "%Y%m%d").date()
    last = datetime.datetime.strptime(end_ymd, "%Y%m%d").date()
    while day <= last:
        # KIS refuses a reservation-list range of 7 days or more (APBK1744).
        chunk_end = min(day + datetime.timedelta(days=5), last)
        with api.request_options(timeout=60, retries=0):
            reservations.extend(api.get_overseas_reservation_orders(start_date=day.strftime("%Y%m%d"),
                                                                    end_date=chunk_end.strftime("%Y%m%d")) or [])
        day = chunk_end + datetime.timedelta(days=1)
    api.get_overseas_reservation_orders = lambda **_kwargs: reservations
    try:
        rows = api._overseas_reservation_history_rows(start_ymd, end_ymd, None)
    finally:
        del api.get_overseas_reservation_orders
    return [{k: v for k, v in r.items() if k != "raw"} for r in rows
            if str(r.get("symbol", "")).upper() == symbol]


def build_context(args):
    box = _load_module("firegate_relink_secret_box", "src/portal/trading/model/secret_box.py")
    db = open_live_db(args.db)
    local = read_local(db)
    cycle = local["cycle"]
    user_id = cycle["user_id"]
    client = firegate_client(db, user_id, box)
    all_portfolios = client.list_portfolios()
    portfolios = [p for p in all_portfolios if fg._normalize_symbol(p.get("ticker")) == SYMBOL]
    target = next((p for p in portfolios if str(p.get("id")) == str(args.portfolio_id)), None)
    if target is None:
        raise RelinkRefused(f"FireGate 포트폴리오 {args.portfolio_id}를 찾지 못함")
    fg_txs = client.list_transactions(target["id"])
    applied_txs = [t for t in fg_txs if not is_pending_relink_tx(t, target)]
    last_day = max((parse_date(t.get("date")) for t in applied_txs if parse_date(t.get("date"))), default=None)
    window_start = (parse_date(args.since) or last_day or datetime.date.today()).isoformat()
    problems = []
    notes = []
    kis_sources = {}
    if local["snapshot"]:
        kis_sources[f"앱 브로커 스냅샷({local['snapshot']['at']})"] = local["snapshot"]["qty"]
    kis_fills = None
    kis_avg = None
    live_read = False  # --apply needs this run's own KIS balance and fill reads
    covered = False
    if args.kis_qty is not None:
        kis_sources["--kis-qty 입력"] = args.kis_qty  # one more source that must agree
    if args.fills_json:
        kis_fills = normalize_kis_fills(json.loads(Path(args.fills_json).read_text(encoding="utf-8")))
        notes.append(f"체결 목록은 --fills-json({Path(args.fills_json).name})에서 읽음 — 계획 확인용, 적용 불가")
    if not args.no_kis_read and not args.fills_json:
        try:
            api, kis_config = kis_reader(db, user_id, box)
            orders, read_notes, covered = read_kis_fills(api, window_start.replace("-", ""),
                                                         datetime.date.today().strftime("%Y%m%d"))
            notes.extend(read_notes)
            with api.request_options(timeout=30, retries=0):
                balance = api.get_balance()
            holding = [h for h in balance.get("holdings", []) or [] if str(h.get("symbol", "")).upper() == SYMBOL]
            kis_sources["KIS 잔고 조회(이번 실행, GET)"] = sum(int(float(h.get("qty", 0) or 0)) for h in holding)
            kis_avg = float(holding[0].get("avg_price", 0) or 0) if holding else None
            kis_fills = normalize_kis_fills(orders)
            live_read = True
            notes.append(f"KIS 읽기 조회 사용: 체결내역 {window_start}~오늘(GET inquire-ccnl, SOXL 종목 보기는 끝까지), "
                         f"잔고(GET inquire-balance); 앱 설정 쓰기 시도 {len(kis_config.dropped_writes)}건은 저장하지 않음")
        except Exception as exc:  # a failed read is not zero shares or zero fills
            problems.append(f"KIS 조회 실패: {type(exc).__name__}: {redact(str(exc))[:160]}")
    if kis_fills is None:
        local_fills = normalize_local_fills(local["trades"])
        kis_fills = [f for f in local_fills if f["date"] >= window_start]
        problems.append("KIS 체결내역을 읽지 않음: 로컬 기록만으로는 11/09 이전 차이를 확인할 수 없음")
    fills, merge_problems = merge_fills(kis_fills, normalize_local_fills(local["trades"]), window_start)
    fills = [f for f in fills if f["date"] >= window_start]
    problems.extend(merge_problems)
    kis_qty, qty_problems = reconcile_quantities(kis_sources)
    problems.extend(qty_problems)
    return {
        "db": db, "client": client, "local": local, "cycle": cycle, "cycle_id": cycle["id"],
        "local_cycle_ids": {c["id"] for c in local["cycles"]},
        "local_trade_ids": [t["id"] for t in local["trades"]],
        "portfolios": portfolios, "all_portfolios": all_portfolios, "target": target,
        "fg_transactions": fg_txs, "window_start": window_start,
        "fills": fills, "kis_sources": kis_sources, "kis_qty": kis_qty, "kis_avg": kis_avg,
        "kis_qty_verified": live_read, "kis_only_covered": covered, "problems": problems, "notes": notes,
    }


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------

def _fill_line(tx):
    extra = f" tΔ={tx.get('tDelta')}" if tx.get("tDelta") is not None else ""
    return (f"  {tx['date']} {tx['type']:<4} {tx['size']:>4}주 @ {tx['price']:<9} 수수료 {tx['commission']}"
            f"{' (추정)' if tx.get('commissionUnverified') else ''}{extra} {tx.get('tOperator', '')}"
            f"  [{tx.get('brokerOrderNo') or tx.get('sourceTradeId')}]")


def describe(plan, context):
    final = plan["final"]
    lines = [f"■ 방식 {plan['method']} — 포트폴리오 {plan['portfolio_id']}"
             + (" (새로 만듦)" if plan["method"] == "B" else " (기존)")]
    added = [t for t in plan["transactions"] if t.get("relinkRepairId") and not t.get("rebuiltFromTransactionId")]
    if plan["method"] == "B":
        lines.append(f"  기존 거래 재입력 {len(plan['transactions']) - len(added)}건 + 빠진 KIS 체결 {len(added)}건")
    lines.append(f"  넣을 KIS 체결 {len(added)}건 (시간순):")
    lines.extend(_fill_line(t) for t in added)
    lines.append("  최종 상태: " + json.dumps(summarize_state(final), ensure_ascii=False))
    kis_qty = context.get("kis_qty")
    match = kis_qty is not None and final.get("holdingQty") == kis_qty
    lines.append(f"  KIS 대조: FireGate {final.get('holdingQty')}주 vs KIS {kis_qty}주 → {'일치' if match else '불일치'}"
                 + (f" / 평단 FireGate {final.get('avgPrice')} vs KIS {context['kis_avg']}" if context.get("kis_avg") else ""))
    for warning in plan.get("warnings") or []:
        lines.append(f"  주의: {warning}")
    lines.append(f"  확인 문구: \"{confirm_phrase(plan, context['cycle_id'])}\"")
    return "\n".join(lines)


def gap_report(context):
    """Quantity FireGate held at the window start vs what KIS implies then."""
    target = context["target"]
    net_after = sum((1 if f["side"] == "buy" else -1) * f["qty"] for f in context["fills"])
    missing = find_missing_fills(context["fg_transactions"], context["fills"], target)
    net_matched = net_after - sum((1 if f["side"] == "buy" else -1) * f["qty"] for f in missing)
    kis_qty = context.get("kis_qty")
    lines = [f"■ 구간 시작 {context['window_start']} 기준 대조"]
    if kis_qty is not None:
        implied = kis_qty - net_after + net_matched
        lines.append(f"  KIS 역산 보유 {implied}주 (현재 {kis_qty} − 구간 순체결 {net_after} + 이미 FireGate에 있는 {net_matched})"
                     f" vs FireGate 현재 상태 {target.get('holdingQty')}주 → "
                     f"{'일치' if implied == target.get('holdingQty') else '불일치'}")
    tx_net = sum((1 if str(t.get('type')) == 'buy' else -1) * int(float(t.get('size', 0) or 0))
                 for t in _original_replay_txs(context["fg_transactions"]))
    lines.append(f"  FireGate 거래 합계 {tx_net}주 vs FireGate 보유 {target.get('holdingQty')}주"
                 f" (차이 {int(target.get('holdingQty') or 0) - tx_net}주: 10/03·10/12 보정이 거래 없이 보유를 맞춘 몫)")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(ROOT / "data/live/trading.db"))
    parser.add_argument("--portfolio-id", type=int, default=DEFAULT_PORTFOLIO_ID)
    parser.add_argument("--method", choices=("A", "B", "both"), default="both")
    parser.add_argument("--since", help="KIS 체결 조회 시작일(기본: FireGate 마지막 거래일)")
    parser.add_argument("--kis-qty", type=int, help="사용자가 확인한 KIS SOXL 보유수량(다른 출처와 일치해야 함)")
    parser.add_argument("--no-kis-read", action="store_true", help="KIS 조회를 하지 않음(계획 확인용, --apply 불가)")
    parser.add_argument("--fills-json", help="KIS 체결 목록 JSON(계획 확인용, --apply 불가)")
    parser.add_argument("--plan-out", help="계획 JSON 저장 경로")
    parser.add_argument("--apply", choices=("A", "B"), help="FireGate에 실제로 쓴다(확인 문구 필요)")
    parser.add_argument("--confirm", default="", help="계획 출력의 확인 문구를 그대로")
    parser.add_argument("--out-dir", default=str(ROOT / "data/reconciliation-audits"))
    args = parser.parse_args(argv)

    context = build_context(args)
    target = context["target"]
    missing = find_missing_fills(context["fg_transactions"], context["fills"], target)
    recent = None
    if any(t == "sell" for t in (f["side"] for f in missing)) and float(target.get("reverseModeStarPrice", 0) or 0) <= 0:
        prices = context["client"].recent_prices(SYMBOL, 5)
        recent = round(sum(prices) / len(prices), 2) if prices else None
    plans = {}
    if args.method in ("A", "both") or args.apply == "A":
        plans["A"] = plan_append(target, missing, context["cycle_id"], recent)
    if args.method in ("B", "both") or args.apply == "B":
        plans["B"] = plan_rebuild(target, context["fg_transactions"], missing, context["cycle_id"],
                                  REBUILD_PORTFOLIO_ID, recent)

    print(f"SOXL FireGate 연결 복구 계획 ({REPAIR_ID}) — 쓰기 없음" if not args.apply else
          f"SOXL FireGate 연결 복구 ({REPAIR_ID}) — 방식 {args.apply} 적용 시도")
    print(f"대상 포트폴리오 {target['id']}: 연결 {target.get('sourceCycleId')} → 현재 사이클 {context['cycle_id']}")
    print("현재 FireGate 상태: " + json.dumps(summarize_state(target), ensure_ascii=False)
          + f", 거래 {len(context['fg_transactions'])}건, 마지막 갱신 {target.get('updatedAt')}")
    print("KIS 보유수량 출처: " + json.dumps(context["kis_sources"], ensure_ascii=False))
    for note in context["notes"]:
        print("참고: " + note)
    print(gap_report(context))
    for plan in plans.values():
        print(describe(plan, context))
        refusals = apply_refusals(plan, context, args.confirm if args.apply == plan["method"] else "")
        real = [r for r in refusals if not r.startswith("확인 문구")]
        print(f"  --apply {plan['method']} 가능 여부: " + ("가능(확인 문구 필요)" if not real else "불가 — " + " / ".join(real)))
    if args.plan_out:
        Path(args.plan_out).write_text(json.dumps({k: {**v, "transactions": [_clean_tx(t) for t in v["transactions"]]}
                                                   for k, v in plans.items()}, ensure_ascii=False, indent=2, default=str),
                                       encoding="utf-8")
    if not args.apply:
        return 0

    plan = plans[args.apply]
    refusals = apply_refusals(plan, context, args.confirm)
    if refusals:
        print("적용 거부: " + " / ".join(refusals))
        return 2
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = out_dir / f"{REPAIR_ID}-{args.apply}-{stamp}-backup.json"
    backup.write_text(json.dumps({"portfolio": target, "transactions": context["fg_transactions"],
                                  "all_soxl_portfolios": context["portfolios"], "cycle": context["cycle"],
                                  "plan": {**plan, "transactions": [_clean_tx(t) for t in plan["transactions"]]},
                                  "kis_sources": context["kis_sources"]},
                                 ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    progress = Progress(out_dir / f"{REPAIR_ID}-{args.apply}-{stamp}-progress.json")
    progress.record("backup_written", file=backup.name)
    try:
        after = (apply_a if args.apply == "A" else apply_b)(context["client"], plan, context, progress)
    except Exception as exc:
        progress.record("failed", error=f"{type(exc).__name__}: {redact(str(exc))[:300]}")
        print(f"적용 중단: {type(exc).__name__}: {redact(str(exc))[:300]}")
        print(f"진행 기록: {progress.path}  (다시 실행하면 이미 넣은 거래는 건너뜀)")
        return 3
    print("적용 완료·재조회 검증 통과: " + json.dumps(summarize_state(after), ensure_ascii=False)
          + f", 연결 {after.get('sourceCycleId')}")
    print(f"백업: {backup}\n진행 기록: {progress.path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RelinkRefused as exc:
        print(f"중단: {redact(exc)}")
        sys.exit(2)
