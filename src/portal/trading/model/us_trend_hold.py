"""US daily trend hold, PAPER only (10-23 research, pre-registered rule A).

Rule (frozen, do not tune): two sleeves of equal seed.
- QQQ -> hold QLD, SPY -> hold SSO (2x ETFs, both order as AMEX).
- A sleeve holds its ETF while the index's 6-month momentum is positive:
  last completed daily close / the close 126 sessions earlier - 1 > 0
  (adjusted closes). Otherwise the sleeve is all cash.
- Decided on the previous session's close, traded once per session from
  09:35 ET (the backtest traded at the next open).
Evidence (scratchpad us_abc_study.py / us_a_extra.py, 0.10%/side):
2007-07..2016 (pick) +13.5%/yr MDD -34%; 2017..2026-10 (held out) +23.8%/yr
MDD -44%; whole period +18.7%/yr MDD -44% vs QLD+SSO held +20.7%/yr MDD -84%
and QQQ+SPY held +13.8%/yr MDD -54%. It is risk control, not extra return:
V-shaped rebounds (2019, 2020, 2023) are missed.

The engine keeps its own ledger (cash, qty per sleeve) and trades only the
quantity it owns; nothing here touches the day-trade or infinite-buy lanes.
"""
import datetime
import json
import math
import os
import sys
import time

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

PAIRS = (("QQQ", "QLD"), ("SPY", "SSO"))
ORDER_EXCHANGE = "AMEX"
PRICE_EXCHANGE = "AMS"
LOOKBACK = 126
TRADE_START = (9, 35)
TRADE_END = (15, 30)
LIMIT_BUFFER = 0.01           # KIS has no US market order: marketable limit
CASH_USE = 0.99               # leave room for the limit buffer and fees
FEE_SIDE = 0.0007             # PAPER ledger estimate per side (event rate)
PENDING_CHECK_SEC = 60
PENDING_GIVE_UP_SEC = 15 * 60
SEED_MIN, SEED_MAX, SEED_DEFAULT = 1000, 1_000_000, 20_000
POLICY_KEY = "us_trend_hold_policy_v1"
STATUS = sys.__dict__.setdefault("_stock8_us_trend_hold_status", {})


def normalize_policy(raw):
    raw = raw if isinstance(raw, dict) else {}
    try:
        seed = int(float(raw.get("seed_usd", SEED_DEFAULT)))
    except (TypeError, ValueError):
        seed = SEED_DEFAULT
    return {"enabled": bool(raw.get("enabled", False)), "seed_usd": max(SEED_MIN, min(SEED_MAX, seed)),
            "owner_user_id": str(raw.get("owner_user_id", "") or ""), "updated_at": str(raw.get("updated_at", "") or "")}


def momentum(closes, lookback=LOOKBACK):
    """closes: completed daily closes, oldest first. -> (on, pct) or (None, None)."""
    values = [float(c) for c in closes if c and float(c) > 0]
    if len(values) <= lookback:
        return None, None
    pct = (values[-1] / values[-1 - lookback] - 1) * 100
    return pct > 0, pct


def completed(rows, session_date):
    """rows: [(date 'YYYY-MM-DD', close)] -> closes of sessions before session_date."""
    out = []
    for day, close in sorted(rows):
        if str(day)[:10] < session_date:
            out.append(float(close))
    return out


def et_now(epoch):
    if ZoneInfo is not None:
        try:
            return datetime.datetime.fromtimestamp(epoch, ZoneInfo("America/New_York"))
        except Exception:
            pass
    # approximate DST (runtimes without tzdata)
    utc = datetime.datetime.utcfromtimestamp(epoch)
    y = utc.year
    mar1 = datetime.datetime(y, 3, 1)
    start = mar1 + datetime.timedelta(days=(6 - mar1.weekday()) % 7 + 7, hours=7)
    nov1 = datetime.datetime(y, 11, 1)
    end = nov1 + datetime.timedelta(days=(6 - nov1.weekday()) % 7, hours=6)
    return utc + datetime.timedelta(hours=-4 if start <= utc < end else -5)


def round_usd(value):
    return round(float(value), 2) if value >= 1 else round(float(value), 4)


class UsTrendHold:
    def __init__(self, broker, state_dir, policy, closes_fn, log=None, now=None, holiday_fn=None):
        """broker: KIS api (get_current_price, buy_order, sell_order, get_balance,
        get_overseas_order_history). closes_fn(symbol) -> [(date, close)]."""
        self.broker = broker
        self.closes_fn = closes_fn
        self.log = log or (lambda *a, **k: None)
        self.now = now or time.time
        self.holiday_fn = holiday_fn or (lambda day: "")
        os.makedirs(state_dir, exist_ok=True)
        self.state_path = os.path.join(state_dir, "state.json")
        self.state = self._load_state()
        self.policy = normalize_policy(policy)
        self.update_policy(self.policy)

    # ------------------------------------------------------------------ state
    def _load_state(self):
        try:
            with open(self.state_path, encoding="utf-8") as handle:
                state = json.load(handle)
            if isinstance(state, dict) and state.get("version") == 1:
                return state
        except (OSError, ValueError):
            pass
        return {"version": 1, "created_at": int(self.now()), "seed_usd": 0, "sleeves": {}, "signals": {},
                "equity": 0.0, "peak_equity": 0.0, "equity_days": [], "decisions": [], "last_error": ""}

    def save(self):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(self.state, handle, ensure_ascii=False)
        os.replace(tmp, self.state_path)

    def update_policy(self, policy):
        policy = normalize_policy(policy)
        per = float(policy["seed_usd"]) / len(PAIRS)
        sleeves = self.state.setdefault("sleeves", {})
        seed_changed = int(self.state.get("seed_usd") or 0) != policy["seed_usd"]
        for index, etf in PAIRS:
            sleeve = sleeves.get(etf)
            if sleeve is None:
                sleeves[etf] = {"index": index, "cash": per, "alloc_usd": per, "qty": 0, "cost_usd": 0.0,
                                "realized_usd": 0.0, "trades": 0, "wins": 0, "pending": None,
                                "last_session": "", "last_action": "", "last_reason": ""}
            elif seed_changed and not sleeve.get("qty") and not sleeve.get("pending"):
                # a new seed applies to flat sleeves; a held sleeve keeps its ledger
                sleeve.update(cash=per, alloc_usd=per)
        if seed_changed:
            self.state["seed_usd"] = policy["seed_usd"]
            self.state["peak_equity"] = 0.0
        self.policy = policy

    # ------------------------------------------------------------------ step
    def step(self):
        now = self.now()
        et = et_now(now)
        session = et.date().isoformat()
        out = {"next_delay": 300}
        self.state["last_error"] = ""
        try:
            self._resolve_pending(now)
            if self.policy["enabled"] and self._trading_window(et):
                out["next_delay"] = 30
                signals = self._signals(session)
                for index, etf in PAIRS:
                    sleeve = self.state["sleeves"][etf]
                    if sleeve.get("pending") or sleeve.get("last_session") == session:
                        continue
                    self._rebalance(etf, sleeve, signals.get(index), session, now)
            elif self._trading_window(et):
                out["next_delay"] = 60
            if any(s.get("pending") for s in self.state["sleeves"].values()):
                out["next_delay"] = 20
        except Exception as exc:  # the worker keeps running; the page shows it
            self.state["last_error"] = str(exc)[:300]
            self._log("USTH_ERROR", "", "ERROR", f"미장 추세 보유 오류: {exc}", {})
            out["next_delay"] = 120
        self._update_equity(now, session)
        self.save()
        self._publish(now)
        return out

    def _trading_window(self, et):
        if et.weekday() >= 5 or self.holiday_fn(et.date().isoformat()):
            return False
        return TRADE_START <= (et.hour, et.minute) < TRADE_END

    def _signals(self, session):
        cached = self.state.get("signals") or {}
        if cached.get("session") == session:
            return cached.get("by_index") or {}
        by_index = {}
        for index, _etf in PAIRS:
            try:
                closes = completed(self.closes_fn(index) or [], session)
            except Exception as exc:
                closes = []
                self._log("USTH_DATA", index, "DATA", f"{index} 일봉 조회 실패: {exc}", {})
            on, pct = momentum(closes)
            by_index[index] = {"on": on, "mom_pct": None if pct is None else round(pct, 2),
                               "last_close": closes[-1] if closes else None, "bars": len(closes)}
        if all(row["on"] is not None for row in by_index.values()):
            # cache only a complete read; a failed source is retried next tick
            self.state["signals"] = {"session": session, "by_index": by_index}
        return by_index

    def _rebalance(self, etf, sleeve, signal, session, now):
        if not signal or signal.get("on") is None:
            sleeve["last_reason"] = "일봉 데이터 부족 — 이번 회차는 현 상태 유지"
            return
        want = bool(signal["on"])
        held = int(sleeve.get("qty") or 0) > 0
        mom = signal.get("mom_pct")
        reason = f"{sleeve['index']} 6개월 수익률 {mom:+.2f}% → {'보유' if want else '현금'}"
        self._decision(session, etf, want, mom)
        if want == held:
            sleeve["last_session"] = session
            sleeve["last_reason"] = reason + " (변경 없음)"
            return
        quote = self.broker.get_current_price(etf, exchange=PRICE_EXCHANGE) or {}
        price = float(quote.get("price") or 0)
        if price <= 0:
            sleeve["last_reason"] = f"{etf} 현재가 없음 — 다음 확인 때 재시도"
            return
        before = self._broker_qty(etf)
        if want:
            qty = int(math.floor(float(sleeve["cash"]) * CASH_USE / (price * (1 + LIMIT_BUFFER))))
            if qty <= 0:
                sleeve["last_session"] = session
                sleeve["last_reason"] = reason + " · 시드 부족으로 매수 불가"
                return
            limit = round_usd(price * (1 + LIMIT_BUFFER))
            order = self.broker.buy_order(etf, qty, price=limit, order_type="MARKET", exchange=ORDER_EXCHANGE)
            side = "BUY"
        else:
            qty = int(sleeve["qty"])
            if before < qty:
                # the account holds less than this ledger: sell what exists, never more
                qty = before
            if qty <= 0:
                self._close(etf, sleeve, 0, 0.0, reason + " · 계좌에 보유 없음 (원장 정리)", session)
                return
            limit = round_usd(price * (1 - LIMIT_BUFFER))
            order = self.broker.sell_order(etf, qty, price=limit, order_type="MARKET", exchange=ORDER_EXCHANGE)
            side = "SELL"
        sleeve["pending"] = {"side": side, "qty": qty, "limit": limit, "quote": price, "before_qty": before,
                             "before_cost": self._broker_cost(etf), "order_no": str((order or {}).get("order_no", "")),
                             "submitted_at": now, "session": session, "reason": reason}
        sleeve["last_action"] = side
        sleeve["last_reason"] = reason + f" · {('매수' if side == 'BUY' else '매도')} {qty}주 주문 (지정가 ${limit})"
        self._log("USTH_ORDER", etf, side, f"미장 추세 보유 {etf} {'매수' if side == 'BUY' else '매도'} {qty}주 주문 · {reason}",
                  {"qty": qty, "limit": limit, "mom_pct": mom}, price=price, order_no=sleeve["pending"]["order_no"])

    # ---------------------------------------------------------------- fills
    def _holdings(self):
        balance = self.broker.get_balance(exchange=ORDER_EXCHANGE) or {}
        return {str(row.get("symbol", "")).upper(): row for row in balance.get("holdings", []) or []}

    def _broker_qty(self, etf):
        return int(float((self._holdings().get(etf) or {}).get("qty", 0) or 0))

    def _broker_cost(self, etf):
        row = self._holdings().get(etf) or {}
        return float(row.get("qty", 0) or 0) * float(row.get("avg_price", 0) or 0)

    def _order_fill(self, etf, pending):
        try:
            day = et_now(float(pending["submitted_at"])).date()
            start = (day - datetime.timedelta(days=1)).strftime("%Y%m%d")
            end = (day + datetime.timedelta(days=1)).strftime("%Y%m%d")
            history = self.broker.get_overseas_order_history(start_date=start, end_date=end, symbol=etf)
        except Exception:
            return 0, 0.0
        rows = history.get("orders", []) if isinstance(history, dict) else (history or [])
        want = str(pending.get("order_no", "")).lstrip("0")
        for row in rows:
            if want and str(row.get("order_no", "")).lstrip("0") == want:
                return int(row.get("filled_qty") or 0), float(row.get("filled_price") or 0)
        return 0, 0.0

    def _resolve_pending(self, now):
        for etf, sleeve in self.state["sleeves"].items():
            pending = sleeve.get("pending")
            if not pending or now - float(pending["submitted_at"]) < PENDING_CHECK_SEC:
                continue
            filled, fill_px = self._order_fill(etf, pending)
            after = self._broker_qty(etf)
            moved = (after - int(pending["before_qty"])) if pending["side"] == "BUY" else (int(pending["before_qty"]) - after)
            done = max(0, min(int(pending["qty"]), filled or moved))
            if done < int(pending["qty"]) and now - float(pending["submitted_at"]) < PENDING_GIVE_UP_SEC:
                continue  # still working; check again
            if done < int(pending["qty"]) and pending.get("order_no"):
                try:
                    self.broker.cancel_overseas_order(pending["order_no"], etf, int(pending["qty"]) - done, exchange=ORDER_EXCHANGE)
                except Exception:
                    pass
            if fill_px <= 0 and pending["side"] == "BUY" and done > 0:
                added = self._broker_cost(etf) - float(pending.get("before_cost") or 0)
                fill_px = added / done if added > 0 else 0.0
            if fill_px <= 0:
                fill_px = float(pending.get("quote") or 0)
            sleeve["pending"] = None
            if pending["side"] == "BUY":
                if done > 0:
                    cost = done * fill_px * (1 + FEE_SIDE)
                    sleeve["cash"] = float(sleeve["cash"]) - cost
                    sleeve["qty"] = int(sleeve.get("qty") or 0) + done
                    sleeve["cost_usd"] = float(sleeve.get("cost_usd") or 0) + cost
                    sleeve["entry_px"] = fill_px
                    sleeve["last_session"] = pending["session"]
                    sleeve["last_reason"] = pending["reason"] + f" · 매수 {done}주 @ ${fill_px:.2f} 체결"
                    self._log("USTH_FILL", etf, "BUY", f"미장 추세 보유 {etf} {done}주 매수 체결 ${fill_px:.2f}",
                              {"qty": done}, price=fill_px, order_no=pending.get("order_no", ""))
                else:
                    sleeve["last_reason"] = pending["reason"] + " · 매수 미체결 — 다음 확인 때 재시도"
            else:
                if done > 0:
                    self._close(etf, sleeve, done, fill_px, pending["reason"], pending["session"], order_no=pending.get("order_no", ""))
                else:
                    sleeve["last_reason"] = pending["reason"] + " · 매도 미체결 — 다음 확인 때 재시도"

    def _close(self, etf, sleeve, qty, price, reason, session, order_no=""):
        held = int(sleeve.get("qty") or 0)
        qty = min(held, int(qty))
        cost_part = float(sleeve.get("cost_usd") or 0) * (qty / held) if held else 0.0
        proceeds = qty * price * (1 - FEE_SIDE)
        pnl = proceeds - cost_part
        sleeve["cash"] = float(sleeve["cash"]) + proceeds
        sleeve["qty"] = held - qty
        sleeve["cost_usd"] = float(sleeve.get("cost_usd") or 0) - cost_part
        if qty > 0:
            sleeve["realized_usd"] = float(sleeve.get("realized_usd") or 0) + pnl
            sleeve["trades"] = int(sleeve.get("trades") or 0) + 1
            sleeve["wins"] = int(sleeve.get("wins") or 0) + (1 if pnl > 0 else 0)
        if sleeve["qty"] <= 0:
            # an account with less than the ledger: the rest is gone, book it flat
            sleeve["qty"] = 0
            sleeve["cost_usd"] = 0.0
        sleeve["last_session"] = session
        sleeve["last_reason"] = reason + (f" · 매도 {qty}주 @ ${price:.2f} 체결 (손익 ${pnl:+,.2f})" if qty else "")
        self._log("USTH_FILL", etf, "SELL", f"미장 추세 보유 {etf} {qty}주 매도 체결 ${price:.2f} (손익 ${pnl:+,.2f})",
                  {"qty": qty, "pnl_usd": round(pnl, 2)}, price=price, order_no=order_no)

    # ---------------------------------------------------------------- output
    def _decision(self, session, etf, want, mom):
        rows = self.state.setdefault("decisions", [])
        if rows and rows[-1][:2] == [session, etf]:
            return
        rows.append([session, etf, "HOLD" if want else "CASH", mom])
        del rows[:-60]

    def _update_equity(self, now, session):
        equity = 0.0
        for etf, sleeve in self.state["sleeves"].items():
            price = float(sleeve.get("last_price") or sleeve.get("entry_px") or 0)
            if sleeve.get("qty") and self.policy["enabled"] and self._trading_window(et_now(now)):
                try:
                    price = float((self.broker.get_current_price(etf, exchange=PRICE_EXCHANGE) or {}).get("price") or price)
                except Exception:
                    pass
            sleeve["last_price"] = price
            equity += float(sleeve["cash"]) + int(sleeve.get("qty") or 0) * price
        self.state["equity"] = round(equity, 2)
        self.state["peak_equity"] = max(float(self.state.get("peak_equity") or 0), equity)
        days = self.state.setdefault("equity_days", [])
        if not days or days[-1][0] != session:
            days.append([session, round(equity, 2)])
            del days[:-400]
        else:
            days[-1][1] = round(equity, 2)

    def snapshot(self):
        sleeves = []
        for etf, s in self.state["sleeves"].items():
            price = float(s.get("last_price") or 0)
            value = float(s["cash"]) + int(s.get("qty") or 0) * price
            sig = ((self.state.get("signals") or {}).get("by_index") or {}).get(s["index"]) or {}
            sleeves.append({"etf": etf, "index": s["index"], "qty": int(s.get("qty") or 0), "cash": round(float(s["cash"]), 2),
                            "price": price, "value": round(value, 2), "alloc_usd": s.get("alloc_usd"),
                            "unrealized_usd": round(int(s.get("qty") or 0) * price - float(s.get("cost_usd") or 0), 2) if s.get("qty") else 0.0,
                            "realized_usd": round(float(s.get("realized_usd") or 0), 2), "trades": s.get("trades", 0),
                            "wins": s.get("wins", 0), "pending": bool(s.get("pending")), "signal": sig,
                            "last_session": s.get("last_session", ""), "last_reason": s.get("last_reason", "")})
        equity = float(self.state.get("equity") or 0)
        peak = float(self.state.get("peak_equity") or 0)
        return {"enabled": self.policy["enabled"], "seed_usd": self.state.get("seed_usd", 0), "equity": equity,
                "peak_equity": peak, "drawdown_pct": round((equity / peak - 1) * 100, 2) if peak > 0 else 0.0,
                "signals_session": (self.state.get("signals") or {}).get("session", ""), "sleeves": sleeves,
                "decisions": (self.state.get("decisions") or [])[-20:], "equity_days": (self.state.get("equity_days") or [])[-250:],
                "last_error": self.state.get("last_error", "")}

    def _publish(self, now):
        snap = self.snapshot()
        snap["updated_at"] = int(now)
        STATUS.clear()
        STATUS.update(snap)

    def _log(self, event, symbol, action, message, payload, price=0.0, order_no=""):
        try:
            self.log(event, symbol, action, message, dict(payload or {}), price=price, order_no=order_no)
        except Exception:
            pass


UsTrendHold.STATUS = STATUS
UsTrendHold.POLICY_KEY = POLICY_KEY
UsTrendHold.PAIRS = PAIRS
UsTrendHold.SEED_MIN = SEED_MIN
UsTrendHold.SEED_MAX = SEED_MAX
UsTrendHold.normalize_policy = staticmethod(normalize_policy)
UsTrendHold.momentum = staticmethod(momentum)
UsTrendHold.completed = staticmethod(completed)

Model = UsTrendHold
