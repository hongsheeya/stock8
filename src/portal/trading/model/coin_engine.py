"""Upbit coin automation engine (admin only, LIVE server process only, 10-22).

Rule: coin_strategy (frozen "breakout 4h_N55_atr4" since 10-24). Each market is an
independent sleeve with seed/N KRW: all-in when long, cash when flat,
compounding on its own ledger (the exchange KRW balance is shared, so the
ledger - not the balance - says what belongs to the automation).

Modes (policy row "coin_policy_v1", read from the DB on every pass):
- off    : strict no-op (no Upbit call at all; open positions are left alone).
- shadow : real quotes, hypothetical fills (best ask/bid, 0.05% fee), no orders.
- live   : market orders through UpbitApi with an order guard that re-reads
           the policy before every POST/DELETE.
Shadow and live keep separate ledgers (state_shadow.json / state_live.json).

Timing: decisions at each UTC 4h close + 10 s (00/04/08/12/16/20 UTC);
entries only within 15 min of the close; stops are watched every few seconds
while long (Upbit has no server-side stop orders). After a sleep or restart
stops are ratcheted through the missed bars and checked against the price.
Kill switch: equity 10% below its peak halts new entries until resumed.

No WIZ globals here: the worker injects the API, paths and the log writer,
so tests drive this module directly.
"""
import hashlib
import json
import math
import os
import sys
import time

STATUS = sys.__dict__.setdefault("_stock8_coin_status", {})
PROBE_STATUS = sys.__dict__.setdefault("_stock8_coin_probe_status", {})
_LOG_SEEN = sys.__dict__.setdefault("_stock8_coin_log_seen", {})

POLICY_KEY = "coin_policy_v1"
ALL_MARKETS = ("KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE")
# DOGE: a 1 KRW tick at ~110 KRW costs ~0.9% per tick; off unless chosen.
DEFAULT_MARKETS = ("KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL")
MODES = ("off", "shadow", "live")
# 10-25 fidelity probe: liquid coins traded in shadow only, in their own
# ledger, to exercise entries/stops/stream/slippage faster. Never live, never
# part of the 4-coin performance or the kill switch (backtests: more coins
# hurt returns, research/2026-10/coin/universe).
PROBE_MARKETS = ("KRW-DOGE", "KRW-ADA", "KRW-SUI", "KRW-XLM", "KRW-TRX",
                 "KRW-LINK", "KRW-AVAX", "KRW-DOT", "KRW-HBAR", "KRW-NEAR")
PROBE_SEED = 1000000
SEED_MIN, SEED_MAX = 50000, 10000000
FEE_SIDE = 0.0005
HISTORY_HOURS = 80 * 24
DECISION_DELAY_SEC = 10
ENTRY_WINDOW_SEC = 15 * 60
KILL_DRAWDOWN = 0.10
RECONCILE_SEC = 60
MIN_ORDER_KRW = 5000
DUST_KRW = 1000
PENDING_GIVE_UP_SEC = 90
REST_POLL_SEC = 3


def account_fingerprint(access_key):
    key = str(access_key or "").strip()
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12] if key else ""


def owner_scope(owner):
    return hashlib.sha256(str(owner or "").encode("utf-8")).hexdigest()[:16]


def normalize_policy(raw):
    raw = raw if isinstance(raw, dict) else {}
    mode = str(raw.get("mode", "off") or "off").lower()
    if mode not in MODES:
        mode = "off"
    try:
        seed = int(float(raw.get("seed_krw", 1000000) or 1000000))
    except (TypeError, ValueError):
        seed = 1000000
    seed = max(SEED_MIN, min(SEED_MAX, seed))
    markets = [m for m in (raw.get("markets") or DEFAULT_MARKETS) if m in ALL_MARKETS]
    if not markets:
        markets = list(DEFAULT_MARKETS)
    try:
        max_order = int(float(raw.get("max_order_krw", 0) or 0))
    except (TypeError, ValueError):
        max_order = 0
    per_sleeve = seed // len(markets)
    if max_order <= 0:
        max_order = per_sleeve * 2  # room for a sleeve that has compounded
    return {
        "mode": mode, "seed_krw": seed, "markets": markets, "max_order_krw": max(MIN_ORDER_KRW, max_order),
        "owner_user_id": str(raw.get("owner_user_id", "") or ""),
        "account_fp": str(raw.get("account_fp", "") or ""),
        "live_confirmed_at": str(raw.get("live_confirmed_at", "") or ""),
        "resume_at": str(raw.get("resume_at", "") or ""),
        "probe": bool(raw.get("probe", True)),
        "updated_at": str(raw.get("updated_at", "") or ""),
    }


def bar_floor(sec, bar_sec):
    return int(sec) // bar_sec * bar_sec


class CoinEngine:
    def __init__(self, api, state_dir, candle_dir, policy, strategy, log=None, now=None, sleep=None, error_cls=Exception, stream=None,
                 probe=False):
        self.probe = bool(probe)
        self.api = api
        self.stream = stream  # upbit_ws.TradeStream: every trade of the held markets
        self._rest_at = 0.0
        self.S = strategy
        self.state_dir = state_dir
        self.candle_dir = candle_dir
        self.policy = self._shape(policy)
        self.mode = self.policy["mode"]
        if self.mode not in ("shadow", "live"):
            raise ValueError("coin engine runs only in shadow or live mode")
        self.log = log or (lambda *a, **k: None)
        self.now = now or time.time
        self.sleep = sleep or time.sleep
        self.ApiError = error_cls
        self.candles = {}
        self.prices = {}
        os.makedirs(state_dir, exist_ok=True)
        os.makedirs(candle_dir, exist_ok=True)
        self.state_path = os.path.join(state_dir, "state_probe.json" if self.probe else f"state_{self.mode}.json")
        self.state = self._load_state()
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
        return {"version": 1, "mode": self.mode, "created_at": int(self.now()), "seed_krw": 0, "sleeves": {},
                "peak_equity": 0.0, "halted": False, "halt_reason": "", "last_decision_bar_end": 0,
                "last_reconcile_at": 0, "decisions": [], "equity_days": []}

    def save(self):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(self.state, handle, ensure_ascii=False)
        os.replace(tmp, self.state_path)  # atomic: a crash never leaves half a ledger

    def _new_sleeve(self, cash):
        return {"cash": float(cash), "alloc_krw": float(cash), "volume": 0.0, "long": False, "entry_px": 0.0,
                "entry_time": 0, "cost_krw": 0.0, "hh": 0.0, "stop": 0.0, "signal_bar_end": 0, "last_bar_end": 0,
                "pending": None, "realized_krw": 0.0, "trades": 0, "wins": 0, "last_action": "", "last_reason": "",
                "indicators": {}, "active": True}

    def _shape(self, policy):
        policy = normalize_policy(policy)
        if self.probe:
            if policy["mode"] == "off":
                raise ValueError("coin engine runs only in shadow or live mode")
            policy.update(mode="shadow", markets=list(PROBE_MARKETS), seed_krw=PROBE_SEED, resume_at="")
        return policy

    def update_policy(self, policy):
        policy = self._shape(policy)
        markets = policy["markets"]
        per = float(policy["seed_krw"] // len(markets))
        sleeves = self.state.setdefault("sleeves", {})
        seed_changed = int(self.state.get("seed_krw") or 0) != policy["seed_krw"]
        for market in markets:
            sleeve = sleeves.get(market)
            if sleeve is None:
                sleeves[market] = self._new_sleeve(per)
            else:
                sleeve["active"] = True
                if seed_changed and not sleeve.get("long") and not sleeve.get("pending"):
                    sleeve.update(cash=per, alloc_krw=per)
        for market, sleeve in list(sleeves.items()):
            if market not in markets:
                if sleeve.get("long") or sleeve.get("pending"):
                    sleeve["active"] = False  # wind down: manage the exit, no new entries
                else:
                    sleeves.pop(market)
        if seed_changed:
            self.state["seed_krw"] = policy["seed_krw"]
            self.state["peak_equity"] = 0.0
        if policy.get("resume_at") and policy["resume_at"] != self.state.get("resumed_at"):
            # the page asked to lift the kill switch (the worker owns the ledger)
            self.state["resumed_at"] = policy["resume_at"]
            if self.state.get("halted"):
                self.state.update(halted=False, halt_reason="", peak_equity=float(self.state.get("equity") or 0))
                self._log("COIN_RESUME", "", "RESUME", "코인 자동매매 신규 진입 재개 (관리자)", {})
        self.policy = policy

    # ---------------------------------------------------------------- candles
    def _candle_path(self, market):
        return os.path.join(self.candle_dir, f"{market}_60m.json")

    def sync_candles(self, market, now_sec):
        rows = self.candles.get(market)
        if rows is None:
            try:
                with open(self._candle_path(market), encoding="utf-8") as handle:
                    rows = json.load(handle)
            except (OSError, ValueError):
                rows = []
        by_t = {int(r["t"]): r for r in rows}
        last = max(by_t) if by_t else 0
        need_from = int(now_sec) - HISTORY_HOURS * 3600
        if last < need_from:
            # backfill: walk back 200 hourly candles per call
            to = None
            for _ in range(HISTORY_HOURS // 200 + 2):
                chunk = self.api.minute_candles(market, unit=60, count=200, to=to)
                if not chunk:
                    break
                for r in chunk:
                    by_t[int(r["t"])] = r
                oldest = int(chunk[0]["t"])
                if oldest <= need_from:
                    break
                to = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(oldest))
        else:
            count = max(3, min(200, (int(now_sec) - last) // 3600 + 3))
            for r in self.api.minute_candles(market, unit=60, count=count):
                by_t[int(r["t"])] = r
        rows = [by_t[t] for t in sorted(by_t) if t >= need_from - 48 * 3600]
        self.candles[market] = rows
        tmp = self._candle_path(market) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(rows, handle)
        os.replace(tmp, self._candle_path(market))
        return rows

    # ------------------------------------------------------------------ steps
    def step(self):
        now = self.now()
        out = {"next_delay": 15}
        sleeves = self.state["sleeves"]
        self._resolve_all_pending()
        long_markets = [m for m, s in sleeves.items() if s.get("long")]
        if long_markets:
            self._watch_stops(long_markets)
        elif self.stream is not None:
            self.stream.watch([], key="probe" if self.probe else "main")  # nothing held: no connection
            self.state["feed"] = ""
        E = bar_floor(now, self.S.BAR_SEC)
        if E > int(self.state.get("last_decision_bar_end") or 0) and now >= E + DECISION_DELAY_SEC:
            self._decide(E, now)
        if self.mode == "live" and now - float(self.state.get("last_reconcile_at") or 0) >= RECONCILE_SEC:
            self._reconcile()
        self._update_equity(now)
        self.save()
        self._publish(now)
        long_now = any(s.get("long") for s in sleeves.values())
        until_decision = E + self.S.BAR_SEC + DECISION_DELAY_SEC - now
        fast = 1.0 if self.state.get("feed") == "websocket" else float(REST_POLL_SEC)
        out["next_delay"] = max(1.0, min(fast if long_now else 15.0, until_decision))
        return out

    def _decide(self, E, now):
        S = self.S
        decisions = self.state.setdefault("decisions", [])
        if not decisions or decisions[-1].get("bar_end") != E:
            decisions.append({"bar_end": E, "at": int(now), "markets": {}})
            del decisions[:-60]
        record = decisions[-1]
        failed = False
        for market, sleeve in self.state["sleeves"].items():
            if int(sleeve.get("decided_bar_end") or 0) >= E:
                continue
            try:
                rows = self.sync_candles(market, now)
            except Exception as exc:  # data outage: retry for 2 minutes, stops untouched
                failed = True
                record["markets"][market] = {"action": "DATA_ERROR", "reason": str(exc)[:120]}
                continue
            closed = [r for r in rows if int(r["t"]) + 3600 <= E]
            bars = S.build_bars(closed)
            if not bars:
                failed = True
                continue
            daily = S.daily_closes(closed, E)
            complete = bars[-1]["end"] == E
            atr = S.atr_series(bars)
            if sleeve.get("long"):
                # Ratchet through every closed bar since the last one used
                # (several after a sleep or restart), as the research does.
                for j, bar in enumerate(bars):
                    if bar["end"] <= int(sleeve.get("last_bar_end") or 0) or atr[j] is None:
                        continue
                    sleeve["hh"] = max(float(sleeve["hh"]), bar["h"])
                    sleeve["stop"] = max(float(sleeve["stop"]), sleeve["hh"] - S.ATR_K * atr[j])
                sleeve["last_bar_end"] = bars[-1]["end"]
            ind = S.indicators(bars, daily, len(bars) - 1)
            sleeve["indicators"] = {k: ind.get(k) for k in ("bar_end", "close", "atr", "donchian_high", "sma50d", "ready")}
            if sleeve.get("long"):
                action, reason = "HOLD", f"보유 중 · 손절가 {float(sleeve['stop']):,.4f}"
            elif sleeve.get("pending"):
                action, reason = "HOLD", "주문 확인 중"
            else:
                action, position, reason = S.decide({"long": False}, ind)
                if action == "ENTER":
                    if not complete:
                        action, reason = "WAIT", "최근 4시간봉 데이터 미완성 — 진입 보류"
                    elif now - E > ENTRY_WINDOW_SEC:
                        action, reason = "WAIT", f"신호 후 {int((now - E) // 60)}분 경과 — 진입 시점 놓침"
                    elif self.state.get("halted"):
                        action, reason = "WAIT", "손실 한도로 신규 진입 중단 중"
                    elif not sleeve.get("active", True):
                        action, reason = "WAIT", "운용 대상에서 제외된 종목"
                    elif float(sleeve.get("cash") or 0) < MIN_ORDER_KRW:
                        action, reason = "WAIT", "슬리브 현금 부족"
                    else:
                        self._enter(market, sleeve, position, reason, E)
                        action, reason = sleeve.get("last_action", action), sleeve.get("last_reason", reason)
            sleeve["last_action"], sleeve["last_reason"] = action, reason
            sleeve["decided_bar_end"] = E
            record["markets"][market] = {"action": action, "reason": reason, "stop": sleeve.get("stop") if sleeve.get("long") else None,
                                         **{k: sleeve["indicators"].get(k) for k in ("close", "donchian_high", "sma50d", "atr")}}
        if not failed or now > E + 120:
            self.state["last_decision_bar_end"] = E

    # ---------------------------------------------------------------- orders
    def _identifier(self, market, side, stamp):
        return f"s8c-{market.split('-')[-1]}-{int(stamp)}-{side}"

    def _enter(self, market, sleeve, position, reason, E):
        book = self.api.orderbook([market]).get(market, {})
        bid = float(book.get("bid") or 0)
        if 0 < bid <= float(position["stop"]):
            # SPEC 5b: the price is already at the stop; the backtest books an
            # immediate round trip whose only result is the costs.
            sleeve.update(last_action="SKIP", last_reason=f"매수호가 ₩{bid:,.4f}가 이미 손절가 ₩{float(position['stop']):,.4f} 이하 — 진입 안 함")
            self._log("COIN_SKIP_BELOW_STOP", market, "SKIP", f"{market} 진입 건너뜀: {sleeve['last_reason']}",
                      {"bid": bid, "stop": position["stop"], "bar_end": E, "shadow": self.mode == "shadow"})
            return
        if self.mode == "shadow":
            ask = float(book.get("ask") or 0)
            if ask <= 0:
                sleeve.update(last_action="SKIP", last_reason="호가 없음 — 진입 보류")
                return
            cash = float(sleeve["cash"])
            volume = self.S.floor_volume(cash * (1 - FEE_SIDE) / ask)
            cost = cash
            sleeve.update(long=True, volume=volume, entry_px=ask, entry_time=int(self.now()), cost_krw=cost, cash=0.0,
                          hh=position["hh"], stop=position["stop"], signal_bar_end=E, last_bar_end=E,
                          last_action="ENTER", last_reason=reason)
            self._log("COIN_SHADOW_BUY", market, "BUY", f"[모의] {market} 매수 {volume} @ ₩{ask:,.4f} · {reason}",
                      {"volume": volume, "price": ask, "funds": cost, "stop": position["stop"], "bar_end": E}, price=ask)
            return
        # live
        balances = self.api.balances()
        krw = float((balances.get("KRW") or {}).get("balance", 0) or 0)
        amount = int(math.floor(min(float(sleeve["cash"]), float(self.policy["max_order_krw"]), krw) / (1 + FEE_SIDE)))
        if amount < MIN_ORDER_KRW:
            sleeve.update(last_action="SKIP", last_reason=f"주문 가능 원화 부족 (가능 ₩{int(krw):,}, 슬리브 ₩{int(sleeve['cash']):,})")
            self._log("COIN_BUY_SKIPPED", market, "SKIP", f"{market} 매수 보류: {sleeve['last_reason']}", {}, noise=True)
            return
        ident = self._identifier(market, "b", E)
        sleeve["pending"] = {"side": "bid", "identifier": ident, "uuid": "", "krw": amount, "placed_at": int(self.now()),
                             "hh": position["hh"], "stop": position["stop"], "bar_end": E, "reason": reason}
        self.save()  # the intent is on disk before the order exists
        try:
            res = self.api.buy_market_krw(market, amount, identifier=ident)
            sleeve["pending"]["uuid"] = str((res or {}).get("uuid", "") or "")
        except self.ApiError as exc:
            if getattr(exc, "status", 0) and 400 <= int(exc.status) < 500 and getattr(exc, "name", "") != "too_many_requests":
                sleeve["pending"] = None  # rejected: nothing was placed
                sleeve.update(last_action="ERROR", last_reason=f"매수 거절: {exc}")
                self._log("COIN_BUY_ERROR", market, "ERROR", f"{market} 매수 거절: {exc}", {"name": getattr(exc, "name", "")})
                return
            sleeve["pending"]["error"] = str(exc)[:160]  # unknown outcome: resolve by identifier
        self.save()
        self._resolve_pending(market, sleeve, wait_sec=6)

    def _exit(self, market, sleeve, reason, price_hint=0.0):
        if self.mode == "shadow":
            book = self.api.orderbook([market]).get(market, {})
            bid = float(book.get("bid") or price_hint or 0)
            proceeds = float(sleeve["volume"]) * bid * (1 - FEE_SIDE)
            self._close(market, sleeve, proceeds, bid, reason, "COIN_SHADOW_SELL", {"model_stop": sleeve.get("stop")})
            return
        if sleeve.get("pending"):
            return
        balances = self.api.balances()
        base = market.split("-")[-1]
        available = float((balances.get(base) or {}).get("balance", 0) or 0)
        volume = self.S.floor_volume(min(float(sleeve["volume"]), available))
        if volume * float(price_hint or sleeve.get("entry_px") or 0) < DUST_KRW:
            self._close_external(market, sleeve, available, price_hint, "매도할 잔고가 없음 — 외부에서 처분된 것으로 처리")
            return
        ident = self._identifier(market, "a", self.now())
        sleeve["pending"] = {"side": "ask", "identifier": ident, "uuid": "", "volume": volume, "placed_at": int(self.now()),
                             "reason": reason, "model_stop": sleeve.get("stop")}
        self.save()
        try:
            res = self.api.sell_market(market, volume, identifier=ident, ref_price=price_hint)
            sleeve["pending"]["uuid"] = str((res or {}).get("uuid", "") or "")
        except self.ApiError as exc:
            if getattr(exc, "status", 0) and 400 <= int(exc.status) < 500 and getattr(exc, "name", "") != "too_many_requests":
                sleeve["pending"] = None
                sleeve.update(last_action="ERROR", last_reason=f"매도 거절: {exc}")
                self._log("COIN_SELL_ERROR", market, "ERROR", f"{market} 매도 거절: {exc} (다음 확인 때 재시도)", {"name": getattr(exc, "name", "")}, noise=True)
                return
            sleeve["pending"]["error"] = str(exc)[:160]
        self.save()
        self._resolve_pending(market, sleeve, wait_sec=6)

    def _resolve_all_pending(self):
        if self.mode != "live":
            return
        for market, sleeve in self.state["sleeves"].items():
            if sleeve.get("pending"):
                self._resolve_pending(market, sleeve, wait_sec=0)

    def _resolve_pending(self, market, sleeve, wait_sec=0):
        pending = sleeve.get("pending")
        if not pending:
            return
        deadline = self.now() + wait_sec
        while True:
            order = None
            try:
                order = self.api.get_order(order_uuid=pending.get("uuid", ""), identifier=pending["identifier"])
            except self.ApiError as exc:
                if int(getattr(exc, "status", 0) or 0) == 404 and self.now() - pending["placed_at"] > PENDING_GIVE_UP_SEC:
                    sleeve["pending"] = None  # the exchange never accepted it
                    sleeve.update(last_action="ERROR", last_reason="주문이 접수되지 않음 (확인 완료)")
                    self._log(f"COIN_{'BUY' if pending['side'] == 'bid' else 'SELL'}_ERROR", market, "ERROR",
                              f"{market} 주문 미접수 확인: {pending.get('error', '')}", {"identifier": pending["identifier"]})
                    return
            if order:
                state = str(order.get("state", "") or "")
                executed = float(order.get("executed_volume", 0) or 0)
                if state in ("done", "cancel"):
                    if executed > 0:
                        self._finalize(market, sleeve, pending, order)
                    else:
                        sleeve["pending"] = None
                        sleeve.update(last_action="ERROR", last_reason="주문 취소됨 (체결 없음)")
                        self._log("COIN_ORDER_CANCELLED", market, "ERROR", f"{market} 주문이 체결 없이 종료", {"uuid": order.get("uuid")})
                    return
            if self.now() >= deadline:
                return
            self.sleep(1.0)

    def _finalize(self, market, sleeve, pending, order):
        trades = order.get("trades") or []
        funds = sum(float(t.get("funds", 0) or 0) for t in trades)
        volume = sum(float(t.get("volume", 0) or 0) for t in trades) or float(order.get("executed_volume", 0) or 0)
        if funds <= 0 and volume > 0:
            funds = volume * float(order.get("price", 0) or order.get("avg_price", 0) or 0)
        fee = float(order.get("paid_fee", 0) or 0)
        avg = funds / volume if volume > 0 else 0.0
        sleeve["pending"] = None
        if pending["side"] == "bid":
            sleeve.update(long=True, volume=volume, entry_px=avg, entry_time=int(self.now()), cost_krw=funds + fee,
                          cash=max(0.0, float(sleeve["cash"]) - funds - fee), hh=pending["hh"], stop=pending["stop"],
                          signal_bar_end=pending["bar_end"], last_bar_end=pending["bar_end"],
                          last_action="ENTER", last_reason=pending.get("reason", ""))
            self._log("COIN_BUY", market, "BUY",
                      f"{market} BUY 실행 | {volume:.8f} {market.split('-')[-1]} · 체결가 ₩{avg:,.4f} · 체결금액 ₩{round(funds):,} | 수수료 ₩{round(fee):,} | {pending.get('reason', '')}",
                      {"uuid": order.get("uuid"), "volume": volume, "price": avg, "funds": funds, "fee": fee, "stop": pending["stop"]},
                      price=avg, order_no=order.get("uuid", ""))
        else:
            self._close(market, sleeve, funds - fee, avg, pending.get("reason", ""), "COIN_SELL", {
                "uuid": order.get("uuid"), "volume": volume, "funds": funds, "fee": fee, "model_stop": pending.get("model_stop")},
                order_no=order.get("uuid", ""), sold_volume=volume)

    def _close(self, market, sleeve, proceeds, price, reason, event, extra, order_no="", sold_volume=None):
        cost = float(sleeve.get("cost_krw") or 0)
        sold = float(sleeve["volume"]) if sold_volume is None else float(sold_volume)
        frac = 1.0 if sleeve["volume"] <= 0 else min(1.0, sold / float(sleeve["volume"]))
        basis = cost * frac
        pnl = proceeds - basis
        sleeve["cash"] = float(sleeve["cash"]) + proceeds
        sleeve["volume"] = max(0.0, float(sleeve["volume"]) - sold)
        sleeve["cost_krw"] = cost - basis
        sleeve["realized_krw"] = float(sleeve.get("realized_krw") or 0) + pnl
        if sleeve["volume"] * float(price or 0) < DUST_KRW:
            sleeve.update(long=False, volume=0.0, cost_krw=0.0, hh=0.0, stop=0.0)
            sleeve["trades"] = int(sleeve.get("trades") or 0) + 1
            sleeve["wins"] = int(sleeve.get("wins") or 0) + (1 if pnl > 0 else 0)
        sleeve.update(last_action="EXIT", last_reason=reason)
        pct = (pnl / basis * 100) if basis > 0 else 0.0
        tag = "[모의] " if event.startswith("COIN_SHADOW") else ""
        self._log(event, market, "SELL",
                  f"{tag}{market} SELL 실행 | {sold:.8f} {market.split('-')[-1]} · 체결가 ₩{price:,.4f} · 체결금액 ₩{round(proceeds):,} | 순손익 ₩{round(pnl):+,} ({pct:+.2f}%) | {reason}",
                  {"volume": sold, "price": price, "proceeds": proceeds, "pnl": pnl, "pnl_pct": pct, **(extra or {})},
                  price=price, order_no=order_no)

    def _close_external(self, market, sleeve, available, price, reason):
        price = float(price or sleeve.get("entry_px") or 0)
        proceeds = max(0.0, float(sleeve["volume"]) - float(available)) * price * (1 - FEE_SIDE)
        self._close(market, sleeve, proceeds, price, reason, "COIN_EXTERNAL_SELL", {"estimated": True})

    # -------------------------------------------------------------- watching
    def _watch_stops(self, markets):
        """Primary feed: the trade stream (lowest trade since the last pass, so
        a short wick through the stop counts, as in the backtest). A market
        without a fresh stream (disconnected, or no trade for STALE_SEC) is
        also polled over REST every REST_POLL_SEC."""
        stale = list(markets)
        if self.stream is not None:
            self.stream.watch(markets, key="probe" if self.probe else "main")
            data = self.stream.read(markets)
            connected = bool(self.stream.connected)
            stale = []
            for market in markets:
                row = data.get(market)
                if row:
                    self.prices[market] = row["price"]
                    self._check_stop(market, row["low"], row["price"], "체결")
                if not connected or not row or row["age"] >= getattr(self.stream, "STALE_SEC", 30.0):
                    stale.append(market)
            self.state["feed"] = "websocket" if connected and not stale else ("websocket+rest" if connected else "rest")
        else:
            self.state["feed"] = "rest"
        if not stale or (self.stream is not None and self.now() - self._rest_at < REST_POLL_SEC):
            return
        self._rest_at = self.now()
        try:
            ticks = self.api.ticker(stale)
        except Exception as exc:
            self.state["last_error"] = f"시세 조회 실패: {str(exc)[:120]}"
            return
        for market in stale:
            price = float((ticks.get(market) or {}).get("trade_price", 0) or 0)
            if price <= 0:
                continue
            self.prices[market] = price
            self._check_stop(market, price, price, "현재가")

    def _check_stop(self, market, low, price, source):
        sleeve = self.state["sleeves"][market]
        if sleeve.get("long") and not sleeve.get("pending") and self.S.stop_hit(sleeve, low):
            detail = f"최저 체결 ₩{low:,.4f}, 현재가 ₩{price:,.4f}" if low < price else f"{source} ₩{price:,.4f}"
            self._exit(market, sleeve, f"손절가 ₩{float(sleeve['stop']):,.4f} 도달 ({detail})", price_hint=price)

    def _reconcile(self):
        self.state["last_reconcile_at"] = int(self.now())
        try:
            balances = self.api.balances()
        except Exception as exc:
            self.state["last_error"] = f"잔고 조회 실패: {str(exc)[:120]}"
            return
        self.state["krw_available"] = float((balances.get("KRW") or {}).get("balance", 0) or 0)
        for market, sleeve in self.state["sleeves"].items():
            if not sleeve.get("long") or sleeve.get("pending"):
                continue
            base = market.split("-")[-1]
            held = float((balances.get(base) or {}).get("balance", 0) or 0) + float((balances.get(base) or {}).get("locked", 0) or 0)
            if held < float(sleeve["volume"]) * 0.98:
                price = self.prices.get(market) or float(sleeve.get("entry_px") or 0)
                if held * price < DUST_KRW:
                    self._close_external(market, sleeve, 0.0, price, "업비트에서 직접 매도됨 (잔고 없음) — 자동매매 장부에서 정리")
                else:
                    sold = float(sleeve["volume"]) - held
                    self._close(market, sleeve, sold * price * (1 - FEE_SIDE), price, "업비트에서 일부 직접 매도됨 — 장부 수량 맞춤",
                                "COIN_EXTERNAL_SELL", {"estimated": True}, sold_volume=sold)

    def _update_equity(self, now):
        equity = 0.0
        for market, sleeve in self.state["sleeves"].items():
            price = self.prices.get(market) or float((sleeve.get("indicators") or {}).get("close") or sleeve.get("entry_px") or 0)
            equity += float(sleeve["cash"]) + float(sleeve["volume"]) * price
        self.state["equity"] = equity
        peak = max(float(self.state.get("peak_equity") or 0), equity)
        self.state["peak_equity"] = peak
        if not self.probe and peak > 0 and equity < peak * (1 - KILL_DRAWDOWN) and not self.state.get("halted"):
            self.state["halted"] = True
            self.state["halt_reason"] = f"고점 ₩{round(peak):,} 대비 -{KILL_DRAWDOWN * 100:.0f}% 도달 (현재 ₩{round(equity):,})"
            self._log("COIN_HALT", "", "HALT", f"코인 자동매매 신규 진입 중단: {self.state['halt_reason']}", {"equity": equity, "peak": peak})
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        days = self.state.setdefault("equity_days", [])
        if not days or days[-1][0] != day:
            days.append([day, round(equity)])
            del days[:-400]
        else:
            days[-1][1] = round(equity)

    def resume(self):
        self.state["halted"] = False
        self.state["halt_reason"] = ""
        self.state["peak_equity"] = float(self.state.get("equity") or 0)
        self.save()

    # ----------------------------------------------------------------- output
    def _log(self, event, market, action, message, payload, price=0.0, order_no="", noise=False):
        if noise:
            key = (event, market, message)
            if time.monotonic() - _LOG_SEEN.get(key, -1e9) < 600:
                return
            _LOG_SEEN[key] = time.monotonic()
        if self.probe:
            message = str(message).replace("[모의] ", "")
            message = "[점검] " + message
        try:
            self.log(event, market, action, message, dict(payload or {}, mode=self.mode, probe=self.probe), price=price, order_no=order_no)
        except Exception:
            pass

    def snapshot(self, now=None):
        now = self.now() if now is None else now
        E = bar_floor(now, self.S.BAR_SEC)
        sleeves = []
        for market, s in self.state["sleeves"].items():
            price = self.prices.get(market) or (s.get("indicators") or {}).get("close") or 0
            value = float(s["cash"]) + float(s["volume"]) * float(price or 0)
            unreal = (float(s["volume"]) * float(price or 0) - float(s.get("cost_krw") or 0)) if s.get("long") else 0.0
            sleeves.append({"market": market, "long": bool(s.get("long")), "active": s.get("active", True),
                            "price": price, "volume": s["volume"], "entry_px": s.get("entry_px"), "stop": s.get("stop") if s.get("long") else None,
                            "cash": s["cash"], "value": value, "unrealized_krw": unreal, "realized_krw": s.get("realized_krw", 0),
                            "trades": s.get("trades", 0), "wins": s.get("wins", 0), "pending": bool(s.get("pending")),
                            "last_action": s.get("last_action", ""), "last_reason": s.get("last_reason", ""),
                            "indicators": s.get("indicators") or {}})
        return {"mode": self.mode, "equity": self.state.get("equity", 0), "peak_equity": self.state.get("peak_equity", 0),
                "seed_krw": self.state.get("seed_krw", 0), "halted": bool(self.state.get("halted")), "halt_reason": self.state.get("halt_reason", ""),
                "last_decision_bar_end": self.state.get("last_decision_bar_end", 0),
                "next_decision_at": E + self.S.BAR_SEC + DECISION_DELAY_SEC, "krw_available": self.state.get("krw_available"),
                "last_error": self.state.get("last_error", ""), "sleeves": sleeves,
                "feed": self.state.get("feed", ""), "stream": self.stream.status() if self.stream is not None else {},
                "decisions": (self.state.get("decisions") or [])[-6:], "equity_days": (self.state.get("equity_days") or [])[-120:]}

    def _publish(self, now):
        snap = self.snapshot(now)
        snap["updated_at"] = int(now)
        target = PROBE_STATUS if self.probe else STATUS
        target.clear()
        target.update(snap)


# wiz.model() hands out only `Model`; expose the module helpers on it.
CoinEngine.STATUS = STATUS
CoinEngine.PROBE_STATUS = PROBE_STATUS
CoinEngine.PROBE_MARKETS = PROBE_MARKETS
CoinEngine.POLICY_KEY = POLICY_KEY
CoinEngine.ALL_MARKETS = ALL_MARKETS
CoinEngine.DEFAULT_MARKETS = DEFAULT_MARKETS
CoinEngine.SEED_MIN = SEED_MIN
CoinEngine.SEED_MAX = SEED_MAX
CoinEngine.normalize_policy = staticmethod(normalize_policy)
CoinEngine.account_fingerprint = staticmethod(account_fingerprint)
CoinEngine.owner_scope = staticmethod(owner_scope)

Model = CoinEngine
