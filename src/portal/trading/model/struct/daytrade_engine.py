# =============================================================================
# Domestic Daytrade Live Engine Blueprint
# =============================================================================
import datetime
import json
import sys
import threading

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

_TIME = wiz.model("portal/trading/kst")


class DomesticDaytradeEngine:
    # KIS API 잔고 조회 결과 TTL 캐시 — Struct 싱글톤 cfg에 저장하나, 폴백용으로 유지
    _KIS_BALANCE_CACHE: dict = {}
    _KIS_BALANCE_CACHE_TS: float = 0.0
    _KIS_BALANCE_CACHE_TTL: float = 120.0  # 2분 캐시 (exec() 재실행 간격보다 길게)

    # 분봉 스냅샷 TTL 캐시 (12초) — 분봉 데이터+현재가 API 중복 호출 방지 (live_status 속도 개선)
    _SNAPSHOT_CACHE: dict = {}   # {"symbol.market": {"session": ..., "bar": ..., "ts": datetime}}
    _SNAPSHOT_CACHE_TTL: float = 12.0

    # 실시간 체결 데이터 기반 1분봉 조립기 (Candle Aggregator)
    _AGGREGATED_CANDLES: dict = {}  # {"symbol.market": {"ticks": [], "last_ts": datetime}}
    _AGGREGATED_CANDLES_TTL: float = 300.0  # 5분 캐시

    def __init__(self, struct):
        self.struct = struct
        self._Daytrade = wiz.model("portal/trading/struct/daytrade")

    @property
    def strategy(self):
        return self._Daytrade(self.struct)

    def _fs(self):
        return wiz.project.fs()

    def _state_path(self):
        return "data/daytrade/live_state.json"

    def _market_key(self, market="", symbol=""):
        hint = str(market or "").upper().strip()
        if self._is_us_market(hint):
            return "US"
        if hint in ("KS", "KQ", "KR"):
            return "KS"
        sym = str(symbol or "").strip().upper()
        if sym.isdigit() and len(sym) == 6:
            return "KS"
        if sym and sym.replace(".", "").isalpha() and len(sym) <= 8:
            return "US"
        return "KS"

    def _runtime_log_path(self, market=""):
        key = self._market_key(market)
        if key == "US":
            return "data/daytrade/runtime_logs_us.json"
        return "data/daytrade/runtime_logs_ks.json"

    def _market_from_event_type(self, event_type="", symbol=""):
        event = str(event_type or "").upper()
        if event.startswith("DT_US_"):
            return "US"
        if event.startswith("DT_KS_"):
            return "KS"
        return self._market_key(symbol=symbol)

    def _dt_event_type(self, action="", market="", symbol=""):
        prefix = "DT_US" if self._market_key(market, symbol) == "US" else "DT_KS"
        return f"{prefix}_{str(action or '').upper()}"

    def _global_lock(self, name):
        key = "_trading_daytrade_engine_locks"
        locks = getattr(sys, key, None)
        if isinstance(locks, dict) is False:
            locks = {}
            setattr(sys, key, locks)
        lock = locks.get(name)
        if lock is None:
            lock = threading.RLock()
            locks[name] = lock
        return lock

    def _safe_float(self, value, default=0.0):
        try:
            value = float(value)
            return value
        except Exception:
            return default

    def _safe_int(self, value, default=0):
        try:
            return int(value)
        except Exception:
            return default

    def _config(self, key, default=""):
        """매 요청 DB 쿼리 대신 Struct 싱글톤 캐시에서 읽음 — 연결 고갈 방지"""
        return self.struct.get_config(key, default)

    def _hard_locked(self):
        return bool(getattr(self.struct, "daytrade_hard_locked", False))

    def _hard_lock_message(self):
        return str(getattr(self.struct, "daytrade_lock_message", "단타 기능은 현재 운영 안정화를 위해 완전히 봉인되어 있습니다."))

    def _hard_locked_result(self):
        return {
            "executed": False,
            "message": self._hard_lock_message(),
            "hard_locked": True,
            "results": [],
            "candidates": [],
        }

    def _feature_enabled(self):
        if self._hard_locked():
            return False
        return str(self._config("daytrade_feature_enabled", "false") or "false").lower() in ("1", "true", "yes", "y", "on")

    def _state_key(self, symbol, market="KS"):
        return f"{symbol}.{market}"

    def _load_state_map(self):
        with self._global_lock("state_io"):
            fs = self._fs()
            if fs.exists(self._state_path()) == False:
                return {}
            return fs.read.json(self._state_path(), default={}) or {}

    def _save_state_map(self, payload):
        with self._global_lock("state_io"):
            fs = self._fs()
            fs.makedirs("data/daytrade")
            fs.write.json(self._state_path(), payload)

    def _now(self):
        return _TIME.now()

    def _timestamp(self):
        return self._now().strftime("%Y-%m-%d %H:%M:%S")

    def _today_open_kst(self, market="KS"):
        now = self._now()
        if self._is_us_market(market):
            return now.replace(hour=22, minute=30, second=0, microsecond=0)
        return now.replace(hour=9, minute=0, second=0, microsecond=0)

    def _today_close_kst(self, market="KS"):
        now = self._now()
        if self._is_us_market(market):
            return now.replace(hour=5, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1 if now.hour >= 9 else 0)
        return now.replace(hour=15, minute=30, second=0, microsecond=0)

    def _minutes_since_market_open(self, market="KS"):
        opened_at = self._today_open_kst(market=market)
        return int((self._now() - opened_at).total_seconds() // 60)

    def _normalize_display_timestamp(self, value=""):
        text = str(value or "").strip()
        if text == "":
            return ""
        return _TIME.normalize(text)

    def _seconds_since_timestamp(self, value=""):
        text = str(value or "").strip()
        if text == "":
            return None
        parsed = _TIME.to_kst(text)
        if parsed is None:
            return None
        return max(0.0, (self._now() - parsed).total_seconds())

    def _reentry_cooldown_status(self, state, profile, market="KS"):
        state = state or {}
        profile = profile or {}
        if self._safe_int(state.get("position_qty", 0), 0) > 0:
            return {
                "active": False,
                "remaining_sec": 0,
                "cooldown_sec": 0,
                "elapsed_sec": 0,
                "action": "",
                "timestamp": "",
                "reason": "",
            }

        exit_action = str(state.get("last_exit_action", "") or state.get("last_signal", "") or "").upper().strip()
        exit_timestamp = str(state.get("last_manual_exit_at", "") or state.get("last_exit_watch_at", "") or "").strip()

        if exit_timestamp == "":
            for order in reversed(list(state.get("orders", []) or [])):
                order_action = str(order.get("action", "") or "").upper().strip()
                if order_action.startswith("SELL") is False:
                    continue
                if exit_action == "":
                    exit_action = order_action
                exit_timestamp = str(order.get("timestamp", "") or "").strip()
                if exit_timestamp != "":
                    break

        if exit_action.startswith("SELL") is False:
            return {
                "active": False,
                "remaining_sec": 0,
                "cooldown_sec": 0,
                "elapsed_sec": 0,
                "action": exit_action,
                "timestamp": exit_timestamp,
                "reason": "",
            }

        base_cooldown = self._safe_int(
            profile.get("reentry_cooldown_sec", self._config("daytrade_reentry_cooldown_sec", "1800")),
            1800,
        )
        if "STOP" in exit_action:
            cooldown_sec = max(
                base_cooldown,
                self._safe_int(
                    profile.get("stop_reentry_cooldown_sec", self._config("daytrade_stop_reentry_cooldown_sec", "3600")),
                    3600,
                ),
            )
        elif "MANUAL" in exit_action:
            cooldown_sec = max(
                base_cooldown,
                self._safe_int(
                    profile.get("manual_reentry_cooldown_sec", self._config("daytrade_manual_reentry_cooldown_sec", "1800")),
                    1800,
                ),
            )
        else:
            cooldown_sec = max(0, base_cooldown)

        elapsed_sec = self._seconds_since_timestamp(exit_timestamp)
        if elapsed_sec is None or cooldown_sec <= 0:
            return {
                "active": False,
                "remaining_sec": 0,
                "cooldown_sec": cooldown_sec,
                "elapsed_sec": 0,
                "action": exit_action,
                "timestamp": exit_timestamp,
                "reason": "",
            }

        remaining_sec = max(0, int(round(cooldown_sec - elapsed_sec)))
        active = remaining_sec > 0
        reason = ""
        same_day_stop_block = bool(profile.get("stop_reentry_same_day_block", False))
        exit_day = self._date_compact(exit_timestamp)
        today_day = self._now().strftime("%Y%m%d")
        if same_day_stop_block and "STOP" in exit_action and exit_day != "" and exit_day == today_day:
            session_end = self._today_close_kst(market=market)
            block_remaining = max(0, int((session_end - self._now()).total_seconds())) if session_end else 0
            return {
                "active": True,
                "remaining_sec": block_remaining,
                "cooldown_sec": max(int(cooldown_sec), block_remaining),
                "elapsed_sec": int(round(elapsed_sec)),
                "action": exit_action,
                "timestamp": exit_timestamp,
                "reason": "당일 손절 종목은 같은 거래일 재진입을 차단합니다.",
            }
        if active:
            reason = f"최근 {exit_action} 이후 재진입 쿨다운 {remaining_sec}초 남음"

        return {
            "active": active,
            "remaining_sec": remaining_sec,
            "cooldown_sec": int(cooldown_sec),
            "elapsed_sec": int(round(elapsed_sec)),
            "action": exit_action,
            "timestamp": exit_timestamp,
            "reason": reason,
        }

    def _profit_reentry_guard(self, state, profile, current_price=0, trigger_price=0):
        state = state or {}
        profile = profile or {}
        if self._safe_int(state.get("position_qty", 0), 0) > 0:
            return {
                "active": False,
                "required_price": 0,
                "last_exit_price": 0,
                "min_pullback_pct": 0,
                "reason": "",
            }

        exit_action = str(state.get("last_exit_action", "") or state.get("last_signal", "") or "").upper().strip()
        if exit_action not in ["SELL_FULL", "SELL_RECENT", "SELL_RESCUE", "SELL_PARTIAL"]:
            return {
                "active": False,
                "required_price": 0,
                "last_exit_price": 0,
                "min_pullback_pct": 0,
                "reason": "",
            }

        last_exit_price = self._safe_float(state.get("last_exit_price", 0), 0)
        if last_exit_price <= 0:
            return {
                "active": False,
                "required_price": 0,
                "last_exit_price": 0,
                "min_pullback_pct": 0,
                "reason": "",
            }

        min_pullback_pct = max(
            self._safe_float(profile.get("profit_reentry_min_pullback_pct", 0.7), 0.7),
            0.25,
        )
        price_cap = last_exit_price * (1 - min_pullback_pct / 100)
        if trigger_price > 0 and price_cap >= trigger_price:
            return {
                "active": False,
                "required_price": round(trigger_price, 4),
                "last_exit_price": round(last_exit_price, 4),
                "min_pullback_pct": round(min_pullback_pct, 4),
                "reason": "",
            }

        active = current_price > 0 and price_cap > 0 and current_price > price_cap
        reason = ""
        if active:
            reason = f"직전 익절가 ₩{round(last_exit_price):,} 대비 최소 -{min_pullback_pct:.2f}% 눌림(₩{round(price_cap):,} 이하) 확인 후 재진입"

        return {
            "active": active,
            "required_price": round(price_cap, 4),
            "last_exit_price": round(last_exit_price, 4),
            "min_pullback_pct": round(min_pullback_pct, 4),
            "reason": reason,
        }

    def _is_obsolete_seed_error(self, message=""):
        text = str(message or "")
        return ("여유 시드 한도" in text) or ("현재 단타 사용 중 자금" in text)

    def _normalize_display_message(self, message=""):
        text = str(message or "")
        if self._is_obsolete_seed_error(text):
            return f"[구형 로그] {text} → 현재는 평가손익이 아니라 원가 기준 시드로 계산합니다."
        return text

    def _normalize_display_log_item(self, item):
        payload = dict(item or {})
        payload["timestamp"] = self._normalize_display_timestamp(payload.get("timestamp", ""))
        payload["message"] = self._normalize_display_message(payload.get("message", ""))
        return payload

    def _date_compact(self, value=""):
        text = str(value or "").strip()
        if text == "":
            return ""
        return text.replace("-", "")[:8]

    def _date_display(self, value=""):
        text = self._date_compact(value)
        if len(text) != 8:
            return str(value or "")
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"

    def _overnight_carry_policy(self, state, profile, bar, current_price=0, avg_price=0, market="KS"):
        profile = profile or {}
        if self._is_us_market(market):
            return {"enabled": False, "eligible": False, "reason": "미장 오버나잇 판정 미사용"}
        enabled = bool(profile.get("carry_overnight_enabled", True))
        if enabled is False:
            return {"enabled": False, "eligible": False, "reason": "오버나잇 비활성화 프로필"}
        pnl_pct = ((current_price / avg_price) - 1) * 100 if current_price > 0 and avg_price > 0 else 0.0
        vwap = self._safe_float(bar.get("vwap", 0), 0)
        min_vwap_ratio = self._safe_float(profile.get("carry_min_vwap_ratio", 0.997), 0.997)
        max_loss_pct = abs(self._safe_float(profile.get("carry_max_loss_pct", 0.8), 0.8))
        min_close_strength_pct = self._safe_float(profile.get("carry_min_close_strength_pct", -1.2), -1.2)
        if avg_price <= 0 or current_price <= 0:
            return {"enabled": enabled, "eligible": False, "reason": "평단가/현재가 부족"}
        if pnl_pct <= (-1.0 * max_loss_pct):
            return {"enabled": enabled, "eligible": False, "reason": f"종가 손익 {pnl_pct:.2f}% < 허용 {-max_loss_pct:.2f}%"}
        if pnl_pct <= min_close_strength_pct:
            return {"enabled": enabled, "eligible": False, "reason": f"종가 강도 {pnl_pct:.2f}% < 최소 {min_close_strength_pct:.2f}%"}
        if vwap > 0 and current_price < (vwap * min_vwap_ratio):
            return {"enabled": enabled, "eligible": False, "reason": f"종가가 VWAP 대비 약세 ({current_price:.0f} < {vwap * min_vwap_ratio:.0f})"}
        return {"enabled": enabled, "eligible": True, "reason": "종가 강도 유지로 오버나잇 허용"}

    def _normalize_trade_action(self, action=""):
        action = str(action or "").upper().strip()
        if action.startswith("BUY"):
            return "BUY"
        if action.startswith("SELL"):
            return "SELL"
        return action

    def _trade_merge_key(self, order_no="", symbol="", action="", created_str="", fallback=""):
        action = self._normalize_trade_action(action)
        created_date = str(created_str or "")[:10].replace("-", "")
        order_no = str(order_no or "").strip()
        symbol = str(symbol or "").strip()
        if order_no != "":
            return f"{symbol}:{action}:{order_no}"
        return str(fallback or f"{created_date}:{symbol}:{action}:local")

    def _round_krw_price(self, value):
        price = self._safe_float(value, 0)
        if price <= 0:
            return 0.0
        tick = 1
        if price < 2000:
            tick = 1
        elif price < 5000:
            tick = 5
        elif price < 20000:
            tick = 10
        elif price < 50000:
            tick = 50
        elif price < 200000:
            tick = 100
        elif price < 500000:
            tick = 500
        else:
            tick = 1000
        return float(int(round(price / float(tick)) * tick))

    def _is_us_market(self, market):
        return str(market or "").upper() in ("US", "NYSE", "NASD", "NASDAQ", "AMEX", "NYS")

    def _is_market_close_approaching(self, market="KS"):
        """장 마감 임박 여부 (강제청산 트리거): 국장 KST 15:20+, 미장 ET 15:40+"""
        now = self._now()
        if self._is_us_market(market):
            # ET = KST - 13h (EDT 여름) or -14h (EST 겨울) — 간단히 -13h 기준
            et_hour = (now.hour - 13) % 24
            et_min = now.minute
            # ET 15:40~16:05 사이
            if et_hour == 15 and et_min >= 40:
                return True
            if et_hour == 16 and et_min <= 5:
                return True
            return False
        else:
            # 국장: KST 15:20 ~ 15:35
            return now.hour == 15 and 20 <= now.minute <= 35

    def _round_usd_price(self, value):
        """USD 가격: $1 이상은 소수점 2자리, $1 미만은 4자리"""
        price = self._safe_float(value, 0)
        if price <= 0:
            return 0.0
        if price < 1.0:
            return round(price, 4)
        return round(price, 2)

    def _normalize_trigger_price(self, value, market="KS"):
        price = self._safe_float(value, 0)
        if price <= 0:
            return 0.0
        if self._is_us_market(market):
            return self._round_usd_price(price)
        return self._round_krw_price(price)

    def _us_exchange(self, symbol):
        """심볼 → KIS 거래소 코드. 기본값 NASD, NYSE 종목은 설정에서 관리."""
        nyse_symbols = {"SPY", "GS", "JPM", "BAC", "WMT", "BRK", "XOM", "JNJ", "PG", "V", "MA"}
        sym = str(symbol or "").upper().split(".")[0]
        return "NYSE" if sym in nyse_symbols else "NASD"

    def _is_us_dst(self):
        """미국 DST 여부 (뉴욕 현지시간 기준)"""
        if ZoneInfo is not None:
            now_et = datetime.datetime.now(ZoneInfo("America/New_York"))
            return bool(now_et.dst())
        now_kst = self._now()
        y = now_kst.year
        mar1 = datetime.datetime(y, 3, 1)
        dst_start = mar1 + datetime.timedelta(days=(6 - mar1.weekday()) % 7 + 7)
        nov1 = datetime.datetime(y, 11, 1)
        dst_end = nov1 + datetime.timedelta(days=(6 - nov1.weekday()) % 7)
        return dst_start <= now_kst < dst_end

    def _us_market_open(self):
        """미국 본장 시간 (ET 09:30~16:00)"""
        if ZoneInfo is not None:
            now_et = datetime.datetime.now(ZoneInfo("America/New_York"))
        else:
            et_offset = -4 if self._is_us_dst() else -5
            now_et = self._now() + datetime.timedelta(hours=et_offset - 9)
        if now_et.weekday() >= 5:
            return False
        hhmm = now_et.hour * 100 + now_et.minute
        return 930 <= hhmm < 1600

    def _us_premarket_open(self):
        """미국 프리마켓 시간 (ET 04:00~09:30)"""
        if ZoneInfo is not None:
            now_et = datetime.datetime.now(ZoneInfo("America/New_York"))
        else:
            et_offset = -4 if self._is_us_dst() else -5
            now_et = self._now() + datetime.timedelta(hours=et_offset - 9)
        if now_et.weekday() >= 5:
            return False
        hhmm = now_et.hour * 100 + now_et.minute
        return 400 <= hhmm < 930

    def _us_auto_buy_ready(self, now=None):
        now = now or self._now()
        hhmm = now.hour * 100 + now.minute
        cutoff = 2220 if self._is_us_dst() else 2320
        return 1000 <= hhmm <= cutoff

    def _us_auto_buy_window(self, now=None):
        now = now or self._now()
        ready = self._us_auto_buy_ready(now)
        cutoff_label = "22:20" if self._is_us_dst() else "23:20"
        window_label = f"10:00-{cutoff_label} KST"
        return {
            "ready": ready,
            "scheduled_at": "10:00 KST",
            "label": f"{window_label} 예약매수 가능",
            "message": (f"{window_label} 원화 자동환전 예약매수 허용" if ready else f"{window_label} 전/후라 원화 자동환전 예약매수 대기 중"),
            "current_time": now.strftime("%H:%M KST"),
        }

    def _mark_exit_watch(self, state, reason="", action="", order_no=""):
        state["last_exit_watch_at"] = self._timestamp()
        if reason != "":
            state["last_exit_reason"] = reason
        if action != "":
            state["last_exit_action"] = action
        if order_no != "":
            state["last_exit_order_no"] = order_no

    def _exit_watch_payload(self, state, signal=None):
        signal = signal or {}
        manual_enabled = bool(state.get("manual_sell_enabled", False))
        manual_price = self._safe_float(state.get("manual_sell_target_price", 0), 0)
        stop_enabled = bool(state.get("stop_loss_enabled", False))
        stop_price = self._safe_float(state.get("stop_loss_price", 0), 0)
        qty = self._safe_int(state.get("position_qty", 0), 0)
        active = qty > 0 and ((manual_enabled and manual_price > 0) or (stop_enabled and stop_price > 0))
        targets = []
        if manual_enabled and manual_price > 0:
            targets.append({"type": "manual_sell", "label": "상단 판매가", "price": round(manual_price, 4), "direction": "gte"})
        if stop_enabled and stop_price > 0:
            targets.append({"type": "stop_loss", "label": "하단 손절가", "price": round(stop_price, 4), "direction": "lte"})
        return {
            "mode": "scheduler_watch",
            "active": active,
            "armed": active,
            "position_qty": qty,
            "targets": targets,
            "target_count": len(targets),
            "last_checked_at": state.get("last_exit_watch_at", ""),
            "last_action": state.get("last_exit_action", ""),
            "last_reason": state.get("last_exit_reason", ""),
            "last_order_no": state.get("last_exit_order_no", ""),
            "pending_signal": signal.get("action", "HOLD"),
            "message": "브로커 서버 예약주문이 아니라 스케줄러 감시형 자동청산입니다.",
        }

    def _clear_pending_sell(self, state):
        """사전 예약 매도 상태 초기화"""
        state["pending_sell_order_no"] = ""
        state["pending_sell_price"] = 0
        state["pending_sell_qty"] = 0
        state["pending_sell_type"] = ""
        state["pending_sell_placed_at"] = ""

    def _open_sell_orders(self, symbol):
        rows = []
        try:
            fills = self.struct.kis_api.get_domestic_fills_today(symbol)
        except Exception:
            return rows
        for item in fills:
            if str(item.get("symbol", "")) != str(symbol):
                continue
            if str(item.get("side", "")) != "SELL":
                continue
            if str(item.get("status", "")) not in ["OPEN", "PARTIAL"]:
                continue
            if self._safe_int(item.get("rmn_qty", 0), 0) <= 0:
                continue
            rows.append(item)
        return rows

    def _cancel_open_sell_orders(self, symbol):
        cancelled = []
        for item in self._open_sell_orders(symbol):
            order_no = str(item.get("order_no", "") or "")
            qty = self._safe_int(item.get("rmn_qty", 0), 0)
            if order_no == "" or qty <= 0:
                continue
            try:
                self.struct.kis_api.cancel_domestic_order(order_no, symbol, qty)
                cancelled.append({"order_no": order_no, "qty": qty})
            except Exception:
                continue
        if len(cancelled) > 0:
            self._invalidate_kis_cache()
        return cancelled

    def _sync_pending_sell(self, state, symbol, market, current_price=0):
        """
        사전 예약 매도 주문 체결 여부 확인 + 가격 이탈 시 자동 취소.
        Returns: "none" | "open" | "filled" | "cancelled"
        """
        order_no = state.get("pending_sell_order_no", "")
        if not order_no:
            return "none"

        # 체결 내역 조회
        try:
            fills = self.struct.kis_api.get_domestic_fills_today(symbol)
        except Exception:
            return "open"  # API 실패 → 대기 유지

        matched = None
        for fill in fills:
            if fill["order_no"] == str(order_no):
                matched = fill
                break

        if matched:
            status = matched.get("status", "OPEN")
            if status == "FILLED":
                filled_price = matched.get("filled_price", 0)
                filled_qty   = matched.get("filled_qty", int(state.get("pending_sell_qty", 0) or 0))
                prev_avg     = self._safe_float(state.get("avg_price", 0), 0)
                prev_qty     = int(state.get("position_qty", 0) or 0)
                realized = (filled_price - prev_avg) * filled_qty if filled_price > 0 and prev_avg > 0 else 0
                state["realized_profit"] = round(self._safe_float(state.get("realized_profit", 0), 0) + realized, 2)
                state["position_qty"] = max(0, prev_qty - filled_qty)
                if state["position_qty"] == 0:
                    state["avg_price"]   = 0.0
                    state["buy1_used"]   = False
                    state["buy2_used"]   = False
                state["last_exit_action"]   = "PRE_SELL_JACKPOT"
                state["last_exit_reason"]   = f"사전 예약 지정가 매도 체결 ₩{round(filled_price):,}"
                state["last_exit_order_no"] = str(order_no)
                self._log_execution(
                    symbol,
                    "SELL_FULL",
                    filled_qty,
                    filled_price,
                    {
                        "order_no": str(order_no),
                        "order_type": "LIMIT",
                        "price": filled_price,
                        "qty": filled_qty,
                    },
                    f"{symbol} SELL_FULL 실행 | {filled_qty}주 · 체결가 ₩{round(filled_price):,} | 사전 예약 지정가 매도 체결",
                    strategy_id=state.get("strategy_id", "vrev"),
                    runtime={
                        "action": "SELL_FULL",
                        "reason": "사전 예약 지정가 매도 체결",
                        "risk_status": "SAFE",
                    },
                    name=state.get("name", ""),
                    filled_price=filled_price,
                    filled_qty=filled_qty,
                )
                self._clear_pending_sell(state)
                return "filled"
            elif status == "CANCELLED":
                self._clear_pending_sell(state)
                return "cancelled"
            elif status == "PARTIAL":
                return "open"  # 부분 체결 중 → 대기

        # OPEN 또는 조회 미매칭 → 가격 이탈 체크
        pending_price   = self._safe_float(state.get("pending_sell_price", 0), 0)
        cancel_threshold = pending_price * 0.990  # 예약가 대비 1% 이상 하락 시 취소
        if pending_price > 0 and current_price > 0 and current_price < cancel_threshold:
            qty = int(state.get("pending_sell_qty", 0) or 0)
            try:
                self.struct.kis_api.cancel_domestic_order(order_no, symbol, qty)
            except Exception:
                pass  # 취소 실패 시에도 pending 해제 (이미 체결/만료 가능성)
            self._clear_pending_sell(state)
            return "cancelled"

        return "open"

    def _default_state(self, symbol, market, seed, name="", strategy_id="vrev"):
        return {
            "symbol": symbol,
            "market": market,
            "name": name or self.strategy.symbol_name(symbol),
            "strategy_id": self.strategy._normalize_strategy(strategy_id),
            "seed": float(seed),
            "session_date": "",
            "first_buy_date": "",
            "buy1_used": False,
            "buy2_used": False,
            "position_qty": 0,
            "avg_price": 0.0,
            "realized_profit": 0.0,
            "manual_sell_enabled": False,
            "manual_sell_target_price": 0.0,
            "stop_loss_enabled": False,
            "stop_loss_price": 0.0,
            "halt_reason": "",
            "recent_errors": [],
            "orders": [],
            "last_signal": "HOLD",
            "last_exit_watch_at": "",
            "last_exit_action": "",
            "last_exit_reason": "",
            "last_exit_order_no": "",
            "last_manual_exit_at": "",
            "last_exit_price": 0.0,
            "carried_overnight": False,
            "updated_at": "",
            # 사전 예약 매도 주문 (잭팟가 근처 진입 시 지정가 선주문)
            "pending_sell_order_no": "",
            "pending_sell_price": 0,
            "pending_sell_qty": 0,
            "pending_sell_type": "",
            "pending_sell_placed_at": "",
            "broker_unmanaged_position": False,
            "broker_unmanaged_qty": 0,
        }

    def _state_for(self, symbol, market="KS", seed=1000000, name="", strategy_id="vrev"):
        state_map = self._load_state_map()
        key = self._state_key(symbol, market)
        state = state_map.get(key, self._default_state(symbol, market, seed, name=name, strategy_id=strategy_id))
        state["symbol"] = symbol
        state["market"] = market
        state["seed"] = float(seed)
        state["strategy_id"] = self.strategy._normalize_strategy(strategy_id)
        if not state.get("name"):
            state["name"] = name or self.strategy.symbol_name(symbol)
        return state

    def _sync_broker_positions(self):
        adopt_broker_positions = str(self._config("daytrade_adopt_broker_positions", "true") or "true").lower() == "true"
        domestic_holdings = []
        overseas_holdings = []
        fetched_markets = set()
        try:
            raw = self._fetch_kis_balance_raw()
            domestic_holdings = raw.get("holdings", []) or []
            fetched_markets.update(["KS", "KQ"])
        except Exception:
            domestic_holdings = []

        try:
            overseas_holdings = self.struct.kis_api.get_balance().get("holdings", []) or []
            fetched_markets.add("US")
        except Exception:
            overseas_holdings = []

        if len(fetched_markets) == 0:
            return

        holdings = []
        for item in domestic_holdings:
            row = dict(item or {})
            row["market"] = str(row.get("market", "KS") or "KS").upper()
            holdings.append(row)
        for item in overseas_holdings:
            row = dict(item or {})
            row["market"] = "US"
            holdings.append(row)

        state_map = self._load_state_map()
        changed = False
        default_strategy = self.strategy.defaults().get("strategy", "vrev")

        # 브로커에 있는 종목 키셋 (qty > 0)
        broker_keys = set()
        for item in holdings:
            symbol = str(item.get("symbol", "") or "").strip()
            qty = self._safe_int(item.get("qty", 0), 0)
            if symbol == "" or qty <= 0:
                continue
            market = str(item.get("market", "KS") or "KS").upper()
            key = self._state_key(symbol, market)
            broker_keys.add(key)

            state = state_map.get(key, self._default_state(symbol, market, 0, name=item.get("name", ""), strategy_id=default_strategy))
            prev_qty = self._safe_int(state.get("position_qty", 0), 0)
            prev_avg = self._safe_float(state.get("avg_price", 0), 0)
            broker_avg = self._safe_float(item.get("avg_price", 0), 0)
            purchase_amount = self._safe_float(item.get("purchase_amount", 0), 0)
            if qty > 0 and purchase_amount > 0 and (broker_avg <= 0 or abs((broker_avg * qty) - purchase_amount) > max(1.0, purchase_amount * 0.2)):
                broker_avg = purchase_amount / qty
            rebuilt = self._state_order_open_position(state)
            rebuilt_qty = self._safe_int(rebuilt.get("qty", 0), 0)
            rebuilt_avg = self._safe_float(rebuilt.get("avg_price", 0), 0)

            state["symbol"] = symbol
            state["market"] = market
            state["name"] = item.get("name", state.get("name", "") or self.strategy.symbol_name(symbol))
            if not state.get("strategy_id"):
                state["strategy_id"] = default_strategy

            managed_qty = max(prev_qty, rebuilt_qty)
            managed_avg = rebuilt_avg if rebuilt_avg > 0 else prev_avg
            if managed_qty > 0:
                state["position_qty"] = managed_qty
                if managed_avg > 0:
                    state["avg_price"] = round(managed_avg, 4)
                state["broker_unmanaged_position"] = False
                state["broker_unmanaged_qty"] = max(0, qty - managed_qty)
                if managed_qty > 0:
                    state["buy1_used"] = True
            elif adopt_broker_positions:
                state["position_qty"] = qty
                if broker_avg > 0:
                    state["avg_price"] = round(broker_avg, 4)
                state["broker_unmanaged_position"] = False
                state["broker_unmanaged_qty"] = 0
            else:
                state["position_qty"] = 0
                state["avg_price"] = 0.0
                state["broker_unmanaged_position"] = qty > 0
                state["broker_unmanaged_qty"] = qty
            state["updated_at"] = self._timestamp()
            state_map[key] = state
            changed = True

        # 로컬 state에 보유중으로 표시돼있지만 브로커에 없는 종목 → 수량 0으로 정리
        for key, state in state_map.items():
            local_qty = self._safe_int(state.get("position_qty", 0), 0)
            local_market = str(state.get("market", "KS") or "KS").upper()
            if local_qty > 0 and local_market in fetched_markets and key not in broker_keys:
                state["position_qty"] = 0
                state["avg_price"] = 0.0
                state["buy1_used"] = False
                state["buy2_used"] = False
                state["broker_unmanaged_position"] = False
                state["broker_unmanaged_qty"] = 0
                state["updated_at"] = self._timestamp()
                state_map[key] = state
                changed = True

        if changed:
            self._save_state_map(state_map)

    def _store_state(self, state):
        with self._global_lock("state_io"):
            state_map = self._load_state_map()
            key = self._state_key(state.get("symbol", ""), state.get("market", "KS"))
            state_map[key] = state
            self._save_state_map(state_map)

    def _profile_for(self, symbol, strategy_id="vrev", market="KS"):
        resolved_strategy = self.strategy._normalize_strategy(strategy_id)
        default_profile = self.strategy._default_profile_for_market(market=market, strategy_id=resolved_strategy)
        trained_profile = self.strategy.latest_profile(symbol=symbol, strategy_id=resolved_strategy, market=market)
        if isinstance(trained_profile, dict):
            return {**default_profile, **trained_profile}
        latest = self.strategy.latest_training(market=market) or {}
        latest_strategy = latest.get("strategy_id", latest.get("best", {}).get("summary", {}).get("strategy_id", "vrev"))
        if latest.get("symbol") == symbol and latest_strategy == resolved_strategy:
            return {**default_profile, **(latest.get("best", {}).get("profile", {}) or {})}
        return default_profile

    def _load_runtime_logs(self, market=""):
        with self._global_lock("runtime_log_io"):
            fs = self._fs()
            logs = []
            targets = []
            market_key = str(market or "").upper().strip()
            if market_key in ("US", "KS", "KQ", "KR"):
                targets.append(self._runtime_log_path(market=market_key))
            else:
                targets = [
                    self._runtime_log_path("KS"),
                    self._runtime_log_path("US"),
                    "data/daytrade/runtime_logs.json",
                ]
            for path in targets:
                try:
                    if fs.exists(path) == False:
                        continue
                    chunk = fs.read.json(path, default=[]) or []
                    if isinstance(chunk, list):
                        logs.extend(chunk)
                except Exception:
                    continue
            if isinstance(logs, list) is False:
                return []
            return [self._normalize_display_log_item(item) for item in logs]

    def _append_runtime_log(self, level, message, symbol="", strategy_id="vrev", meta=None, dedup_sec=300, market=""):
        """
        런타임 로그 추가.
        dedup_sec: 동일 메시지가 이 시간(초) 이내에 이미 기록된 경우 스킵 (기본 300초=5분).
        타임스탬프는 파일에 KST로 저장하고, dedup 비교도 KST 기준으로 처리.
        """
        import time as _t
        with self._global_lock("runtime_log_io"):
            fs = self._fs()
            market_key = self._market_key(market=market, symbol=symbol)
            runtime_path = self._runtime_log_path(market=market_key)
            raw_logs = []
            try:
                if fs.exists(runtime_path):
                    raw_logs = fs.read.json(runtime_path, default=[]) or []
                    if not isinstance(raw_logs, list):
                        raw_logs = []
            except Exception:
                raw_logs = []
            raw_logs = raw_logs[-299:]

            kst_now = self._now()
            for recent in reversed(raw_logs[-20:]):
                if recent.get("level") != level or recent.get("message") != message:
                    continue
                if recent.get("symbol", "") != symbol:
                    continue
                ts_str = str(recent.get("timestamp", "") or "")
                ts_dt = _TIME.to_kst(ts_str)
                if ts_dt is not None and (kst_now - ts_dt).total_seconds() < dedup_sec:
                    return

            raw_logs.append({
                "timestamp": self._timestamp(),
                "level": level,
                "message": message,
                "symbol": symbol,
                "market": market_key,
                "strategy_id": self.strategy._normalize_strategy(strategy_id),
                "meta": meta or {},
            })
            fs.makedirs("data/daytrade")
            fs.write.json(runtime_path, raw_logs)

    def _chunk_qty(self, budget, price):
        budget = self._safe_float(budget, 0)
        price = self._safe_float(price, 0)
        if budget <= 0 or price <= 0:
            return 0
        return int(budget / price)

    def _buy_buffer_ratio(self):
        ratio = self._safe_float(self._config("daytrade_buy_buffer_ratio", "0.985"), 0.985)
        if ratio <= 0 or ratio > 1:
            return 0.985
        return ratio

    def _buy_qty(self, budget, price):
        safe_budget = self._safe_float(budget, 0) * self._buy_buffer_ratio()
        return self._chunk_qty(safe_budget, price)

    def _market_buy_budget(self, seed, price, market="KS"):
        requested_seed_krw = self._safe_float(seed, 0)
        current_price = self._safe_float(price, 0)
        payload = {
            "requested_seed_krw": round(requested_seed_krw, 2),
            "budget_total": requested_seed_krw,
            "buy_budget": requested_seed_krw,
            "budget_currency": "KRW",
            "price_currency": "KRW",
            "usd_krw": 0.0,
        }
        if self._is_us_market(market) is False:
            return payload

        usd_krw = 0.0
        try:
            raw = self._fetch_kis_balance_raw(use_cache_only=True)
            usd_krw = self._safe_float(raw.get("usd_krw", 0), 0)
        except Exception:
            usd_krw = 0.0
        if usd_krw <= 0:
            try:
                present = self.struct.kis_api.get_present_balance()
                usd_krw = self._safe_float(present.get("usd_krw", 0), 0)
            except Exception:
                usd_krw = 0.0
        if usd_krw <= 0:
            try:
                fx = self.struct.kis_api._get_usd_krw_rate_fallback()
                usd_krw = self._safe_float(fx.get("rate", 0), 0)
            except Exception:
                usd_krw = 0.0

        buy_budget_usd = (requested_seed_krw / usd_krw) if requested_seed_krw > 0 and usd_krw > 0 else 0.0
        min_entry_usd = self._minimum_entry_seed(current_price, market=market)
        budget_total_usd = max(buy_budget_usd, min_entry_usd) if min_entry_usd > 0 else buy_budget_usd
        payload.update({
            "budget_total": round(budget_total_usd, 4),
            "buy_budget": round(buy_budget_usd, 4),
            "budget_currency": "USD",
            "price_currency": "USD",
            "usd_krw": round(usd_krw, 4),
            "min_entry_budget": round(min_entry_usd, 4),
        })
        return payload

    def _minimum_entry_seed(self, price, market="KS"):
        base_price = self._safe_float(price, 0)
        if base_price <= 0:
            return 0.0
        ratio = self._buy_buffer_ratio()
        if ratio <= 0:
            ratio = 1.0
        required = max(base_price / ratio, base_price, 1.0)
        if self._buy_qty(required, base_price) < 1:
            required = (base_price + max(1.0, base_price * 0.001)) / ratio
        return float(required)

    def _state_order_open_position(self, state):
        orders = list((state or {}).get("orders", []) or [])
        open_qty = 0
        open_cost = 0.0
        for order in orders:
            action = str(order.get("action", "") or "").upper()
            qty = self._safe_int(order.get("qty", 0), 0)
            price = self._safe_float(order.get("price", 0), 0)
            if qty <= 0 or price <= 0:
                continue
            if action.startswith("BUY"):
                open_qty += qty
                open_cost += price * qty
                continue
            if action.startswith("SELL") and open_qty > 0:
                sell_qty = min(open_qty, qty)
                avg_price = (open_cost / open_qty) if open_qty > 0 else 0.0
                open_qty -= sell_qty
                open_cost = max(0.0, open_cost - (avg_price * sell_qty))
                if open_qty <= 0:
                    open_qty = 0
                    open_cost = 0.0
        avg_price = (open_cost / open_qty) if open_qty > 0 else 0.0
        return {
            "qty": open_qty,
            "avg_price": round(avg_price, 4),
        }

    def _recommendation_price_cap(self, raw_price_cap):
        raw_price_cap = self._safe_float(raw_price_cap, 0)
        if raw_price_cap <= 0:
            return 0.0
        if raw_price_cap < 100000:
            return float(int(raw_price_cap / 1000.0) * 1000)
        return float(int(raw_price_cap / 10000.0) * 10000)

    def _break_even_price(self, avg_price):
        avg_price = self._safe_float(avg_price, 0)
        if avg_price <= 0:
            return 0.0
        fee_buy = 0.00015
        fee_sell = 0.00195
        return avg_price * (1 + fee_buy) / (1 - fee_sell)

    def _estimate_exit_net_profit(self, avg_price, exit_price, qty):
        avg_price = self._safe_float(avg_price, 0)
        exit_price = self._safe_float(exit_price, 0)
        qty = self._safe_int(qty, 0)
        if avg_price <= 0 or exit_price <= 0 or qty <= 0:
            return 0.0
        gross = (exit_price - avg_price) * qty
        fee_buy = avg_price * qty * 0.00015
        fee_sell = exit_price * qty * 0.00195
        return gross - fee_buy - fee_sell

    def _estimate_exit_total_fee(self, avg_price, exit_price, qty):
        avg_price = self._safe_float(avg_price, 0)
        exit_price = self._safe_float(exit_price, 0)
        qty = self._safe_int(qty, 0)
        if avg_price <= 0 or exit_price <= 0 or qty <= 0:
            return 0.0
        fee_buy = avg_price * qty * 0.00015
        fee_sell = exit_price * qty * 0.00195
        return fee_buy + fee_sell

    def _last_buy_order(self, state):
        orders = list(state.get("orders", []) or [])
        for item in reversed(orders):
            if str(item.get("action", "")).startswith("BUY"):
                return item
        return None

    def _position_opened_at(self, state):
        state = state or {}
        orders = list(state.get("orders", []) or [])
        for item in orders:
            if str(item.get("action", "") or "").upper().startswith("BUY") is False:
                continue
            timestamp = str(item.get("timestamp", "") or "").strip()
            if timestamp != "":
                return timestamp
        first_buy_date = str(state.get("first_buy_date", "") or "").strip().replace("-", "")[:8]
        if len(first_buy_date) == 8:
            return f"{first_buy_date[:4]}-{first_buy_date[4:6]}-{first_buy_date[6:8]} 00:00:00"
        return ""

    def _active_position_sort_key(self, row):
        row = row or {}
        opened_at = str(row.get("opened_at", "") or "").strip()
        first_buy_date = str(row.get("first_buy_date", "") or "").strip().replace("-", "")[:8]
        if opened_at == "" and len(first_buy_date) == 8:
            opened_at = f"{first_buy_date[:4]}-{first_buy_date[4:6]}-{first_buy_date[6:8]} 00:00:00"
        symbol = str(row.get("symbol", "") or "")
        strategy_id = str(row.get("strategy_id", "") or "")
        return (opened_at == "", opened_at, symbol, strategy_id)

    def _minutes_since(self, timestamp):
        ts = str(timestamp or "").strip()
        if ts == "":
            return 0.0
        try:
            dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            return max(0.0, (self._now() - dt).total_seconds() / 60.0)
        except Exception:
            return 0.0

    def _aggregate_ticks_to_candle(self, symbol, market="KS"):
        """실시간 체결 틱을 모아 1분봉을 조립하여 반환. 데이터가 없으면 None 반환."""
        key = self._state_key(symbol, market)
        now = self._now()
        
        # 캐시 정리
        if key in self._AGGREGATED_CANDLES and (now - self._AGGREGATED_CANDLES[key]["last_ts"]).total_seconds() > self._AGGREGATED_CANDLES_TTL:
            del self._AGGREGATED_CANDLES[key]

        # KIS 실시간 체결가 API 호출
        try:
            ticks = self.struct.kis_api.get_domestic_realtime_price_details(symbol)
            if not ticks:
                return None
        except Exception:
            return None

        if key not in self._AGGREGATED_CANDLES:
            self._AGGREGATED_CANDLES[key] = {"ticks": [], "last_ts": now}
        
        self._AGGREGATED_CANDLES[key]["ticks"].extend(ticks)
        self._AGGREGATED_CANDLES[key]["last_ts"] = now

        all_ticks = self._AGGREGATED_CANDLES[key]["ticks"]
        if not all_ticks:
            return None

        # 현재 분(minute)에 해당하는 틱만 필터링
        current_minute_ticks = [
            t for t in all_ticks 
            if t.get("timestamp") and t["timestamp"].minute == now.minute
        ]

        if not current_minute_ticks:
            return None

        # OHLCV 계산
        open_price = current_minute_ticks[0]["price"]
        high_price = max(t["price"] for t in current_minute_ticks)
        low_price = min(t["price"] for t in current_minute_ticks)
        close_price = current_minute_ticks[-1]["price"]
        volume = sum(t["volume"] for t in current_minute_ticks)

        return {
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume,
            "timestamp": now.replace(second=0, microsecond=0),
        }

    def infinite_buy_daily_reserve(self):
        reserve_items = []
        reserve_usd = 0.0
        try:
            cycles = self.struct.engine.get_active_cycles()
        except Exception:
            cycles = []
        for cycle in cycles:
            status = str(cycle.get("status", ""))
            if status not in ["ACTIVE", "HOLDING"]:
                continue
            current_round = self._safe_int(cycle.get("current_round", 0), 0)
            division_count = self._safe_int(cycle.get("division_count", 0), 0)
            remaining_investment = self._safe_float(cycle.get("remaining_investment", 0), 0)
            remaining_rounds = max(division_count - current_round, 0)
            if remaining_rounds <= 0 or remaining_investment <= 0:
                continue
            next_buy_usd = remaining_investment / remaining_rounds
            reserve_usd += next_buy_usd
            reserve_items.append({
                "symbol": cycle.get("symbol", ""),
                "status": status,
                "current_round": current_round,
                "division_count": division_count,
                "next_buy_usd": round(next_buy_usd, 2),
            })
        return {
            "reserve_usd": round(reserve_usd, 2),
            "cycles": reserve_items,
            "cycle_count": len(reserve_items),
        }

    def _fetch_kis_balance_raw(self):
        """
        KIS API로 실제 잔고를 반환 (sys 모듈 기반 프로세스 레벨 캐시 경유)

        sys 모듈 속성은 exec() 재실행/클래스 재생성에도 살아남음 → 진짜 2분 TTL.
        TTL: 120초.
        """
        import time as _t, sys as _sys
        now = _t.time()
        _CACHE_KEY = "_trading_kis_balance_cache_v2"
        _CACHE_TS_KEY = "_trading_kis_balance_cache_ts"
        _CACHE_TTL = 120.0

        cached = getattr(_sys, _CACHE_KEY, None)
        cached_ts = getattr(_sys, _CACHE_TS_KEY, 0.0)
        if cached and (now - cached_ts) < _CACHE_TTL:
            return cached

        krw_balance = 0.0
        deposit_krw = 0.0
        withdrawable_krw = 0.0
        balance_withdrawable_krw = 0.0
        usd_krw = 0.0
        same_day_sell_krw = 0.0
        same_day_buy_krw = 0.0
        domestic_eval_krw = 0.0
        foreign_eval_krw = 0.0
        usd_cash_balance_usd = 0.0
        usd_cash_balance_krw = 0.0
        subscription_deposit_krw = 0.0
        d1_deposit_krw = 0.0
        d2_deposit_krw = 0.0
        present_total_asset_krw = 0.0
        direct_total_asset_krw = 0.0
        summary_total_asset_krw = 0.0
        source = "manual"
        total_asset_source = "fallback"
        # 1순위: 주문가능금액 조회 (TTTC8908R) → 실제 매수 가능액(당일매도 재사용 포함)
        try:
            defaults = self.strategy.defaults()
            budget_symbol = defaults.get("symbol", "005930")
            domestic = self.struct.kis_api.get_domestic_buying_power_info(symbol=budget_symbol, order_type="MARKET")
            if domestic.get("ok"):
                withdrawable_krw = self._safe_float(domestic.get("amount", 0), 0)
                source = f"buying_power:{domestic.get('source', 'ord_psbl_cash')}"
        except Exception:
            pass
        # 2순위: 잔고조회는 당일 매수/매도 흐름 참고용으로만 사용한다.
        # 실주문 예산은 예수금총액이 아니라 현금최대가능 금액(TTTC8908R) 기준으로 계산한다.
        try:
            domestic_bal = self.struct.kis_api.get_domestic_balance()
            same_day_sell_krw = self._safe_float(domestic_bal.get("same_day_sell_krw", 0), 0)
            same_day_buy_krw = self._safe_float(domestic_bal.get("same_day_buy_krw", 0), 0)
            _krw = self._safe_float(domestic_bal.get("krw_balance", 0), 0)
            if _krw > 0:
                deposit_krw = _krw
                krw_balance = _krw
            domestic_holdings = domestic_bal.get("holdings", []) or []
            holdings_eval_krw = round(sum(
                self._safe_float(item.get("current_price", 0), 0) * self._safe_int(item.get("qty", 0), 0)
                for item in domestic_holdings
            ), 2)
            domestic_eval_krw = holdings_eval_krw
            raw_summary = domestic_bal.get("raw", {}).get("output2", {}) if isinstance(domestic_bal.get("raw", {}), dict) else {}
            if isinstance(raw_summary, list):
                raw_summary = raw_summary[0] if len(raw_summary) > 0 else {}
            if isinstance(raw_summary, dict):
                summary_domestic_eval = self.struct.kis_api._pick_first_amount(raw_summary, [
                    "scts_evlu_amt",
                    "evlu_amt_smtl_amt",
                ])
                if summary_domestic_eval > 0:
                    domestic_eval_krw = summary_domestic_eval
                subscription_deposit_krw = self.struct.kis_api._pick_first_amount(raw_summary, [
                    "subsc_amt",
                    "subsc_tot_amt",
                    "subsprc_amt",
                    "subsprc_tot_amt",
                    "req_ipos_amt",
                    "stck_subs_amt",
                    "subt_dps",
                ])
                d1_deposit_krw = self.struct.kis_api._pick_first_amount(raw_summary, [
                    "nxdy_excc_amt",
                    "prvs_rcdl_excc_amt",
                ])
                d2_deposit_krw = self.struct.kis_api._pick_first_amount(raw_summary, [
                    "d2_auto_rdpt_amt",
                    "nxdy_auto_rdpt_amt",
                ])
                summary_total_asset_krw = self.struct.kis_api._pick_first_amount(raw_summary, [
                    "tot_evlu_amt",
                    "nass_amt",
                    "bfdy_tot_asst_evlu_amt",
                    "tot_asst_amt",
                ])
            _wdw = self._safe_float(domestic_bal.get("withdrawable_krw", 0), 0)
            balance_withdrawable_krw = _wdw or _krw
            if balance_withdrawable_krw > withdrawable_krw:
                withdrawable_krw = balance_withdrawable_krw
                source = "domestic_balance:inquire-balance"
        except Exception:
            pass
        if deposit_krw <= 0 and withdrawable_krw > 0:
            deposit_krw = withdrawable_krw
        krw_balance = deposit_krw
        # 환율은 해외주식 잔고 API에서
        try:
            present = self.struct.kis_api.get_present_balance()
            usd_krw = self._safe_float(present.get("usd_krw", 0), 0)
            present_total_asset_krw = self._safe_float(present.get("total_asset_krw", 0), 0)
            if present_total_asset_krw > 0:
                total_asset_source = "present_balance.total_asset_krw"
        except Exception:
            pass
        try:
            overseas = self.struct.kis_api.get_balance()
            usd_cash_balance_usd = self._safe_float(overseas.get("cash_balance", 0), 0)
            foreign_eval_usd = self._safe_float(overseas.get("total_eval", 0), 0)
            if foreign_eval_usd <= 0:
                foreign_eval_usd = sum(self._safe_float(item.get("eval_amount", 0), 0) for item in (overseas.get("holdings", []) or []))
            foreign_eval_krw = round(foreign_eval_usd * usd_krw, 2) if usd_krw > 0 else 0.0
            usd_cash_balance_krw = round(usd_cash_balance_usd * usd_krw, 2) if usd_krw > 0 else 0.0
        except Exception:
            pass
        direct_total_asset_krw = round(
            balance_withdrawable_krw + domestic_eval_krw + foreign_eval_krw + usd_cash_balance_krw + subscription_deposit_krw,
            2,
        )
        fallback_total_asset_krw = round(balance_withdrawable_krw + domestic_eval_krw + foreign_eval_krw + subscription_deposit_krw, 2)
        total_asset_candidates = [
            (present_total_asset_krw, "present_balance.total_asset_krw"),
            (direct_total_asset_krw, "direct(krw+domestic_eval+usd_cash+usd_eval)"),
            (summary_total_asset_krw, "domestic_balance.summary_total_asset_krw"),
            (max(
                fallback_total_asset_krw,
                d1_deposit_krw,
                d2_deposit_krw,
                balance_withdrawable_krw,
                deposit_krw,
            ), "fallback_total_asset_krw"),
        ]
        total_asset_krw, total_asset_source = max(total_asset_candidates, key=lambda item: self._safe_float(item[0], 0))
        total_asset_krw = round(self._safe_float(total_asset_krw, 0), 2)
        raw = {
            "krw_balance": krw_balance,
            "deposit_krw": deposit_krw,
            "withdrawable_krw": withdrawable_krw,
            "holdings": domestic_holdings,
            "usd_krw": usd_krw,
            "same_day_sell_krw": same_day_sell_krw,
            "same_day_buy_krw": same_day_buy_krw,
            "domestic_eval_krw": domestic_eval_krw,
            "foreign_eval_krw": foreign_eval_krw,
            "usd_cash_balance_usd": usd_cash_balance_usd,
            "usd_cash_balance_krw": usd_cash_balance_krw,
            "subscription_deposit_krw": subscription_deposit_krw,
            "d1_deposit_krw": d1_deposit_krw,
            "d2_deposit_krw": d2_deposit_krw,
            "present_total_asset_krw": present_total_asset_krw,
            "direct_total_asset_krw": direct_total_asset_krw,
            "fallback_total_asset_krw": fallback_total_asset_krw,
            "summary_total_asset_krw": summary_total_asset_krw,
            "total_asset_krw": total_asset_krw,
            "source": source,
            "total_asset_source": total_asset_source,
        }
        # sys 모듈에 인메모리 캐시 저장 (exec() 재실행 후에도 유지)
        setattr(_sys, _CACHE_KEY, raw)
        setattr(_sys, _CACHE_TS_KEY, now)
        return raw

    def shared_budget_status(self, requested_seed=0, use_cache_only=False, market="KS"):
        """
        예산 상태 반환.
        use_cache_only=True: 캐시 없으면 KIS API 호출 없이 0으로 반환 (UI fast path용)
        """
        import time as _t, sys as _sys
        market_key = "US" if self._is_us_market(market) else "KS"
        reserve = self.infinite_buy_daily_reserve()
        _CACHE_KEY = "_trading_kis_balance_cache_v2"
        _CACHE_TS_KEY = "_trading_kis_balance_cache_ts"
        _CACHE_TTL = 120.0
        cached = getattr(_sys, _CACHE_KEY, None)
        cached_ts = getattr(_sys, _CACHE_TS_KEY, 0.0)
        cache_fresh = cached and (_t.time() - cached_ts) < _CACHE_TTL
        
        if use_cache_only and not cache_fresh:
            # 캐시 없음 → 빠른 응답 (잔고 0)
            raw = {"krw_balance": 0.0, "withdrawable_krw": 0.0, "usd_krw": 0.0,
                   "same_day_sell_krw": 0.0, "same_day_buy_krw": 0.0, "source": "cache_miss"}
        else:
            raw = self._fetch_kis_balance_raw()
        withdrawable_krw = raw["withdrawable_krw"]
        krw_balance = raw["krw_balance"]
        deposit_krw = self._safe_float(raw.get("deposit_krw", krw_balance), 0)
        usd_krw = raw["usd_krw"]
        same_day_sell_krw = self._safe_float(raw.get("same_day_sell_krw", 0), 0)
        same_day_buy_krw = self._safe_float(raw.get("same_day_buy_krw", 0), 0)
        domestic_eval_krw = self._safe_float(raw.get("domestic_eval_krw", 0), 0)
        foreign_eval_krw = self._safe_float(raw.get("foreign_eval_krw", 0), 0)
        usd_cash_balance_usd = self._safe_float(raw.get("usd_cash_balance_usd", 0), 0)
        usd_cash_balance_krw = self._safe_float(raw.get("usd_cash_balance_krw", 0), 0)
        subscription_deposit_krw = self._safe_float(raw.get("subscription_deposit_krw", 0), 0)
        d1_deposit_krw = self._safe_float(raw.get("d1_deposit_krw", 0), 0)
        d2_deposit_krw = self._safe_float(raw.get("d2_deposit_krw", 0), 0)
        present_total_asset_krw = self._safe_float(raw.get("present_total_asset_krw", 0), 0)
        direct_total_asset_krw = self._safe_float(raw.get("direct_total_asset_krw", 0), 0)
        fallback_total_asset_krw = self._safe_float(raw.get("fallback_total_asset_krw", 0), 0)
        summary_total_asset_krw = self._safe_float(raw.get("summary_total_asset_krw", 0), 0)
        total_asset_krw = self._safe_float(raw.get("total_asset_krw", 0), 0)
        source = raw["source"]
        total_asset_source = raw.get("total_asset_source", "fallback_total_asset_krw")
        us_orderable_amount_usd = 0.0
        us_orderable_amount_krw = 0.0
        us_combined_orderable_amount_usd = 0.0
        us_combined_orderable_amount_krw = 0.0
        us_estimated_orderable_amount_usd = 0.0
        us_estimated_orderable_qty = 0
        us_orderable_qty = 0
        us_cash_balance_usd = 0.0
        us_krw_auto_exchange_krw = 0.0
        us_krw_auto_exchange_estimate_usd = 0.0
        if market_key == "US":
            try:
                us_defaults = self.strategy.us_defaults()
                budget_symbol = str(us_defaults.get("symbol", "TQQQ") or "TQQQ").upper()
                exchange = "NASD"
                for item in (self.strategy.us_candidate_universe() or []):
                    if str(item.get("symbol", "") or "").upper() == budget_symbol:
                        exchange = str(item.get("exchange", exchange) or exchange).upper()
                        break
                us_power = self.struct.kis_api.get_buying_power_info(symbol=budget_symbol, exchange=exchange)
                if us_power.get("ok"):
                    us_orderable_amount_usd = self._safe_float(us_power.get("amount", 0), 0)
                    us_orderable_qty = max(0, self._safe_int(us_power.get("qty", 0), 0))
                    us_estimated_orderable_amount_usd = max(
                        us_orderable_amount_usd,
                        self._safe_float(us_power.get("estimated_amount", us_orderable_amount_usd), us_orderable_amount_usd),
                    )
                    us_estimated_orderable_qty = max(
                        us_orderable_qty,
                        self._safe_int(us_power.get("estimated_qty", us_orderable_qty), us_orderable_qty),
                    )
                    us_krw_auto_exchange_estimate_usd = self._safe_float(us_power.get("krw_auto_exchange_estimate_usd", 0), 0)
                    us_orderable_amount_krw = round(us_orderable_amount_usd * usd_krw, 2) if usd_krw > 0 else 0.0
                    us_combined_orderable_amount_usd = us_estimated_orderable_amount_usd
                    us_combined_orderable_amount_krw = round(us_combined_orderable_amount_usd * usd_krw, 2) if usd_krw > 0 else 0.0
                    source = f"us_buying_power:{us_power.get('source', 'ovrs_ord_psbl_amt')}"
            except Exception:
                pass
            try:
                overseas_balance = self.struct.kis_api.get_balance() or {}
                us_cash_balance_usd = self._safe_float(overseas_balance.get("cash_balance", 0), 0)
            except Exception:
                us_cash_balance_usd = 0.0
            if withdrawable_krw > 0:
                us_krw_auto_exchange_krw = withdrawable_krw
        # 무한매수 예약금 차감 여부 콜록 (DB 콘피그)
        ignore_reserve = str(self._config("daytrade_ignore_reserve", "false")).lower() == "true"
        reserved_krw = 0.0
        if ignore_reserve is False and market_key == "US":
            reserved_krw = reserve.get("reserve_usd", 0) * usd_krw if usd_krw > 0 else 0.0
        # withdrawable_krw는 TTTC8908R(주문가능금액) 기준이므로 당일매도분이 이미 포함됨.
        # same_day_sell_krw는 참고용 표시 전용 — 여기에 다시 더하면 이중계산 됨.
        intraday_usable_krw = 0.0  # 이중계산 방지: 주문가능금액에 이미 반영
        # D+1: 익일 주문가능금액(nxdy_excc_amt) — D+0에 D+1 결제분 추가된 증분액
        # D+2: D+2 자동상환금액(d2_auto_rdpt_amt) — D+2에 결제되는 증분액
        # 전체 사용 가능 예수금 = D+0 + D+1 + D+2 증분 합산
        if market_key == "US":
            tradable_cash_krw = max(us_combined_orderable_amount_krw, us_orderable_amount_krw + us_krw_auto_exchange_krw)
        else:
            tradable_cash_krw = withdrawable_krw + d1_deposit_krw + d2_deposit_krw
            if tradable_cash_krw <= 0 and domestic_eval_krw <= 0 and foreign_eval_krw <= 0:
                tradable_cash_krw = max(tradable_cash_krw, total_asset_krw)
        available_before_reserve = max(0.0, tradable_cash_krw)
        available_for_daytrade = max(0.0, available_before_reserve - reserved_krw)
        requested_seed = self._safe_float(requested_seed, 0)
        live_order_seed = available_for_daytrade
        portfolio = self.portfolio_usage(use_live_price=True, market_filter=market_key)
        market_used_seed_krw = round(max(0.0, self._safe_float(portfolio.get("active_entry_seed_krw", portfolio.get("active_cost_krw", 0)), 0)), 2)
        cross_market_used_seed_krw = market_used_seed_krw
        if market_key == "US":
            try:
                shared_portfolio = self.portfolio_usage(use_live_price=True)
                cross_market_used_seed_krw = round(max(0.0, self._safe_float(shared_portfolio.get("active_entry_seed_krw", shared_portfolio.get("active_cost_krw", market_used_seed_krw)), market_used_seed_krw)), 2)
            except Exception:
                cross_market_used_seed_krw = market_used_seed_krw
        used_seed_krw = max(market_used_seed_krw, cross_market_used_seed_krw)
        capacity_daytrade_seed_krw = round(max(0.0, available_for_daytrade + used_seed_krw), 2)
        # total_seed_krw: min(requested_seed, total_asset_krw) — 총 자산이 시드 상한
        # 설정 시드가 총 자산보다 크면 총 자산이 곧 시드 (없는 돈을 시드로 쓸 수 없음)
        _asset_cap = total_asset_krw if total_asset_krw > 0 else capacity_daytrade_seed_krw
        if requested_seed > 0:
            total_seed_krw = round(min(requested_seed, _asset_cap), 2)
        else:
            total_seed_krw = round(_asset_cap, 2)
        # remaining_seed_krw: total_seed - used (현금 cap 없음)
        # 총 자산 - 현재 포지션 매입금액 = 추가 매수 가능 금액
        remaining_seed_krw = round(max(0.0, total_seed_krw - used_seed_krw), 2)
        # effective_seed: 실질 주문 기준 시드 = remaining_seed (총자산기반)
        # available_for_daytrade(현금기준 21,539)로 cap하지 않음
        effective_seed = remaining_seed_krw
        position_count = self._safe_int(portfolio.get("position_count", 0), 0)
        max_symbols = self._auto_max_symbols(market=market_key)
        slot_min_key = "daytrade_us_min_slot_seed_krw" if market_key == "US" else "daytrade_ks_min_slot_seed_krw"
        min_slot_seed_krw = max(10000.0, self._safe_float(self._config(slot_min_key, self._config("daytrade_min_slot_seed_krw", "50000")), 50000))
        slot_target_count = min(max_symbols, max(position_count + (1 if remaining_seed_krw > 0 and position_count < max_symbols else 0), 1))
        available_slot_count = max(0, max_symbols - position_count)
        slot_seed_limit_krw = round(max(0.0, total_seed_krw / slot_target_count), 2) if total_seed_krw > 0 and slot_target_count > 0 else 0.0
        per_symbol_seed_krw = round(min(remaining_seed_krw, slot_seed_limit_krw if slot_seed_limit_krw > 0 else remaining_seed_krw), 2) if remaining_seed_krw > 0 else 0.0
        return {
            "market": market_key,
            "cash_max_krw": round(tradable_cash_krw, 2),
            "withdrawable_krw": round(withdrawable_krw, 2),
            "krw_balance": round(krw_balance, 2),
            "deposit_krw": round(deposit_krw, 2),
            "usd_krw": round(usd_krw, 4),
            "us_orderable_amount_usd": round(us_orderable_amount_usd, 2),
            "us_orderable_amount_krw": round(us_orderable_amount_krw, 2),
            "us_orderable_qty": us_orderable_qty,
            "us_estimated_orderable_amount_usd": round(us_estimated_orderable_amount_usd, 2),
            "us_estimated_orderable_qty": us_estimated_orderable_qty,
            "us_combined_orderable_amount_usd": round(us_combined_orderable_amount_usd, 2),
            "us_combined_orderable_amount_krw": round(us_combined_orderable_amount_krw, 2),
            "us_cash_balance_usd": round(us_cash_balance_usd, 2),
            "us_krw_auto_exchange_krw": round(us_krw_auto_exchange_krw, 2),
            "us_krw_auto_exchange_estimate_usd": round(us_krw_auto_exchange_estimate_usd, 2),
            "same_day_sell_krw": round(same_day_sell_krw, 2),
            "same_day_buy_krw": round(same_day_buy_krw, 2),
            "domestic_eval_krw": round(domestic_eval_krw, 2),
            "foreign_eval_krw": round(foreign_eval_krw, 2),
            "usd_cash_balance_usd": round(usd_cash_balance_usd, 2),
            "usd_cash_balance_krw": round(usd_cash_balance_krw, 2),
            "subscription_deposit_krw": round(subscription_deposit_krw, 2),
            "d1_deposit_krw": round(d1_deposit_krw, 2),
            "d2_deposit_krw": round(d2_deposit_krw, 2),
            "present_total_asset_krw": round(present_total_asset_krw, 2),
            "direct_total_asset_krw": round(direct_total_asset_krw, 2),
            "fallback_total_asset_krw": round(fallback_total_asset_krw, 2),
            "summary_total_asset_krw": round(summary_total_asset_krw, 2),
            "total_asset_krw": round(total_asset_krw, 2),
            "total_asset_source": total_asset_source,
            "intraday_usable_krw": round(intraday_usable_krw, 2),
            "available_before_reserve": round(available_before_reserve, 2),
            "infinite_buy_daily_reserve_usd": round(reserve.get("reserve_usd", 0), 2),
            "infinite_buy_daily_reserve_krw": round(reserve.get("reserve_usd", 0) * usd_krw if usd_krw > 0 else 0.0, 2),
            "reserve_ignored": ignore_reserve,
            "available_for_daytrade": round(available_for_daytrade, 2),
            "actual_orderable_seed_krw": round(available_for_daytrade, 2),
            "live_order_seed": round(live_order_seed, 2),
            "requested_seed": round(requested_seed, 2),
            "effective_daytrade_seed": round(effective_seed, 2),
            "capacity_daytrade_seed_krw": capacity_daytrade_seed_krw,
            "total_seed_krw": total_seed_krw,
            "market_used_seed_krw": market_used_seed_krw,
            "cross_market_used_seed_krw": cross_market_used_seed_krw,
            "used_seed_krw": used_seed_krw,
            "remaining_seed_krw": remaining_seed_krw,
            "seed_usage_pct": round((used_seed_krw / total_seed_krw * 100), 2) if total_seed_krw > 0 else 0.0,
            "position_count": position_count,
            "max_symbols": max_symbols,
            "slot_target_count": slot_target_count,
            "available_slot_count": available_slot_count,
            "slot_seed_limit_krw": slot_seed_limit_krw,
            "per_symbol_seed_krw": per_symbol_seed_krw,
            "portfolio": portfolio,
            "source": source,
            "reserve_cycles": reserve.get("cycles", []),
            "reserve_cycle_count": reserve.get("cycle_count", 0),
            "message": ("무한매수 예약금 무시 중 — 현금최대가능 전액을 단타 실주문에 사용합니다." if ignore_reserve
                else "무한매수 당일 예약금 차감 후 남는 현금최대가능 금액만 단타 실주문에 사용합니다."),
        }

    def _current_price(self, symbol, market="KS", fallback=0.0):
        try:
            # 1순위: 실시간 조립 캔들
            candle = self._aggregate_ticks_to_candle(symbol, market=market)
            if candle and self._safe_float(candle.get("close", 0), 0) > 0:
                return self._safe_float(candle.get("close", 0), 0)
            
            # 2순위: 스냅샷 캐시
            _session, bar = self._latest_snapshot(symbol, market=market)
            price = self._safe_float(bar.get("close", 0), 0)
            if price > 0:
                return price
        except Exception:
            pass
        return self._safe_float(fallback, 0)

    def portfolio_usage(self, use_live_price=True, market_filter=None):
        rows = []
        active_market_value = 0.0
        active_cost_value = 0.0
        active_committed_seed = 0.0
        active_entry_seed = 0.0
        active_qty = 0
        positions = self.active_positions()
        for position in positions:
            qty = self._safe_int(position.get("position_qty", 0), 0)
            if qty <= 0:
                continue
            symbol = position.get("symbol", "")
            market = position.get("market", "KS")
            if market_filter is not None and str(market).upper() != str(market_filter).upper():
                continue
            avg_price = self._safe_float(position.get("avg_price", 0), 0)
            current_price = self._safe_float(position.get("current_price", avg_price), avg_price)
            if use_live_price:
                current_price = self._current_price(symbol, market=market, fallback=current_price or avg_price)
            market_value = current_price * qty
            cost_value = avg_price * qty
            committed_seed = max(cost_value, market_value)
            active_market_value += market_value
            active_cost_value += cost_value
            active_committed_seed += committed_seed
            active_entry_seed += cost_value
            active_qty += qty
            rows.append({
                "symbol": symbol,
                "market": market,
                "name": position.get("name", self.strategy.symbol_name(symbol)),
                "strategy_id": position.get("strategy_id", "vrev"),
                "position_qty": qty,
                "avg_price": round(avg_price, 4),
                "current_price": round(current_price, 4),
                "position_value": round(market_value, 2),
                "position_cost": round(cost_value, 2),
                "entry_seed": round(cost_value, 2),
                "committed_seed": round(committed_seed, 2),
            })
        rows.sort(key=lambda x: x.get("position_value", 0), reverse=True)
        return {
            "active_value_krw": round(active_market_value, 2),
            "active_cost_krw": round(active_cost_value, 2),
            "active_market_value_krw": round(active_market_value, 2),
            "active_entry_seed_krw": round(active_entry_seed, 2),
            "active_committed_seed_krw": round(active_committed_seed, 2),
            "active_qty": active_qty,
            "active_positions": rows,
            "position_count": len(rows),
        }

    def daily_loss_status(self, requested_seed=0, use_live_price=True, use_cache_only=False):
        today = self._now().strftime("%Y-%m-%d")
        state_map = self._load_state_map()
        realized_profit = 0.0
        unrealized_profit = 0.0
        tracked_symbols = []
        for key in state_map:
            state = state_map.get(key, {}) or {}
            qty = self._safe_int(state.get("position_qty", 0), 0)
            session_date = str(state.get("session_date", "") or "")
            if qty <= 0 and session_date != today:
                continue
            symbol = state.get("symbol", "")
            market = state.get("market", "KS")
            avg_price = self._safe_float(state.get("avg_price", 0), 0)
            fallback_price = self._safe_float(state.get("last_price", avg_price), avg_price)
            if use_live_price:
                current_price = self._current_price(symbol, market=market, fallback=fallback_price or avg_price)
            else:
                current_price = fallback_price if fallback_price > 0 else avg_price
            realized = self._safe_float(state.get("realized_profit", 0), 0)
            unrealized = ((current_price - avg_price) * qty) if qty > 0 and avg_price > 0 else 0.0
            realized_profit += realized
            unrealized_profit += unrealized
            tracked_symbols.append({
                "symbol": symbol,
                "market": market,
                "name": state.get("name", self.strategy.symbol_name(symbol)),
                "strategy_id": state.get("strategy_id", "vrev"),
                "realized_profit": round(realized, 2),
                "unrealized_profit": round(unrealized, 2),
                "position_qty": qty,
            })
        total_pnl = realized_profit + unrealized_profit
        loss_limit = abs(self._safe_float(self._config("daytrade_daily_loss_limit_krw", "150000"), 150000))
        soft_limit_reached = loss_limit > 0 and total_pnl <= (-1 * loss_limit)
        halt_enabled = str(self._config("daytrade_daily_loss_halt_enabled", "false") or "false").lower() == "true"
        halt_new_buys = halt_enabled and soft_limit_reached
        remaining_buffer = max(0.0, loss_limit + total_pnl) if loss_limit > 0 else 0.0
        seed = self.shared_budget_status(requested_seed=requested_seed, use_cache_only=use_cache_only)
        return {
            "session_date": today,
            "requested_seed": round(self._safe_float(requested_seed, 0), 2),
            "effective_seed": seed.get("effective_daytrade_seed", 0),
            "daily_loss_limit_krw": round(loss_limit, 2),
            "realized_profit": round(realized_profit, 2),
            "unrealized_profit": round(unrealized_profit, 2),
            "total_pnl": round(total_pnl, 2),
            "remaining_buffer": round(remaining_buffer, 2),
            "halt_enabled": halt_enabled,
            "soft_limit_reached": soft_limit_reached,
            "halt_new_buys": halt_new_buys,
            "tracked_symbols": tracked_symbols,
        }

    def kr_auto_cycle(self, requested_seed=0, force_recommend=False):
        if self._hard_locked():
            return self._hard_locked_result()
        if self.auto_enabled() is False:
            return {
                "executed": False,
                "message": "단타 자동운용이 비활성 상태입니다.",
                "budget": self.shared_budget_status(requested_seed=requested_seed, market="KS"),
                "daily_loss": self.daily_loss_status(requested_seed=requested_seed),
                "results": [],
                "candidates": [],
            }

        if not self._daytrade_market_open(market="KS"):
            return {
                "executed": False,
                "message": "국내 주식 시장이 열려있지 않습니다.",
                "budget": self.shared_budget_status(requested_seed=requested_seed, market="KS"),
                "daily_loss": self.daily_loss_status(requested_seed=requested_seed),
                "results": [],
                "candidates": [],
            }

        candidate_payload = self.auto_candidates(requested_seed=requested_seed, force_recommend=force_recommend, market="KS")
        self._append_runtime_log("info", "국내 단타 자동순환 시작", meta={
            "market": "KS",
            "requested_seed": round(self._safe_float(requested_seed, 0), 2),
            "candidate_count": len(candidate_payload.get("candidates", []) or []),
            "excluded_count": len(candidate_payload.get("excluded_by_price", []) or []),
            "position_count": self._safe_int(candidate_payload.get("position_count", 0), 0),
            "max_symbols": self._safe_int(candidate_payload.get("max_symbols", self._auto_max_symbols(market="KS")), self._auto_max_symbols(market="KS")),
            "remaining_seed_krw": round(self._safe_float(candidate_payload.get("remaining_seed_krw", 0), 0), 2),
        })

        effective_seed = self._safe_float(candidate_payload.get("effective_seed", 0), 0)
        remaining_seed_krw = self._safe_float(candidate_payload.get("remaining_seed_krw", effective_seed), effective_seed)
        tracked_position_count = self._safe_int(candidate_payload.get("position_count", 0), 0)
        excluded_by_price = candidate_payload.get("excluded_by_price", []) or []
        max_affordable = candidate_payload.get("max_affordable_per_share", 0)

        if effective_seed <= 0:
            return {
                "executed": False,
                "message": "단타에 사용할 수 있는 여유 시드가 없습니다.",
                "budget": self.shared_budget_status(requested_seed=requested_seed, market="KS"),
                "daily_loss": self.daily_loss_status(requested_seed=requested_seed),
                "results": [],
                "candidates": candidate_payload.get("candidates", []),
                "excluded_by_price": excluded_by_price,
                "max_affordable_per_share": max_affordable,
            }

        results = []
        executed_count = 0
        candidate_rows = list(candidate_payload.get("candidates", []) or [])
        slot_seed_limit_krw = self._safe_float(candidate_payload.get("slot_seed_limit_krw", 0), 0)

        for item in candidate_rows:
            symbol = item.get("symbol", "")
            market = item.get("market", "KS")
            strategy_id = item.get("strategy_id", "vrev")
            remaining_slots = max(0, self._auto_max_symbols(market="KS") - tracked_position_count)
            is_new_entry = item.get("source") != "active_position"
            allocation_seed = 0.0
            min_required_seed = self._minimum_entry_seed(self._safe_float(item.get("last_price", 0), 0), market=market)

            if is_new_entry:
                if remaining_seed_krw <= 0:
                    results.append({
                        "symbol": symbol,
                        "market": market,
                        "name": item.get("name", ""),
                        "strategy_id": strategy_id,
                        "source": item.get("source", "leaderboard"),
                        "score": item.get("score", 0),
                        "executed": False,
                        "message": "남은 시드가 없어 신규 진입을 보류했습니다.",
                        "signal": "HOLD",
                        "risk_status": "WARN",
                        "current_price": self._safe_float(item.get("last_price", 0), 0),
                        "allocated_seed": 0,
                        "remaining_seed_before": round(remaining_seed_krw, 2),
                        "remaining_seed_after": round(remaining_seed_krw, 2),
                    })
                    continue
                if remaining_slots <= 0:
                    results.append({
                        "symbol": symbol,
                        "market": market,
                        "name": item.get("name", ""),
                        "strategy_id": strategy_id,
                        "source": item.get("source", "leaderboard"),
                        "score": item.get("score", 0),
                        "executed": False,
                        "message": "보유 종목 수 상한에 도달해 신규 진입을 보류했습니다.",
                        "signal": "HOLD",
                        "risk_status": "WARN",
                        "current_price": self._safe_float(item.get("last_price", 0), 0),
                        "allocated_seed": 0,
                        "remaining_seed_before": round(remaining_seed_krw, 2),
                        "remaining_seed_after": round(remaining_seed_krw, 2),
                    })
                    continue
                allocation_seed = max(
                    self._safe_float(item.get("entry_seed_krw", 0), 0),
                    min_required_seed,
                )
                if slot_seed_limit_krw > 0:
                    allocation_seed = min(allocation_seed, slot_seed_limit_krw)
                allocation_seed = min(remaining_seed_krw, allocation_seed)
            else:
                current_price = max(
                    self._safe_float(item.get("last_price", 0), 0),
                    self._safe_float(item.get("current_price", 0), 0),
                    0,
                )
                current_position_value = self._safe_float(item.get("position_value_krw", 0), 0)
                target_position_seed = slot_seed_limit_krw if slot_seed_limit_krw > 0 else remaining_seed_krw
                addable_seed = max(0.0, target_position_seed - current_position_value)
                allocation_seed = max(current_price, min(remaining_seed_krw, addable_seed)) if addable_seed > 0 else 0.0
                if allocation_seed <= 0:
                    results.append({
                        "symbol": symbol,
                        "market": market,
                        "name": item.get("name", ""),
                        "strategy_id": strategy_id,
                        "source": item.get("source", "active_position"),
                        "score": item.get("score", 0),
                        "executed": False,
                        "message": "종목당 시드 한도에 도달해 추가 매수를 보류했습니다.",
                        "signal": "HOLD",
                        "risk_status": "SAFE",
                        "current_price": current_price,
                        "allocated_seed": 0,
                        "remaining_seed_before": round(remaining_seed_krw, 2),
                        "remaining_seed_after": round(remaining_seed_krw, 2),
                    })
                    continue

            before_seed = remaining_seed_krw
            try:
                outcome = self.execute_live(symbol, market=market, seed=allocation_seed, name=item.get("name", ""), strategy_id=strategy_id)
                action = str(outcome.get("action", "") or outcome.get("status", {}).get("signal", {}).get("action", "HOLD"))
                order_value = self._safe_float(outcome.get("order_value", 0), 0)
                runtime_payload = outcome.get("status", {}).get("runtime", {}) or {}
                if outcome.get("executed"):
                    executed_count += 1
                    if action.startswith("BUY"):
                        tracked_position_count += 1
                        remaining_seed_krw = max(0.0, remaining_seed_krw - max(order_value, 0))
                    elif action.startswith("SELL"):
                        tracked_position_count = max(0, tracked_position_count - 1)
                        remaining_seed_krw = min(effective_seed, remaining_seed_krw + max(order_value, 0))
                results.append({
                    "symbol": symbol,
                    "market": market,
                    "name": item.get("name", ""),
                    "strategy_id": strategy_id,
                    "source": item.get("source", "leaderboard"),
                    "score": item.get("score", 0),
                    "executed": bool(outcome.get("executed", False)),
                    "message": outcome.get("message", ""),
                    "signal": outcome.get("status", {}).get("signal", {}).get("action", "HOLD"),
                    "risk_status": outcome.get("status", {}).get("runtime", {}).get("risk_status", "SAFE"),
                    "current_price": self._safe_float(outcome.get("status", {}).get("signal", {}).get("current_price", 0), 0),
                    "signal_reason": outcome.get("status", {}).get("signal", {}).get("reason", outcome.get("message", "")),
                    "runtime_issues": runtime_payload.get("issues", []),
                    "runtime_warnings": runtime_payload.get("warnings", []),
                    "order_value": round(order_value, 2),
                    "allocated_seed": round(allocation_seed, 2),
                    "remaining_seed_before": round(before_seed, 2),
                    "remaining_seed_after": round(remaining_seed_krw, 2),
                })
            except Exception as e:
                results.append({
                    "symbol": symbol,
                    "market": market,
                    "name": item.get("name", ""),
                    "strategy_id": strategy_id,
                    "source": item.get("source", "leaderboard"),
                    "score": item.get("score", 0),
                    "executed": False,
                    "message": str(e),
                    "signal": "ERROR",
                    "risk_status": "HALT",
                    "current_price": self._safe_float(item.get("last_price", 0), 0),
                    "runtime_issues": [str(e)],
                    "runtime_warnings": [],
                    "order_value": 0,
                    "allocated_seed": round(allocation_seed, 2),
                    "remaining_seed_before": round(before_seed, 2),
                    "remaining_seed_after": round(remaining_seed_krw, 2),
                })

        daily_loss = self.daily_loss_status(requested_seed=effective_seed)
        message = f"국내 주식 자동 점검 완료. 후보 {len(candidate_rows)}개를 점검했습니다."
        if executed_count > 0:
            message = f"국내 단타 자동순환으로 {executed_count}건의 주문을 실행했습니다."
        elif len(candidate_rows) == 0 and excluded_by_price:
            msg_names = ", ".join([x.get("name", x.get("symbol", "")) for x in excluded_by_price[:3]])
            message = f"시드 한도 때문에 신규 진입 가능한 국내 후보가 없습니다. ({msg_names})"
        elif daily_loss.get("halt_new_buys"):
            message = "일일 손실 제한에 도달해 국내 신규 단타 진입을 차단했습니다."

        return {
            "executed": executed_count > 0,
            "executed_count": executed_count,
            "message": message,
            "budget": self.shared_budget_status(requested_seed=requested_seed, market="KS"),
            "daily_loss": self.daily_loss_status(requested_seed=requested_seed),
            "portfolio": self.portfolio_usage(market_filter="KS"),
            "results": results,
            "candidates": candidate_payload.get("candidates", []),
            "excluded_by_price": excluded_by_price,
            "max_affordable_per_share": max_affordable,
            "max_symbols": candidate_payload.get("max_symbols", self._auto_max_symbols(market="KS")),
        }

    def _vrev_preflight_check(self, symbol, market, bar, profile):
        """vrev 라이브 진입 직전 하락 추세/과도한 이탈 위험 점검"""
        if hasattr(self.strategy, "vrev_entry_issues"):
            try:
                return list(self.strategy.vrev_entry_issues(bar, profile))
            except Exception:
                pass

        issues = []
        current_price = self._safe_float(bar.get("close", 0), 0)
        vwap = self._safe_float(bar.get("vwap", 0), 0)
        rsi_live = self._safe_float(bar.get("rsi14", 50), 50)
        min_live_entry_rsi = self._safe_float(profile.get("min_live_entry_rsi", profile.get("rsi_entry", 30)), 30)
        max_live_vwap_discount_pct = self._safe_float(profile.get("max_live_vwap_discount_pct", 0.8), 0.8)
        if current_price > 0 and vwap > 0:
            vwap_discount_pct = (1 - (current_price / vwap)) * 100
            if vwap_discount_pct > max_live_vwap_discount_pct:
                issues.append(f"VWAP 대비 하락 과다 ({vwap_discount_pct:.2f}% > 최대 {max_live_vwap_discount_pct:.1f}%)")
        if current_price > 0 and rsi_live < min_live_entry_rsi:
            issues.append(f"RSI {rsi_live:.1f} < 최소 {min_live_entry_rsi:.1f}")
        return issues

    def _live_strategy_allowed(self, strategy_id="vrev", market="KS"):
        strategy_id = str(strategy_id or "").strip().lower()
        spec = self.strategy.strategy_spec(strategy_id)
        spec_market = str(spec.get("market", "KS") or "KS").upper()
        live_supported = bool(spec.get("live_supported", False))
        if self._is_us_market(market):
            return live_supported and spec_market == "US"
        return live_supported and spec_market != "US"

    def execute_live(self, symbol, market="KS", seed=1000000, name="", strategy_id="vrev", force=False, allow_buy=True):
        if self._hard_locked():
            return {
                "executed": False,
                "message": self._hard_lock_message(),
                "status": self.signal_status(symbol, market=market, seed=seed, name=name, strategy_id=strategy_id),
                "action": "HARD_LOCKED",
                "order_value": 0,
                "hard_locked": True,
            }
        if self._feature_enabled() is False:
            return {
                "executed": False,
                "message": "단타 기능이 관리자 설정에서 비활성화되어 주문을 실행하지 않습니다.",
                "status": self.signal_status(symbol, market=market, seed=seed, name=name, strategy_id=strategy_id),
                "action": "DISABLED",
                "order_value": 0,
            }
        strategy_id = self.strategy._normalize_strategy(strategy_id)
        status = self.signal_status(symbol, market=market, seed=seed, name=name, strategy_id=strategy_id)
        signal = status.get("signal", {}) or {}
        state = status.get("state", {}) or {}
        runtime = status.get("runtime", {}) or {}
        action = str(signal.get("action", "HOLD") or "HOLD")
        qty = max(0, self._safe_int(signal.get("order_qty", 0), 0))
        current_price = self._safe_float(signal.get("current_price", 0), 0)
        order_value = round(current_price * qty, 2)
        breakout_meta = signal.get("breakout_meta")


        self._append_runtime_log(
            "info",
            f"{symbol} 실행 판단: {action} · {signal.get('reason', '')}",
            symbol=symbol,
            strategy_id=strategy_id,
            meta=self._compact_runtime_meta(status, {
                "seed": round(self._safe_float(seed, 0), 2),
                "force": bool(force),
                "allow_buy": bool(allow_buy),
                "order_value": order_value,
            }),
        )

        if action.startswith("BUY") and allow_buy is False:
            message = "자동청산 감시 모드라 신규 매수는 실행하지 않습니다."
            self._append_runtime_log("info", f"{symbol} 신규 매수 차단: 자동청산 감시 전용", symbol=symbol, strategy_id=strategy_id, meta=self._compact_runtime_meta(status))
            return {
                "executed": False,
                "message": message,
                "status": status,
                "action": action,
                "order_value": 0,
            }

        if action == "HOLD":
            return {
                "executed": False,
                "message": signal.get("reason", "현재 실행할 신호가 없습니다."),
                "status": status,
                "action": action,
                "order_value": 0,
            }

        if runtime.get("risk_status") == "HALT":
            halt_reason = runtime.get("halt_reason", "실행이 차단되었습니다.")
            self._push_state_error(state, halt_reason)
            state["updated_at"] = self._timestamp()
            self._store_state(state)
            self._append_runtime_log("warning", f"{symbol} 주문 차단: {halt_reason}", symbol=symbol, strategy_id=strategy_id, meta=self._compact_runtime_meta(status))
            return {
                "executed": False,
                "message": halt_reason,
                "status": self.signal_status(symbol, market=market, seed=seed, name=name, strategy_id=strategy_id),
                "action": action,
                "order_value": 0,
            }

        if qty <= 0:
            message = "주문 수량이 0주라 실행하지 않습니다."
            self._append_runtime_log("warning", f"{symbol} 주문 보류: 수량 0", symbol=symbol, strategy_id=strategy_id, meta=self._compact_runtime_meta(status))
            return {
                "executed": False,
                "message": message,
                "status": status,
                "action": action,
                "order_value": 0,
            }

        order = None
        realized = 0.0
        prev_qty = self._safe_int(state.get("position_qty", 0), 0)
        prev_avg = self._safe_float(state.get("avg_price", 0), 0)

        try:
            if action == "PRE_SELL_JACKPOT":
                limit_price = self._round_krw_price(self._safe_float(signal.get("pre_sell_price", current_price), current_price))
                order = self.struct.kis_api.sell_domestic_order(symbol, qty, price=limit_price, order_type="LIMIT")
                state["pending_sell_order_no"] = str(order.get("order_no", "") or "")
                state["pending_sell_price"] = limit_price
                state["pending_sell_qty"] = qty
                state["pending_sell_type"] = "JACKPOT"
                state["pending_sell_placed_at"] = self._timestamp()
                state["last_signal"] = action
                state["updated_at"] = self._timestamp()
                self._append_order(state, action, qty, limit_price, order, strategy_id=strategy_id, reason=signal.get("reason", ""))
                self._store_state(state)
                self._invalidate_kis_cache()
                log_message = f"{symbol} 잭팟 사전예약 매도 등록 | {qty}주 · 지정가 ₩{limit_price:,} | {signal.get('reason', '')}"
                self._log_execution(symbol, action, qty, limit_price, order, log_message, strategy_id=strategy_id, runtime=self._compact_runtime_meta(status, {"order_value": round(limit_price * qty, 2), "pending_sell": True}), name=name or state.get("name", ""), breakout_meta=breakout_meta)
                return {
                    "executed": True,
                    "message": f"{symbol} 잭팟 지정가 매도를 예약했습니다.",
                    "order": order,
                    "status": self.signal_status(symbol, market=market, seed=seed, name=name, strategy_id=strategy_id),
                    "action": action,
                    "order_value": round(limit_price * qty, 2),
                }

            if action.startswith("BUY"):
                if self._is_us_market(market):
                    auto_buy_window = self._us_auto_buy_window()
                    if auto_buy_window.get("ready") is False:
                        message = str(auto_buy_window.get("message", "10:00 KST 전이라 미장 예약매수 대기 중입니다.") or "10:00 KST 전이라 미장 예약매수 대기 중입니다.")
                        self._append_runtime_log(
                            "info",
                            f"{symbol} 예약매수 대기: {message}",
                            symbol=symbol,
                            strategy_id=strategy_id,
                            meta=self._compact_runtime_meta(status, {
                                "scheduled_at": auto_buy_window.get("scheduled_at", "10:00 KST"),
                                "current_time": auto_buy_window.get("current_time", ""),
                            }),
                        )
                        return {
                            "executed": False,
                            "message": message,
                            "status": status,
                            "action": action,
                            "order_value": 0,
                        }
                    exchange = self._us_exchange(symbol)
                    buying_power = self.struct.kis_api.get_buying_power_info(symbol=symbol, price=round(current_price, 2), exchange=exchange)
                    max_qty = max(0, self._safe_int(buying_power.get("executable_qty", buying_power.get("broker_qty", buying_power.get("qty", 0))), 0))
                    orderable_amount_usd = self._safe_float(buying_power.get("executable_amount", buying_power.get("broker_amount", buying_power.get("amount", 0))), 0)
                    estimated_amount_usd = max(
                        orderable_amount_usd,
                        self._safe_float(buying_power.get("estimated_amount", buying_power.get("amount", orderable_amount_usd)), orderable_amount_usd),
                    )
                    estimated_qty = max(
                        max_qty,
                        self._safe_int(buying_power.get("estimated_qty", buying_power.get("qty", max_qty)), max_qty),
                    )
                    auto_exchange_usd = self._safe_float(buying_power.get("auto_exchange_usd", 0), 0)
                    auto_exchange_ready = bool(buying_power.get("auto_exchange_ready", False))
                    requested_amount_usd = round(current_price * qty, 2)
                    planning_amount_usd = max(orderable_amount_usd, estimated_amount_usd)
                    planning_qty = max(max_qty, estimated_qty)
                    if planning_qty <= 0 or planning_amount_usd <= 0 or (requested_amount_usd > 0 and planning_amount_usd + 1e-9 < requested_amount_usd):
                        message = (
                            f"{symbol} 해외 주문가능금액 부족. "
                            f"실주문가능 ${orderable_amount_usd:.2f} / 통합판단 ${planning_amount_usd:.2f} / 가능수량 {planning_qty}주 / 요청 ${requested_amount_usd:.2f}"
                        )
                        if estimated_amount_usd > orderable_amount_usd + 0.01 or auto_exchange_usd > 0.01:
                            message += (
                                f" · 원화 자동환전 추정 포함 가용 ${estimated_amount_usd:.2f} / 환전후반영 ${auto_exchange_usd:.2f}"
                            )
                        self._append_runtime_log(
                            "warning",
                            message,
                            symbol=symbol,
                            strategy_id=strategy_id,
                            meta=self._compact_runtime_meta(status, {
                                "exchange": exchange,
                                "orderable_amount_usd": round(orderable_amount_usd, 2),
                                "estimated_amount_usd": round(estimated_amount_usd, 2),
                                "planning_amount_usd": round(planning_amount_usd, 2),
                                "auto_exchange_usd": round(auto_exchange_usd, 2),
                                "auto_exchange_ready": auto_exchange_ready,
                                "max_qty": max_qty,
                                "estimated_qty": estimated_qty,
                                "planning_qty": planning_qty,
                                "requested_qty": qty,
                                "requested_amount_usd": requested_amount_usd,
                            }),
                        )
                        return {
                            "executed": False,
                            "message": message,
                            "status": status,
                            "action": action,
                            "order_value": 0,
                        }
                    if qty > planning_qty:
                        qty = planning_qty
                        order_value = round(current_price * qty, 2)
                    order = self.struct.kis_api.buy_order(symbol, qty, price=round(current_price, 2), order_type="MARKET", exchange=exchange)
                    # 해외 체결 확인 API 미구현 → fallback 사용
                    fill = {"filled_price": current_price, "filled_qty": qty, "status": "UNKNOWN"}
                else:
                    order = self.struct.kis_api.buy_domestic_order(symbol, qty, price=0, order_type="MARKET")
                    fill = self._resolve_domestic_fill(symbol, "BUY", order, fallback_price=current_price, fallback_qty=qty)
                exec_price = self._safe_float(fill.get("filled_price", current_price), current_price)
                exec_qty = max(0, self._safe_int(fill.get("filled_qty", qty), qty))
                new_qty = prev_qty + exec_qty
                total_cost = (prev_avg * prev_qty) + (exec_price * exec_qty)
                state["position_qty"] = new_qty
                state["avg_price"] = round((total_cost / new_qty), 4) if new_qty > 0 else 0.0
                if action == "BUY1":
                    state["buy1_used"] = True
                if action == "BUY2":
                    state["buy2_used"] = True
                state["session_date"] = signal.get("session_date", state.get("session_date", ""))
                if not state.get("first_buy_date"):
                    state["first_buy_date"] = self._now().strftime("%Y%m%d")
                state["carried_overnight"] = False
                state["last_signal"] = action
                state["updated_at"] = self._timestamp()
                self._append_order(state, action, qty, current_price, order, strategy_id=strategy_id, reason=signal.get("reason", ""))
                self._store_state(state)
                self._invalidate_kis_cache()
            else:
                if self._is_us_market(market):
                    exchange = self._us_exchange(symbol)
                    order = self.struct.kis_api.sell_order(symbol, qty, price=round(current_price, 2), order_type="MARKET", exchange=exchange)
                    fill = {"filled_price": current_price, "filled_qty": qty, "status": "UNKNOWN"}
                else:
                    order = self.struct.kis_api.sell_domestic_order(symbol, qty, price=0, order_type="MARKET")
                    fill = self._resolve_domestic_fill(symbol, "SELL", order, fallback_price=current_price, fallback_qty=qty)
                exec_price = self._safe_float(fill.get("filled_price", current_price), current_price)
                exec_qty = max(0, self._safe_int(fill.get("filled_qty", qty), qty))
                sell_qty = min(prev_qty, exec_qty)
                realized = (exec_price - prev_avg) * sell_qty if prev_avg > 0 else 0.0
                state["realized_profit"] = round(self._safe_float(state.get("realized_profit", 0), 0) + realized, 2)
                new_qty = max(0, prev_qty - sell_qty)
                state["position_qty"] = new_qty
                state["last_exit_price"] = round(exec_price, 4) if exec_price > 0 else 0.0
                self._mark_exit_watch(state, reason=signal.get("reason", ""), action=action, order_no=order.get("order_no", ""))
                if new_qty <= 0:
                    state["avg_price"] = 0.0
                    state["buy1_used"] = False
                    state["buy2_used"] = False
                    state["first_buy_date"] = ""
                    state["carried_overnight"] = False
                    self._clear_pending_sell(state)
                else:
                    if action == "SELL_PARTIAL":
                        state["buy1_used"] = True  # 1차 익절 완료 표시 (재진입 방지)
                state["last_signal"] = action
                state["updated_at"] = self._timestamp()
                self._append_order(state, action, qty, current_price, order, strategy_id=strategy_id, reason=signal.get("reason", ""))
                self._store_state(state)
                self._invalidate_kis_cache()

                actual_price = exec_price if 'exec_price' in locals() else current_price
                actual_qty = exec_qty if 'exec_qty' in locals() else qty
                actual_order_value = round(actual_price * actual_qty, 2)
                if self._is_us_market(market):
                    # KIS 미국 수수료: 0.25% 매수/매도 + SEC fee $8/million (매도)
                    fee_buy_usd = round(actual_price * actual_qty * 0.0025, 4)
                    sec_fee_usd = round(actual_price * actual_qty / 1_000_000 * 8.0, 4) if action.startswith("SELL") else 0
                    fee_sell_usd = round(actual_price * actual_qty * 0.0025, 4) if action.startswith("SELL") else 0
                    total_fee_usd = fee_buy_usd + fee_sell_usd + sec_fee_usd
                    if action.startswith("BUY"):
                        log_message = f"{symbol} {action} 실행 | {actual_qty}주 · ${actual_price:.2f} · 체결금액 ${actual_order_value:.2f} | {signal.get('reason', '')}"
                    else:
                        gross_usd = round((actual_price - prev_avg) * actual_qty, 4) if prev_avg > 0 else 0
                        net_usd = gross_usd - total_fee_usd
                        log_message = f"{symbol} {action} 실행 | {actual_qty}주 · ${actual_price:.2f} | 손익 ${gross_usd:+.2f} | 수수료 ${total_fee_usd:.4f} | 순손익 ${net_usd:+.2f} | {signal.get('reason', '')}"
                else:
                    fee_buy = round(prev_avg * actual_qty * 0.00015) if action.startswith("SELL") else round(actual_price * actual_qty * 0.00015)
                    fee_sell = round(actual_price * actual_qty * 0.00195) if action.startswith("SELL") else 0
                    if action.startswith("BUY"):
                        log_message = f"{symbol} {action} 실행 | {actual_qty}주 · 체결가 ₩{round(actual_price):,} · 체결금액 ₩{round(actual_order_value):,} | {signal.get('reason', '')}"
                    else:
                        gross = round(realized)
                        net = gross - fee_buy - fee_sell
                        log_message = f"{symbol} {action} 실행 | {actual_qty}주 · 체결가 ₩{round(actual_price):,} | 손익 ₩{gross:+,} | 수수료 ₩{fee_buy + fee_sell:,} | 순손익 ₩{net:+,} | {signal.get('reason', '')}"
                self._log_execution(
                    symbol,
                    action,
                    actual_qty,
                    actual_price,
                    order,
                    log_message,
                    strategy_id=strategy_id,
                    runtime=self._compact_runtime_meta(status, {
                        "order_value": actual_order_value,
                        "realized": round(realized, 2),
                        "post_position_qty": self._safe_int(state.get("position_qty", 0), 0),
                        "post_avg_price": round(self._safe_float(state.get("avg_price", 0), 0), 4),
                    }),
                    name=name or state.get("name", ""),
                    filled_price=actual_price,
                    filled_qty=actual_qty,
                    breakout_meta=breakout_meta,
                )

                return {
                    "executed": True,
                    "message": log_message,
                    "order": order,
                    "status": self.signal_status(symbol, market=market, seed=seed, name=name, strategy_id=strategy_id),
                    "action": action,
                    "order_value": order_value,
                }
        except Exception as e:
            error_message = str(e)
            self._push_state_error(state, error_message)
            state["updated_at"] = self._timestamp()
            self._store_state(state)
            self._append_runtime_log("error", f"{symbol} 주문 실패: {error_message}", symbol=symbol, strategy_id=strategy_id, meta=self._compact_runtime_meta(status, {"failed_action": action, "order_value": order_value}))
            return {
                "executed": False,
                "message": error_message,
                "status": self.signal_status(symbol, market=market, seed=seed, name=name, strategy_id=strategy_id),
                "action": action,
                "order_value": 0,
            }

    def execute_exit_watch(self, requested_seed=0, market="ALL"):
        def _disabled_result(message):
            return {
                "executed": False,
                "executed_count": 0,
                "watched_count": 0,
                "message": message,
                "hard_locked": self._hard_locked(),
                "results": [],
            }

        if self._hard_locked():
            return _disabled_result(self._hard_lock_message())
        if self._feature_enabled() is False:
            return _disabled_result("단타 기능이 관리자 설정에서 비활성화되어 자동청산 감시를 실행하지 않습니다.")

        def _market_exit_watch_enabled(target_market):
            if self._is_us_market(target_market):
                modern = str(self._config("daytrade_us_exit_watch_enabled", "")).lower()
                legacy = str(self._config("us_daytrade_exit_watch_enabled", "")).lower()
                if modern in ("true", "false"):
                    exit_enabled = modern == "true"
                elif legacy in ("true", "false"):
                    exit_enabled = legacy == "true"
                else:
                    exit_enabled = True
                return self.auto_enabled(market="US") and exit_enabled
            exit_enabled = str(self._config("daytrade_exit_watch_enabled", "true") or "true").lower() == "true"
            return self.auto_enabled(market="KS") and exit_enabled

        market_label = str(market or "ALL").upper()
        if market_label in ["ALL", "BOTH", "*"]:
            kr_result = self.kr_execute_exit_watch(requested_seed=requested_seed) if _market_exit_watch_enabled("KS") else _disabled_result("국장 단타 자동청산 감시 비활성")
            us_result = self.us_execute_exit_watch(requested_seed=requested_seed, market="US") if _market_exit_watch_enabled("US") else _disabled_result("미장 단타 자동청산 감시 비활성")
            executed_count = self._safe_int(kr_result.get("executed_count", 0), 0) + self._safe_int(us_result.get("executed_count", 0), 0)
            watched_count = self._safe_int(kr_result.get("watched_count", 0), 0) + self._safe_int(us_result.get("watched_count", 0), 0)
            message = "자동청산 감시 대상이 없습니다."
            if watched_count > 0:
                message = f"자동청산 감시 {watched_count}건 점검 완료"
            if executed_count > 0:
                message = f"자동청산 감시로 {executed_count}건 주문을 실행했습니다."
            return {
                "executed": executed_count > 0,
                "executed_count": executed_count,
                "watched_count": watched_count,
                "message": message,
                "results": (kr_result.get("results", []) or []) + (us_result.get("results", []) or []),
                "markets": {
                    "KS": kr_result,
                    "US": us_result,
                },
            }
        if self._is_us_market(market):
            if _market_exit_watch_enabled(market) is False:
                return _disabled_result("미장 단타 자동청산 감시 비활성")
            return self.us_execute_exit_watch(requested_seed=requested_seed, market=market)
        if _market_exit_watch_enabled("KS") is False:
            return _disabled_result("국장 단타 자동청산 감시 비활성")
        return self.kr_execute_exit_watch(requested_seed=requested_seed)

    def cancel_pending_auto_sells(self, market="ALL", reason=""):
        market_label = str(market or "ALL").upper()
        state_map = self._load_state_map() or {}
        changed = False
        cancelled_orders = []
        cleared_symbols = []

        def _matches(target_market):
            if market_label in ["ALL", "BOTH", "*"]:
                return True
            if self._is_us_market(market_label):
                return self._is_us_market(target_market)
            return not self._is_us_market(target_market)

        for key, state in state_map.items():
            if not isinstance(state, dict):
                continue
            target_market = state.get("market", "KS")
            if _matches(target_market) is False:
                continue
            symbol = str(state.get("symbol", "") or "")
            had_pending = bool(state.get("pending_sell_order_no", "") or self._safe_int(state.get("pending_sell_qty", 0), 0) > 0)
            cancelled_for_symbol = []
            if self._is_us_market(target_market) is False and symbol != "":
                for item in self._cancel_open_sell_orders(symbol):
                    payload = {"symbol": symbol, **item}
                    cancelled_orders.append(payload)
                    cancelled_for_symbol.append(payload)
            if had_pending or len(cancelled_for_symbol) > 0:
                self._clear_pending_sell(state)
                state["updated_at"] = self._timestamp()
                if reason:
                    state["last_exit_reason"] = reason
                state_map[key] = state
                changed = True
                if symbol != "":
                    cleared_symbols.append(symbol)

        if changed:
            self._save_state_map(state_map)
            self._invalidate_kis_cache()

        unique_symbols = []
        for symbol in cleared_symbols:
            if symbol not in unique_symbols:
                unique_symbols.append(symbol)

        return {
            "executed": changed or len(cancelled_orders) > 0,
            "cancelled_order_count": len(cancelled_orders),
            "cleared_symbol_count": len(unique_symbols),
            "symbols": unique_symbols,
            "orders": cancelled_orders,
            "message": f"자동 매도 예약 {len(unique_symbols)}개 종목을 정리했습니다." if (changed or len(cancelled_orders) > 0) else "정리할 자동 매도 예약이 없습니다.",
        }

    def kr_execute_exit_watch(self, requested_seed=0):
        """활성 포지션에 대해 자동청산 감시 실행 (신규 매수 없음)"""
        if self._hard_locked():
            return {"executed": False, "executed_count": 0, "watched_count": 0, "message": self._hard_lock_message(), "hard_locked": True, "results": []}
        with self._global_lock("engine_cycle"):
            positions = [p for p in self.active_positions() if not self._is_us_market(p.get("market", "KS"))]
            results = []
            executed_count = 0
            watched_count = 0
            for item in positions:
                symbol = item.get("symbol", "")
                market = item.get("market", "KS")
                strategy_id = item.get("strategy_id", "vrev")
                state = self._state_for(symbol, market=market, seed=max(self._safe_float(item.get("current_price", 0), 0) * self._safe_int(item.get("position_qty", 0), 0), 1), name=item.get("name", ""), strategy_id=strategy_id)
                has_watch = (
                    self._safe_int(state.get("position_qty", 0), 0) > 0 and
                    self._safe_float(state.get("avg_price", 0), 0) > 0
                )
                if not has_watch:
                    continue
                watched_count += 1
                outcome = self.execute_live(
                    symbol,
                    market=market,
                    seed=max(self._safe_float(item.get("current_price", 0), 0) * self._safe_int(item.get("position_qty", 0), 0), self._safe_float(requested_seed, 0), 1),
                    name=item.get("name", ""),
                    strategy_id=strategy_id,
                    force=False,
                    allow_buy=False,
                )
                if outcome.get("executed"):
                    executed_count += 1
                results.append({
                    "symbol": symbol,
                    "market": market,
                    "name": item.get("name", ""),
                    "strategy_id": strategy_id,
                    "executed": bool(outcome.get("executed", False)),
                    "message": outcome.get("message", ""),
                    "signal": outcome.get("status", {}).get("signal", {}).get("action", "HOLD"),
                    "current_price": self._safe_float(item.get("current_price", 0), 0),
                    "watch_active": True,
                })

            message = "자동청산 감시 대상이 없습니다."
            if watched_count > 0:
                message = f"자동청산 감시 {watched_count}건 점검 완료"
            if executed_count > 0:
                message = f"자동청산 감시로 {executed_count}건 주문을 실행했습니다."
            self._append_runtime_log("info", message, meta={"watched_count": watched_count, "executed_count": executed_count})
            return {"executed": executed_count > 0, "executed_count": executed_count, "watched_count": watched_count, "message": message, "results": results}

    def manual_sell(self, symbol, market="KS", seed=1000000, name="", strategy_id="vrev", qty=None):
        if self._hard_locked():
            raise Exception(self._hard_lock_message())
        if self._feature_enabled() is False:
            raise Exception("단타 기능이 관리자 설정에서 비활성화되어 수동 단타 매도를 실행하지 않습니다.")
        state = self._state_for(symbol, market=market, seed=seed, name=name, strategy_id=strategy_id)
        position_qty = self._safe_int(state.get("position_qty", 0), 0)
        if position_qty <= 0:
            raise Exception("수동 매도할 보유 수량이 없습니다.")

        sell_qty = position_qty if qty is None else min(position_qty, max(0, self._safe_int(qty, 0)))
        if sell_qty <= 0:
            raise Exception("수동 매도 수량이 올바르지 않습니다.")

        current_price = self._current_price(symbol, market=market, fallback=self._safe_float(state.get("avg_price", 0), 0))
        if self._is_us_market(market):
            exchange = self._us_exchange(symbol)
            order = self.struct.kis_api.sell_order(symbol, sell_qty, price=round(current_price, 2), order_type="MARKET", exchange=exchange)
            fill = {"filled_price": current_price, "filled_qty": sell_qty, "status": "UNKNOWN"}
            exec_price = self._safe_float(fill.get("filled_price", current_price), current_price)
        else:
            order = self.struct.kis_api.sell_domestic_order(symbol, sell_qty, price=0, order_type="MARKET")
            exec_price = current_price

        prev_avg = self._safe_float(state.get("avg_price", 0), 0)
        new_qty = max(0, position_qty - sell_qty)
        realized = (exec_price - prev_avg) * sell_qty
        state["realized_profit"] = round(self._safe_float(state.get("realized_profit", 0), 0) + realized, 2)
        state["position_qty"] = new_qty
        if new_qty == 0:
            state["avg_price"] = 0.0
            state["buy1_used"] = False
            state["buy2_used"] = False
            state["first_buy_date"] = ""
            state["carried_overnight"] = False
            self._clear_pending_sell(state)
        state["last_signal"] = "SELL_MANUAL_NOW"
        state["last_manual_exit_at"] = self._timestamp()
        state["last_exit_price"] = round(exec_price, 4) if exec_price > 0 else 0.0
        self._mark_exit_watch(state, reason="사용자 즉시 매도를 실행했습니다.", action="SELL_MANUAL_NOW", order_no=order.get("order_no", ""))
        state["updated_at"] = self._timestamp()
        self._append_order(state, "SELL_MANUAL_NOW", sell_qty, exec_price, order, strategy_id=strategy_id, reason="사용자 즉시 매도")
        self._store_state(state)
        self._invalidate_kis_cache()
        if self._is_us_market(market):
            _msell_fee = round(exec_price * sell_qty * 0.0025, 4)
            _mbuy_fee = round(prev_avg * sell_qty * 0.0025, 4)
            _sec_fee = round(exec_price * sell_qty / 1_000_000 * 8.0, 4)
            _mgross = round((exec_price - prev_avg) * sell_qty, 4)
            _mnet = _mgross - _msell_fee - _mbuy_fee - _sec_fee
            _m_log = (f"사용자 즉시 매도 [시장가] | "
                f"평단 ${prev_avg:.2f}→매도 ${exec_price:.2f} | "
                f"손익 ${_mgross:+.4f} | 수수료 ${_msell_fee + _mbuy_fee + _sec_fee:.4f} | 순손익 ${_mnet:+.4f}")
        else:
            _msell_fee = round(exec_price * sell_qty * 0.00195)
            _mbuy_fee = round(prev_avg * sell_qty * 0.00015)
            _mgross = round((exec_price - prev_avg) * sell_qty)
            _mnet = _mgross - _msell_fee - _mbuy_fee
            _m_log = (f"사용자 즉시 매도 [시장가] | "
                f"평단 ₩{round(prev_avg):,}→매도 ₩{round(exec_price):,} | "
                f"손익 ₩{_mgross:+,} | 수수료 ₩{_msell_fee + _mbuy_fee:,} | 순손익 ₩{_mnet:+,}")
        self._log_execution(symbol, "SELL_MANUAL_NOW", sell_qty, exec_price, order, _m_log, strategy_id=strategy_id, runtime={"manual": True}, name=name or state.get("name", ""))
        self._append_runtime_log("warning", f"{symbol} 수동 즉시 매도 실행", symbol=symbol, strategy_id=strategy_id, meta={"qty": sell_qty, "price": exec_price})
        return {
            "executed": True,
            "message": f"{symbol} 보유 수량 {sell_qty}주를 즉시 시장가 매도했습니다.",
            "order": order,
            "status": self.signal_status(symbol, market=market, seed=seed, name=name, strategy_id=strategy_id),
        }

    def _invalidate_kis_cache(self):
        """KIS 잔고 캐시 즉시 만료 (실시간 잔고 갱신용)"""
        import sys as _sys
        _CACHE_KEY = "_trading_kis_balance_cache_v2"
        _CACHE_TS_KEY = "_trading_kis_balance_cache_ts"
        if hasattr(_sys, _CACHE_KEY):
            delattr(_sys, _CACHE_KEY)
        if hasattr(_sys, _CACHE_TS_KEY):
            delattr(_sys, _CACHE_TS_KEY)

    def period_trade_summary(self, date_from="", date_to="", sync_broker=True, broker_lookback_days=0, include_valuation=True):
        """
        지정된 기간 동안의 거래 내역을 KIS 증권사 실체결 데이터와 동기화하여 FIFO 방식으로 손익을 집계합니다.
        - KIS API를 통해 해당 기간의 모든 체결 내역을 가져옵니다.
        - 로컬 DB의 거래 로그와 통합하고, KIS 데이터를 기준으로 보정합니다.
        - 모든 거래를 시간순으로 재처리하여 정확한 P&L을 계산합니다.
        """
        today = self._now()
        d_from_str = self._date_compact(date_from) if date_from else today.strftime("%Y%m%d")
        d_to_str = self._date_compact(date_to) if date_to else today.strftime("%Y%m%d")
        
        if d_from_str > d_to_str:
            d_from_str, d_to_str = d_to_str, d_from_str

        # 1. KIS API 체결 동기화는 선택적으로만 수행합니다.
        # 일지 화면은 즉시성이 더 중요하므로 기본 일간 조회에서는 로컬 로그만으로도 렌더링 가능해야 합니다.
        broker_fills = []
        broker_sync_errors = []
        broker_sync_sources = []
        broker_sync_status_by_market = {"KS": False, "US": False}
        broker_trade_profit_rows = []
        broker_trade_profit_totals = {}
        if sync_broker:
            lookback_days = max(0, min(7, self._safe_int(broker_lookback_days, 0)))
            history_from = d_from_str
            if lookback_days > 0:
                history_from = (datetime.datetime.strptime(d_from_str, "%Y%m%d") - datetime.timedelta(days=lookback_days)).strftime("%Y%m%d")
            try:
                domestic_fills = self.struct.kis_api.get_domestic_fills_by_date(history_from, d_to_str)
                if domestic_fills:
                    broker_sync_sources.append("domestic")
                broker_fills.extend(domestic_fills or [])
                broker_sync_status_by_market["KS"] = True
            except Exception as e:
                broker_sync_errors.append(f"domestic:{str(e)}")
            try:
                overseas_fills = self.struct.kis_api.get_overseas_fills_by_date(history_from, d_to_str)
                if overseas_fills:
                    broker_sync_sources.append("overseas")
                broker_fills.extend(overseas_fills or [])
                broker_sync_status_by_market["US"] = True
            except Exception as e:
                broker_sync_errors.append(f"overseas:{str(e)}")
            try:
                broker_trade_profit = self.struct.kis_api.get_domestic_period_trade_profit(d_from_str, d_to_str)
                broker_trade_profit_rows = list(broker_trade_profit.get("rows", []) or [])
                broker_trade_profit_totals = dict(broker_trade_profit.get("totals", {}) or {})
                if broker_trade_profit_rows:
                    broker_sync_sources.append("domestic_profit")
            except Exception as e:
                self._append_runtime_log(
                    "warning",
                    f"거래 일지 KIS 손익 동기화 실패: {str(e)}",
                    dedup_sec=300,
                )
            if broker_sync_errors:
                level = "warning" if len(broker_fills) == 0 else "info"
                self._append_runtime_log(
                    level,
                    f"거래 일지 KIS 동기화 일부 실패: {' | '.join(broker_sync_errors)}",
                    dedup_sec=300,
                )

        # 2. 로컬 DB에서 *모든* 단타 거래 로그 조회 (이월된 매수 포지션 계산용)
        log_db = self.struct.db("trade_log")
        try:
            all_local_logs = log_db.rows(event_type__startswith="DT_", orderby="created", order="ASC", dump=20000)
        except Exception:
            all_local_logs = []

        # 3. KIS 데이터와 로컬 데이터를 통합 및 정제
        all_trades = {}
        symbol_market_map = {}
        broker_orders = []
        
        # 로컬 로그를 먼저 추가 (참고 정보용)
        for row in all_local_logs:
            order_no = str(row.get("order_no", "") or "")
            action = self._normalize_trade_action(row.get("action", ""))
            created_str = str(row.get("created", "") or "")
            created_compact = created_str[:10].replace("-", "")
            event_type = str(row.get("event_type", "") or "")
            symbol = str(row.get("symbol", "") or "")
            market = self._market_from_event_type(event_type, symbol)
            market_key = "US" if self._is_us_market(market) else "KS"
            if (
                sync_broker
                and action in ["BUY", "SELL"]
                and d_from_str <= created_compact <= d_to_str
                and broker_sync_status_by_market.get(market_key, False)
            ):
                continue
            merge_key = self._trade_merge_key(order_no, row.get("symbol", ""), action, created_str, fallback=f"local_{row.get('id')}")

            _event_type = event_type
            _symbol = symbol
            all_trades[merge_key] = {
                "id": row.get("id"),
                "order_no": str(row.get("order_no", "") or ""),
                "symbol": _symbol,
                "market": self._market_from_event_type(_event_type, _symbol),
                "name": str(row.get("name", "") or ""),
                "action": action,
                "filled_price": self._safe_float(row.get("filled_price", 0)),
                "filled_qty": self._safe_int(row.get("filled_qty", 0)),
                "created_str": created_str,
                "source": "local",
                "message": row.get("message", ""),
                "event_type": _event_type,
            }
            if _symbol:
                symbol_market_map[_symbol] = all_trades[merge_key]["market"]

        # KIS 체결 내역으로 덮어쓰기 및 추가
        for fill in broker_fills:
            order_no = str(fill.get("order_no", "") or "")
            if not order_no:
                continue

            created_str = f"{fill.get('order_date', '')[:4]}-{fill.get('order_date', '')[4:6]}-{fill.get('order_date', '')[6:8]} {fill.get('order_time', '')[:2]}:{fill.get('order_time', '')[2:4]}:{fill.get('order_time', '')[4:6]}"
            action = self._normalize_trade_action(fill.get("side", ""))
            symbol = str(fill.get("symbol", "") or "")
            fill_market = self._market_key(fill.get("market", ""), symbol)
            filled_qty = self._safe_int(fill.get("filled_qty", 0))

            if d_from_str <= created_str[:10].replace("-", "") <= d_to_str:
                broker_orders.append({
                    "order_no": order_no,
                    "symbol": symbol,
                    "market": fill_market,
                    "exchange": str(fill.get("exchange", "") or ""),
                    "name": str(fill.get("name", "") or "") or self.strategy.symbol_name(symbol),
                    "action": action,
                    "status": str(fill.get("status", "") or ""),
                    "ord_qty": self._safe_int(fill.get("ord_qty", 0)),
                    "filled_qty": filled_qty,
                    "filled_price": self._safe_float(fill.get("filled_price", 0)),
                    "created": created_str,
                    "source": "kis_api",
                })

            if filled_qty <= 0:
                stale_keys = [
                    key for key, value in list(all_trades.items())
                    if value.get("source") == "local"
                    and str(value.get("order_no", "") or "") == order_no
                    and str(value.get("symbol", "") or "") == symbol
                    and self._normalize_trade_action(value.get("action", "")) == action
                ]
                for stale_key in stale_keys:
                    del all_trades[stale_key]
                continue

            merge_key = self._trade_merge_key(order_no, fill.get("symbol", ""), action, created_str)

            existing_event = all_trades.get(merge_key, {}).get("event_type", self._dt_event_type(action=action, market=fill_market, symbol=symbol))
            all_trades[merge_key] = {
                "id": all_trades.get(merge_key, {}).get("id", f"kis_{order_no}"),
                "order_no": order_no,
                "symbol": symbol,
                "market": fill_market,
                "name": str(fill.get("name", "") or "") or self.strategy.symbol_name(symbol),
                "action": action,
                "filled_price": self._safe_float(fill.get("filled_price", 0)),
                "filled_qty": filled_qty,
                "created_str": created_str,
                "source": "kis",
                "message": all_trades.get(merge_key, {}).get("message", "KIS 증권사 동기화"),
                "event_type": existing_event,
            }
            if symbol:
                symbol_market_map[symbol] = fill_market

        # 통합된 거래 목록을 시간순으로 정렬
        sorted_trades = sorted(all_trades.values(), key=lambda x: x["created_str"])

        # 4. 손익 재계산
        buy_queues = {}
        ks_books = {}
        logs = []

        def _journal_buy_rate(symbol, market):
            profile = self._profile_for(symbol, market=market)
            if self._is_us_market(market):
                return self._safe_float(profile.get("commission_bps", 25.0), 25.0) / 10000.0
            return self._safe_float(profile.get("commission_bps", 1.5), 1.5) / 10000.0

        def _journal_sell_rate(symbol, market):
            profile = self._profile_for(symbol, market=market)
            if self._is_us_market(market):
                return self._safe_float(profile.get("sell_commission_bps", profile.get("commission_bps", 25.0)), 25.0) / 10000.0
            commission_bps = self._safe_float(profile.get("commission_bps", 1.5), 1.5)
            tax_bps = self._safe_float(profile.get("sell_tax_bps", 18.0), 18.0)
            return (commission_bps + tax_bps) / 10000.0

        def _journal_fee(notional, symbol, market, is_sell=False):
            amount = self._safe_float(notional, 0)
            if amount <= 0:
                return 0
            if self._is_us_market(market):
                profile = self._profile_for(symbol, market=market)
                commission_rate = _journal_sell_rate(symbol, market) if is_sell else _journal_buy_rate(symbol, market)
                fee = amount * commission_rate
                if is_sell:
                    fee += amount / 1_000_000.0 * self._safe_float(profile.get("sec_fee_per_million_usd", 8.0), 8.0)
                return round(fee, 4)
            rate = _journal_sell_rate(symbol, market) if is_sell else _journal_buy_rate(symbol, market)
            return round(amount * rate)

        def _included_buy_fee(cost_amount, symbol, market):
            cost_amount = self._safe_float(cost_amount, 0)
            if cost_amount <= 0:
                return 0
            rate = _journal_buy_rate(symbol, market)
            if rate <= 0:
                return 0
            gross = cost_amount / (1.0 + rate)
            fee = cost_amount - gross
            return round(fee, 4) if self._is_us_market(market) else round(fee)

        for row in sorted_trades:
            created_str = row["created_str"]
            created_date = created_str[:10]
            
            action = row["action"]
            symbol = row["symbol"]
            market = str(row.get("market", "") or self._market_from_event_type(row.get("event_type", ""), symbol))

            if not symbol:
                continue

            filled_price = row["filled_price"]
            filled_qty = row["filled_qty"]

            if filled_qty <= 0 or filled_price <= 0:
                continue

            pnl_gross = pnl_net = avg_buy_price = matched_qty = carry_over_qty = 0
            matched_buy_amount = 0.0
            carry_over_buy_amount = 0.0
            buy_lots = []
            buy_fee_component = 0.0

            if action == "BUY":
                if self._is_us_market(market):
                    if symbol not in buy_queues:
                        buy_queues[symbol] = []
                    buy_queues[symbol].append({
                        "price": filled_price, "qty": filled_qty, "created": created_str,
                        "order_no": row["order_no"],
                    })
                else:
                    buy_fee_component = _journal_fee(filled_price * filled_qty, symbol, market, is_sell=False)
                    book = ks_books.setdefault(symbol, {
                        "qty": 0,
                        "cost": 0.0,
                        "carry_qty": 0,
                        "selected_qty": 0,
                        "last_created": created_str,
                    })
                    book["qty"] += filled_qty
                    book["cost"] += (filled_price * filled_qty) + buy_fee_component
                    if created_date.replace("-", "") < d_from_str:
                        book["carry_qty"] += filled_qty
                    else:
                        book["selected_qty"] += filled_qty
                    book["last_created"] = created_str
            elif action == "SELL":
                if self._is_us_market(market):
                    queue = buy_queues.get(symbol, [])
                    remaining_sell_qty = filled_qty
                    total_cost = 0.0

                    temp_processed_queue = []
                    for buy_lot in queue:
                        if remaining_sell_qty <= 0:
                            temp_processed_queue.append(buy_lot)
                            continue

                        buy_price = self._safe_float(buy_lot.get("price", 0))
                        buy_qty = self._safe_int(buy_lot.get("qty", 0))
                        take = min(remaining_sell_qty, buy_qty)

                        total_cost += buy_price * take
                        matched_qty += take
                        remaining_sell_qty -= take

                        buy_lot_created_date = buy_lot.get("created", "")[:10]
                        if buy_lot_created_date != created_date:
                            carry_over_qty += take
                            carry_over_buy_amount += buy_price * take

                        buy_lots.append({
                            "created": buy_lot.get("created", ""), "qty": take, "price": round(buy_price, 4),
                            "order_no": buy_lot.get("order_no", ""),
                        })

                        buy_lot["qty"] -= take
                        if buy_lot["qty"] > 0:
                            temp_processed_queue.append(buy_lot)

                    buy_queues[symbol] = temp_processed_queue

                    matched_buy_amount = total_cost
                    if matched_qty > 0:
                        avg_buy_price = round(total_cost / matched_qty, 4)
                        sell_amount = filled_price * matched_qty
                        sell_fee = _journal_fee(sell_amount, symbol, market, is_sell=True)
                        buy_fee_component = _included_buy_fee(total_cost, symbol, market)
                        pnl_gross = round(sell_amount - total_cost, 4)
                        pnl_net = round(pnl_gross - sell_fee, 4)
                else:
                    book = ks_books.setdefault(symbol, {
                        "qty": 0,
                        "cost": 0.0,
                        "carry_qty": 0,
                        "selected_qty": 0,
                        "last_created": created_str,
                    })
                    qty_before = self._safe_int(book.get("qty", 0), 0)
                    cost_before = self._safe_float(book.get("cost", 0), 0)
                    matched_qty = min(filled_qty, qty_before)
                    if matched_qty > 0 and qty_before > 0 and cost_before > 0:
                        avg_cost = cost_before / qty_before
                        avg_buy_price = round(avg_cost, 4)
                        matched_buy_amount = avg_cost * matched_qty
                        sell_amount = filled_price * matched_qty
                        sell_fee = _journal_fee(sell_amount, symbol, market, is_sell=True)
                        pnl_gross = round(sell_amount - matched_buy_amount)
                        pnl_net = round(pnl_gross - sell_fee)
                        buy_fee_component = _included_buy_fee(matched_buy_amount, symbol, market)

                        carry_qty_before = self._safe_int(book.get("carry_qty", 0), 0)
                        selected_qty_before = self._safe_int(book.get("selected_qty", 0), 0)
                        sold_carry_qty = min(carry_qty_before, int(round(matched_qty * (carry_qty_before / qty_before)))) if qty_before > 0 else 0
                        sold_carry_qty = min(sold_carry_qty, matched_qty)
                        sold_selected_qty = matched_qty - sold_carry_qty
                        if sold_selected_qty > selected_qty_before:
                            overflow = sold_selected_qty - selected_qty_before
                            sold_selected_qty = selected_qty_before
                            sold_carry_qty = min(carry_qty_before, sold_carry_qty + overflow)

                        carry_over_qty = sold_carry_qty
                        carry_over_buy_amount = avg_cost * sold_carry_qty
                        if sold_carry_qty > 0:
                            buy_lots.append({
                                "created": str(d_from_str),
                                "qty": sold_carry_qty,
                                "price": round(avg_cost, 4),
                                "order_no": "avg-carry",
                            })
                        if sold_selected_qty > 0:
                            buy_lots.append({
                                "created": created_str,
                                "qty": sold_selected_qty,
                                "price": round(avg_cost, 4),
                                "order_no": "avg-selected",
                            })

                        book["qty"] = max(0, qty_before - matched_qty)
                        book["cost"] = max(0.0, cost_before - matched_buy_amount)
                        book["carry_qty"] = max(0, carry_qty_before - sold_carry_qty)
                        book["selected_qty"] = max(0, selected_qty_before - sold_selected_qty)
                        book["last_created"] = created_str

            # 5. 조회 기간에 해당하는 로그만 최종 결과에 추가
            if d_from_str <= created_date.replace("-","") <= d_to_str:
                amount = filled_price * filled_qty
                fee = _journal_fee(amount, symbol, market, is_sell=(action == "SELL"))
                name = row["name"] or self.strategy.symbol_name(symbol)
                verification = row["source"]
                verification_status = "verified" if verification == "kis" else "local"
                verification_label = "실체결" if verification == "kis" else "로컬 로그"

                logs.append({
                    "id": row["id"], "symbol": symbol, "market": market, "name": name,
                    "event_type": row["event_type"], "action": action,
                    "order_no": row["order_no"], "filled_price": filled_price, "filled_qty": filled_qty,
                    "amount": round(amount), "fee": fee, "pnl_gross": pnl_gross, "pnl_net": pnl_net,
                    "avg_buy_price": avg_buy_price, "matched_qty": matched_qty,
                    "buy_fee_component": round(buy_fee_component),
                    "matched_buy_amount": round(matched_buy_amount), "carry_over_qty": carry_over_qty,
                    "carry_over_buy_amount": round(carry_over_buy_amount),
                    "buy_lots": buy_lots, "message": row["message"], "created": created_str,
                    "verification": verification,
                    "verification_status": verification_status,
                    "verification_label": verification_label,
                })

        # 6. 최종 요약 집계
        logs.sort(key=lambda x: x["created"], reverse=True)
        for i, log in enumerate(logs):
            log["trade_no"] = len(logs) - i

        trade_count = len(logs)
        buy_count = len([log for log in logs if log["action"] == "BUY"])
        sell_count = len([log for log in logs if log["action"] == "SELL"])
        total_buy_amount = sum(log.get("amount", 0) for log in logs if log["action"] == "BUY")
        total_sell_amount = sum(log.get("amount", 0) for log in logs if log["action"] == "SELL")
        total_carry_over_buy_amount = sum(log.get("carry_over_buy_amount", 0) for log in logs if log["action"] == "SELL")
        
        total_fee = 0
        for log in logs:
            if log["action"] == "BUY":
                total_fee += log["fee"]
            elif log["action"] == "SELL":
                total_fee += log["fee"]
                total_fee += round(log.get("buy_fee_component", 0) or 0)

        total_pnl_gross = sum(log.get("pnl_gross", 0) for log in logs)
        total_pnl_net = sum(log.get("pnl_net", 0) for log in logs)

        range_symbols = set([log.get("symbol", "") for log in logs if log.get("symbol", "")])
        symbol_name_map = {log.get("symbol", ""): log.get("name", "") for log in logs if log.get("symbol", "")}
        selected_is_today = include_valuation and d_to_str == self._now().strftime("%Y%m%d")
        remaining_positions = []
        remaining_qty_total = 0
        remaining_cost_amount = 0.0
        remaining_unrealized_pnl = 0.0

        for sym, queue in buy_queues.items():
            if sym not in range_symbols:
                continue

            position_qty = 0
            total_cost = 0.0
            carry_over_qty = 0
            carry_over_amount = 0.0
            selected_buy_qty = 0
            selected_buy_amount = 0.0
            remaining_lots = []

            for lot in queue:
                lot_qty = self._safe_int(lot.get("qty", 0))
                lot_price = self._safe_float(lot.get("price", 0))
                lot_created = str(lot.get("created", "") or "")
                lot_date = lot_created[:10].replace("-", "")
                if lot_qty <= 0 or lot_price <= 0:
                    continue

                amount = lot_qty * lot_price
                position_qty += lot_qty
                total_cost += amount
                if lot_date < d_from_str:
                    carry_over_qty += lot_qty
                    carry_over_amount += amount
                else:
                    selected_buy_qty += lot_qty
                    selected_buy_amount += amount

                remaining_lots.append({
                    "created": lot_created,
                    "qty": lot_qty,
                    "price": round(lot_price, 4),
                    "order_no": lot.get("order_no", ""),
                })

            if position_qty <= 0:
                continue

            avg_price = (total_cost / position_qty) if position_qty > 0 else 0.0
            current_price = 0.0
            unrealized_pnl = 0.0
            if selected_is_today:
                current_price = self._safe_float(self._current_price(sym, market=symbol_market_map.get(sym, self._market_key(symbol=sym)), fallback=avg_price), avg_price)
                if current_price > 0 and avg_price > 0:
                    unrealized_pnl = (current_price - avg_price) * position_qty

            remaining_qty_total += position_qty
            remaining_cost_amount += total_cost
            remaining_unrealized_pnl += unrealized_pnl
            remaining_positions.append({
                "symbol": sym,
                "name": symbol_name_map.get(sym, self.strategy.symbol_name(sym)),
                "position_qty": position_qty,
                "avg_price": round(avg_price, 4),
                "remaining_amount": round(total_cost),
                "carry_over_qty": carry_over_qty,
                "carry_over_amount": round(carry_over_amount),
                "selected_buy_qty": selected_buy_qty,
                "selected_buy_amount": round(selected_buy_amount),
                "current_price": round(current_price, 4) if current_price > 0 else 0,
                "unrealized_pnl": round(unrealized_pnl),
                "valuation_available": selected_is_today,
                "lots": remaining_lots,
            })

            if sym not in symbol_name_map:
                symbol_name_map[sym] = self.strategy.symbol_name(sym)

        for sym, book in ks_books.items():
            if sym not in range_symbols:
                continue

            position_qty = self._safe_int(book.get("qty", 0), 0)
            total_cost = self._safe_float(book.get("cost", 0), 0)
            carry_over_qty = self._safe_int(book.get("carry_qty", 0), 0)
            selected_buy_qty = self._safe_int(book.get("selected_qty", 0), 0)
            if position_qty <= 0 or total_cost <= 0:
                continue

            avg_price = (total_cost / position_qty) if position_qty > 0 else 0.0
            carry_over_amount = avg_price * carry_over_qty
            selected_buy_amount = avg_price * selected_buy_qty
            current_price = 0.0
            unrealized_pnl = 0.0
            if selected_is_today:
                current_price = self._safe_float(self._current_price(sym, market=symbol_market_map.get(sym, "KS"), fallback=avg_price), avg_price)
                if current_price > 0 and avg_price > 0:
                    unrealized_pnl = (current_price - avg_price) * position_qty

            remaining_lots = []
            if carry_over_qty > 0:
                remaining_lots.append({
                    "created": self._date_display(d_from_str),
                    "qty": carry_over_qty,
                    "price": round(avg_price, 4),
                    "order_no": "avg-carry",
                })
            if selected_buy_qty > 0:
                remaining_lots.append({
                    "created": str(book.get("last_created", "") or self._date_display(d_to_str)),
                    "qty": selected_buy_qty,
                    "price": round(avg_price, 4),
                    "order_no": "avg-selected",
                })

            remaining_qty_total += position_qty
            remaining_cost_amount += total_cost
            remaining_unrealized_pnl += unrealized_pnl
            remaining_positions.append({
                "symbol": sym,
                "name": symbol_name_map.get(sym, self.strategy.symbol_name(sym)),
                "position_qty": position_qty,
                "avg_price": round(avg_price, 4),
                "remaining_amount": round(total_cost),
                "carry_over_qty": carry_over_qty,
                "carry_over_amount": round(carry_over_amount),
                "selected_buy_qty": selected_buy_qty,
                "selected_buy_amount": round(selected_buy_amount),
                "current_price": round(current_price, 4) if current_price > 0 else 0,
                "unrealized_pnl": round(unrealized_pnl),
                "valuation_available": selected_is_today,
                "lots": remaining_lots,
            })

            if sym not in symbol_name_map:
                symbol_name_map[sym] = self.strategy.symbol_name(sym)

        daily_breakdown = {}
        cycle_rows = []
        cycle_counter = {}

        for log in sorted(logs, key=lambda x: x.get("created", "")):
            log_date = str(log.get("created", "") or "")[:10]
            if log_date:
                item = daily_breakdown.get(log_date, {
                    "date": log_date,
                    "trade_count": 0,
                    "buy_count": 0,
                    "sell_count": 0,
                    "total_buy_amount": 0,
                    "total_sell_amount": 0,
                    "total_carry_over_buy_amount": 0,
                    "total_fee": 0,
                    "pnl_gross": 0,
                    "pnl_net": 0,
                })
                item["trade_count"] += 1
                item["total_fee"] += round(log.get("fee", 0) or 0)
                if log.get("action") == "BUY":
                    item["buy_count"] += 1
                    item["total_buy_amount"] += round(log.get("amount", 0) or 0)
                elif log.get("action") == "SELL":
                    item["sell_count"] += 1
                    item["total_sell_amount"] += round(log.get("amount", 0) or 0)
                    item["total_carry_over_buy_amount"] += round(log.get("carry_over_buy_amount", 0) or 0)
                    item["pnl_gross"] += round(log.get("pnl_gross", 0) or 0)
                    item["pnl_net"] += round(log.get("pnl_net", 0) or 0)
                    item["total_fee"] += round(log.get("buy_fee_component", 0) or 0)
                daily_breakdown[log_date] = item

            symbol = str(log.get("symbol", "") or "")
            if symbol == "":
                continue
            if log.get("action") == "SELL" and int(log.get("matched_qty", 0) or 0) > 0:
                cycle_counter[symbol] = cycle_counter.get(symbol, 0) + 1
                cycle_no = cycle_counter[symbol]
                cycle_rows.append({
                    "symbol": symbol,
                    "name": log.get("name", symbol),
                    "cycle_no": cycle_no,
                    "cycle_label": f"사이클 #{cycle_no}",
                    "buy_count": len(log.get("buy_lots", []) or []) or 1,
                    "sell_count": 1,
                    "buy_amount": round(log.get("matched_buy_amount", 0) or 0),
                    "carry_over_buy_amount": round(log.get("carry_over_buy_amount", 0) or 0),
                    "sell_amount": round(log.get("amount", 0) or 0),
                    "total_fee": round((log.get("fee", 0) or 0) + (log.get("buy_fee_component", 0) or 0)),
                    "realized_pnl_gross": round(log.get("pnl_gross", 0) or 0),
                    "realized_pnl_net": round(log.get("pnl_net", 0) or 0),
                    "pnl_gross": round(log.get("pnl_gross", 0) or 0),
                    "pnl_net": round(log.get("pnl_net", 0) or 0),
                    "remaining_qty": 0,
                    "remaining_avg_price": 0,
                })

        for item in sorted(remaining_positions, key=lambda x: (x.get("name", ""), x.get("symbol", ""))):
            symbol = str(item.get("symbol", "") or "")
            if symbol == "":
                continue
            lots = item.get("lots", []) or []
            if len(lots) == 0:
                cycle_counter[symbol] = cycle_counter.get(symbol, 0) + 1
                cycle_no = cycle_counter[symbol]
                cycle_rows.append({
                    "symbol": symbol,
                    "name": item.get("name", symbol),
                    "cycle_no": cycle_no,
                    "cycle_label": f"사이클 #{cycle_no}",
                    "buy_count": 1 if int(item.get("position_qty", 0) or 0) > 0 else 0,
                    "sell_count": 0,
                    "buy_amount": round(item.get("remaining_amount", 0) or 0),
                    "carry_over_buy_amount": round(item.get("carry_over_amount", 0) or 0),
                    "sell_amount": 0,
                    "total_fee": 0,
                    "realized_pnl_gross": 0,
                    "realized_pnl_net": 0,
                    "pnl_gross": 0,
                    "pnl_net": 0,
                    "remaining_qty": item.get("position_qty", 0),
                    "remaining_avg_price": item.get("avg_price", 0),
                })
                continue

            for lot in lots:
                lot_qty = self._safe_int(lot.get("qty", 0), 0)
                lot_price = self._safe_float(lot.get("price", 0), 0)
                if lot_qty <= 0 or lot_price <= 0:
                    continue
                cycle_counter[symbol] = cycle_counter.get(symbol, 0) + 1
                cycle_no = cycle_counter[symbol]
                lot_created = str(lot.get("created", "") or "")
                cycle_rows.append({
                    "symbol": symbol,
                    "name": item.get("name", symbol),
                    "cycle_no": cycle_no,
                    "cycle_label": f"사이클 #{cycle_no}",
                    "buy_count": 1,
                    "sell_count": 0,
                    "buy_amount": round(lot_qty * lot_price),
                    "carry_over_buy_amount": round(lot_qty * lot_price) if lot_created[:10].replace("-", "") < d_from_str else 0,
                    "sell_amount": 0,
                    "total_fee": 0,
                    "realized_pnl_gross": 0,
                    "realized_pnl_net": 0,
                    "pnl_gross": 0,
                    "pnl_net": 0,
                    "remaining_qty": lot_qty,
                    "remaining_avg_price": round(lot_price, 4),
                })

        symbol_summary = sorted(cycle_rows, key=lambda x: (x.get("name", ""), x.get("symbol", ""), x.get("cycle_no", 0)))

        symbol_summary_map = {}

        def _symbol_summary_item(symbol, name="", market=""):
            item = symbol_summary_map.get(symbol)
            if item is None:
                item = {
                    "symbol": symbol,
                    "market": market,
                    "name": name or self.strategy.symbol_name(symbol),
                    "buy_count": 0,
                    "sell_count": 0,
                    "buy_amount": 0,
                    "carry_over_buy_amount": 0,
                    "sell_amount": 0,
                    "total_fee": 0,
                    "realized_pnl_gross": 0,
                    "realized_pnl_net": 0,
                    "pnl_gross": 0,
                    "pnl_net": 0,
                    "remaining_qty": 0,
                    "remaining_avg_price": 0,
                    "remaining_amount": 0,
                    "remaining_unrealized_pnl": 0,
                    "carry_over_remaining_qty": 0,
                    "selected_buy_remaining_qty": 0,
                }
                symbol_summary_map[symbol] = item
            else:
                if market and not item.get("market"):
                    item["market"] = market
                if name and not item.get("name"):
                    item["name"] = name
            return item

        for log in logs:
            symbol = str(log.get("symbol", "") or "")
            if symbol == "":
                continue
            market = str(log.get("market", "") or symbol_market_map.get(symbol, self._market_key(symbol=symbol)))
            item = _symbol_summary_item(symbol, name=log.get("name", ""), market=market)
            amount = round(log.get("amount", 0) or 0)
            fee = round(log.get("fee", 0) or 0)
            buy_fee_component = round(log.get("buy_fee_component", 0) or 0)
            action = str(log.get("action", "") or "")
            if action == "BUY":
                item["buy_count"] += 1
                item["buy_amount"] += amount
                item["total_fee"] += fee
            elif action == "SELL":
                item["sell_count"] += 1
                item["sell_amount"] += amount
                item["carry_over_buy_amount"] += round(log.get("carry_over_buy_amount", 0) or 0)
                item["total_fee"] += fee + buy_fee_component
                item["realized_pnl_gross"] += round(log.get("pnl_gross", 0) or 0)
                item["realized_pnl_net"] += round(log.get("pnl_net", 0) or 0)
                item["pnl_gross"] += round(log.get("pnl_gross", 0) or 0)
                item["pnl_net"] += round(log.get("pnl_net", 0) or 0)

        for item in remaining_positions:
            symbol = str(item.get("symbol", "") or "")
            if symbol == "":
                continue
            market = symbol_market_map.get(symbol, self._market_key(symbol=symbol))
            summary_item = _symbol_summary_item(symbol, name=item.get("name", ""), market=market)
            summary_item["remaining_qty"] = int(item.get("position_qty", 0) or 0)
            summary_item["remaining_avg_price"] = item.get("avg_price", 0)
            summary_item["remaining_amount"] = round(item.get("remaining_amount", 0) or 0)
            summary_item["remaining_unrealized_pnl"] = round(item.get("unrealized_pnl", 0) or 0)
            summary_item["carry_over_remaining_qty"] = int(item.get("carry_over_qty", 0) or 0)
            summary_item["selected_buy_remaining_qty"] = int(item.get("selected_buy_qty", 0) or 0)

        broker_daily_breakdown = {}
        broker_trade_profit_total = None
        broker_trade_profit_cost_total = None
        if broker_trade_profit_rows:
            for row in broker_trade_profit_rows:
                symbol = str(row.get("symbol", "") or "")
                if symbol == "":
                    continue
                item = _symbol_summary_item(symbol, name=row.get("name", ""), market=symbol_market_map.get(symbol, "KS"))
                pnl = round(self._safe_float(row.get("pnl", 0), 0))
                fee_total = round(
                    self._safe_float(row.get("fee", 0), 0)
                    + self._safe_float(row.get("tax", 0), 0)
                    + self._safe_float(row.get("loan_interest", 0), 0)
                )
                item["buy_amount"] = round(self._safe_float(row.get("buy_amount", 0), 0))
                item["sell_amount"] = round(self._safe_float(row.get("sell_amount", 0), 0))
                item["total_fee"] = fee_total
                item["realized_pnl_gross"] = pnl + fee_total
                item["realized_pnl_net"] = pnl
                item["pnl_gross"] = pnl + fee_total
                item["pnl_net"] = pnl
                item["broker_authoritative"] = True

                date_key = str(row.get("date", "") or "")
                if len(date_key) == 8:
                    date_key = f"{date_key[:4]}-{date_key[4:6]}-{date_key[6:8]}"
                if date_key:
                    bucket = broker_daily_breakdown.get(date_key, {
                        "date": date_key,
                        "trade_count": 0,
                        "buy_count": 0,
                        "sell_count": 0,
                        "total_buy_amount": 0,
                        "total_sell_amount": 0,
                        "total_carry_over_buy_amount": 0,
                        "total_fee": 0,
                        "pnl_gross": 0,
                        "pnl_net": 0,
                    })
                    bucket["trade_count"] += 1
                    bucket["buy_count"] += 1 if self._safe_int(row.get("buy_qty", 0), 0) > 0 else 0
                    bucket["sell_count"] += 1 if self._safe_int(row.get("sell_qty", 0), 0) > 0 else 0
                    bucket["total_buy_amount"] += round(self._safe_float(row.get("buy_amount", 0), 0))
                    bucket["total_sell_amount"] += round(self._safe_float(row.get("sell_amount", 0), 0))
                    bucket["total_fee"] += fee_total
                    bucket["pnl_gross"] += pnl + fee_total
                    bucket["pnl_net"] += pnl
                    broker_daily_breakdown[date_key] = bucket

            broker_trade_profit_total = round(self._safe_float(broker_trade_profit_totals.get("pnl", 0), 0))
            broker_trade_profit_cost_total = round(self._safe_float(broker_trade_profit_totals.get("cost_total", 0), 0))

        aggregated_symbol_summary = sorted(symbol_summary_map.values(), key=lambda x: (x.get("name", ""), x.get("symbol", "")))
        if broker_trade_profit_total is not None:
            total_buy_amount = sum(round(item.get("buy_amount", 0) or 0) for item in aggregated_symbol_summary)
            total_sell_amount = sum(round(item.get("sell_amount", 0) or 0) for item in aggregated_symbol_summary)
            total_fee = sum(round(item.get("total_fee", 0) or 0) for item in aggregated_symbol_summary)
            total_pnl_gross = sum(round(item.get("pnl_gross", 0) or 0) for item in aggregated_symbol_summary)
            total_pnl_net = sum(round(item.get("pnl_net", 0) or 0) for item in aggregated_symbol_summary)
            if broker_trade_profit_cost_total is not None:
                total_fee = broker_trade_profit_cost_total
            total_pnl_net = broker_trade_profit_total + sum(
                round(item.get("pnl_net", 0) or 0)
                for item in aggregated_symbol_summary
                if self._is_us_market(item.get("market", ""))
            )
            total_pnl_gross = total_pnl_net + total_fee
        else:
            total_buy_amount = sum(round(item.get("buy_amount", 0) or 0) for item in aggregated_symbol_summary)
            total_sell_amount = sum(round(item.get("sell_amount", 0) or 0) for item in aggregated_symbol_summary)
            total_fee = sum(round(item.get("total_fee", 0) or 0) for item in aggregated_symbol_summary)
            total_pnl_gross = sum(round(item.get("pnl_gross", 0) or 0) for item in aggregated_symbol_summary)
            total_pnl_net = sum(round(item.get("pnl_net", 0) or 0) for item in aggregated_symbol_summary)

        daily_breakdown_result = sorted(
            (broker_daily_breakdown or daily_breakdown).values(),
            key=lambda x: x["date"],
        )

        return {
            "date_from": self._date_display(d_from_str),
            "date_to": self._date_display(d_to_str),
            "trade_count": trade_count,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "total_buy_amount": round(total_buy_amount),
            "total_carry_over_buy_amount": round(total_carry_over_buy_amount),
            "total_sell_amount": round(total_sell_amount),
            "total_fee": round(total_fee),
            "pnl_gross": round(total_pnl_gross),
            "pnl_net": round(total_pnl_net),
            "symbol_summary": aggregated_symbol_summary,
            "cycle_summary": symbol_summary,
            "remaining_positions": sorted(remaining_positions, key=lambda x: (x["name"], x["symbol"])),
            "remaining_position_count": len(remaining_positions),
            "remaining_qty_total": remaining_qty_total,
            "remaining_cost_amount": round(remaining_cost_amount),
            "remaining_unrealized_pnl": round(remaining_unrealized_pnl),
            "valuation_available": selected_is_today,
            "daily_breakdown": daily_breakdown_result,
            "logs": logs,
            "broker_orders": sorted(broker_orders, key=lambda x: x["created"], reverse=True),
            "broker_order_count": len(broker_orders),
            "broker_sync_enabled": bool(sync_broker),
            "broker_sync_ok": bool(sync_broker) and len(broker_sync_errors) == 0,
            "broker_sync_errors": broker_sync_errors,
            "broker_sync_sources": broker_sync_sources,
            "broker_fill_count": len(broker_fills),
            "broker_trade_profit_authoritative": broker_trade_profit_total is not None,
            "broker_trade_profit": round(broker_trade_profit_total) if broker_trade_profit_total is not None else None,
            "broker_trade_profit_cost_total": round(broker_trade_profit_cost_total) if broker_trade_profit_cost_total is not None else None,
            "verified_count": len([l for l in logs if l["verification"] == "kis"]),
            "recovered_count": 0,
            "unverified_count": len([l for l in logs if l["verification"] == "local"]),
            "excluded_recovery_count": 0,
            "excluded_recovery_logs": [],
            "verification_summary": {
                "kis": len([l for l in logs if l["verification"] == "kis"]),
                "local": len([l for l in logs if l["verification"] == "local"]),
                "total": len(logs)
            },
        }

    def _daily_trade_summary_local_fast(self, session_date=""):
        today = self._date_compact(session_date) if session_date else self._now().strftime("%Y%m%d")
        day_prefix = f"{today[:4]}-{today[4:6]}-{today[6:8]}"
        log_db = self.struct.db("trade_log")
        try:
            recent_rows = log_db.rows(event_type__startswith="DT_", orderby="created", order="DESC", dump=500)
        except Exception:
            recent_rows = []

        selected_rows = []
        for row in recent_rows:
            created = str(row.get("created", "") or "")
            if created.startswith(day_prefix):
                selected_rows.append(row)
        selected_rows.reverse()

        _FEE_BUY = 0.00015
        _FEE_SELL = 0.00195
        logs = []
        symbol_summary = {}
        total_buy_amount = 0.0
        total_sell_amount = 0.0
        total_fee = 0.0

        for row in selected_rows:
            symbol = str(row.get("symbol", "") or "")
            event_type = str(row.get("event_type", "") or "")
            market = self._market_from_event_type(event_type, symbol)
            action = self._normalize_trade_action(row.get("action", ""))
            filled_price = self._safe_float(row.get("filled_price", 0), 0)
            filled_qty = self._safe_int(row.get("filled_qty", 0), 0)
            if not symbol or filled_price <= 0 or filled_qty <= 0 or action not in ["BUY", "SELL"]:
                continue

            amount = round(filled_price * filled_qty)
            fee = round(amount * (_FEE_BUY if action == "BUY" else _FEE_SELL))
            created = str(row.get("created", "") or "")
            name = str(row.get("name", "") or "") or self.strategy.symbol_name(symbol)

            logs.append({
                "id": row.get("id"),
                "symbol": symbol,
                "market": market,
                "name": name,
                "event_type": event_type,
                "action": action,
                "order_no": str(row.get("order_no", "") or ""),
                "filled_price": filled_price,
                "filled_qty": filled_qty,
                "amount": amount,
                "fee": fee,
                "pnl_gross": 0,
                "pnl_net": 0,
                "avg_buy_price": 0,
                "matched_qty": 0,
                "matched_buy_amount": 0,
                "carry_over_qty": 0,
                "carry_over_buy_amount": 0,
                "buy_lots": [],
                "message": row.get("message", ""),
                "created": created,
                "verification": "local",
                "verification_status": "local",
                "verification_label": "로컬 로그",
            })

            if symbol not in symbol_summary:
                symbol_summary[symbol] = {
                    "symbol": symbol,
                    "name": name,
                    "buy_count": 0,
                    "sell_count": 0,
                    "buy_amount": 0,
                    "carry_over_buy_amount": 0,
                    "sell_amount": 0,
                    "total_fee": 0,
                    "realized_pnl_gross": 0,
                    "realized_pnl_net": 0,
                    "pnl_gross": 0,
                    "pnl_net": 0,
                }

            symbol_summary[symbol]["total_fee"] += fee
            total_fee += fee
            if action == "BUY":
                symbol_summary[symbol]["buy_count"] += 1
                symbol_summary[symbol]["buy_amount"] += amount
                total_buy_amount += amount
            else:
                symbol_summary[symbol]["sell_count"] += 1
                symbol_summary[symbol]["sell_amount"] += amount
                total_sell_amount += amount

        state_map = self._load_state_map()
        remaining_positions = []
        remaining_qty_total = 0
        remaining_cost_amount = 0.0
        total_realized_profit = 0.0

        for state in (state_map or {}).values():
            state = state or {}
            symbol = str(state.get("symbol", "") or "")
            if not symbol:
                continue
            session_day = str(state.get("session_date", "") or "").replace("-", "")
            qty = self._safe_int(state.get("position_qty", 0), 0)
            avg_price = self._safe_float(state.get("avg_price", 0), 0)
            name = state.get("name", self.strategy.symbol_name(symbol))
            realized_profit = self._safe_float(state.get("realized_profit", 0), 0)

            if session_day == today:
                total_realized_profit += realized_profit
                if symbol not in symbol_summary:
                    symbol_summary[symbol] = {
                        "symbol": symbol,
                        "name": name,
                        "buy_count": 0,
                        "sell_count": 0,
                        "buy_amount": 0,
                        "carry_over_buy_amount": 0,
                        "sell_amount": 0,
                        "total_fee": 0,
                        "realized_pnl_gross": 0,
                        "realized_pnl_net": 0,
                        "pnl_gross": 0,
                        "pnl_net": 0,
                    }
                symbol_summary[symbol]["realized_pnl_gross"] = round(realized_profit)
                symbol_summary[symbol]["realized_pnl_net"] = round(realized_profit)
                symbol_summary[symbol]["pnl_gross"] = round(realized_profit)
                symbol_summary[symbol]["pnl_net"] = round(realized_profit)

            if qty <= 0:
                continue

            remaining_amount = round(avg_price * qty)
            remaining_qty_total += qty
            remaining_cost_amount += remaining_amount
            remaining_positions.append({
                "symbol": symbol,
                "name": name,
                "position_qty": qty,
                "avg_price": round(avg_price, 4),
                "remaining_amount": remaining_amount,
                "carry_over_qty": qty if session_day != today else 0,
                "carry_over_amount": remaining_amount if session_day != today else 0,
                "selected_buy_qty": qty if session_day == today else 0,
                "selected_buy_amount": remaining_amount if session_day == today else 0,
                "current_price": 0,
                "unrealized_pnl": 0,
                "valuation_available": False,
                "lots": [],
            })

            if symbol not in symbol_summary:
                symbol_summary[symbol] = {
                    "symbol": symbol,
                    "name": name,
                    "buy_count": 0,
                    "sell_count": 0,
                    "buy_amount": 0,
                    "carry_over_buy_amount": 0,
                    "sell_amount": 0,
                    "total_fee": 0,
                    "realized_pnl_gross": 0,
                    "realized_pnl_net": 0,
                    "pnl_gross": 0,
                    "pnl_net": 0,
                }
            symbol_summary[symbol]["remaining_qty"] = qty
            symbol_summary[symbol]["remaining_avg_price"] = round(avg_price, 4)
            symbol_summary[symbol]["remaining_amount"] = remaining_amount
            symbol_summary[symbol]["remaining_unrealized_pnl"] = 0
            symbol_summary[symbol]["carry_over_remaining_qty"] = qty if session_day != today else 0
            symbol_summary[symbol]["selected_buy_remaining_qty"] = qty if session_day == today else 0

        logs.sort(key=lambda x: x.get("created", ""), reverse=True)
        for i, log in enumerate(logs):
            log["trade_no"] = len(logs) - i

        return {
            "date_from": self._date_display(today),
            "date_to": self._date_display(today),
            "trade_count": len(logs),
            "buy_count": len([log for log in logs if log.get("action") == "BUY"]),
            "sell_count": len([log for log in logs if log.get("action") == "SELL"]),
            "total_buy_amount": round(total_buy_amount),
            "total_carry_over_buy_amount": 0,
            "total_sell_amount": round(total_sell_amount),
            "total_fee": round(total_fee),
            "pnl_gross": round(total_realized_profit),
            "pnl_net": round(total_realized_profit),
            "symbol_summary": list(symbol_summary.values()),
            "remaining_positions": sorted(remaining_positions, key=lambda x: (x["name"], x["symbol"])),
            "remaining_position_count": len(remaining_positions),
            "remaining_qty_total": remaining_qty_total,
            "remaining_cost_amount": round(remaining_cost_amount),
            "remaining_unrealized_pnl": 0,
            "valuation_available": False,
            "daily_breakdown": [],
            "logs": logs,
            "broker_orders": [],
            "broker_order_count": 0,
            "verified_count": 0,
            "recovered_count": 0,
            "unverified_count": len(logs),
            "excluded_recovery_count": 0,
            "excluded_recovery_logs": [],
            "verification_summary": {
                "kis": 0,
                "local": len(logs),
                "total": len(logs),
            },
        }

    def daily_trade_summary(self, session_date="", sync_broker=True, include_valuation=True):
        """오늘 단타 거래 로그 집계. period_trade_summary를 호출하여 일관성을 유지합니다."""
        today = session_date if session_date else self._now().strftime("%Y%m%d")
        if sync_broker is False and include_valuation is False and self._date_compact(today) == self._now().strftime("%Y%m%d"):
            return self._daily_trade_summary_local_fast(session_date=today)
        return self.period_trade_summary(date_from=today, date_to=today, sync_broker=sync_broker, include_valuation=include_valuation)

    def auto_enabled(self, market="KS"):
        if self._hard_locked():
            return False
        if self._feature_enabled() is False:
            return False
        if self._is_us_market(market):
            modern = str(self._config("daytrade_us_auto_enabled", "")).lower()
            legacy = str(self._config("us_daytrade_auto_enabled", "")).lower()
            if modern in ("true", "false"):
                return modern == "true"
            if legacy in ("true", "false"):
                return legacy == "true"
            return False
        return str(self._config("daytrade_auto_enabled", "false")).lower() == "true"

    def _auto_max_symbols(self, market="KS"):
        market_key = "US" if self._is_us_market(market) else "KS"
        if market_key == "US":
            value = self._safe_int(self._config("daytrade_us_auto_max_symbols", self._config("daytrade_auto_max_symbols", "5")), 5)
            return max(1, min(30, value))
        else:
            value = self._safe_int(self._config("daytrade_ks_auto_max_symbols", self._config("daytrade_auto_max_symbols", "5")), 5)
            return max(16, min(30, value))

    def _cached_recommendation_narrow_for_auto(self, cached, filtered, target_count):
        cached = cached or {}
        filtered = filtered or {}
        cached_leaderboard = list(cached.get("leaderboard", []) or [])
        filtered_leaderboard = list(filtered.get("leaderboard", []) or [])
        cached_limit = self._safe_int(cached.get("leaderboard_limit", 0), 0)
        filtered_limit = self._safe_int(filtered.get("leaderboard_limit", 0), 0)
        cached_count = len(cached_leaderboard)
        filtered_count = len(filtered_leaderboard)
        should_refresh = cached_count < max(1, self._safe_int(target_count, 0)) and cached_limit < filtered_limit
        return should_refresh, {
            "cached_leaderboard_count": cached_count,
            "cached_leaderboard_limit": cached_limit,
            "filtered_leaderboard_count": filtered_count,
            "filtered_leaderboard_limit": filtered_limit,
            "target_count": self._safe_int(target_count, 0),
        }

    def _expand_recommendation_with_candidate_universe(self, recommendation, market="KS", target_count=0, max_count=0):
        payload = dict(recommendation or {})
        leaderboard = list(payload.get("leaderboard", []) or [])
        target = max(0, self._safe_int(target_count, 0))
        limit = max(target, self._safe_int(max_count, 0)) if self._safe_int(max_count, 0) > 0 else target
        if limit <= 0 or len(leaderboard) >= target:
            payload["fast_universe_added_count"] = 0
            payload["fast_universe_expanded"] = False
            payload["candidate_universe_count"] = len(leaderboard)
            return payload

        universe = []
        if self._is_us_market(market):
            if hasattr(self.strategy, "us_candidate_universe"):
                universe = list(self.strategy.us_candidate_universe() or [])
        elif hasattr(self.strategy, "candidate_universe"):
            universe = list(self.strategy.candidate_universe(market=market) or [])

        existing = {
            (str(item.get("symbol", "") or "").strip(), str(item.get("market", market) or market).upper(), str(item.get("strategy_id", "vrev") or "vrev").strip().lower())
            for item in leaderboard
        }
        added_count = 0
        for item in universe:
            symbol = str(item.get("symbol", "") or "").strip()
            item_market = str(item.get("market", market) or market).upper()
            strategy_id = str(item.get("strategy_id", "vrev") or "vrev").strip().lower()
            key = (symbol, item_market, strategy_id)
            if symbol == "" or key in existing:
                continue
            leaderboard.append({
                "symbol": symbol,
                "market": item_market,
                "name": item.get("name", self.strategy.symbol_name(symbol)),
                "strategy_id": strategy_id,
                "strategy_name": item.get("strategy_name", strategy_id),
                "trade_ready": False,
                "score": self._safe_float(item.get("score", 0), 0),
                "rank_score": self._safe_float(item.get("rank_score", item.get("score", 0)), 0),
                "source": "candidate_universe",
            })
            existing.add(key)
            added_count += 1
            if len(leaderboard) >= limit:
                break

        payload["leaderboard"] = leaderboard[:limit] if limit > 0 else leaderboard
        payload["fast_universe_added_count"] = added_count
        payload["fast_universe_expanded"] = added_count > 0
        payload["candidate_universe_count"] = len(universe)
        return payload

    def _auto_cycle_wait_summary(self, results, excluded_by_price, daily_loss, market="KS"):
        reason_counts = {}
        for item in list(excluded_by_price or []):
            reason = str((item or {}).get("reason", "") or "").strip()
            label = reason
            if "품질" in reason or "검증" in reason or "trade_ready" in reason:
                label = "품질 게이트 대기"
            elif "시드" in reason or "1주" in reason or "상한" in reason:
                label = "시드 대기"
            elif "슬롯" in reason or "보유 종목 수" in reason:
                label = "슬롯 대기"
            elif reason == "":
                label = "기타 대기"
            reason_counts[label] = reason_counts.get(label, 0) + 1
        summary_rows = [
            {"reason": reason, "count": count}
            for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        return {
            "market": self._market_key(market),
            "result_count": len(list(results or [])),
            "excluded_count": len(list(excluded_by_price or [])),
            "halt_new_buys": bool((daily_loss or {}).get("halt_new_buys", False)),
            "reason_summary": summary_rows,
        }

    def _daytrade_market_open(self, market="KS"):
        if self._is_us_market(market):
            return self._us_market_open()
        now = self._now()
        if now.weekday() >= 5:
            return False
        hhmm = now.hour * 100 + now.minute
        return 900 <= hhmm < 1520

    def auto_candidates(self, requested_seed=0, force_recommend=False, market="KS"):
        seed_status = self.shared_budget_status(requested_seed=requested_seed, market=market)
        effective_seed = self._safe_float(seed_status.get("effective_daytrade_seed", 0), 0)
        total_seed_krw = self._safe_float(seed_status.get("total_seed_krw", effective_seed), effective_seed)
        max_symbols = self._safe_int(seed_status.get("max_symbols", self._auto_max_symbols(market=market)), self._auto_max_symbols(market=market))
        slot_target_count = self._safe_int(seed_status.get("slot_target_count", max_symbols), max_symbols)

        portfolio = seed_status.get("portfolio", {}) or {}
        if isinstance(portfolio, dict) is False or isinstance(portfolio.get("active_positions", []), list) is False:
            portfolio = self.portfolio_usage(use_live_price=True, market_filter=("US" if self._is_us_market(market) else "KS"))
        used_seed_krw = self._safe_float(seed_status.get("used_seed_krw", portfolio.get("active_entry_seed_krw", portfolio.get("active_cost_krw", 0))), 0)
        position_count = self._safe_int(seed_status.get("position_count", portfolio.get("position_count", 0)), 0)
        remaining_seed_krw = self._safe_float(seed_status.get("remaining_seed_krw", max(0.0, total_seed_krw - used_seed_krw)), 0)
        available_slot_count = self._safe_int(seed_status.get("available_slot_count", max(0, max_symbols - position_count)), max(0, max_symbols - position_count))
        slot_seed_limit_krw = round(self._safe_float(seed_status.get("slot_seed_limit_krw", 0), 0), 2)
        if slot_seed_limit_krw <= 0 and total_seed_krw > 0 and slot_target_count > 0:
            slot_seed_limit_krw = round(max(0.0, total_seed_krw / slot_target_count), 2)
        per_symbol_seed_krw = self._safe_float(seed_status.get("per_symbol_seed_krw", slot_seed_limit_krw), 0)
        # 예산 현황 진단 로그 — 구매 상한이 낮을 때 원인 파악용
        _avail = round(self._safe_float(seed_status.get("available_for_daytrade", 0), 0), 0)
        _withdrawable = round(self._safe_float(seed_status.get("withdrawable_krw", 0), 0), 0)
        _d1 = round(self._safe_float(seed_status.get("d1_deposit_krw", 0), 0), 0)
        _d2 = round(self._safe_float(seed_status.get("d2_deposit_krw", 0), 0), 0)
        _reserve = round(self._safe_float(seed_status.get("infinite_buy_daily_reserve_krw", 0), 0), 0)
        _source = seed_status.get("source", "")
        budget_meta = {
            "market": market,
            "requested_seed": round(self._safe_float(requested_seed, 0), 2),
            "effective_seed": round(effective_seed, 2),
            "total_seed_krw": round(total_seed_krw, 2),
            "used_seed_krw": round(used_seed_krw, 2),
            "remaining_seed_krw": round(remaining_seed_krw, 2),
            "per_symbol_seed_krw": round(per_symbol_seed_krw, 2),
            "slot_seed_limit_krw": round(slot_seed_limit_krw, 2),
            "position_count": position_count,
            "available_slot_count": available_slot_count,
            "slot_target_count": slot_target_count,
            # KIS 잔고 breakdown — 구매 상한 낮은 원인 추적용
            "kis_withdrawable_krw": _withdrawable,
            "kis_d1_deposit_krw": _d1,
            "kis_d2_deposit_krw": _d2,
            "kis_available_for_daytrade": _avail,
            "infinite_buy_reserve_krw": _reserve,
            "balance_source": _source,
        }
        self._append_runtime_log("info", f"단타 후보 계산 시작 ({market})", meta=budget_meta)
        # 구매 상한이 낮을 때 (10만원 미만) 별도 경고 로그
        max_affordable_preview = remaining_seed_krw * self._buy_buffer_ratio() if remaining_seed_krw > 0 else 0.0
        if 0 < max_affordable_preview < 100000:
            self._append_runtime_log(
                "warning",
                f"구매 상한 낮음: 1주당 {max_affordable_preview:,.0f}원 이하만 매수 가능"
                f" (KIS 주문가능금액 {_withdrawable:,.0f}원 / D1 {_d1:,.0f}원 / D2 {_d2:,.0f}원"
                f"{f' / 무한매수 예약금 -{_reserve:,.0f}원' if _reserve > 0 else ''})",
                meta={"withdrawable": _withdrawable, "d1": _d1, "d2": _d2, "reserve": _reserve, "max_affordable": round(max_affordable_preview, 0)},
                dedup_sec=600,
            )

        rows = []
        seen = set()
        active_positions = portfolio.get("active_positions", [])
        active_symbols = {position.get("symbol", "") for position in active_positions if position.get("symbol", "")}
        for position in active_positions:
            symbol = position.get("symbol", "")
            pos_market = position.get("market", "KS")
            if not symbol or symbol in seen or self._is_us_market(pos_market) != self._is_us_market(market):
                continue
            seen.add(symbol)
            rows.append({
                "symbol": symbol,
                "market": pos_market,
                "name": position.get("name", ""),
                "strategy_id": position.get("strategy_id", "vrev"),
                "source": "active_position",
                "score": 999999,
                "position_value_krw": position.get("position_value", 0),
                "decision_reason": "이미 보유 중인 종목이라 신규 진입보다 보유/청산 판단을 우선합니다.",
                "entry_seed_krw": 0.0,
            })
        
        recommendation = None
        affordable_seed_cap_krw = min(remaining_seed_krw, slot_seed_limit_krw) if slot_seed_limit_krw > 0 else remaining_seed_krw
        max_affordable_per_share = affordable_seed_cap_krw * self._buy_buffer_ratio() if affordable_seed_cap_krw > 0 else 0.0
        price_cap_krw = max(0.0, max_affordable_per_share)
        min_day_range_pct = self._safe_float(self._config("daytrade_min_day_range_pct", "3.0"), 3.0)
        target_slot_count = max(1, min(max_symbols, max(position_count + available_slot_count, slot_target_count)))
        slot_seed_limit_krw = round(min(slot_seed_limit_krw if slot_seed_limit_krw > 0 else max(0.0, total_seed_krw / target_slot_count), remaining_seed_krw if remaining_seed_krw > 0 else max(0.0, total_seed_krw / target_slot_count)), 2) if total_seed_krw > 0 else round(max(0.0, slot_seed_limit_krw), 2)
        is_auto_mode = self.auto_enabled(market=market)
        market_open = self._daytrade_market_open(market=market)
        preopen_refresh_window = False
        if self._is_us_market(market):
            preopen_refresh_window = self._us_premarket_open() and market_open is False
        else:
            try:
                seconds_until_open = (self._today_open_kst(market=market) - self._now()).total_seconds()
                preopen_refresh_window = 0 <= seconds_until_open <= 3600
            except Exception:
                preopen_refresh_window = False

        hourly_refresh_sec = max(
            300,
            self._safe_int(
                self._config("daytrade_training_refresh_sec", self._config("daytrade_intraday_retrain_sec", "3600")),
                3600,
            ),
        )
        default_idle_refresh = "43200" if is_auto_mode else self._config("daytrade_recommendation_refresh_sec", "43200")
        idle_refresh_sec = max(hourly_refresh_sec, self._safe_int(default_idle_refresh, 43200))

        if market_open or preopen_refresh_window:
            refresh_sec = hourly_refresh_sec
        else:
            refresh_sec = idle_refresh_sec

        try:
            recommendation = self.strategy.recommend(
                seed=max(total_seed_krw, requested_seed or 0, 0),
                force=bool(force_recommend),
                price_cap=price_cap_krw,
                max_age_sec=refresh_sec,
                market=market,
            )
        except Exception as e:
            self._append_runtime_log("warning", f"단타 자동 추천 갱신 실패 ({market}): {str(e)}")
            recommendation = self.strategy.latest_recommendation(
                seed=max(total_seed_krw, requested_seed or 0, 0),
                strategy_id="",
                price_cap=price_cap_krw,
                max_age_sec=max(refresh_sec, 43200),
                allow_stale_day=True,
                market=market,
            ) or self.strategy.latest_recommendation(allow_stale_day=True, market=market)
        
        leaderboard = recommendation.get("leaderboard", []) if recommendation else []
        valid = [x for x in leaderboard if x.get("error") is None]
        valid.sort(
            key=lambda x: (
                1 if x.get("trade_ready") else 0,
                self._safe_float(x.get("rank_score", x.get("score", 0)), 0),
                self._safe_float(x.get("validation_return", 0), 0),
                self._safe_float(x.get("validation_win_rate", 0), 0),
                self._safe_float(x.get("validation_robustness", 0), 0),
                self._safe_float(x.get("avg_day_range_pct", 0), 0),
                self._safe_float(x.get("liquidity_score", 0), 0),
            ),
            reverse=True,
        )
        if self._is_us_market(market):
            diversified = []
            used_strategy = set()
            for item in valid:
                strategy_id = str(item.get("strategy_id", "") or "").strip().lower()
                if strategy_id == "" or strategy_id in used_strategy:
                    continue
                diversified.append(item)
                used_strategy.add(strategy_id)
            remaining = [item for item in valid if item not in diversified]
            valid = diversified + remaining

        live_valid = [item for item in valid if self._live_strategy_allowed(item.get("strategy_id", "vrev"), market=market)]
        live_quality_guard = self.strategy._build_quality_guard(
            live_valid,
            self.strategy.recommendation_training_defaults(),
            market=market,
        ) if hasattr(self.strategy, "_build_quality_guard") else {
            "block_new_entries": len([row for row in live_valid if row.get("trade_ready")]) <= 0,
            "issues": [],
            "trade_ready_count": len([row for row in live_valid if row.get("trade_ready")]),
        }
        if isinstance(recommendation, dict):
            recommendation["live_quality_guard"] = live_quality_guard
        valid = live_valid

        excluded_by_price = []
        quality_guard = live_quality_guard if isinstance(live_quality_guard, dict) else {}
        if quality_guard.get("block_new_entries"):
            guard_reason = " / ".join(quality_guard.get("issues", [])[:3])
            if guard_reason == "":
                guard_reason = "실주문 가능한 V-REV 후보가 없어 신규 진입을 차단했습니다."
            self._append_runtime_log("warning", f"단타 신규 진입 차단 ({market}): {guard_reason}", meta=quality_guard, dedup_sec=300)
            excluded_by_price.append({
                "symbol": "",
                "name": "추천 품질 가드",
                "last_price": 0,
                "max_affordable": round(max_affordable_per_share, 0),
                "reason": f"추천/훈련 검증 품질이 약해 신규 진입을 차단했습니다. {guard_reason}",
            })
            return {
                "effective_seed": round(effective_seed, 2),
                "total_seed_krw": round(total_seed_krw, 2),
                "used_seed_krw": round(used_seed_krw, 2),
                "remaining_seed_krw": round(remaining_seed_krw, 2),
                "per_symbol_seed_krw": round(per_symbol_seed_krw, 2),
                "position_count": position_count,
                "slot_target_count": slot_target_count,
                "available_slot_count": available_slot_count,
                "max_symbols": max_symbols,
                "slot_seed_limit_krw": round(slot_seed_limit_krw, 2),
                "min_day_range_pct": round(min_day_range_pct, 2),
                "max_affordable_per_share": round(max_affordable_per_share, 0),
                "recommendation_refresh_sec": refresh_sec,
                "candidates": rows,
                "excluded_by_price": excluded_by_price,
                "recommendation": recommendation,
            }
        for item in valid:
            symbol = item.get("symbol", "")
            if not symbol or symbol in seen:
                continue

            strategy_id = item.get("strategy_id", "vrev")
            item_market = item.get("market", "KS")

            # 미국 시장 전용 전략 필터링
            if self._is_us_market(market):
                if not strategy_id.startswith("us_"):
                    continue
            else: # 한국 시장
                if strategy_id.startswith("us_"):
                    continue
                if strategy_id != "vrev":
                    excluded_by_price.append({
                        "symbol": symbol,
                        "name": item.get("name", ""),
                        "last_price": self._safe_float(item.get("last_price", 0), 0),
                        "max_affordable": round(max_affordable_per_share, 0),
                        "reason": "국내 실시간 분봉 공급이 불안정해 현재 실주문 자동매매는 V-REV 전략만 허용합니다.",
                    })
                    self._append_runtime_log("info", f"단타 후보 제외(실주문 전략 제한): {item.get('name', symbol)} {strategy_id}")
                    continue

            last_price = self._safe_float(item.get("last_price", 0), 0)
            is_new_entry = symbol not in active_symbols
            avg_day_range_pct = self._safe_float(item.get("avg_day_range_pct", 0), 0)
            
            if is_new_entry and available_slot_count <= 0:
                excluded_by_price.append({
                    "symbol": symbol, "name": item.get("name", ""), "last_price": last_price,
                    "max_affordable": round(max_affordable_per_share, 0),
                    "reason": f"보유 종목 수가 최대 {max_symbols}개에 도달해 신규 슬롯이 없습니다.",
                })
                continue

            if is_new_entry and avg_day_range_pct > 0 and avg_day_range_pct < min_day_range_pct:
                excluded_by_price.append({
                    "symbol": symbol, "name": item.get("name", ""), "last_price": last_price,
                    "max_affordable": round(max_affordable_per_share, 0),
                    "reason": f"단타 변동성 부족: 평균 일중 변동폭 {avg_day_range_pct:.2f}% < 최소 {min_day_range_pct:.2f}%",
                })
                self._append_runtime_log(
                    "info",
                    f"단타 후보 제외(변동성 부족): {item.get('name', symbol)} 평균 일중 변동폭 {avg_day_range_pct:.2f}% / 최소 {min_day_range_pct:.2f}%"
                )
                continue
            
            if is_new_entry and self._is_us_market(market) is False and last_price > 0 and max_affordable_per_share > 0 and last_price > max_affordable_per_share:
                excluded_by_price.append({
                    "symbol": symbol, "name": item.get("name", ""), "last_price": last_price,
                    "max_affordable": round(max_affordable_per_share, 0),
                    "reason": f"남은 시드 전액 기준 1주당 {max_affordable_per_share:,.0f}원까지만 진입 가능합니다.",
                })
                self._append_runtime_log("info", f"단타 후보 제외(시드 초과): {item.get('name', symbol)} 주당 {last_price:,.0f}원 / 1주 진입 상한 {max_affordable_per_share:,.0f}원")
                continue

            seen.add(symbol)
            rows.append({
                "symbol": symbol,
                "market": item_market,
                "name": item.get("name", ""),
                "strategy_id": strategy_id,
                "strategy_name": item.get("strategy_name", strategy_id),
                "score": self._safe_float(item.get("score", 0), 0),
                "avg_day_range_pct": self._safe_float(item.get("avg_day_range_pct", 0), 0),
                "avg_intraday_move_pct": self._safe_float(item.get("avg_intraday_move_pct", 0), 0),
                "liquidity_score": self._safe_float(item.get("liquidity_score", 0), 0),
                "last_price": last_price,
                "source": "leaderboard",
                "entry_seed_krw": (
                    round(self._minimum_entry_seed(last_price, market=item_market), 2)
                    if is_new_entry and self._is_us_market(item_market)
                    else round(min(remaining_seed_krw, slot_seed_limit_krw), 2) if is_new_entry else 0.0
                ),
                "decision_reason": (
                    "미장은 요청 시드와 무관하게 최소 1주 진입 가능 수량으로 실시간 진입을 검토합니다."
                    if self._is_us_market(item_market)
                    else f"점수와 조건이 맞으면 슬롯당 시드 한도 ₩{slot_seed_limit_krw:,.0f} 내에서 신규 진입을 검토합니다."
                ),
            })
            if len(rows) >= max(max_symbols, len(active_positions)):
                break
        
        return {
            "effective_seed": round(effective_seed, 2),
            "total_seed_krw": round(total_seed_krw, 2),
            "used_seed_krw": round(used_seed_krw, 2),
            "remaining_seed_krw": round(remaining_seed_krw, 2),
            "per_symbol_seed_krw": round(per_symbol_seed_krw, 2),
            "position_count": position_count,
            "slot_target_count": slot_target_count,
            "available_slot_count": available_slot_count,
            "max_symbols": max_symbols,
            "slot_seed_limit_krw": round(slot_seed_limit_krw, 2),
            "min_day_range_pct": round(min_day_range_pct, 2),
            "max_affordable_per_share": round(max_affordable_per_share, 0),
            "recommendation_refresh_sec": refresh_sec,
            "candidates": rows,
            "excluded_by_price": excluded_by_price,
            "portfolio": portfolio,
            "recommendation": recommendation,
        }

    def _rotation_opportunity(self, candidate_payload, remaining_seed_krw=0):
        portfolio = candidate_payload.get("portfolio", {}) or {}
        active_positions = portfolio.get("active_positions", []) if isinstance(portfolio, dict) else []
        if isinstance(active_positions, list) is False or len(active_positions) == 0:
            active_positions = self.active_positions()
        if len(active_positions) == 0:
            return None
        max_symbols = candidate_payload.get("max_symbols", self._auto_max_symbols())
        if remaining_seed_krw > 0 and len(active_positions) < max_symbols:
            return None

        score_map = {}
        recommendation = candidate_payload.get("recommendation", {}) or {}
        for row in (recommendation.get("leaderboard", []) or []):
            if row.get("error"):
                continue
            score_map[(row.get("symbol", ""), row.get("strategy_id", "vrev"))] = self._safe_float(row.get("score", 0), 0)

        alternatives = [
            item for item in (candidate_payload.get("candidates", []) or [])
            if item.get("source") != "active_position"
        ]
        if len(alternatives) == 0:
            return None

        min_hold_minutes = self._safe_float(self._config("daytrade_rotation_hold_minutes", "20"), 20)
        min_score_gap = self._safe_float(self._config("daytrade_rotation_score_gap", "8"), 8)
        max_volume_ratio = self._safe_float(self._config("daytrade_rotation_max_volume_ratio", "0.9"), 0.9)
        max_range_pct = self._safe_float(self._config("daytrade_rotation_max_range_pct", "1.4"), 1.4)

        for position in active_positions:
            state = self._state_for(
                position.get("symbol", ""),
                market=position.get("market", "KS"),
                seed=max(self._safe_float(position.get("current_price", 0), 0) * self._safe_int(position.get("position_qty", 0), 0), 1),
                name=position.get("name", ""),
                strategy_id=position.get("strategy_id", "vrev"),
            )
            buy_order = self._last_buy_order(state)
            hold_minutes = self._minutes_since((buy_order or {}).get("timestamp", state.get("updated_at", "")))
            if hold_minutes < min_hold_minutes:
                continue
            avg_price = self._safe_float(position.get("avg_price", 0), 0)
            current_price = self._safe_float(position.get("current_price", 0), 0)
            break_even = self._break_even_price(avg_price)
            if break_even <= 0 or current_price < break_even:
                continue
            status = self.signal_status(
                position.get("symbol", ""),
                market=position.get("market", "KS"),
                seed=max(current_price * self._safe_int(position.get("position_qty", 0), 0), current_price, 1),
                name=position.get("name", ""),
                strategy_id=position.get("strategy_id", "vrev"),
            )
            if str(status.get("signal", {}).get("action", "HOLD")).startswith("SELL"):
                continue
            bar = status.get("bar", {}) or {}
            stagnant = (
                self._safe_float(bar.get("volume_surge_ratio", 0), 0) <= max_volume_ratio
                and self._safe_float(bar.get("intraday_range_pct", 0), 0) <= max_range_pct
                and abs(self._safe_float(bar.get("vwap_gap_pct", 0), 0)) <= 0.5
            )
            if stagnant is False:
                continue
            position_score = score_map.get((position.get("symbol", ""), position.get("strategy_id", "vrev")), 0.0)
            for alternative in alternatives:
                alternative_score = self._safe_float(alternative.get("score", 0), 0)
                if alternative_score <= position_score + min_score_gap:
                    continue
                alt_seed = max(self._safe_float(alternative.get("entry_seed_krw", 0), 0), self._safe_float(alternative.get("last_price", 0), 0), 1)
                alt_status = self.signal_status(
                    alternative.get("symbol", ""),
                    market=alternative.get("market", "KS"),
                    seed=alt_seed,
                    name=alternative.get("name", ""),
                    strategy_id=alternative.get("strategy_id", "vrev"),
                )
                if str(alt_status.get("signal", {}).get("action", "HOLD")).startswith("BUY") is False:
                    continue
                return {
                    "from": position,
                    "to": alternative,
                    "reason": f"{position.get('name', position.get('symbol', ''))} 정체 {hold_minutes:.0f}분 · 본전 이상 구간이라 {alternative.get('name', alternative.get('symbol', ''))}로 교체 검토",
                    "hold_minutes": round(hold_minutes, 1),
                    "break_even_price": round(break_even, 2),
                    "position_score": round(position_score, 2),
                    "target_score": round(alternative_score, 2),
                }
        return None

    def auto_cycle(self, requested_seed=0, force_recommend=False, market="KS", user_id=""):
        if self._hard_locked():
            return self._hard_locked_result()
        if self._is_us_market(market):
            return self.us_auto_cycle(requested_seed=requested_seed, force_recommend=force_recommend, user_id=user_id)
        return self.kr_auto_cycle(requested_seed=requested_seed, force_recommend=force_recommend)

    def us_auto_cycle(self, requested_seed=0, force_recommend=False, user_id=""):
        """미국 주식 자동매매 사이클"""
        if self._hard_locked():
            return self._hard_locked_result()
        if self.auto_enabled(market="US") is False:
            return {
                "executed": False,
                "message": "미국주식 단타 자동운용이 비활성 상태입니다.",
                "budget": self.shared_budget_status(requested_seed=requested_seed, market="US"),
                "daily_loss": self.daily_loss_status(requested_seed=requested_seed),
                "results": [],
                "candidates": [],
            }

        if not self._us_market_open() and not self._us_premarket_open():
            return {
                "executed": False,
                "message": "미국 주식 시장(프리마켓/본장)이 열려있지 않습니다.",
                "budget": self.shared_budget_status(requested_seed=requested_seed, market="US"),
                "daily_loss": self.daily_loss_status(requested_seed=requested_seed),
                "results": [],
                "candidates": [],
            }

        candidate_payload = self.auto_candidates(requested_seed=requested_seed, force_recommend=force_recommend, market="US")
        self._append_runtime_log("info", "미국 단타 자동순환 시작", meta={
            "market": "US",
            "user_id": user_id,
            "requested_seed": round(self._safe_float(requested_seed, 0), 2),
            "candidate_count": len(candidate_payload.get("candidates", []) or []),
            "position_count": self._safe_int(candidate_payload.get("position_count", 0), 0),
            "remaining_seed_krw": round(self._safe_float(candidate_payload.get("remaining_seed_krw", 0), 0), 2),
        })

        effective_seed = self._safe_float(candidate_payload.get("effective_seed", 0), 0)
        remaining_seed_krw = self._safe_float(candidate_payload.get("remaining_seed_krw", effective_seed), effective_seed)
        tracked_position_count = self._safe_int(candidate_payload.get("position_count", 0), 0)
        excluded_by_price = candidate_payload.get("excluded_by_price", []) or []
        max_affordable = candidate_payload.get("max_affordable_per_share", 0)

        if effective_seed <= 0:
            return {
                "executed": False,
                "message": "미장 단타에 사용할 수 있는 여유 시드가 없습니다.",
                "budget": self.shared_budget_status(requested_seed=requested_seed, market="US"),
                "daily_loss": self.daily_loss_status(requested_seed=requested_seed),
                "results": [],
                "candidates": candidate_payload.get("candidates", []),
                "excluded_by_price": excluded_by_price,
            }

        results = []
        executed_count = 0
        candidate_rows = list(candidate_payload.get("candidates", []) or [])
        slot_seed_limit_krw = self._safe_float(candidate_payload.get("slot_seed_limit_krw", 0), 0)

        for item in candidate_rows:
            symbol = item.get("symbol", "")
            market = item.get("market", "US")
            strategy_id = item.get("strategy_id", "us_premarket")
            remaining_slots = max(0, self._auto_max_symbols(market="US") - tracked_position_count)
            is_new_entry = item.get("source") != "active_position"
            allocation_seed = 0.0
            min_required_seed = self._minimum_entry_seed(self._safe_float(item.get("last_price", 0), 0), market=market)

            if is_new_entry:
                if remaining_seed_krw <= 0:
                    results.append({
                        "symbol": symbol,
                        "market": market,
                        "name": item.get("name", ""),
                        "strategy_id": strategy_id,
                        "executed": False,
                        "message": "남은 시드가 없어 신규 진입을 보류했습니다.",
                        "signal": "HOLD",
                        "risk_status": "WARN",
                        "current_price": self._safe_float(item.get("last_price", 0), 0),
                        "allocated_seed": 0,
                        "remaining_seed_before": round(remaining_seed_krw, 2),
                        "remaining_seed_after": round(remaining_seed_krw, 2),
                    })
                    continue
                if remaining_slots <= 0:
                    results.append({
                        "symbol": symbol,
                        "market": market,
                        "name": item.get("name", ""),
                        "strategy_id": strategy_id,
                        "executed": False,
                        "message": "보유 종목 수 상한에 도달해 신규 진입을 보류했습니다.",
                        "signal": "HOLD",
                        "risk_status": "WARN",
                        "current_price": self._safe_float(item.get("last_price", 0), 0),
                        "allocated_seed": 0,
                        "remaining_seed_before": round(remaining_seed_krw, 2),
                        "remaining_seed_after": round(remaining_seed_krw, 2),
                    })
                    continue
                allocation_seed = max(
                    self._safe_float(item.get("entry_seed_krw", 0), 0),
                    min_required_seed,
                )
                if self._is_us_market(market):
                    allocation_seed = max(allocation_seed, min_required_seed)
                else:
                    if slot_seed_limit_krw > 0:
                        allocation_seed = min(allocation_seed, slot_seed_limit_krw)
                    allocation_seed = min(remaining_seed_krw, allocation_seed)
            else:
                current_price = max(
                    self._safe_float(item.get("last_price", 0), 0),
                    self._safe_float(item.get("current_price", 0), 0),
                    0,
                )
                current_position_value = self._safe_float(item.get("position_value_krw", 0), 0)
                target_position_seed = slot_seed_limit_krw if slot_seed_limit_krw > 0 else remaining_seed_krw
                addable_seed = max(0.0, target_position_seed - current_position_value)
                allocation_seed = max(current_price, min(remaining_seed_krw, addable_seed)) if addable_seed > 0 else 0.0
                if allocation_seed <= 0:
                    results.append({
                        "symbol": symbol,
                        "market": market,
                        "name": item.get("name", ""),
                        "strategy_id": strategy_id,
                        "executed": False,
                        "message": "종목당 시드 한도에 도달해 추가 매수를 보류했습니다.",
                        "signal": "HOLD",
                        "risk_status": "SAFE",
                        "current_price": current_price,
                        "allocated_seed": 0,
                        "remaining_seed_before": round(remaining_seed_krw, 2),
                        "remaining_seed_after": round(remaining_seed_krw, 2),
                    })
                    continue

            before_seed = remaining_seed_krw
            try:
                outcome = self.execute_live(symbol, market=market, seed=allocation_seed, name=item.get("name", ""), strategy_id=strategy_id)
                action = str(outcome.get("action", "") or outcome.get("status", {}).get("signal", {}).get("action", "HOLD"))
                order_value = self._safe_float(outcome.get("order_value", 0), 0)
                runtime_payload = outcome.get("status", {}).get("runtime", {}) or {}
                if outcome.get("executed"):
                    executed_count += 1
                    if action.startswith("BUY"):
                        tracked_position_count += 1
                        remaining_seed_krw = max(0.0, remaining_seed_krw - max(order_value, 0))
                    elif action.startswith("SELL"):
                        tracked_position_count = max(0, tracked_position_count - 1)
                        remaining_seed_krw = min(effective_seed, remaining_seed_krw + max(order_value, 0))
                results.append({
                    "symbol": symbol,
                    "market": market,
                    "name": item.get("name", ""),
                    "strategy_id": strategy_id,
                    "source": item.get("source", "leaderboard"),
                    "score": item.get("score", 0),
                    "executed": bool(outcome.get("executed", False)),
                    "message": outcome.get("message", ""),
                    "signal": outcome.get("status", {}).get("signal", {}).get("action", "HOLD"),
                    "risk_status": outcome.get("status", {}).get("runtime", {}).get("risk_status", "SAFE"),
                    "current_price": self._safe_float(outcome.get("status", {}).get("signal", {}).get("current_price", 0), 0),
                    "signal_reason": outcome.get("status", {}).get("signal", {}).get("reason", outcome.get("message", "")),
                    "runtime_issues": runtime_payload.get("issues", []),
                    "runtime_warnings": runtime_payload.get("warnings", []),
                    "order_value": round(order_value, 2),
                    "allocated_seed": round(allocation_seed, 2),
                    "remaining_seed_before": round(before_seed, 2),
                    "remaining_seed_after": round(remaining_seed_krw, 2),
                })
            except Exception as e:
                results.append({
                    "symbol": symbol,
                    "market": market,
                    "name": item.get("name", ""),
                    "strategy_id": strategy_id,
                    "executed": False,
                    "message": str(e),
                    "signal": "ERROR",
                    "risk_status": "HALT",
                    "current_price": self._safe_float(item.get("last_price", 0), 0),
                    "runtime_issues": [str(e)],
                    "runtime_warnings": [],
                    "order_value": 0,
                    "allocated_seed": round(allocation_seed, 2),
                    "remaining_seed_before": round(before_seed, 2),
                    "remaining_seed_after": round(remaining_seed_krw, 2),
                })

        daily_loss = self.daily_loss_status(requested_seed=effective_seed)
        message = f"미국 주식 자동 점검 완료. 후보 {len(candidate_rows)}개를 점검했습니다."
        if executed_count > 0:
            message = f"미국 주식 자동순환으로 {executed_count}건의 주문을 실행했습니다."
        elif daily_loss.get("halt_new_buys"):
            message = "일일 손실 제한에 도달해 미장 신규 단타 진입을 차단했습니다."

        return {
            "executed": executed_count > 0,
            "executed_count": executed_count,
            "message": message,
            "budget": self.shared_budget_status(requested_seed=requested_seed, market="US"),
            "daily_loss": self.daily_loss_status(requested_seed=requested_seed),
            "portfolio": self.portfolio_usage(market_filter="US"),
            "results": results,
            "candidates": candidate_payload.get("candidates", []),
            "excluded_by_price": excluded_by_price,
            "max_affordable_per_share": max_affordable,
            "max_symbols": candidate_payload.get("max_symbols", self._auto_max_symbols(market="US")),
        }

    def us_execute_exit_watch(self, requested_seed=0, market="US"):
        """미장 활성 포지션에 대해 자동청산 감시 실행 (신규 매수 없음)"""
        if self._hard_locked():
            return {"executed": False, "executed_count": 0, "watched_count": 0, "message": self._hard_lock_message(), "hard_locked": True, "results": []}
        with self._global_lock("engine_cycle"):
            positions = [p for p in self.active_positions() if self._is_us_market(p.get("market", "KS"))]
            results = []
            executed_count = 0
            watched_count = 0
            for item in positions:
                symbol = item.get("symbol", "")
                market = item.get("market", "US")
                strategy_id = item.get("strategy_id", "us_premarket")
                state = self._state_for(symbol, market=market, seed=max(self._safe_float(item.get("current_price", 0), 0) * self._safe_int(item.get("position_qty", 0), 0), 1), name=item.get("name", ""), strategy_id=strategy_id)
                has_watch = (
                    self._safe_int(state.get("position_qty", 0), 0) > 0 and
                    self._safe_float(state.get("avg_price", 0), 0) > 0
                )
                if not has_watch:
                    continue
                watched_count += 1
                outcome = self.execute_live(
                    symbol,
                    market=market,
                    seed=max(self._safe_float(item.get("current_price", 0), 0) * self._safe_int(item.get("position_qty", 0), 0), self._safe_float(requested_seed, 0), 1),
                    name=item.get("name", ""),
                    strategy_id=strategy_id,
                    force=False,
                    allow_buy=False,
                )
                if outcome.get("executed"):
                    executed_count += 1
                results.append({
                    "symbol": symbol,
                    "market": market,
                    "name": item.get("name", ""),
                    "strategy_id": strategy_id,
                    "executed": bool(outcome.get("executed", False)),
                    "message": outcome.get("message", ""),
                    "signal": outcome.get("status", {}).get("signal", {}).get("action", "HOLD"),
                    "current_price": self._safe_float(item.get("current_price", 0), 0),
                    "watch_active": True,
                })

            message = "미장 자동청산 감시 대상이 없습니다."
            if watched_count > 0:
                message = f"미장 자동청산 감시 {watched_count}건 점검 완료"
            if executed_count > 0:
                message = f"미장 자동청산 감시로 {executed_count}건 주문을 실행했습니다."
            self._append_runtime_log("info", message, meta={"watched_count": watched_count, "executed_count": executed_count})
            return {"executed": executed_count > 0, "executed_count": executed_count, "watched_count": watched_count, "message": message, "results": results}

    def _latest_snapshot(self, symbol, market="KS"):
        """
        최신 분봉 스냅샷 반환 (sys 모듈 기반 프로세스 레벨 캐시, TTL 12초)
        exec() 재실행/클래스 재생성에도 캐시 유지.
        """
        import sys as _sys
        _SNAP_KEY = "_trading_snapshot_cache_v2"
        _SNAP_TTL = 12.0
        cache_key = f"{symbol}.{market}"
        now = self._now()
        snapshot_cache = getattr(_sys, _SNAP_KEY, {})
        cached = snapshot_cache.get(cache_key)
        max_session_reuse_sec = 180.0

        def _apply_kis_quote(base_bar):
            bar = dict(base_bar or {})
            try:
                if self._is_us_market(market):
                    exchange = self._us_exchange(symbol)
                    quote = self.struct.kis_api.get_current_price(symbol, exchange=exchange)
                    source_label = "kis_overseas_quote"
                else:
                    quote = self.struct.kis_api.get_domestic_current_price(symbol)
                    source_label = "kis_domestic_quote"
            except Exception:
                return bar
            price = self._safe_float(quote.get("price", 0), 0)
            if price <= 0:
                return bar
            quote_open = self._safe_float(quote.get("open", 0), 0)
            quote_high = self._safe_float(quote.get("high", 0), 0)
            quote_low = self._safe_float(quote.get("low", 0), 0)
            bar["close"] = price
            bar["open"] = quote_open if quote_open > 0 else self._safe_float(bar.get("open", price), price)
            bar["high"] = quote_high if quote_high > 0 else price
            bar["low"] = quote_low if quote_low > 0 else price
            bar["timestamp"] = quote.get("timestamp", bar.get("timestamp", ""))
            bar["price_source"] = quote.get("source", source_label)
            return bar

        def _fallback_snapshot_from_state(reason=""):
            fallback_state = self._state_for(symbol, market=market, seed=0, name="", strategy_id="vrev")
            fallback_price = 0.0
            fallback_source = "cached_state"
            quote_open = 0.0
            quote_high = 0.0
            quote_low = 0.0
            quote_prev_close = 0.0
            try:
                if self._is_us_market(market):
                    exchange = self._us_exchange(symbol)
                    quote = self.struct.kis_api.get_current_price(symbol, exchange=exchange)
                    default_source = "kis_overseas_quote"
                else:
                    quote = self.struct.kis_api.get_domestic_current_price(symbol)
                    default_source = "kis_domestic_quote"
                fallback_price = self._safe_float(quote.get("price", 0), 0)
                if fallback_price > 0:
                    fallback_source = quote.get("source", default_source)
                quote_open = self._safe_float(quote.get("open", 0), 0)
                quote_high = self._safe_float(quote.get("high", 0), 0)
                quote_low = self._safe_float(quote.get("low", 0), 0)
                quote_prev_close = self._safe_float(quote.get("prev_close", 0), 0)
            except Exception:
                pass
            if fallback_price <= 0:
                fallback_price = self._safe_float(fallback_state.get("last_price", 0), 0)
            if fallback_price <= 0:
                fallback_price = self._safe_float(fallback_state.get("avg_price", 0), 0)
            anchor_price = max(
                quote_prev_close,
                quote_open,
                self._safe_float(fallback_state.get("anchor_price", 0), 0),
                self._safe_float(fallback_state.get("avg_price", 0), 0),
                fallback_price,
            )
            if fallback_price <= 0 or anchor_price <= 0:
                raise Exception(reason or "라이브 시그널에 사용할 가격 데이터가 없습니다.")
            now_kst = self._now()
            session_date = self._date_display(fallback_state.get("session_date", ""))
            if str(session_date or "").strip() == "":
                session_date = now_kst.strftime("%Y-%m-%d")
            gap_pct = ((fallback_price - anchor_price) / anchor_price * 100) if anchor_price > 0 else 0
            bar = {
                "timestamp": now_kst.strftime("%Y-%m-%d %H:%M:%S"),
                "date": session_date,
                "time": now_kst.strftime("%H:%M"),
                "open": quote_open if quote_open > 0 else anchor_price,
                "high": quote_high if quote_high > 0 else max(anchor_price, fallback_price),
                "low": quote_low if quote_low > 0 else min(anchor_price, fallback_price),
                "close": fallback_price,
                "volume": 0,
                "vwap": anchor_price,
                "open_price": quote_open if quote_open > 0 else anchor_price,
                "volume_above_ratio": 0.5,
                "volume_below_ratio": 0.5,
                "gap_from_open_pct": round(gap_pct, 4),
                "intraday_range_pct": round(abs(gap_pct), 4),
                "ma_fast": fallback_price,
                "ma_slow": fallback_price,
                "ma_trend": fallback_price,
                "rsi14": 50.0,
                "macd": 0.0,
                "macd_signal": 0.0,
                "macd_hist": 0.0,
                "volume_avg_5": 0.0,
                "volume_surge_ratio": 1.0,
                "breakout_high_20": fallback_price,
                "breakout_low_20": fallback_price,
                "trend_strength_pct": 0.0,
                "vwap_gap_pct": round(gap_pct, 4),
                "bb_upper": fallback_price,
                "bb_lower": fallback_price,
                "bb_mid": fallback_price,
                "price_source": fallback_source if fallback_source == "kis_domestic_quote" else f"{fallback_source}_fallback",
                "intraday_unavailable": True,
            }
            session = {
                "date": session_date,
                "prev_close": quote_prev_close if quote_prev_close > 0 else anchor_price,
                "bars": [bar],
                "fallback": True,
                "fallback_reason": reason,
            }
            return session, bar

        if cached:
            age = (now - cached["ts"]).total_seconds()
            if age < _SNAP_TTL:
                return cached["session"], dict(cached["bar"])  # 캐시 히트 → KIS API 스킵
            if age < max_session_reuse_sec:
                try:
                    bar = _apply_kis_quote(cached.get("bar", {}))
                    snapshot_cache[cache_key] = {"session": cached["session"], "bar": bar, "ts": now}
                    setattr(_sys, _SNAP_KEY, snapshot_cache)
                    return cached["session"], bar
                except Exception:
                    return cached["session"], dict(cached["bar"])
        try:
            sessions = self.strategy._prepare_dataset(symbol, market=market, period="1d", interval="1m")
            if len(sessions) == 0:
                raise Exception("라이브 시그널에 사용할 분봉 데이터가 없습니다.")
            session = sessions[-1]
            bars = session.get("bars", [])
            if len(bars) == 0:
                raise Exception("라이브 시그널에 사용할 장중 바가 없습니다.")
            bar = dict(bars[-1])
            try:
                bar = _apply_kis_quote(bar)
            except Exception:
                bar["price_source"] = "yfinance_intraday"
        except Exception as e:
            self._append_runtime_log("warning", f"{symbol} 라이브 분봉 fallback: {str(e)}", symbol=symbol, dedup_sec=600)
            session, bar = _fallback_snapshot_from_state(reason=str(e))
        # sys 모듈에 캐시 저장 (exec() 재실행 후에도 유지)
        if not isinstance(snapshot_cache, dict):
            snapshot_cache = {}
        snapshot_cache[cache_key] = {"session": session, "bar": bar, "ts": now}
        setattr(_sys, _SNAP_KEY, snapshot_cache)
        return session, bar

    def _recent_error_messages(self, state):
        items = state.get("recent_errors", []) or []
        rows = []
        for item in items[-10:]:
            rows.append(self._normalize_display_log_item(item))
        return rows[-5:]

    def _push_state_error(self, state, message):
        items = list(state.get("recent_errors", []) or [])[-4:]
        items.append({
            "timestamp": self._timestamp(),
            "message": message,
        })
        state["recent_errors"] = items
        state["halt_reason"] = message

    def _guardrails(self, symbol, market, seed, state, signal, session, bar, profile):
        issues = []
        warnings = []
        action = signal.get("action", "HOLD")
        strategy_id = str(signal.get("strategy_id", "vrev") or "vrev")
        is_buy = str(action).startswith("BUY")
        is_sell = str(action).startswith("SELL")
        connection = self.check_kis_connection()
        if connection.get("connected") is False:
            issues.append("KIS API 연결이 준비되지 않았습니다.")
        price_source = signal.get("price_source", "")
        if is_buy and connection.get("is_real") and price_source not in ("kis_domestic_quote", "kis_overseas_quote") and not self._is_us_market(market):
            issues.append("실전 모드에서는 KIS 실시간 시세가 아니면 신규 주문을 차단합니다.")
        elif price_source not in ("kis_domestic_quote", "kis_overseas_quote"):
            if is_sell:
                warnings.append("청산 신호는 지연 시세에서 계산되었지만 주문은 시장가로 즉시 전송합니다.")
            else:
                warnings.append("지연 시세 기반입니다.")
        if bool(bar.get("intraday_unavailable", False)):
            if is_buy and strategy_id != "vrev":
                issues.append("장중 분봉 데이터를 확보하지 못해 신규 주문을 차단합니다.")
            elif is_buy and strategy_id == "vrev" and price_source == "kis_domestic_quote":
                pass
            else:
                warnings.append("장중 분봉이 없어 KIS 현재가/캐시 기준으로만 청산 판단 중입니다.")
        day_range_pct = self._safe_float(bar.get("intraday_range_pct", 0), 0)
        if day_range_pct >= self._safe_float(profile.get("max_live_day_range_pct", 8.5), 8.5):
            if is_buy:
                issues.append(f"장중 변동폭 {day_range_pct:.2f}%로 급변장입니다.")
            else:
                warnings.append(f"장중 변동폭 {day_range_pct:.2f}% 급변장이라 청산만 우선 허용합니다.")
        gap_open = abs(self._safe_float(bar.get("gap_from_open_pct", 0), 0))
        if gap_open >= self._safe_float(profile.get("max_live_gap_pct", 5.5), 5.5):
            if is_buy:
                issues.append(f"시가 대비 괴리율 {gap_open:.2f}%로 과열/급락 상태입니다.")
            else:
                warnings.append(f"시가 대비 괴리율 {gap_open:.2f}% 급변 상태지만 청산은 허용합니다.")
        orders = state.get("orders", []) or []
        cooldown = self._safe_int(profile.get("max_order_cooldown_sec", 20), 20)
        if len(orders) > 0:
            latest = orders[-1]
            try:
                last_ts = datetime.datetime.strptime(latest.get("timestamp", ""), "%Y-%m-%d %H:%M:%S")
                diff = (self._now() - last_ts).total_seconds()
                if diff < cooldown:
                    if is_buy:
                        issues.append(f"최근 주문 후 {cooldown}초 쿨다운이 지나지 않았습니다.")
                    elif is_sell:
                        warnings.append(f"최근 주문 후 {cooldown}초 쿨다운 중이지만 청산은 우선 허용합니다.")
            except Exception:
                pass
        order_value = self._safe_int(signal.get("order_qty", 0), 0) * self._safe_float(signal.get("current_price", 0), 0)
        configured_budget = float(seed) * float(profile.get("budget_ratio", 1.0))
        active_budget = max(configured_budget, float(seed) * self._buy_buffer_ratio())
        if is_buy and order_value > active_budget * 1.02:
            issues.append(f"주문 금액이 현재 배정 시드 ₩{round(active_budget):,}를 초과합니다.")
        portfolio = self.portfolio_usage()
        committed_seed = self._safe_float(portfolio.get("active_entry_seed_krw", portfolio.get("active_cost_krw", 0)), 0)
        budget_snapshot = self.shared_budget_status(requested_seed=max(float(seed), committed_seed + order_value), use_cache_only=True)
        portfolio_limit = max(
            self._safe_float(budget_snapshot.get("capacity_daytrade_seed_krw", 0), 0),
            self._safe_float(budget_snapshot.get("total_seed_krw", 0), 0),
            float(seed),
        )
        daily_loss = self.daily_loss_status(requested_seed=seed)
        if is_buy and daily_loss.get("halt_new_buys"):
            issues.append(f"일일 손실 제한 도달: {daily_loss.get('total_pnl', 0):,.0f}원 / 제한 {daily_loss.get('daily_loss_limit_krw', 0):,.0f}원")
        elif is_buy and daily_loss.get("soft_limit_reached"):
            warnings.append(f"일일 손실 제한 구간({daily_loss.get('total_pnl', 0):,.0f}원)이지만 신규 진입은 계속 허용합니다.")
        elif daily_loss.get("halt_new_buys"):
            warnings.append("일일 손실 제한 도달 상태라 신규 진입만 차단하고 청산은 허용합니다.")
        risk_status = "HALT" if len(issues) > 0 else ("WARN" if len(warnings) > 0 else "SAFE")
        return {
            "risk_status": risk_status,
            "halted": len(issues) > 0,
            "issues": issues,
            "warnings": warnings,
            "price_source": price_source,
            "order_value": round(order_value, 2),
            "active_budget": round(active_budget, 2),
            "portfolio": portfolio,
            "daily_loss": daily_loss,
            "mode": "live" if connection.get("is_real") else "paper",
            "connection": connection,
            "portfolio_limit": round(portfolio_limit, 2),
        }

    def runtime_status(self, symbol, market="KS", seed=1000000, name="", strategy_id="vrev"):
        payload = self._signal_from_state(symbol, market=market, seed=seed, name=name, strategy_id=strategy_id)
        state = payload.get("state", {})
        signal = payload.get("signal", {})
        guardrails = self._guardrails(symbol, market, seed, state, signal, payload.get("session", {}), payload.get("bar", {}), payload.get("profile", {}))
        return {
            "mode": guardrails.get("mode", "paper"),
            "risk_status": guardrails.get("risk_status", "SAFE"),
            "halt_reason": state.get("halt_reason", "") or (guardrails.get("issues", [""])[0] if guardrails.get("issues") else ""),
            "issues": guardrails.get("issues", []),
            "warnings": guardrails.get("warnings", []),
            "recent_errors": self._recent_error_messages(state),
            "recent_logs": self._load_runtime_logs()[-30:],
            "connection": guardrails.get("connection", {}),
            "portfolio": guardrails.get("portfolio", {}),
            "daily_loss": guardrails.get("daily_loss", {}),
            "exit_watch": self._exit_watch_payload(state, signal),
        }

    def active_positions(self, sync_broker=True):
        if sync_broker:
            self._sync_broker_positions()
        state_map = self._load_state_map()
        rows_map = {}
        default_strategy = self.strategy.defaults().get("strategy", "vrev")

        for key in state_map:
            state = state_map.get(key, {}) or {}
            qty = self._safe_int(state.get("position_qty", 0), 0)
            if qty <= 0:
                continue
            symbol = state.get("symbol", "")
            market = state.get("market", "KS")
            avg_price = self._safe_float(state.get("avg_price", 0), 0)
            current_price = 0.0
            try:
                _session, bar = self._latest_snapshot(symbol, market=market)
                current_price = self._safe_float(bar.get("close", 0), 0)
            except Exception:
                current_price = avg_price
            pnl = ((current_price - avg_price) * qty) if avg_price > 0 else 0.0
            pnl_pct = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
            rows_map[self._state_key(symbol, market)] = {
                "symbol": symbol,
                "market": market,
                "name": state.get("name", self.strategy.symbol_name(symbol)),
                "strategy_id": state.get("strategy_id", default_strategy),
                "strategy_name": self.strategy.strategy_spec(state.get("strategy_id", default_strategy)).get("name", state.get("strategy_id", default_strategy)),
                "position_qty": qty,
                "avg_price": round(avg_price, 4),
                "current_price": round(current_price, 4),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "updated_at": state.get("updated_at", ""),
                "source": "state",
                "auto_managed": not bool(state.get("broker_unmanaged_position", False)),
                "broker_unmanaged_position": bool(state.get("broker_unmanaged_position", False)),
                "broker_unmanaged_qty": self._safe_int(state.get("broker_unmanaged_qty", 0), 0),
            }

        broker_rows = []
        try:
            domestic_rows = self.struct.kis_api.get_domestic_balance().get("holdings", []) or []
            for item in domestic_rows:
                row = dict(item or {})
                row["market"] = str(row.get("market", "KS") or "KS").upper()
                broker_rows.append(row)
        except Exception:
            pass

        try:
            overseas_rows = self.struct.kis_api.get_balance().get("holdings", []) or []
            for item in overseas_rows:
                row = dict(item or {})
                row["market"] = "US"
                broker_rows.append(row)
        except Exception:
            pass

        for item in broker_rows:
            symbol = str(item.get("symbol", "") or "").strip()
            qty = self._safe_int(item.get("qty", 0), 0)
            if symbol == "" or qty <= 0:
                continue
            market = str(item.get("market", "KS") or "KS").upper()
            key = self._state_key(symbol, market)
            state = state_map.get(key, {}) or {}
            avg_price = self._safe_float(item.get("avg_price", state.get("avg_price", 0)), 0)
            current_price = self._safe_float(item.get("current_price", 0), 0)
            eval_amount = self._safe_float(item.get("eval_amount", 0), 0)
            purchase_amount = self._safe_float(item.get("purchase_amount", 0), 0)
            profit_loss = self._safe_float(item.get("profit_loss", 0), 0)
            if qty > 0 and eval_amount > 0 and (current_price <= 0 or abs((current_price * qty) - eval_amount) > max(1.0, eval_amount * 0.2)):
                current_price = eval_amount / qty
            if qty > 0 and purchase_amount > 0 and (avg_price <= 0 or abs((avg_price * qty) - purchase_amount) > max(1.0, purchase_amount * 0.2)):
                avg_price = purchase_amount / qty
            elif qty > 0 and eval_amount > 0 and abs(profit_loss) > 1e-9:
                inferred_cost = max(0.0, eval_amount - profit_loss)
                if inferred_cost > 0 and (avg_price <= 0 or abs((avg_price * qty) - inferred_cost) > max(1.0, inferred_cost * 0.2)):
                    avg_price = inferred_cost / qty
            if current_price <= 0:
                current_price = avg_price
            if eval_amount <= 0 and current_price > 0:
                eval_amount = current_price * qty
            cost_amount = purchase_amount if purchase_amount > 0 else (avg_price * qty if avg_price > 0 else 0.0)
            if cost_amount <= 0 and eval_amount > 0 and abs(profit_loss) > 1e-9:
                cost_amount = max(0.0, eval_amount - profit_loss)
            pnl = profit_loss if abs(profit_loss) > 1e-9 else (((current_price - avg_price) * qty) if avg_price > 0 else 0.0)
            pnl_pct = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
            rows_map[key] = {
                "symbol": symbol,
                "market": market,
                "name": item.get("name", state.get("name", "") or self.strategy.symbol_name(symbol)),
                "strategy_id": state.get("strategy_id", default_strategy),
                "strategy_name": self.strategy.strategy_spec(state.get("strategy_id", default_strategy)).get("name", state.get("strategy_id", default_strategy)),
                "first_buy_date": state.get("first_buy_date", ""),
                "opened_at": self._position_opened_at(state),
                "position_qty": qty,
                "avg_price": round(avg_price, 4),
                "current_price": round(current_price, 4),
                "eval_amount": round(eval_amount, 2),
                "cost_amount": round(cost_amount, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "updated_at": state.get("updated_at", "") or self._timestamp(),
                "source": "broker",
                "auto_managed": not bool(state.get("broker_unmanaged_position", False)),
                "broker_unmanaged_position": bool(state.get("broker_unmanaged_position", False)),
                "broker_unmanaged_qty": self._safe_int(state.get("broker_unmanaged_qty", 0), 0),
            }

        rows = list(rows_map.values())
        rows.sort(key=self._active_position_sort_key)
        return rows

    def active_positions_from_state(self, market_filter=None):
        """KIS API 호출 없이 state DB만 읽어 포지션 반환 (고속 부트스트랩용).
        market_filter: "US" 등 특정 마켓만 반환 (None이면 전체)
        """
        state_map = self._load_state_map()
        default_strategy = self.strategy.defaults().get("strategy", "vrev")
        rows = []
        for key in state_map:
            state = state_map.get(key, {}) or {}
            qty = self._safe_int(state.get("position_qty", 0), 0)
            if qty <= 0:
                continue
            symbol = state.get("symbol", "")
            market = state.get("market", "KS")
            if market_filter is not None and str(market).upper() != str(market_filter).upper():
                continue
            avg_price = self._safe_float(state.get("avg_price", 0), 0)
            current_price = self._safe_float(state.get("last_price", 0), 0)
            if current_price <= 0:
                current_price = avg_price
            pnl = ((current_price - avg_price) * qty) if avg_price > 0 else 0.0
            pnl_pct = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
            rows.append({
                "symbol": symbol,
                "market": market,
                "name": state.get("name", self.strategy.symbol_name(symbol)),
                "strategy_id": state.get("strategy_id", default_strategy),
                "strategy_name": self.strategy.strategy_spec(state.get("strategy_id", default_strategy)).get("name", state.get("strategy_id", default_strategy)),
                "first_buy_date": state.get("first_buy_date", ""),
                "opened_at": self._position_opened_at(state),
                "position_qty": qty,
                "avg_price": round(avg_price, 4),
                "current_price": round(current_price, 4),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "updated_at": state.get("updated_at", ""),
                "source": "state_only",
            })
        rows.sort(key=self._active_position_sort_key)
        return rows

    def update_trade_settings(self, symbol, market="KS", seed=1000000, name="", strategy_id="vrev", manual_sell_enabled=None, manual_sell_target_price=None, stop_loss_enabled=None, stop_loss_price=None):
        state = self._state_for(symbol, market=market, seed=seed, name=name, strategy_id=strategy_id)
        if manual_sell_enabled is not None:
            state["manual_sell_enabled"] = bool(manual_sell_enabled)
        if manual_sell_target_price is not None:
            value = self._normalize_trigger_price(manual_sell_target_price, market=market)
            state["manual_sell_target_price"] = value if value > 0 else 0.0
        if stop_loss_enabled is not None:
            state["stop_loss_enabled"] = bool(stop_loss_enabled)
        if stop_loss_price is not None:
            value = self._normalize_trigger_price(stop_loss_price, market=market)
            state["stop_loss_price"] = value if value > 0 else 0.0
        self._mark_exit_watch(state, reason="자동청산 감시 설정을 갱신했습니다.")
        state["updated_at"] = self._timestamp()
        self._store_state(state)
        return self.signal_status(symbol, market=market, seed=seed, name=name, strategy_id=strategy_id)

    def _breakout_preflight_check(self, symbol, market, bar, profile):
        """volume_breakout 전략 진입 직전 위험 점검 (preflight guard)"""
        issues = []
        current_price = self._safe_float(bar.get("close", 0), 0)
        vwap = self._safe_float(bar.get("vwap", 0), 0)
        breakout_high = self._safe_float(bar.get("breakout_high_20", 0), 0)

        # 1. 돌파폭 검사
        min_breakout_range_pct = self._safe_float(profile.get("min_breakout_range_pct", 0.3), 0.3)
        if breakout_high > 0 and current_price > 0:
            breakout_range_pct = (current_price / breakout_high - 1) * 100
            if breakout_range_pct < min_breakout_range_pct:
                issues.append(f"돌파폭 협소 ({breakout_range_pct:.2f}% < 최소 {min_breakout_range_pct}%)")

        # 2. VWAP 괴리율 검사
        max_vwap_gap_pct = self._safe_float(profile.get("max_vwap_gap_pct_preflight", 1.5), 1.5)
        if vwap > 0 and current_price > 0:
            vwap_gap_pct = (current_price / vwap - 1) * 100
            if vwap_gap_pct > max_vwap_gap_pct:
                issues.append(f"VWAP 과괴리 ({vwap_gap_pct:.2f}% > 최대 {max_vwap_gap_pct}%)")

        # 3. 호가 스프레드 및 슬리피지 위험 점검 (KIS API 필요)
        try:
            hoga = self.struct.kis_api.search_realtime_hoga(symbol, market)
            if hoga:
                ask1 = self._safe_float(hoga.get("askp1", 0), 0)
                bid1 = self._safe_float(hoga.get("bidp1", 0), 0)
                if ask1 > 0 and bid1 > 0:
                    spread_pct = (ask1 / bid1 - 1) * 100
                    max_spread_pct = self._safe_float(profile.get("max_hoga_spread_pct", 0.3), 0.3)
                    if spread_pct > max_spread_pct:
                        issues.append(f"호가 스프레드 과다 ({spread_pct:.2f}% > 최대 {max_spread_pct}%)")
        except Exception as e:
            self._append_runtime_log("warning", f"{symbol} 호가 조회 실패 (preflight): {e}", symbol=symbol, dedup_sec=300)

        return issues

    def _signal_from_state(self, symbol, market="KS", seed=1000000, name="", strategy_id="vrev", sync_broker=True):
        strategy_id = self.strategy._normalize_strategy(strategy_id)
        profile = self._profile_for(symbol, strategy_id=strategy_id, market=market)
        if sync_broker:
            self._sync_broker_positions()
        state = self._state_for(symbol, market=market, seed=seed, name=name, strategy_id=strategy_id)
        session, bar = self._latest_snapshot(symbol, market=market)

        # 실시간 집계 캔들 우선 사용
        agg_candle = self._aggregate_ticks_to_candle(symbol, market)
        if agg_candle and agg_candle.get("close", 0) > 0:
            bar.update(agg_candle)
            bar["price_source"] = "agg_candle"

        session_date = session.get("date", "")

        if state.get("session_date") != session_date:
            position_qty = self._safe_int(state.get("position_qty", 0), 0)
            avg_price = self._safe_float(state.get("avg_price", 0), 0)
            realized_profit = self._safe_float(state.get("realized_profit", 0), 0)
            first_buy_date = state.get("first_buy_date", "")
            buy1_used = bool(state.get("buy1_used", False))
            buy2_used = bool(state.get("buy2_used", False))
            orders = list(state.get("orders", []) or [])
            halt_reason = state.get("halt_reason", "")
            last_signal = state.get("last_signal", "HOLD")
            updated_at = state.get("updated_at", "")
            last_exit_watch_at = state.get("last_exit_watch_at", "")
            last_exit_action = state.get("last_exit_action", "")
            last_exit_reason = state.get("last_exit_reason", "")
            last_exit_order_no = state.get("last_exit_order_no", "")
            last_manual_exit_at = state.get("last_manual_exit_at", "")
            last_exit_price = self._safe_float(state.get("last_exit_price", 0), 0)
            manual_sell_enabled = bool(state.get("manual_sell_enabled", False))
            manual_sell_target_price = self._safe_float(state.get("manual_sell_target_price", 0), 0)
            stop_loss_enabled = bool(state.get("stop_loss_enabled", False))
            stop_loss_price = self._safe_float(state.get("stop_loss_price", 0), 0)
            recent_errors = list(state.get("recent_errors", []) or [])
            carried_overnight = position_qty > 0
            state.update(self._default_state(symbol, market, seed, name=name or state.get("name", ""), strategy_id=strategy_id))
            state["position_qty"] = position_qty
            state["avg_price"] = avg_price
            state["realized_profit"] = realized_profit
            state["first_buy_date"] = first_buy_date
            state["buy1_used"] = buy1_used
            state["buy2_used"] = buy2_used
            state["orders"] = orders
            state["halt_reason"] = halt_reason
            state["last_signal"] = last_signal
            state["updated_at"] = updated_at
            state["last_exit_watch_at"] = last_exit_watch_at
            state["last_exit_action"] = last_exit_action
            state["last_exit_reason"] = last_exit_reason
            state["last_exit_order_no"] = last_exit_order_no
            state["last_manual_exit_at"] = last_manual_exit_at
            state["last_exit_price"] = last_exit_price
            state["manual_sell_enabled"] = manual_sell_enabled
            state["manual_sell_target_price"] = manual_sell_target_price
            state["stop_loss_enabled"] = stop_loss_enabled
            state["stop_loss_price"] = stop_loss_price
            state["recent_errors"] = recent_errors
            state["carried_overnight"] = carried_overnight
            if carried_overnight:
                state["buy1_used"] = True
                state["buy2_used"] = True
            state["session_date"] = session_date

        current_price = self._safe_float(bar.get("close", 0))
        prev_close = self._safe_float(session.get("prev_close", 0), 0)
        session_open = self._safe_float(bar.get("open", 0), 0)
        vwap_price = self._safe_float(bar.get("vwap", 0), 0)
        anchor_candidates = [price for price in [prev_close, session_open, vwap_price] if price > 0]
        anchor = max(anchor_candidates) if len(anchor_candidates) > 0 else current_price
        budget_context = self._market_buy_budget(seed, current_price, market=market)
        budget_total = self._safe_float(budget_context.get("budget_total", seed), 0)
        buy_budget = self._safe_float(budget_context.get("buy_budget", seed), 0)
        buy1_trigger_pct = self._safe_float(profile.get("buy_trigger_1_pct", -0.1), -0.1)
        buy2_trigger_pct = self._safe_float(profile.get("buy_trigger_2_pct", -0.8), -0.8)
        if anchor > 0 and current_price >= anchor * 1.01:
            buy1_trigger_pct = max(buy1_trigger_pct, -0.05)
            buy2_trigger_pct = max(buy2_trigger_pct, -0.4)
        buy1_trigger = anchor * (1 + buy1_trigger_pct / 100)
        buy2_trigger = anchor * (1 + buy2_trigger_pct / 100)
        avg_price = self._safe_float(state.get("avg_price", 0), 0)
        position_qty = int(state.get("position_qty", 0) or 0)
        manual_sell_enabled = bool(state.get("manual_sell_enabled", False))
        manual_sell_target_price = self._safe_float(state.get("manual_sell_target_price", 0), 0)
        stop_loss_enabled = bool(state.get("stop_loss_enabled", False))
        stop_loss_price = self._safe_float(state.get("stop_loss_price", 0), 0)
        reentry_cooldown = self._reentry_cooldown_status(state, profile, market=market)
        profit_reentry_guard_buy1 = self._profit_reentry_guard(state, profile, current_price=current_price, trigger_price=buy1_trigger)
        profit_reentry_guard_buy2 = self._profit_reentry_guard(state, profile, current_price=current_price, trigger_price=buy2_trigger)

        signal = {
            "action": "HOLD",
            "reason": "현재 실행할 신호가 없습니다.",
            "order_qty": 0,
            "current_price": round(current_price, 4),
            "anchor_price": round(anchor, 4),
            "anchor_prev_close": round(prev_close, 4),
            "anchor_open": round(session_open, 4),
            "anchor_vwap": round(vwap_price, 4),
            "buy1_trigger_pct": round(buy1_trigger_pct, 4),
            "buy2_trigger_pct": round(buy2_trigger_pct, 4),
            "buy1_trigger": round(buy1_trigger, 4),
            "buy2_trigger": round(buy2_trigger, 4),
            "avg_price": round(avg_price, 4),
            "position_qty": position_qty,
            "manual_sell_enabled": manual_sell_enabled,
            "manual_sell_target_price": round(manual_sell_target_price, 4),
            "stop_loss_enabled": stop_loss_enabled,
            "stop_loss_price": round(stop_loss_price, 4),
            "last_exit_action": reentry_cooldown.get("action", ""),
            "reentry_cooldown_active": bool(reentry_cooldown.get("active", False)),
            "reentry_cooldown_remaining_sec": self._safe_int(reentry_cooldown.get("remaining_sec", 0), 0),
            "profit_reentry_guard_active": bool(profit_reentry_guard_buy1.get("active", False) or profit_reentry_guard_buy2.get("active", False)),
            "profit_reentry_guard_price": round(self._safe_float(profit_reentry_guard_buy1.get("required_price", 0), 0), 4),
            "last_exit_price": round(self._safe_float(state.get("last_exit_price", 0), 0), 4),
            "price_source": bar.get("price_source", "yfinance_intraday"),
            "session_date": session_date,
            "strategy_id": strategy_id,
            "strategy_name": self.strategy.strategy_spec(strategy_id).get("name", strategy_id),
            "requested_seed_krw": round(self._safe_float(budget_context.get("requested_seed_krw", seed), 0), 2),
            "buy_budget": round(self._safe_float(budget_context.get("buy_budget", seed), 0), 4),
            "budget_total": round(self._safe_float(budget_context.get("budget_total", seed), 0), 4),
            "budget_currency": budget_context.get("budget_currency", "KRW"),
            "price_currency": budget_context.get("price_currency", "KRW"),
            "usd_krw": round(self._safe_float(budget_context.get("usd_krw", 0), 0), 4),
        }

        carried_overnight = bool(state.get("carried_overnight", False))
        minutes_since_open = self._minutes_since_market_open(market=market)

        sell_priority_hit = False
        if position_qty > 0 and avg_price > 0:
            _stop_loss_pct_val = self._safe_float(profile.get("stop_loss_pct", 1.5), 1.5)
            _auto_stop_price = round(avg_price * (1 - _stop_loss_pct_val / 100)) if _stop_loss_pct_val > 0 else 0
            _jackpot_pct_val = float(profile.get("jackpot_take_profit_pct", 2.0))
            _jackpot = avg_price * (1 + _jackpot_pct_val / 100)
            _jackpot_soft_exit_guard = _jackpot * self._safe_float(profile.get("jackpot_soft_exit_guard_ratio", 0.995), 0.995)
            _recent_target = anchor * (1 + float(profile.get("recent_lot_take_profit_pct", 0.6)) / 100)
            _rescue_target = avg_price * (1 + float(profile.get("rescue_take_profit_pct", 0.5)) / 100)
            _bb_upper_live = self._safe_float(bar.get("bb_upper", 0), 0)
            _rsi_live = self._safe_float(bar.get("rsi14", 50), 50)
            _rsi_exit_overbought = self._safe_float(profile.get("rsi_exit_overbought", 75), 75)
            sell_priority_hit = (
                (stop_loss_enabled and stop_loss_price > 0 and current_price <= stop_loss_price)
                or (manual_sell_enabled and manual_sell_target_price > 0 and current_price >= manual_sell_target_price)
                or (_auto_stop_price > 0 and current_price <= _auto_stop_price)
                or (strategy_id == "vrev" and current_price >= _jackpot)
                or (strategy_id == "vrev" and current_price >= _jackpot_soft_exit_guard)
                or (strategy_id == "vrev" and _bb_upper_live > 0 and current_price >= _bb_upper_live and current_price >= avg_price)
                or (strategy_id == "vrev" and _rsi_live >= _rsi_exit_overbought and current_price >= avg_price)
                or (strategy_id == "vrev" and current_price >= _recent_target)
                or (strategy_id == "vrev" and state.get("buy2_used") and current_price >= _rescue_target)
            )

        if strategy_id == "vrev" and position_qty == 0 and state.get("buy1_used") == False and current_price <= buy1_trigger and reentry_cooldown.get("active") is False and profit_reentry_guard_buy1.get("active") is False:
            vrev_preflight_issues = self._vrev_preflight_check(symbol, market, bar, profile)
            if len(vrev_preflight_issues) > 0:
                signal.update({
                    "action": "HOLD",
                    "reason": f"vrev 진입 보류: {vrev_preflight_issues[0]}",
                    "order_qty": 0,
                    "preflight_issues": vrev_preflight_issues,
                })
            else:
                signal.update({
                    "action": "BUY1",
                    "reason": "1차 눌림 구간 진입 신호",
                    "order_qty": self._buy_qty(buy_budget, current_price),
                })
        elif strategy_id == "vrev" and position_qty > 0 and carried_overnight is False and state.get("buy1_used") == True and state.get("buy2_used") == False and current_price <= buy2_trigger and sell_priority_hit is False and reentry_cooldown.get("active") is False and profit_reentry_guard_buy2.get("active") is False:
            vrev_preflight_issues = self._vrev_preflight_check(symbol, market, bar, profile)
            if len(vrev_preflight_issues) > 0:
                signal.update({
                    "action": "HOLD",
                    "reason": f"vrev 진입 보류: {vrev_preflight_issues[0]}",
                    "order_qty": 0,
                    "preflight_issues": vrev_preflight_issues,
                })
            else:
                signal.update({
                    "action": "BUY2",
                    "reason": "2차 깊은 눌림 구간 진입 신호",
                    "order_qty": self._buy_qty(buy_budget, current_price),
                })
        elif strategy_id == "volume_breakout" and position_qty == 0:
            # volume_breakout 메타데이터 수집
            breakout_meta = {
                "breakout_high_20": self._safe_float(bar.get("breakout_high_20", 0), 0),
                "breakout_low_20": self._safe_float(bar.get("breakout_low_20", 0), 0),
                "volume_surge_ratio": self._safe_float(bar.get("volume_surge_ratio", 0), 0),
                "vwap_gap_pct": self._safe_float(bar.get("vwap_gap_pct", 0), 0),
                "preflight_issues": [],
            }

            if self._safe_float(bar.get("volume_surge_ratio", 0), 0) >= self._safe_float(profile.get("breakout_volume_ratio", 1.2), 1.2) and current_price >= self._safe_float(bar.get("breakout_high_20", 0), 0) * 0.998 and current_price >= self._safe_float(bar.get("vwap", 0), 0) * 0.995:
                preflight_issues = self._breakout_preflight_check(symbol, market, bar, profile)
                breakout_meta["preflight_issues"] = preflight_issues

                if preflight_issues:
                    signal.update({
                        "action": "HOLD",
                        "reason": f"진입 가드 실패: {', '.join(preflight_issues)}",
                        "breakout_meta": breakout_meta,
                    })
                else:
                    shadow_mode = profile.get("shadow_mode", True)
                    if shadow_mode:
                        order_qty = self._buy_qty(buy_budget, current_price)
                        breakout_meta["mock_trade"] = {
                            "price": current_price,
                            "qty": order_qty,
                            "budget": buy_budget
                        }
                        signal.update({
                            "action": "HOLD",
                            "reason": "shadow mode",
                            "breakout_meta": breakout_meta,
                        })
                    else:
                        signal.update({
                            "action": "BUY",
                            "reason": "거래량 돌파 신호",
                            "order_qty": self._buy_qty(buy_budget, current_price),
                            "breakout_meta": breakout_meta,
                        })
            signal["breakout_meta"] = breakout_meta

        # ── US 프리마켓 갭업 하따 전략 ──────────────────────────────────────
        elif strategy_id == "us_premarket" and position_qty == 0:
            premarket_gap_min = self._safe_float(profile.get("premarket_gap_min_pct", 5.0), 5.0)
            entry_drawdown_min = self._safe_float(profile.get("entry_drawdown_min_pct", 3.0), 3.0)
            entry_drawdown_max = self._safe_float(profile.get("entry_drawdown_max_pct", 10.0), 10.0)
            min_volume_usd = self._safe_float(profile.get("min_volume_usd", 2_000_000), 2_000_000)
            # 갭 = 반드시 전일 종가 대비 계산 (session_open/vwap 혼입 금지)
            gap_anchor = prev_close if prev_close > 0 else current_price
            gap_pct = (current_price - gap_anchor) / gap_anchor * 100 if gap_anchor > 0 else 0
            intraday_high = self._safe_float(bar.get("high", current_price), current_price)
            drawdown_from_high_pct = (intraday_high - current_price) / intraday_high * 100 if intraday_high > 0 else 0
            # 대략적인 거래대금 판단: close * volume (USD)
            estimated_volume_usd = self._safe_float(bar.get("close", 0), 0) * self._safe_int(bar.get("volume", 0), 0)
            us_meta = {
                "gap_pct": round(gap_pct, 4),
                "drawdown_from_high_pct": round(drawdown_from_high_pct, 4),
                "intraday_high": round(intraday_high, 4),
                "estimated_volume_usd": round(estimated_volume_usd, 2),
                "premarket_gap_min": premarket_gap_min,
                "entry_drawdown_min": entry_drawdown_min,
                "entry_drawdown_max": entry_drawdown_max,
            }
            if gap_pct < premarket_gap_min:
                signal.update({
                    "action": "HOLD",
                    "reason": f"프리마켓 갭 {gap_pct:.2f}% < 최소 {premarket_gap_min:.1f}%",
                    "us_meta": us_meta,
                })
            elif drawdown_from_high_pct < entry_drawdown_min:
                signal.update({
                    "action": "HOLD",
                    "reason": f"되밀림 {drawdown_from_high_pct:.2f}% < 최소 {entry_drawdown_min:.1f}%",
                    "us_meta": us_meta,
                })
            elif drawdown_from_high_pct > entry_drawdown_max:
                signal.update({
                    "action": "HOLD",
                    "reason": f"되밀림 과다 {drawdown_from_high_pct:.2f}% > 최대 {entry_drawdown_max:.1f}%",
                    "us_meta": us_meta,
                })
            elif estimated_volume_usd > 0 and estimated_volume_usd < min_volume_usd:
                signal.update({
                    "action": "HOLD",
                    "reason": f"거래대금 ${estimated_volume_usd:,.0f} < 최소 ${min_volume_usd:,.0f}",
                    "us_meta": us_meta,
                })
            else:
                shadow_mode = profile.get("shadow_mode", True)
                if shadow_mode:
                    us_meta["mock_trade"] = {
                        "price": current_price,
                        "qty": self._buy_qty(buy_budget, current_price),
                        "budget": buy_budget,
                    }
                    signal.update({
                        "action": "HOLD",
                        "reason": f"us_premarket shadow mode — 갭 {gap_pct:.1f}% / 되밀림 {drawdown_from_high_pct:.1f}%",
                        "us_meta": us_meta,
                    })
                else:
                    signal.update({
                        "action": "BUY",
                        "reason": f"US 프리마켓 갭업 {gap_pct:.1f}% 후 되밀림 진입 ({drawdown_from_high_pct:.1f}%)",
                        "order_qty": self._buy_qty(buy_budget, current_price),
                        "us_meta": us_meta,
                    })

        # ── US 개장 돌파 전략 ────────────────────────────────────────────────
        elif strategy_id == "us_breakout" and position_qty == 0:
            breakout_volume_ratio = self._safe_float(profile.get("breakout_volume_ratio", 3.0), 3.0)
            min_change_pct = self._safe_float(profile.get("min_change_pct", 5.0), 5.0)
            prev_high = self._safe_float(bar.get("prev_high", 0), 0) or self._safe_float(bar.get("high", 0), 0)
            avg_volume = self._safe_int(bar.get("avg_volume", 0), 0) or 1
            cur_volume = self._safe_int(bar.get("volume", 0), 0)
            volume_ratio = cur_volume / avg_volume if avg_volume > 0 else 0
            change_pct = (current_price - prev_close) / prev_close * 100 if prev_close > 0 else 0
            shadow_mode = profile.get("shadow_mode", True)
            us_meta = {
                "change_pct": round(change_pct, 4),
                "prev_high": round(prev_high, 4),
                "volume_ratio": round(volume_ratio, 2),
                "breakout_volume_ratio": breakout_volume_ratio,
            }
            if change_pct < min_change_pct:
                signal.update({"action": "HOLD", "reason": f"상승률 {change_pct:.2f}% < 최소 {min_change_pct:.1f}%", "us_meta": us_meta})
            elif volume_ratio < breakout_volume_ratio:
                signal.update({"action": "HOLD", "reason": f"거래량 비율 {volume_ratio:.1f}x < 기준 {breakout_volume_ratio:.1f}x", "us_meta": us_meta})
            elif prev_high > 0 and current_price <= prev_high:
                signal.update({"action": "HOLD", "reason": f"전일 고가 ${prev_high:.2f} 미돌파", "us_meta": us_meta})
            elif shadow_mode:
                us_meta["mock_trade"] = {"price": current_price, "qty": self._buy_qty(buy_budget, current_price)}
                signal.update({"action": "HOLD", "reason": f"us_breakout shadow mode — 상승 {change_pct:.1f}% / 거래량 {volume_ratio:.1f}x", "us_meta": us_meta})
            else:
                signal.update({"action": "BUY", "reason": f"개장 전고 돌파 진입 (상승 {change_pct:.1f}%, 거래량 {volume_ratio:.1f}x)", "order_qty": self._buy_qty(buy_budget, current_price), "us_meta": us_meta})

        # ── US 눌림목 반등 전략 ──────────────────────────────────────────────
        elif strategy_id == "us_pullback" and position_qty == 0:
            min_prior_surge_pct = self._safe_float(profile.get("min_prior_surge_pct", 10.0), 10.0)
            avg_volume = self._safe_int(bar.get("avg_volume", 0), 0) or 1
            cur_volume = self._safe_int(bar.get("volume", 0), 0)
            volume_ratio = cur_volume / avg_volume if avg_volume > 0 else 0
            surge_pct = ((self._safe_float(bar.get("high", current_price), current_price)) - prev_close) / prev_close * 100 if prev_close > 0 else 0
            drawdown_from_high = (self._safe_float(bar.get("high", current_price), current_price) - current_price) / self._safe_float(bar.get("high", current_price), current_price) * 100 if self._safe_float(bar.get("high", current_price), current_price) > 0 else 0
            vwap = self._safe_float(bar.get("vwap", 0), 0)
            now_hour_et = (self._now() - datetime.timedelta(hours=9)).hour  # KST - 9h ≈ ET
            shadow_mode = profile.get("shadow_mode", True)
            us_meta = {"surge_pct": round(surge_pct, 2), "drawdown_from_high": round(drawdown_from_high, 2), "volume_ratio": round(volume_ratio, 2), "vwap": round(vwap, 4)}
            if now_hour_et >= 11 and now_hour_et < 14:
                signal.update({"action": "HOLD", "reason": f"ET {now_hour_et}시 횡보구간 진입 금지", "us_meta": us_meta})
            elif surge_pct < min_prior_surge_pct:
                signal.update({"action": "HOLD", "reason": f"선행 급등 {surge_pct:.1f}% < 최소 {min_prior_surge_pct:.1f}%", "us_meta": us_meta})
            elif volume_ratio > 2.0:
                signal.update({"action": "HOLD", "reason": f"눌림목 아님: 거래량 급증 {volume_ratio:.1f}x", "us_meta": us_meta})
            elif drawdown_from_high < 2.0:
                signal.update({"action": "HOLD", "reason": f"고점 대비 되밀림 {drawdown_from_high:.1f}% 부족 (최소 2%)", "us_meta": us_meta})
            elif shadow_mode:
                us_meta["mock_trade"] = {"price": current_price, "qty": self._buy_qty(buy_budget, current_price)}
                signal.update({"action": "HOLD", "reason": f"us_pullback shadow mode — 급등 {surge_pct:.1f}% / 되밀림 {drawdown_from_high:.1f}%", "us_meta": us_meta})
            else:
                signal.update({"action": "BUY", "reason": f"급등 후 눌림목 진입 (선행급등 {surge_pct:.1f}%, 되밀림 {drawdown_from_high:.1f}%)", "order_qty": self._buy_qty(buy_budget, current_price), "us_meta": us_meta})

        # ── US VWAP 밴드 전략 ────────────────────────────────────────────────
        elif strategy_id == "us_vwap" and position_qty == 0:
            vwap = self._safe_float(bar.get("vwap", 0), 0)
            avg_volume = self._safe_int(bar.get("avg_volume", 0), 0) or 1
            cur_volume = self._safe_int(bar.get("volume", 0), 0)
            volume_ratio = cur_volume / avg_volume if avg_volume > 0 else 0
            shadow_mode = profile.get("shadow_mode", True)
            us_meta = {"vwap": round(vwap, 4), "volume_ratio": round(volume_ratio, 2), "current_price": round(current_price, 4)}
            if vwap <= 0:
                signal.update({"action": "HOLD", "reason": "VWAP 데이터 없음", "us_meta": us_meta})
            elif current_price < vwap:
                signal.update({"action": "HOLD", "reason": f"현재가 ${current_price:.2f} < VWAP ${vwap:.2f}", "us_meta": us_meta})
            elif volume_ratio < 2.0:
                signal.update({"action": "HOLD", "reason": f"거래량 비율 {volume_ratio:.1f}x < 기준 2.0x", "us_meta": us_meta})
            elif shadow_mode:
                us_meta["mock_trade"] = {"price": current_price, "qty": self._buy_qty(buy_budget, current_price)}
                signal.update({"action": "HOLD", "reason": f"us_vwap shadow mode — 현재가 ${current_price:.2f} / VWAP ${vwap:.2f}", "us_meta": us_meta})
            else:
                signal.update({"action": "BUY", "reason": f"VWAP 상단 유지 진입 (현재 ${current_price:.2f} > VWAP ${vwap:.2f}, 거래량 {volume_ratio:.1f}x)", "order_qty": self._buy_qty(buy_budget, current_price), "us_meta": us_meta})

        # 보유 포지션 청산 로직
        elif position_qty > 0 and avg_price > 0:
            jackpot_pct_val = float(profile.get("jackpot_take_profit_pct", 2.0))
            jackpot = avg_price * (1 + jackpot_pct_val / 100)
            jackpot_soft_exit_guard = jackpot * self._safe_float(profile.get("jackpot_soft_exit_guard_ratio", 0.995), 0.995)
            recent_target = anchor * (1 + float(profile.get("recent_lot_take_profit_pct", 0.6)) / 100)
            rescue_target = avg_price * (1 + float(profile.get("rescue_take_profit_pct", 0.5)) / 100)
            stop_loss_pct_val = self._safe_float(profile.get("stop_loss_pct", 1.5), 1.5)
            auto_stop_price = round(avg_price * (1 - stop_loss_pct_val / 100)) if stop_loss_pct_val > 0 else 0
            break_even_price = self._break_even_price(avg_price)
            bb_upper_live = self._safe_float(bar.get("bb_upper", 0), 0)
            stop_touch_price = current_price
            auto_stop_hit = auto_stop_price > 0 and current_price <= auto_stop_price
            rsi_live = self._safe_float(bar.get("rsi14", 50), 50)
            rsi_exit_overbought = self._safe_float(profile.get("rsi_exit_overbought", 75), 75)
            chunk_qty = max(1, min(position_qty, self._chunk_qty(budget_total, current_price)))
            signal.update({
                "jackpot_target": round(jackpot, 4),
                "recent_target": round(recent_target, 4),
                "rescue_target": round(rescue_target, 4),
                "auto_stop_price": auto_stop_price,
                "stop_touch_price": round(stop_touch_price, 4),
                "break_even_price": round(break_even_price, 4),
                "bb_upper_live": round(bb_upper_live, 4),
                "rsi_live": round(rsi_live, 2),
            })
            overnight_policy = self._overnight_carry_policy(state, profile, bar, current_price=current_price, avg_price=avg_price, market=market)
            # ── 사전 예약 매도 동기화 (pending sell order 체결 확인 + 가격 이탈 취소) ──
            _pending_status = self._sync_pending_sell(state, symbol, market, current_price=current_price)
            _has_pending = False
            if _pending_status == "filled":
                _filled_price_label = round(state.get("pending_sell_price", 0) or jackpot)
                signal["reason"] = f"사전 예약 지정가 매도 체결 완료 (₩{_filled_price_label:,})"
                _has_pending = True
            elif _pending_status == "open":
                pending_stop_hit = (
                    (stop_loss_enabled and stop_loss_price > 0 and current_price <= stop_loss_price)
                    or auto_stop_hit
                )
                if pending_stop_hit:
                    pending_order_no = str(state.get("pending_sell_order_no", "") or "")
                    pending_qty = self._safe_int(state.get("pending_sell_qty", 0), 0)
                    if pending_order_no != "" and pending_qty > 0:
                        try:
                            self.struct.kis_api.cancel_domestic_order(pending_order_no, symbol, pending_qty)
                        except Exception:
                            pass
                    self._clear_pending_sell(state)
                    self._append_runtime_log("warning", f"{symbol} 손절 우선 실행을 위해 사전 예약 매도를 취소했습니다.", symbol=symbol, strategy_id=strategy_id, dedup_sec=60)
                else:
                    signal.update({
                        "action": "HOLD",
                        "reason": f"지정가 매도 예약 대기 중 ₩{round(state.get('pending_sell_price', 0)):,} — 체결 감시 중",
                        "order_qty": 0,
                    })
                    _has_pending = True
            if not _has_pending:
                overnight_open_grace_minutes = max(0, self._safe_int(profile.get("overnight_open_grace_minutes", 18), 18))
                overnight_panic_stop_loss_pct = abs(self._safe_float(profile.get("overnight_panic_stop_loss_pct", 3.2), 3.2))
                close_liquidity_take_profit_pct = max(0.0, self._safe_float(profile.get("close_liquidity_take_profit_pct", 0.4), 0.4))
                close_liquidity_take_profit_price = avg_price * (1 + close_liquidity_take_profit_pct / 100) if avg_price > 0 else 0
                pnl_pct = ((current_price / avg_price) - 1) * 100 if current_price > 0 and avg_price > 0 else 0.0
                overnight_grace_active = (
                    strategy_id == "vrev"
                    and carried_overnight
                    and minutes_since_open >= 0
                    and minutes_since_open < overnight_open_grace_minutes
                    and pnl_pct > (-1.0 * overnight_panic_stop_loss_pct)
                )
                if self._is_market_close_approaching(market) and strategy_id == "vrev":
                    if close_liquidity_take_profit_price > 0 and current_price >= close_liquidity_take_profit_price:
                        signal.update({
                            "action": "SELL_FULL",
                            "reason": f"장마감 시드 확보 익절 (+{close_liquidity_take_profit_pct:.2f}% 기준)",
                            "order_qty": position_qty,
                            "ignore_jackpot_soft_guard": True,
                        })
                    elif overnight_policy.get("eligible"):
                        signal.update({
                            "action": "HOLD",
                            "reason": overnight_policy.get("reason", "종가 강도 유지로 오버나잇 보유"),
                            "order_qty": 0,
                        })
                    else:
                        signal.update({
                            "action": "SELL_FULL",
                            "reason": f"장마감 약세 정리: {overnight_policy.get('reason', '오버나잇 조건 미충족')}",
                            "order_qty": position_qty,
                        })
                elif stop_loss_enabled and stop_loss_price > 0 and current_price <= stop_loss_price:
                    signal.update({
                        "action": "SELL_STOP_LOSS",
                        "reason": "사용자 지정 손절가 확인",
                        "order_qty": position_qty,
                        "stop_loss_hit": True,
                    })
                elif auto_stop_hit:
                    signal.update({
                        "action": "SELL_STOP_LOSS",
                        "reason": f"자동 손절가 확인 (평단가 -{stop_loss_pct_val}%)",
                        "order_qty": position_qty,
                    })
                elif manual_sell_enabled and manual_sell_target_price > 0 and current_price >= manual_sell_target_price:
                    signal.update({
                        "action": "SELL_MANUAL",
                        "reason": "사용자 지정 판매가 도달",
                        "order_qty": position_qty,
                        "manual_target_hit": True,
                    })
                elif overnight_grace_active:
                    signal.update({
                        "action": "HOLD",
                        "reason": f"오버나잇 보유 종목 시초 추세 확인 중 ({minutes_since_open}분 / {overnight_open_grace_minutes}분)",
                        "order_qty": 0,
                    })
                elif strategy_id == "vrev" and current_price >= jackpot:
                    signal.update({
                        "action": "SELL_FULL",
                        "reason": f"목표 수익 {jackpot_pct_val}% 달성 전량 청산",
                        "order_qty": position_qty,
                    })
                elif strategy_id == "vrev" and current_price >= jackpot_soft_exit_guard:
                    # 잭팟가 근처에서는 soft exit보다 잭팟 예약을 우선한다.
                    signal.update({
                        "action": "PRE_SELL_JACKPOT",
                        "reason": f"잭팟가 ₩{round(jackpot):,} 근접 — 사전 지정가 예약 우선",
                        "order_qty": position_qty,
                        "pre_sell_price": round(jackpot),
                    })
                elif strategy_id == "vrev" and bb_upper_live > 0 and current_price >= bb_upper_live and current_price >= avg_price:
                    signal.update({
                        "action": "SELL_FULL",
                        "reason": "볼린저 밴드 상단 저항 도달 익절",
                        "order_qty": position_qty,
                    })
                elif strategy_id == "vrev" and rsi_live >= rsi_exit_overbought and current_price >= avg_price:
                    signal.update({
                        "action": "SELL_FULL",
                        "reason": f"RSI {rsi_live:.0f} 과매수 구간 익절",
                        "order_qty": position_qty,
                    })
                elif strategy_id == "vrev" and current_price >= recent_target:
                    signal.update({
                        "action": "SELL_RECENT",
                        "reason": "최근 레이어 방어 청산",
                        "order_qty": chunk_qty,
                    })
                elif strategy_id == "vrev" and state.get("buy2_used") and current_price >= rescue_target:
                    signal.update({
                        "action": "SELL_RESCUE",
                        "reason": "구조 복구 구간 부분 청산",
                        "order_qty": chunk_qty,
                    })
                elif strategy_id == "vrev" and self._is_market_close_approaching(market) and close_liquidity_take_profit_price > 0 and current_price >= close_liquidity_take_profit_price:
                    signal.update({
                        "action": "SELL_FULL",
                        "reason": f"장마감 시드 확보 익절 (+{close_liquidity_take_profit_pct:.2f}% 기준)",
                        "order_qty": position_qty,
                        "ignore_jackpot_soft_guard": True,
                    })
                elif strategy_id == "volume_breakout" and (
                    current_price >= avg_price * (1 + self._safe_float(profile.get("breakout_take_profit_pct", 1.4), 1.4) / 100)
                    or current_price < self._safe_float(bar.get("breakout_low_20", 0), 0)
                    or current_price < self._safe_float(bar.get("vwap", 0), 0)
                ):
                    signal.update({
                        "action": "SELL_FULL",
                        "reason": "거래량 돌파 후 이탈/목표 달성 청산",
                        "order_qty": position_qty,
                })
                elif strategy_id in ("us_premarket", "us_breakout", "us_pullback", "us_vwap"):
                    # ── US 전략 공통 청산 로직 ──────────────────────────────
                    us_high_stop_pct = self._safe_float(profile.get("high_stop_pct", 20.0), 20.0)
                    jackpot2_pct = self._safe_float(profile.get("jackpot2_take_profit_pct", 5.0), 5.0)
                    jackpot1_pct = self._safe_float(profile.get("jackpot_take_profit_pct", 3.0), 3.0)
                    jackpot1_target = avg_price * (1 + jackpot1_pct / 100)
                    jackpot2_target = avg_price * (1 + jackpot2_pct / 100)
                    split_ratio = self._safe_float(profile.get("buy_split_ratio", 0.5), 0.5)
                    buy1_used = bool(state.get("buy1_used", False))
                    intraday_high = self._safe_float(bar.get("high", current_price), current_price)
                    high_stop_price = intraday_high * (1 - us_high_stop_pct / 100) if intraday_high > 0 else 0
                    vwap = self._safe_float(bar.get("vwap", 0), 0)

                    if strategy_id == "us_vwap" and vwap > 0 and current_price < vwap:
                        signal.update({"action": "SELL_STOP_LOSS", "reason": f"VWAP 하단 이탈 즉시 손절 (현재 ${current_price:.2f} < VWAP ${vwap:.2f})", "order_qty": position_qty})
                    elif high_stop_price > 0 and current_price <= high_stop_price:
                        signal.update({"action": "SELL_STOP_LOSS", "reason": f"고점 대비 -{us_high_stop_pct:.0f}% 손절 (고점 ${intraday_high:.2f})", "order_qty": position_qty})
                    elif current_price >= jackpot2_target:
                        signal.update({"action": "SELL_FULL", "reason": f"2차 목표 +{jackpot2_pct:.0f}% 달성 전량 청산", "order_qty": position_qty})
                    elif current_price >= jackpot1_target and not buy1_used:
                        sell_partial_qty = max(1, round(position_qty * split_ratio))
                        signal.update({"action": "SELL_PARTIAL", "reason": f"1차 목표 +{jackpot1_pct:.0f}% 달성 부분 청산 ({sell_partial_qty}주)", "order_qty": sell_partial_qty})

        if strategy_id == "vrev" and signal.get("action") in ["SELL_FULL", "SELL_RECENT", "SELL_RESCUE"] and current_price > 0:
            if bool(signal.get("ignore_jackpot_soft_guard", False)) is False and current_price < jackpot_soft_exit_guard:
                prev_reason = signal.get("reason", "")
                signal.update({
                    "action": "HOLD",
                    "reason": f"잭팟 우선 홀드 — ₩{round(current_price):,}는 잭팟 방어선 ₩{round(jackpot_soft_exit_guard):,} 미만 (현재 {prev_reason})",
                    "order_qty": 0,
                })

        # 수수료 손익분기 체크 — 수수료만 나가는 매도 방지 (손절 제외)
        # 매수 수수료 0.015% + 매도 수수료 0.015% + 증권거래세 0.18% = 총 ~0.21%
        _FEE_BUY = 0.00015
        _FEE_SELL = 0.00195  # 0.015% + 0.18% 거래세
        if signal["action"].startswith("SELL") and "STOP" not in signal["action"] and signal["action"] != "SELL_MANUAL" and avg_price > 0 and current_price > 0:
            break_even = avg_price * (1 + _FEE_BUY) / (1 - _FEE_SELL)  # ≈ avg_price * 1.0021
            sell_qty_for_check = min(position_qty, max(1, self._safe_int(signal.get("order_qty", position_qty), position_qty)))
            min_exit_net_profit = max(0, round(self._safe_float(profile.get("min_exit_net_profit_krw", 500), 500)))
            est_net_profit = round(self._estimate_exit_net_profit(avg_price, current_price, sell_qty_for_check))
            est_total_fee = round(self._estimate_exit_total_fee(avg_price, current_price, sell_qty_for_check))
            min_exit_fee_multiple = max(1.0, self._safe_float(profile.get("min_exit_fee_multiple", 2.0), 2.0))
            fee_based_min_profit = round(est_total_fee * min_exit_fee_multiple)
            required_min_profit = max(min_exit_net_profit, fee_based_min_profit)
            if current_price < break_even:
                prev_reason = signal["reason"]
                signal.update({
                    "action": "HOLD",
                    "reason": f"수수료 손익분기 미달 — ₩{round(break_even):,} 이상 도달 후 매도 가능 (현재 {prev_reason})",
                    "order_qty": 0,
                })
            elif required_min_profit > 0 and est_net_profit < required_min_profit:
                prev_reason = signal["reason"]
                signal.update({
                    "action": "HOLD",
                    "reason": f"미세 익절 보류 — 예상 순이익 ₩{est_net_profit:,} < 최소 ₩{required_min_profit:,} (수수료 ₩{est_total_fee:,}×{min_exit_fee_multiple:.1f}, 현재 {prev_reason})",
                    "order_qty": 0,
                })

        # HOLD 상태일 때 이유를 문맥에 맞게 갱신 — 자동매매 결과 패널에서 원인 파악 가능하도록
        if signal["action"] == "HOLD":
            hold_reason = str(signal.get("reason", "") or "")
            if hold_reason not in ["", "현재 실행할 신호가 없습니다."]:
                pass
            elif position_qty > 0 and avg_price > 0:
                pnl_pct = round((current_price - avg_price) / avg_price * 100, 2) if avg_price > 0 else 0
                gap_to_jackpot = round(avg_price * (1 + float(profile.get("jackpot_take_profit_pct", 2.0)) / 100) - current_price)
                signal["reason"] = f"보유 중 ({pnl_pct:+.2f}%) 잭팟까지 ₩{gap_to_jackpot:,} 남음"
            elif reentry_cooldown.get("active"):
                signal["reason"] = reentry_cooldown.get("reason", "재진입 쿨다운 중")
            elif strategy_id == "vrev" and position_qty == 0 and state.get("buy1_used") == False and current_price <= buy1_trigger and profit_reentry_guard_buy1.get("active"):
                signal["reason"] = profit_reentry_guard_buy1.get("reason", "익절 직후 재진입 가격 확인 중")
            elif strategy_id == "vrev" and state.get("buy2_used") == False and current_price <= buy2_trigger and profit_reentry_guard_buy2.get("active"):
                signal["reason"] = profit_reentry_guard_buy2.get("reason", "익절 직후 재진입 가격 확인 중")
            else:
                signal["reason"] = "진입 대기 중"

        if self._is_us_market(market) and signal["action"].startswith("BUY") and buy_budget <= 0:
            reason = "USD 주문가능금액 기준 매수 예산이 0이라 신규 진입을 중단했습니다."
            if self._safe_float(budget_context.get("usd_krw", 0), 0) <= 0:
                reason = "USD 환율/해외주식 주문가능금액을 확인할 수 없어 신규 진입을 중단했습니다."
            signal.update({
                "action": "HOLD",
                "reason": reason,
                "order_qty": 0,
            })

        feature_snapshot = {
            "price": round(current_price, 4),
            "anchor_price": round(anchor, 4),
            "ma_fast": round(self._safe_float(bar.get("ma_fast", 0), 0), 4),
            "ma_slow": round(self._safe_float(bar.get("ma_slow", 0), 0), 4),
            "ma_trend": round(self._safe_float(bar.get("ma_trend", 0), 0), 4),
            "rsi14": round(self._safe_float(bar.get("rsi14", 0), 0), 4),
            "macd": round(self._safe_float(bar.get("macd", 0), 0), 4),
            "macd_signal": round(self._safe_float(bar.get("macd_signal", 0), 0), 4),
            "macd_hist": round(self._safe_float(bar.get("macd_hist", 0), 0), 4),
            "volume_surge_ratio": round(self._safe_float(bar.get("volume_surge_ratio", 0), 0), 4),
            "intraday_range_pct": round(self._safe_float(bar.get("intraday_range_pct", 0), 0), 4),
            "gap_from_open_pct": round(self._safe_float(bar.get("gap_from_open_pct", 0), 0), 4),
            "vwap_gap_pct": round(self._safe_float(bar.get("vwap_gap_pct", 0), 0), 4),
            "bb_upper": round(self._safe_float(bar.get("bb_upper", 0), 0), 4),
            "bb_lower": round(self._safe_float(bar.get("bb_lower", 0), 0), 4),
            "event_filter": self.strategy._event_filter_snapshot(symbol, market=market),
        }
        state["last_price"] = round(current_price, 4)
        state["anchor_price"] = round(anchor, 4)
        state["last_signal_reason"] = signal.get("reason", "")
        return {
            "state": state,
            "signal": signal,
            "profile": profile,
            "bar": bar,
            "session": session,
            "feature_snapshot": feature_snapshot,
        }

    def signal_status(self, symbol, market="KS", seed=1000000, name="", strategy_id="vrev", sync_broker=True):
        try:
            payload = self._signal_from_state(symbol, market=market, seed=seed, name=name, strategy_id=strategy_id, sync_broker=sync_broker)
            state = payload.get("state", {})
            signal = payload.get("signal", {})
            guardrails = self._guardrails(symbol, market, seed, state, signal, payload.get("session", {}), payload.get("bar", {}), payload.get("profile", {}))
            state["last_signal"] = signal.get("action", "HOLD")
            state["strategy_id"] = self.strategy._normalize_strategy(strategy_id)
            state["halt_reason"] = guardrails.get("issues", [""])[0] if guardrails.get("issues") else ""
            state["updated_at"] = self._timestamp()
            self._store_state(state)
            return {
                "symbol": symbol,
                "market": market,
                "name": state.get("name", name or self.strategy.symbol_name(symbol)),
                "state": state,
                "signal": signal,
                "profile": payload.get("profile", {}),
                "session": payload.get("session", {}),
                "bar": payload.get("bar", {}),
                "feature_snapshot": payload.get("feature_snapshot", {}),
                "runtime": {
                    "mode": guardrails.get("mode", "paper"),
                    "risk_status": guardrails.get("risk_status", "SAFE"),
                    "issues": guardrails.get("issues", []),
                    "warnings": guardrails.get("warnings", []),
                    "halt_reason": state.get("halt_reason", ""),
                    "recent_errors": self._recent_error_messages(state),
                    "recent_logs": self._load_runtime_logs()[-30:],
                    "connection": guardrails.get("connection", {}),
                    "portfolio": guardrails.get("portfolio", {}),
                    "daily_loss": guardrails.get("daily_loss", {}),
                    "exit_watch": self._exit_watch_payload(state, signal),
                },
            }
        except Exception as e:
            error_message = str(e)
            state = self._state_for(symbol, market=market, seed=seed, name=name, strategy_id=strategy_id)
            current_price = max(
                self._safe_float(state.get("last_price", 0), 0),
                self._safe_float(state.get("avg_price", 0), 0),
            )
            session_date = self._date_display(state.get("session_date", "")) or self._now().strftime("%Y%m%d")
            self._push_state_error(state, error_message)
            state["last_signal"] = "HOLD"
            state["halt_reason"] = error_message
            state["updated_at"] = self._timestamp()
            self._store_state(state)
            self._append_runtime_log("error", f"{symbol} 라이브 시그널 계산 실패: {error_message}", symbol=symbol, strategy_id=strategy_id, dedup_sec=300)
            signal = {
                "action": "HOLD",
                "reason": error_message,
                "order_qty": 0,
                "current_price": round(current_price, 4),
                "anchor_price": round(self._safe_float(state.get("anchor_price", current_price), current_price), 4),
                "buy1_trigger_pct": 0,
                "buy2_trigger_pct": 0,
                "buy1_trigger": 0,
                "buy2_trigger": 0,
                "avg_price": round(self._safe_float(state.get("avg_price", 0), 0), 4),
                "position_qty": self._safe_int(state.get("position_qty", 0), 0),
                "manual_sell_enabled": bool(state.get("manual_sell_enabled", False)),
                "manual_sell_target_price": round(self._safe_float(state.get("manual_sell_target_price", 0), 0), 4),
                "stop_loss_enabled": bool(state.get("stop_loss_enabled", False)),
                "stop_loss_price": round(self._safe_float(state.get("stop_loss_price", 0), 0), 4),
                "auto_stop_price": round(self._safe_float(signal.get("auto_stop_price", 0), 0), 4),
                "stop_touch_price": round(self._safe_float(signal.get("stop_touch_price", 0), 0), 4),
                "break_even_price": round(self._safe_float(signal.get("break_even_price", 0), 0), 4),
                "price_source": "error_fallback",
                "session_date": session_date,
                "strategy_id": self.strategy._normalize_strategy(strategy_id),
                "strategy_name": self.strategy.strategy_spec(strategy_id).get("name", strategy_id),
            }
            return {
                "symbol": symbol,
                "market": market,
                "name": state.get("name", name or self.strategy.symbol_name(symbol)),
                "state": state,
                "signal": signal,
                "profile": self._profile_for(symbol, strategy_id=strategy_id),
                "session": {"date": session_date, "prev_close": self._safe_float(state.get("anchor_price", current_price), current_price), "bars": []},
                "bar": {"close": current_price, "price_source": "error_fallback", "intraday_unavailable": True},
                "feature_snapshot": {},
                "runtime": {
                    "mode": "degraded",
                    "risk_status": "HALT",
                    "issues": [error_message],
                    "warnings": [],
                    "halt_reason": error_message,
                    "recent_errors": self._recent_error_messages(state),
                    "recent_logs": self._load_runtime_logs()[-30:],
                    "connection": self.check_kis_connection(),
                    "portfolio": self.portfolio_usage(),
                    "daily_loss": self.daily_loss_status(requested_seed=seed),
                    "exit_watch": self._exit_watch_payload(state, signal),
                },
            }

    def check_kis_connection(self):
        """KIS API 연동 상태 확인"""
        try:
            kis = self.struct.kis_api
            if not kis.app_key or not kis.app_secret:
                return {"connected": False, "message": "KIS API 키가 설정되지 않았습니다. 설정 > KIS API에서 등록해주세요."}
            if not kis.account_no:
                return {"connected": False, "message": "KIS 계좌번호가 설정되지 않았습니다."}
            return {"connected": True, "message": "KIS API 연동 완료", "is_real": kis.is_real, "account": kis.account_prefix + "-" + kis.account_suffix}
        except Exception as e:
            return {"connected": False, "message": f"KIS API 연동 오류: {str(e)}"}

    def _append_order(self, state, action, qty, price, order, strategy_id="vrev", reason=""):
        orders = list(state.get("orders", []) or [])[-19:]
        orders.append({
            "timestamp": self._timestamp(),
            "action": action,
            "qty": int(qty),
            "price": round(float(price), 4),
            "order_no": order.get("order_no", ""),
            "order_type": order.get("order_type", "MARKET"),
            "strategy_id": self.strategy._normalize_strategy(strategy_id),
            "reason": reason,
        })
        state["orders"] = orders

    def _safe_json_dumps(self, payload):
        try:
            return json.dumps(payload or {}, ensure_ascii=False)
        except Exception:
            try:
                return json.dumps(str(payload), ensure_ascii=False)
            except Exception:
                return "{}"

    def _compact_runtime_meta(self, status=None, extra=None):
        status = status or {}
        signal = status.get("signal", {}) if isinstance(status, dict) else {}
        runtime = status.get("runtime", {}) if isinstance(status, dict) else {}
        state = status.get("state", {}) if isinstance(status, dict) else {}
        payload = {
            "action": signal.get("action", "HOLD"),
            "reason": signal.get("reason", ""),
            "risk_status": runtime.get("risk_status", "SAFE"),
            "issues": runtime.get("issues", []),
            "warnings": runtime.get("warnings", []),
            "current_price": round(self._safe_float(signal.get("current_price", 0), 0), 4),
            "buy1_trigger": round(self._safe_float(signal.get("buy1_trigger", 0), 0), 4),
            "buy2_trigger": round(self._safe_float(signal.get("buy2_trigger", 0), 0), 4),
            "order_qty": self._safe_int(signal.get("order_qty", 0), 0),
            "position_qty": self._safe_int(state.get("position_qty", 0), 0),
            "avg_price": round(self._safe_float(state.get("avg_price", 0), 0), 4),
            "manual_sell": bool(state.get("manual_sell_enabled", False)),
            "manual_sell_target": round(self._safe_float(state.get("manual_sell_target_price", 0), 0), 4),
            "stop_loss": bool(state.get("stop_loss_enabled", False)),
            "stop_loss_price": round(self._safe_float(state.get("stop_loss_price", 0), 0), 4),
            "auto_stop_price": round(self._safe_float(signal.get("auto_stop_price", 0), 0), 4),
            "stop_touch_price": round(self._safe_float(signal.get("stop_touch_price", 0), 0), 4),
            "break_even_price": round(self._safe_float(signal.get("break_even_price", 0), 0), 4),
            "price_source": signal.get("price_source", ""),
        }
        if isinstance(extra, dict):
            payload.update(extra)
        return payload
    
    def _resolve_domestic_fill(self, symbol, side, order, fallback_price=0, fallback_qty=0):
        order_no = str((order or {}).get("order_no", "") or "")
        side = str(side or "").upper()
        if order_no == "":
            return {
                "filled_price": self._safe_float(fallback_price, 0),
                "filled_qty": self._safe_int(fallback_qty, 0),
                "status": "UNKNOWN",
            }
        try:
            fills = self.struct.kis_api.get_domestic_fills_today(symbol)
        except Exception:
            fills = []
        for fill in fills or []:
            if str(fill.get("order_no", "") or "") != order_no:
                continue
            if str(fill.get("side", "") or "").upper() != side:
                continue
            return {
                "filled_price": self._safe_float(fill.get("filled_price", fallback_price), fallback_price),
                "filled_qty": self._safe_int(fill.get("filled_qty", fallback_qty), fallback_qty),
                "status": str(fill.get("status", "") or "UNKNOWN"),
            }
        return {
            "filled_price": self._safe_float(fallback_price, 0),
            "filled_qty": self._safe_int(fallback_qty, 0),
            "status": "UNKNOWN",
        }

    def _log_execution(self, symbol, action, qty, price, order, message, strategy_id="vrev", runtime=None, name="", filled_price=None, filled_qty=None, breakout_meta=None):
        strategy_id = self.strategy._normalize_strategy(strategy_id)
        log_price = self._safe_float(filled_price, self._safe_float(price, 0))
        log_qty = self._safe_int(filled_qty, self._safe_int(qty, 0))

        runtime_payload = runtime or {}
        if breakout_meta:
            runtime_payload['breakout_meta'] = breakout_meta
        market = self._market_key(
            market=str((order or {}).get("market", "") or runtime_payload.get("market", "") or ""),
            symbol=symbol,
        )

        payload = {
            "symbol": symbol,
            "market": market,
            "name": name or self.strategy.symbol_name(symbol),
            "action": action,
            "qty": log_qty,
            "price": round(log_price, 4),
            "order": order or {},
            "runtime": runtime_payload,
            "message": message,
        }
        try:
            db = self.struct.db("trade_log")
            db.insert({
                "cycle_id": f"daytrade:{market.lower()}:{symbol}",
                "symbol": symbol,
                "event_type": self._dt_event_type(action=action, market=market, symbol=symbol),
                "action": self._normalize_trade_action(action),
                "order_no": str((order or {}).get("order_no", "") or ""),
                "order_price": self._safe_float((order or {}).get("price", price), 0),
                "order_qty": self._safe_int((order or {}).get("qty", qty), 0),
                "filled_price": log_price,
                "filled_qty": log_qty,
                "message": message,
                "raw_response": self._safe_json_dumps(payload),
            })
        except Exception as e:
            self._append_runtime_log("warning", f"{symbol} 거래 로그 저장 실패: {str(e)}", symbol=symbol, strategy_id=strategy_id, market=market)
        self._append_runtime_log("info", message, symbol=symbol, strategy_id=strategy_id, meta=(runtime_payload or {}), market=market)

    def _execute_live_legacy_tail(self, symbol, market="KS", seed=1000000, name="", strategy_id="vrev", force=False, allow_buy=True):
        strategy_id = self.strategy._normalize_strategy(strategy_id)
        status = self.signal_status(symbol, market=market, seed=seed, name=name, strategy_id=strategy_id)
        signal = status.get("signal", {}) or {}
        state = status.get("state", {}) or {}
        runtime = status.get("runtime", {}) or {}
        action = str(signal.get("action", "HOLD") or outcome.get("status", {}).get("signal", {}).get("action", "HOLD"))
        qty = max(0, self._safe_int(signal.get("order_qty", 0), 0))
        current_price = self._safe_float(signal.get("current_price", 0), 0)
        order_value = round(current_price * qty, 2)
        breakout_meta = signal.get("breakout_meta")
        self._append_runtime_log(
            "info",
            f"{symbol} 실행 판단: {action} · {signal.get('reason', '')}",
            symbol=symbol,
            strategy_id=strategy_id,
            meta=self._compact_runtime_meta(status, {
                "seed": round(self._safe_float(seed, 0), 2),
                "force": bool(force),
                "allow_buy": bool(allow_buy),
                "order_value": order_value,
            }),
        )

        if action.startswith("BUY") and allow_buy is False:
            message = "자동청산 감시 모드라 신규 매수는 실행하지 않습니다."
            self._append_runtime_log("info", f"{symbol} 신규 매수 차단: 자동청산 감시 전용", symbol=symbol, strategy_id=strategy_id, meta=self._compact_runtime_meta(status))
            return {
                "executed": False,
                "message": message,
                "status": status,
                "action": action,
                "order_value": 0,
            }

        if action == "HOLD":
            return {
                "executed": False,
                "message": signal.get("reason", "현재 실행할 신호가 없습니다."),
                "status": status,
                "action": action,
                "order_value": 0,
            }

        if runtime.get("risk_status") == "HALT":
            halt_reason = runtime.get("halt_reason", "실행이 차단되었습니다.")
            self._push_state_error(state, halt_reason)
            state["updated_at"] = self._timestamp
            return {
                "executed": False,
                "message": halt_reason,
                "status": status,
                "action": action,
                "order_value": 0,
            }


Model = DomesticDaytradeEngine
