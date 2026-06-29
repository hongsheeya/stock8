# =============================================================================
# 무한매수법 알고리즘 엔진 Sub-Struct
# =============================================================================
# 라오어의 무한매수법 규칙에 따라 매수/매도 판단 및 실행
# =============================================================================
import datetime
import contextlib
import math
import time

_TIME = wiz.model("portal/trading/kst")

# 사이클 상태 상수
STATUS_IDLE = "IDLE"
STATUS_ACTIVE = "ACTIVE"
STATUS_HOLDING = "HOLDING"
STATUS_PAUSED = "PAUSED"
STATUS_PENDING_EXTENSION = "PENDING_EXTENSION"
STATUS_COMPLETED = "COMPLETED"

# 거래 액션
ACTION_BUY = "BUY"
ACTION_SELL = "SELL"
ACTION_SKIP = "SKIP"

# 주문 상태
ORDER_PENDING = "PENDING"
ORDER_FILLED = "FILLED"
ORDER_CANCELLED = "CANCELLED"
ORDER_EXPIRED = "EXPIRED"
SYNTHETIC_EXTERNAL_ORDER_TYPES = {"RECON", "AUDIT"}

# 사이클 모드
CYCLE_MODE_AUTO = "auto"
CYCLE_MODE_CONFIRM = "confirm"
CYCLE_MODE_MANUAL = "manual"

# 전략 타입
STRATEGY_NORMAL = "NORMAL"
STRATEGY_FULL_SELL = "FULL_SELL"
STRATEGY_PARTIAL_SELL = "PARTIAL_SELL"
STRATEGY_CRASH_BUY = "CRASH_BUY"

DEFAULT_INFINITY_SYMBOLS = {
    "TQQQ": {
        "name": "ProShares UltraPro QQQ",
        "exchange": "NASD",
        "total_investment": 10000.0,
        "division_count": 20,
        "target_profit": 15.0,
    },
    "SOXL": {
        "name": "Direxion Daily Semiconductor Bull 3X Shares",
        "exchange": "AMEX",
        "total_investment": 15000.0,
        "division_count": 20,
        "target_profit": 20.0,
    },
}


class Engine:
    """무한매수법 알고리즘 엔진"""

    def __init__(self, struct):
        self.struct = struct
        self._reservation_order_cache = {}

    def _now(self):
        return _TIME.now()

    def _load_kis_api(self):
        """Return the selected broker API client used by order/sync routines."""
        try:
            return getattr(self.struct, "broker_api", None) or getattr(self.struct, "kis_api", None)
        except Exception:
            return None

    def _broker_request_options(self, broker, timeout=3.0, retries=0):
        options = getattr(broker, "request_options", None)
        if callable(options):
            return options(timeout=timeout, retries=retries)
        return contextlib.nullcontext()

    def _clear_reservation_order_cache(self):
        try:
            self._reservation_order_cache = {}
        except Exception:
            pass

    def _load_reservation_orders(self, kis_api, start_date=None, exchanges=None, timeout=4.0):
        start_date = start_date or self._reservation_query_start_date()
        exchange_key = tuple(str(item or "").upper() for item in (exchanges or []))
        cache_key = (str(start_date or ""), exchange_key)
        cache = getattr(self, "_reservation_order_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._reservation_order_cache = cache
        if cache_key in cache:
            return [dict(row or {}) for row in (cache.get(cache_key) or [])]
        with self._broker_request_options(kis_api, timeout=timeout, retries=0):
            rows = kis_api.get_overseas_reservation_orders(
                start_date=start_date,
                exchanges=list(exchange_key) if exchange_key else None,
            ) or []
        cache[cache_key] = [dict(row or {}) for row in rows]
        return [dict(row or {}) for row in rows]

    def _config_bool(self, key, default=False):
        raw_default = "true" if default else "false"
        try:
            value = str(self._get_config_value(key, raw_default) or raw_default).strip().lower()
        except Exception:
            value = raw_default
        return value in ("1", "true", "yes", "y", "on")

    def _firegate_reservation_authority_required(self):
        return self._config_bool("firegate_authoritative_reservations_only", False)

    def _load_firegate_authoritative_states(self, symbol_filter=""):
        try:
            fg = wiz.model("portal/trading/struct/firegate_bridge")
            loader = getattr(fg, "authoritative_portfolio_states", None)
            if not callable(loader):
                return {"states": {}, "error": "FireGate 원본 상태 조회 함수가 없습니다."}
            states = loader(self.struct, symbol_filter=symbol_filter) or {}
            normalized = {}
            for symbol, state in states.items():
                key = str(symbol or (state or {}).get("symbol", "") or "").upper().strip()
                if key:
                    normalized[key] = dict(state or {})
            return {"states": normalized, "error": ""}
        except Exception as e:
            return {"states": {}, "error": str(e)}

    def _cycle_with_firegate_authority(self, cycle, firegate_states, required=False, load_error=""):
        symbol = str((cycle or {}).get("symbol", "") or "").upper().strip()
        state = dict((firegate_states or {}).get(symbol) or {})
        if state and not state.get("_firegate_ambiguous"):
            merged = dict(cycle or {})
            merged.update(state)
            return merged, ""
        if not required:
            return cycle, ""
        if state.get("_firegate_ambiguous"):
            ids = ", ".join(state.get("_firegate_duplicate_portfolio_ids", []) or [])
            return None, f"FireGate {symbol} 포트폴리오가 중복되어 예약을 차단했습니다. 중복 ID: {ids or 'unknown'}"
        if load_error:
            return None, f"FireGate 원본 상태 조회 실패로 로컬 DB 기준 예약을 차단했습니다: {load_error}"
        return None, f"FireGate {symbol} 원본 포트폴리오를 찾지 못해 로컬 DB 기준 예약을 차단했습니다."

    # =========================================================================
    # DB 헬퍼
    # =========================================================================

    def _cycle_db(self):
        return self.struct.db("trading_cycle")

    def _trade_db(self):
        return self.struct.db("cycle_trade")

    def _log_db(self):
        return self.struct.db("trade_log")

    def _watchlist_db(self):
        return self.struct.db("etf_watchlist")

    def _snapshot_db(self):
        return self.struct.db("account_snapshot")

    def _ensure_runtime_schema(self):
        try:
            migrate = getattr(self.struct, "_migrate_schema", None)
            if callable(migrate):
                migrate()
        except Exception:
            pass

    def _insert_trade_record(self, trade_db, trade_data):
        """Insert a cycle_trade row even while an old DB is being migrated."""
        data = dict(trade_data or {})
        removable = ["broker_order_no", "source", "commission", "strategy_type"]
        for _ in range(len(removable) + 1):
            try:
                return trade_db.insert(data)
            except Exception as e:
                message = str(e).lower()
                removed = False
                for column in list(removable):
                    if column in data and column.lower() in message:
                        data.pop(column, None)
                        removable.remove(column)
                        removed = True
                        break
                if not removed:
                    raise
        return trade_db.insert(data)

    def _is_synthetic_external_trade(self, row):
        """Rows used only for old reconciliation must never affect holdings/history."""
        row = row or {}
        order_type = str(row.get("order_type", "") or "").upper().strip()
        order_no = str(row.get("broker_order_no", "") or "").upper().strip()
        return order_type in SYNTHETIC_EXTERNAL_ORDER_TYPES or order_no.startswith("RECONCILE-")

    # =========================================================================
    # 거래소 코드 헬퍼
    # =========================================================================

    # 주문용 4글자 → 시세조회용 3글자 변환
    EXCHANGE_MAP = {"NASD": "NAS", "NYSE": "NYS", "AMEX": "AMS"}

    def _default_order_exchange(self, symbol):
        symbol = str(symbol or "").upper().strip()
        return str((DEFAULT_INFINITY_SYMBOLS.get(symbol) or {}).get("exchange", "NASD") or "NASD").upper()

    def _resolve_order_exchange(self, symbol, exchange=""):
        symbol = str(symbol or "").upper().strip()
        exchange = str(exchange or "").upper().strip()
        default_exchange = self._default_order_exchange(symbol)
        if symbol in DEFAULT_INFINITY_SYMBOLS and exchange in ("", "NASD") and default_exchange != "NASD":
            return default_exchange
        return exchange or default_exchange or "NASD"

    def _get_exchange(self, symbol):
        """워치리스트에서 종목의 주문용 거래소 코드(4글자) 조회"""
        watchlist = self._watchlist_db()
        etf = watchlist.get(symbol=symbol)
        if etf:
            return self._resolve_order_exchange(symbol, etf.get("exchange", "NASD"))
        return self._resolve_order_exchange(symbol, "")

    def _price_exchange(self, order_exchange):
        """주문용 거래소 코드(4글자)를 시세조회용(3글자)으로 변환"""
        return self.EXCHANGE_MAP.get(order_exchange, "NAS")

    # =========================================================================
    # 수수료 설정 헬퍼
    # =========================================================================

    def _get_commission_rates(self):
        """trading_config에서 수수료/세금 설정 조회"""
        buy_rate = float(self._get_config_value("buy_commission_rate", "0.25"))
        sell_rate = float(self._get_config_value("sell_commission_rate", "0.25"))
        tax_rate = float(self._get_config_value("tax_rate", "0"))
        return {
            "buy_rate": buy_rate / 100,     # % → 소수
            "sell_rate": sell_rate / 100,
            "tax_rate": tax_rate / 100,
        }

    def _calc_buy_commission(self, amount, rates=None):
        """매수 수수료 계산"""
        if rates is None:
            rates = self._get_commission_rates()
        return round(amount * rates["buy_rate"], 2)

    def _calc_sell_commission(self, amount, rates=None):
        """매도 수수료 + 세금 계산"""
        if rates is None:
            rates = self._get_commission_rates()
        commission = amount * rates["sell_rate"]
        tax = amount * rates["tax_rate"]
        return round(commission + tax, 2)

    # =========================================================================
    # 전략 설정 로드
    # =========================================================================

    def _get_strategy_params(self):
        """trading_config에서 전략 파라미터 조회"""
        partial_sell_stages = [
            {"min_round": 11, "max_round": 20, "profit_threshold": 5.0, "sell_ratio": 20.0},
            {"min_round": 21, "max_round": 30, "profit_threshold": 4.0, "sell_ratio": 30.0},
            {"min_round": 31, "max_round": None, "profit_threshold": 3.0, "sell_ratio": 40.0},
        ]
        try:
            strat_mod = self._load_strategy_module()
            partial_sell_stages = strat_mod.get("DEFAULT_PARAMS", {}).get("partial_sell_stages", partial_sell_stages)
        except Exception:
            pass

        return {
            "sell_strategy": self._get_config_value("sell_strategy", "firegate"),
            "partial_sell_stages": partial_sell_stages,
            "partial_sell_remaining_full_exit": self._get_config_value("partial_sell_remaining_full_exit", "true") == "true",
            "crash_buy_enabled": self._get_config_value("crash_buy_enabled", "false") == "true",
            "crash_buy_drop_pct": float(self._get_config_value("crash_buy_drop_pct", "5")),
            "crash_buy_ma_drop_pct": float(self._get_config_value("crash_buy_ma_drop_pct", "10")),
            "crash_buy_ratio": float(self._get_config_value("crash_buy_ratio", "10")),
            "crash_buy_max_per_cycle": int(self._get_config_value("crash_buy_max_per_cycle", "3")),
        }

    def _load_strategy_module(self):
        """strategy 모듈 로드"""
        return self.struct._Strategy

    # =========================================================================
    # 사이클 번호 헬퍼
    # =========================================================================

    def _next_cycle_number(self, symbol):
        """해당 종목의 다음 사이클 번호 계산"""
        cycle_db = self._cycle_db()
        all_cycles = cycle_db.rows(symbol=symbol, orderby="cycle_number", order="DESC", dump=1)
        if all_cycles and len(all_cycles) > 0:
            return int(all_cycles[0].get("cycle_number", 0)) + 1
        return 1

    # =========================================================================
    # 사이클 관리
    # =========================================================================

    def start_cycle(self, symbol, total_investment=None, division_count=None, target_profit=None):
        """
        새 사이클 시작
        - watchlist에서 종목 설정 조회
        - 사용자가 override 파라미터를 전달하면 해당 값 사용
        - trading_cycle 레코드 생성 (상태: ACTIVE)
        반환: cycle dict
        """
        watchlist = self._watchlist_db()
        etf = watchlist.get(symbol=symbol, is_active=True)
        if not etf:
            raise Exception(f"종목 [{symbol}]이 워치리스트에 없거나 비활성 상태입니다.")

        # 이미 진행 중인 사이클 확인
        cycle_db = self._cycle_db()
        active = cycle_db.get(symbol=symbol, status=STATUS_ACTIVE)
        holding = cycle_db.get(symbol=symbol, status=STATUS_HOLDING)
        paused = cycle_db.get(symbol=symbol, status=STATUS_PAUSED)
        pending = cycle_db.get(symbol=symbol, status=STATUS_PENDING_EXTENSION)
        if active or holding or paused or pending:
            raise Exception(f"종목 [{symbol}]에 이미 진행 중인 사이클이 있습니다.")

        now = self._now()
        # 사용자 override가 있으면 해당 값 사용, 없으면 워치리스트 기본값
        total_investment = float(total_investment) if total_investment is not None else float(etf["total_investment"])
        division_count = int(division_count) if division_count is not None else int(etf["division_count"])
        target_profit = float(target_profit) if target_profit is not None else float(etf["target_profit"])
        cycle_number = self._next_cycle_number(symbol)

        cycle_data = {
            "symbol": symbol,
            "cycle_number": cycle_number,
            "status": STATUS_ACTIVE,
            "current_round": 0,
            "division_count": division_count,
            "target_profit": target_profit,
            "total_investment": total_investment,
            "total_spent": 0.0,
            "total_qty": 0,
            "avg_price": 0.0,
            "current_price": 0.0,
            "current_eval": 0.0,
            "profit_rate": 0.0,
            "total_commission": 0.0,
            "remaining_investment": total_investment,
            "started_at": now,
            "completed_at": None,
            "created": now,
            "updated": now,
        }
        cycle_db.insert(cycle_data)

        self._log_event(symbol, "", "CYCLE_START", message=f"사이클 #{cycle_number} 시작: 투자금 ${total_investment}, {division_count}분할, 목표 {target_profit}%")

        return cycle_db.get(symbol=symbol, status=STATUS_ACTIVE)

    def complete_cycle(self, cycle_id):
        """사이클 완료 처리"""
        cycle_db = self._cycle_db()
        now = self._now()
        cycle_db.update({
            "status": STATUS_COMPLETED,
            "completed_at": now,
            "updated": now,
        }, id=cycle_id)

        cycle = cycle_db.get(id=cycle_id)
        self._log_event(cycle["symbol"], cycle_id, "CYCLE_COMPLETE",
                        message=f"사이클 #{cycle.get('cycle_number', '?')} 완료: 수익률 {cycle['profit_rate']:.2f}%")
        self._auto_start_next_cycle_after_completion(cycle)

    def _auto_start_next_cycle_after_completion(self, completed_cycle):
        """Start the next active cycle after a completed infinite-buy cycle."""
        try:
            enabled = str(self._get_config_value("auto_start_next_cycle_enabled", "true") or "true").lower() in ("1", "true", "yes", "y", "on")
            if enabled is False:
                return None
            symbol = str((completed_cycle or {}).get("symbol", "") or "").upper()
            if not symbol:
                return None
            watchlist = self._watchlist_db()
            item = watchlist.get(symbol=symbol, is_active=True)
            if not item:
                return None
            cycle_db = self._cycle_db()
            for status in [STATUS_ACTIVE, STATUS_HOLDING, STATUS_PAUSED, STATUS_PENDING_EXTENSION]:
                if cycle_db.get(symbol=symbol, status=status):
                    return None
            next_cycle = self.start_cycle(symbol)
            if next_cycle:
                self._log_event(symbol, next_cycle.get("id", ""), "CYCLE_AUTO_RESTART",
                                message=f"이전 사이클 #{(completed_cycle or {}).get('cycle_number', '?')} 완료 후 새 사이클 #{next_cycle.get('cycle_number', '?')} 자동 시작")
            return next_cycle
        except Exception as e:
            try:
                self._log_event(str((completed_cycle or {}).get("symbol", "") or "").upper(), (completed_cycle or {}).get("id", ""),
                                "CYCLE_AUTO_RESTART_ERROR", message=f"새 사이클 자동 시작 실패: {str(e)}")
            except Exception:
                pass
            return None

    def force_close_cycle(self, cycle_id):
        """
        사이클 강제 종료
        - 현재 보유 주식을 현재가 기준으로 전량 매도 처리
        - 실제 KIS API 매도 주문은 호출자가 별도 처리
        """
        cycle_db = self._cycle_db()
        cycle = cycle_db.get(id=cycle_id)
        if not cycle:
            raise Exception(f"사이클을 찾을 수 없습니다: {cycle_id}")

        status = cycle["status"]
        if status == STATUS_COMPLETED:
            raise Exception("이미 완료된 사이클입니다.")

        total_qty = int(cycle["total_qty"])
        total_spent = float(cycle["total_spent"])
        current_price = float(cycle["current_price"])
        total_commission_before = float(cycle.get("total_commission", 0))

        now = self._now()

        if total_qty > 0 and current_price > 0:
            # 매도 처리 (현재가 기준)
            sell_amount = total_qty * current_price
            rates = self._get_commission_rates()
            sell_commission = self._calc_sell_commission(sell_amount, rates)
            total_commission = total_commission_before + sell_commission
            net_proceeds = sell_amount - sell_commission
            profit_rate = ((net_proceeds - total_spent) / total_spent * 100) if total_spent > 0 else 0

            # 매도 거래 기록
            trade_db = self._trade_db()
            self._insert_trade_record(trade_db, {
                "cycle_id": cycle_id,
                "symbol": cycle["symbol"],
                "round": int(cycle["current_round"]),
                "trade_date": now.strftime("%Y-%m-%d"),
                "action": ACTION_SELL,
                "order_type": "FORCE_CLOSE",
                "order_price": current_price,
                "order_qty": total_qty,
                "filled_price": current_price,
                "filled_qty": total_qty,
                "filled_amount": round(sell_amount, 2),
                "commission": sell_commission,
                "avg_buy_price": float(cycle["avg_price"]),
                "total_qty_after": 0,
                "total_spent_after": 0,
                "current_eval": round(net_proceeds, 2),
                "profit_rate": round(profit_rate, 2),
                "remaining_investment": 0,
                "remaining_rounds": 0,
                "status": ORDER_FILLED,
                "memo": "강제 종료",
                "created": now,
            })

            cycle_db.update({
                "total_qty": 0,
                "total_spent": 0,
                "avg_price": 0,
                "current_eval": round(net_proceeds, 2),
                "profit_rate": round(profit_rate, 2),
                "total_commission": round(total_commission, 2),
                "remaining_investment": 0,
                "status": STATUS_COMPLETED,
                "completed_at": now,
                "updated": now,
            }, id=cycle_id)

            self._log_event(cycle["symbol"], cycle_id, "FORCE_CLOSE",
                            action=ACTION_SELL,
                            message=f"사이클 #{cycle.get('cycle_number', '?')} 강제 종료: {total_qty}주 @ ${current_price:.2f}, 수익률 {profit_rate:.2f}%")
        else:
            # 보유 주식 없으면 그냥 완료 처리
            cycle_db.update({
                "status": STATUS_COMPLETED,
                "completed_at": now,
                "updated": now,
            }, id=cycle_id)

            self._log_event(cycle["symbol"], cycle_id, "FORCE_CLOSE",
                            message=f"사이클 #{cycle.get('cycle_number', '?')} 강제 종료 (보유 없음)")

        return cycle_db.get(id=cycle_id)

    def pause_cycle(self, cycle_id):
        """사이클 일시 정지"""
        cycle_db = self._cycle_db()
        cycle = cycle_db.get(id=cycle_id)
        if not cycle:
            raise Exception(f"사이클을 찾을 수 없습니다: {cycle_id}")

        status = cycle["status"]
        if status not in [STATUS_ACTIVE, STATUS_HOLDING, STATUS_PENDING_EXTENSION]:
            raise Exception(f"일시정지할 수 없는 상태입니다: {status}")

        now = self._now()
        cycle_db.update({
            "status": STATUS_PAUSED,
            "updated": now,
        }, id=cycle_id)

        self._log_event(cycle["symbol"], cycle_id, "CYCLE_PAUSE",
                        message=f"사이클 #{cycle.get('cycle_number', '?')} 일시 정지 (이전 상태: {status})")

        return cycle_db.get(id=cycle_id)

    def resume_cycle(self, cycle_id):
        """사이클 재개 — ACTIVE, HOLDING, 또는 PENDING_EXTENSION 상태로 복원"""
        cycle_db = self._cycle_db()
        cycle = cycle_db.get(id=cycle_id)
        if not cycle:
            raise Exception(f"사이클을 찾을 수 없습니다: {cycle_id}")

        if cycle["status"] != STATUS_PAUSED:
            raise Exception(f"PAUSED 상태가 아닙니다: {cycle['status']}")

        # 분할 횟수 소진 시 PENDING_EXTENSION 또는 HOLDING, 아니면 ACTIVE
        current_round = int(cycle["current_round"])
        division_count = int(cycle["division_count"])
        if current_round >= division_count:
            new_status = STATUS_PENDING_EXTENSION
        else:
            new_status = STATUS_ACTIVE

        now = self._now()
        cycle_db.update({
            "status": new_status,
            "updated": now,
        }, id=cycle_id)

        self._log_event(cycle["symbol"], cycle_id, "CYCLE_RESUME",
                        message=f"사이클 #{cycle.get('cycle_number', '?')} 재개 → {new_status}")

        return cycle_db.get(id=cycle_id)

    def delete_cycle(self, cycle_id):
        """사이클 삭제 — PAUSED/COMPLETED 상태에서 허용, 관련 거래/로그 레코드도 삭제"""
        cycle_db = self._cycle_db()
        trade_db = self._trade_db()
        log_db = self._log_db()
        cycle = cycle_db.get(id=cycle_id)
        if not cycle:
            raise Exception(f"사이클을 찾을 수 없습니다: {cycle_id}")

        allowed = [STATUS_PAUSED, STATUS_COMPLETED]
        if cycle["status"] not in allowed:
            raise Exception(f"PAUSED 또는 COMPLETED 상태에서만 삭제할 수 있습니다. 현재 상태: {cycle['status']}")

        if cycle["status"] != STATUS_COMPLETED and int(cycle.get("total_qty", 0)) > 0:
            raise Exception(f"보유 주식이 있는 사이클은 삭제할 수 없습니다. ({cycle['symbol']} {cycle['total_qty']}주)")

        symbol = cycle["symbol"]
        cycle_number = cycle.get("cycle_number", "?")

        # 관련 거래 레코드 전체 삭제 (페이징 제한 우회)
        while True:
            trades = trade_db.rows(cycle_id=cycle_id, dump=100)
            if not trades:
                break
            for trade in trades:
                trade_db.delete(id=trade["id"])

        # 관련 로그 전체 삭제
        while True:
            logs = log_db.rows(cycle_id=cycle_id, dump=100)
            if not logs:
                break
            for log in logs:
                log_db.delete(id=log["id"])

        # 사이클 삭제
        cycle_db.delete(id=cycle_id)

        # 삭제 로그 (사이클 없이 기록)
        self._log_event(symbol, "", "CYCLE_DELETE",
                        message=f"사이클 #{cycle_number} 삭제됨 ({symbol})")

        return {"deleted": True, "symbol": symbol, "cycle_number": cycle_number}

    def delete_trade(self, trade_id):
        """
        개별 거래 삭제 — 삭제 후 사이클 통계(total_spent, total_qty, avg_price, current_round) 재계산
        """
        trade_db = self._trade_db()
        cycle_db = self._cycle_db()
        trade = trade_db.get(id=trade_id)
        if not trade:
            raise Exception(f"거래를 찾을 수 없습니다: {trade_id}")

        cycle_id = trade.get("cycle_id", "")
        cycle = cycle_db.get(id=cycle_id) if cycle_id else None

        # 거래 레코드 삭제
        trade_db.delete(id=trade_id)

        # 사이클이 있으면 통계 재계산
        if cycle:
            remaining_trades = trade_db.rows(cycle_id=cycle_id, orderby="round", order="ASC")

            total_spent = 0.0
            total_qty = 0
            buy_round = 0

            for t in remaining_trades:
                action = t.get("action", "")
                if action == "BUY":
                    buy_round += 1
                    total_qty += int(t.get("filled_qty", 0))
                    total_spent += float(t.get("filled_amount", 0))
                elif action == "SELL":
                    total_qty -= int(t.get("filled_qty", 0))
                    total_spent -= float(t.get("filled_amount", 0))

            avg_price = (total_spent / total_qty) if total_qty > 0 else 0.0
            total_investment = float(cycle.get("total_investment", 0))
            remaining_investment = total_investment - total_spent

            now = self._now()
            cycle_db.update({
                "current_round": buy_round,
                "total_spent": round(total_spent, 4),
                "total_qty": max(total_qty, 0),
                "avg_price": round(avg_price, 6),
                "remaining_investment": round(max(remaining_investment, 0), 4),
                "updated": now,
            }, id=cycle_id)

            # 남은 trade의 round 번호 재정렬
            new_round = 0
            for t in remaining_trades:
                if t.get("action") == "BUY":
                    new_round += 1
                # 각 trade의 round를 재설정
                running_qty = 0
                running_spent = 0.0
                for prev_t in remaining_trades:
                    if prev_t["id"] == t["id"]:
                        break
                    if prev_t.get("action") == "BUY":
                        running_qty += int(prev_t.get("filled_qty", 0))
                        running_spent += float(prev_t.get("filled_amount", 0))
                    elif prev_t.get("action") == "SELL":
                        running_qty -= int(prev_t.get("filled_qty", 0))

                if t.get("action") == "BUY":
                    running_qty += int(t.get("filled_qty", 0))
                    running_spent += float(t.get("filled_amount", 0))

                new_avg = (running_spent / running_qty) if running_qty > 0 else 0.0
                update_data = {
                    "round": new_round if t.get("action") == "BUY" else new_round,
                    "avg_buy_price": round(new_avg, 6),
                    "total_qty_after": max(running_qty, 0),
                    "total_spent_after": round(running_spent, 4),
                }
                trade_db.update(update_data, id=t["id"])

            symbol = cycle.get("symbol", "")
            self._log_event(symbol, cycle_id, "TRADE_DELETE",
                            message=f"거래 삭제됨 (ID: {trade_id[:8]}...), 통계 재계산 완료")

            return {"deleted": True, "cycle_id": cycle_id, "recalculated": True}

        return {"deleted": True, "cycle_id": cycle_id, "recalculated": False}

    def _recalculate_cycle_from_trades(self, cycle_id):
        cycle_id = str(cycle_id or "").strip()
        if not cycle_id:
            return {"recalculated": False, "reason": "cycle_id_missing"}
        trade_db = self._trade_db()
        cycle_db = self._cycle_db()
        cycle = cycle_db.get(id=cycle_id)
        if not cycle:
            return {"recalculated": False, "reason": "cycle_missing"}

        rows = trade_db.rows(cycle_id=cycle_id, orderby="created", order="ASC", dump=1000) or []
        total_spent = 0.0
        total_qty = 0
        total_commission = 0.0
        buy_round = 0
        had_sell = False
        applied_rows = 0
        audit_only_rows = 0

        for row in rows:
            action = str((row or {}).get("action", "") or "").upper()
            status = str((row or {}).get("status", "") or "").upper()
            if self._is_synthetic_external_trade(row):
                audit_only_rows += 1
                continue
            if status and status != ORDER_FILLED:
                continue
            try:
                qty = int(float((row or {}).get("filled_qty", 0) or 0))
            except Exception:
                qty = 0
            try:
                price = float((row or {}).get("filled_price", 0) or 0)
            except Exception:
                price = 0.0
            try:
                amount = float((row or {}).get("filled_amount", 0) or 0)
            except Exception:
                amount = 0.0
            if amount <= 0 and qty > 0 and price > 0:
                amount = qty * price
            try:
                commission = float((row or {}).get("commission", 0) or 0)
            except Exception:
                commission = 0.0

            if action == ACTION_BUY:
                applied_rows += 1
                buy_round += 1
                total_qty += qty
                total_spent += amount + commission
                total_commission += commission
            elif action == ACTION_SELL:
                applied_rows += 1
                had_sell = True
                total_qty -= qty
                total_spent -= amount
                total_commission += commission

            running_qty = max(total_qty, 0)
            running_spent = max(total_spent, 0.0)
            running_avg = (running_spent / running_qty) if running_qty > 0 else 0.0
            try:
                trade_db.update({
                    "round": buy_round,
                    "avg_buy_price": round(running_avg, 6),
                    "total_qty_after": running_qty,
                    "total_spent_after": round(running_spent, 4),
                }, id=row["id"])
            except Exception:
                pass

        if applied_rows == 0 and audit_only_rows > 0:
            return {
                "recalculated": False,
                "reason": "audit_only_rows_do_not_change_cycle_totals",
                "cycle_id": cycle_id,
                "total_qty": int(float(cycle.get("total_qty", 0) or 0)),
                "total_spent": round(float(cycle.get("total_spent", 0) or 0), 2),
            }

        total_qty = max(total_qty, 0)
        total_spent = max(total_spent, 0.0)
        division_count = int(float(cycle.get("division_count", 0) or 0))
        remaining_investment = float(cycle.get("total_investment", 0) or 0) - total_spent
        avg_price = (total_spent / total_qty) if total_qty > 0 else 0.0
        status = str(cycle.get("status", STATUS_ACTIVE) or STATUS_ACTIVE)
        if total_qty <= 0 and had_sell:
            status = STATUS_COMPLETED
        elif status == STATUS_COMPLETED and total_qty > 0:
            status = STATUS_ACTIVE
        elif division_count > 0 and buy_round >= division_count and total_qty > 0:
            status = STATUS_PENDING_EXTENSION

        cycle_db.update({
            "current_round": buy_round,
            "total_spent": round(total_spent, 2),
            "total_qty": total_qty,
            "avg_price": round(avg_price, 4),
            "remaining_investment": round(max(remaining_investment, 0), 2),
            "total_commission": round(total_commission, 2),
            "status": status,
            "updated": self._now(),
        }, id=cycle_id)
        return {
            "recalculated": True,
            "cycle_id": cycle_id,
            "total_qty": total_qty,
            "total_spent": round(total_spent, 2),
            "current_round": buy_round,
            "status": status,
        }

    def update_cycle_params(self, cycle_id, target_profit=None, division_count=None, total_investment=None):
        """
        활성 사이클 파라미터 수정 — ACTIVE 또는 PAUSED 상태에서 변경 가능
        - target_profit: 목표 수익률 (%)
        - division_count: 분할 횟수 (current_round보다 작으면 거부)
        - total_investment: 총 투자금 (총 사용금보다 작으면 거부)
        """
        cycle_db = self._cycle_db()
        cycle = cycle_db.get(id=cycle_id)
        if not cycle:
            raise Exception(f"사이클을 찾을 수 없습니다: {cycle_id}")

        status = cycle["status"]
        if status not in [STATUS_ACTIVE, STATUS_PAUSED, STATUS_HOLDING, STATUS_PENDING_EXTENSION]:
            raise Exception(f"수정할 수 없는 상태입니다: {status}")

        update_data = {"updated": self._now()}
        changes = []
        current_round = int(cycle["current_round"])
        total_spent = float(cycle["total_spent"])

        if target_profit is not None:
            target_profit = float(target_profit)
            if target_profit <= 0 or target_profit > 100:
                raise Exception("목표 수익률은 0~100% 사이여야 합니다")
            old_val = float(cycle["target_profit"])
            update_data["target_profit"] = target_profit
            changes.append(f"목표수익률 {old_val}% → {target_profit}%")

        if division_count is not None:
            division_count = int(division_count)
            if division_count < current_round:
                raise Exception(f"분할 횟수는 현재 라운드({current_round}) 이상이어야 합니다")
            if division_count < 1 or division_count > 200:
                raise Exception("분할 횟수는 1~200 사이여야 합니다")
            old_val = int(cycle["division_count"])
            update_data["division_count"] = division_count
            changes.append(f"분할횟수 {old_val} → {division_count}")

        if total_investment is not None:
            total_investment = float(total_investment)
            if total_investment < total_spent:
                raise Exception(f"총 투자금은 이미 집행된 금액(${total_spent:.2f}) 이상이어야 합니다")
            old_val = float(cycle["total_investment"])
            update_data["total_investment"] = round(total_investment, 2)
            update_data["remaining_investment"] = round(total_investment - total_spent, 2)
            changes.append(f"투자금 ${old_val:.0f} → ${total_investment:.0f}")

        if not changes:
            raise Exception("변경할 항목이 없습니다")

        cycle_db.update(update_data, id=cycle_id)
        self._log_event(cycle["symbol"], cycle_id, "CYCLE_UPDATE",
                        message=f"사이클 #{cycle.get('cycle_number', '?')} 수정: {', '.join(changes)}")

        return cycle_db.get(id=cycle_id)

    def extend_cycle(self, cycle_id, extra_rounds, extra_investment=0):
        """
        사이클 연장 — PENDING_EXTENSION 상태에서 추가 매수 분할 진행
        - extra_rounds: 추가 분할 횟수 (10, 20, 40 등)
        - extra_investment: 추가 투자금 (0이면 기존 잔여금으로)
        - 상태를 ACTIVE로 전환
        """
        cycle_db = self._cycle_db()
        cycle = cycle_db.get(id=cycle_id)
        if not cycle:
            raise Exception(f"사이클을 찾을 수 없습니다: {cycle_id}")

        if cycle["status"] != STATUS_PENDING_EXTENSION:
            raise Exception(f"PENDING_EXTENSION 상태가 아닙니다: {cycle['status']}")

        extra_rounds = int(extra_rounds)
        extra_investment = float(extra_investment)
        if extra_rounds <= 0:
            raise Exception("추가 분할 횟수는 1 이상이어야 합니다.")

        old_division = int(cycle["division_count"])
        new_division = old_division + extra_rounds
        old_investment = float(cycle["total_investment"])
        new_investment = old_investment + extra_investment
        remaining = float(cycle["remaining_investment"]) + extra_investment

        now = self._now()
        cycle_db.update({
            "division_count": new_division,
            "total_investment": round(new_investment, 2),
            "remaining_investment": round(remaining, 2),
            "status": STATUS_ACTIVE,
            "updated": now,
        }, id=cycle_id)

        self._log_event(cycle["symbol"], cycle_id, "CYCLE_EXTEND",
                        message=f"사이클 #{cycle.get('cycle_number', '?')} 연장: "
                                f"{old_division}→{new_division}분할, "
                                f"추가 투자금 ${extra_investment:.2f}, "
                                f"잔여금 ${remaining:.2f}")

        return cycle_db.get(id=cycle_id)

    def keep_holding(self, cycle_id):
        """
        PENDING_EXTENSION → HOLDING 전환
        추가 매수 없이 매도 체크만 계속
        """
        cycle_db = self._cycle_db()
        cycle = cycle_db.get(id=cycle_id)
        if not cycle:
            raise Exception(f"사이클을 찾을 수 없습니다: {cycle_id}")

        if cycle["status"] != STATUS_PENDING_EXTENSION:
            raise Exception(f"PENDING_EXTENSION 상태가 아닙니다: {cycle['status']}")

        now = self._now()
        cycle_db.update({
            "status": STATUS_HOLDING,
            "updated": now,
        }, id=cycle_id)

        self._log_event(cycle["symbol"], cycle_id, "KEEP_HOLDING",
                        message=f"사이클 #{cycle.get('cycle_number', '?')} 홀딩 유지 선택 (추가 매수 안 함)")

        return cycle_db.get(id=cycle_id)

    def get_active_cycles(self):
        """활성 사이클 목록 조회 (ACTIVE + HOLDING + PAUSED + PENDING_EXTENSION)"""
        cycle_db = self._cycle_db()
        active = cycle_db.rows(status=STATUS_ACTIVE, order="ASC", orderby="started_at") or []
        holding = cycle_db.rows(status=STATUS_HOLDING, order="ASC", orderby="started_at") or []
        paused = cycle_db.rows(status=STATUS_PAUSED, order="ASC", orderby="started_at") or []
        pending = cycle_db.rows(status=STATUS_PENDING_EXTENSION, order="ASC", orderby="started_at") or []
        return active + holding + paused + pending

    # =========================================================================
    # 매수 판단 로직
    # =========================================================================

    def _round_down_cent(self, value):
        return math.floor(float(value or 0) * 100) / 100

    def _round_nearest_cent(self, value):
        return math.floor(float(value or 0) * 100 + 0.5) / 100

    def _firegate_extra_buy_unit(self, base_qty):
        base_qty = int(float(base_qty or 0))
        if base_qty > 100:
            return 10
        if base_qty > 50:
            return 5
        return 1

    def _firegate_v4_extra_buy_orders(self, one_turn, base_qty, first_price, avg_price_limit=0):
        one_turn = float(one_turn or 0)
        base_qty = int(float(base_qty or 0))
        first_price = float(first_price or 0)
        avg_price_limit = float(avg_price_limit or 0)
        unit = self._firegate_extra_buy_unit(base_qty)
        orders = []
        if one_turn <= 0 or base_qty <= 0 or first_price <= 0:
            return orders
        for index in range(1, 8):
            denom = base_qty + index * unit
            price = self._round_nearest_cent(one_turn / denom)
            if price < first_price and (avg_price_limit <= 0 or price < avg_price_limit):
                orders.append({"label": "LOC", "loc_price": price, "order_qty": unit, "order_type": "LOC"})
        return orders

    def _firegate_v4_t_value(self, cycle):
        value = (cycle or {}).get("t_value", None)
        if value in (None, ""):
            value = (cycle or {}).get("current_round", 0)
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    def _firegate_v4_reservation_avg_price(self, cycle):
        return float((cycle or {}).get("avg_price", 0) or 0)

    def _firegate_v4_invested_value(self, cycle):
        total_buy = (cycle or {}).get("total_buy", None)
        if total_buy in (None, ""):
            total_buy = (cycle or {}).get("total_spent", 0)
        total_sell = (cycle or {}).get("total_sell", 0)
        return float(total_buy or 0) - float(total_sell or 0)

    def _firegate_v4_remaining_seed(self, cycle):
        total_investment = float((cycle or {}).get("total_investment", 0) or 0)
        if (cycle or {}).get("_firegate_authoritative"):
            return max(total_investment - self._firegate_v4_invested_value(cycle), 0.0)
        try:
            remaining_investment = float((cycle or {}).get("remaining_investment", 0) or 0)
            if remaining_investment > 0:
                return remaining_investment
        except Exception:
            pass
        remaining = total_investment - self._firegate_v4_invested_value(cycle)
        if remaining < 0:
            remaining = float((cycle or {}).get("remaining_investment", 0) or 0)
        return max(remaining, 0.0)

    def _firegate_v4_investment_per_turn(self, cycle):
        division_count = max(int(float((cycle or {}).get("division_count", 20) or 20)), 1)
        remaining_turns = division_count - self._firegate_v4_t_value(cycle)
        if remaining_turns <= 0:
            return 0.0
        return self._firegate_v4_remaining_seed(cycle) / remaining_turns

    def _firegate_v4_star_percent(self, symbol, division_count, t_value):
        symbol = str(symbol or "").upper()
        division_count = int(float(division_count or 20))
        t_value = float(t_value or 0)
        if symbol == "TQQQ":
            if division_count == 20:
                return round(15 - 1.5 * t_value, 2)
            if division_count == 30:
                return round(15 - t_value, 2)
            return round(15 - 0.75 * t_value, 2)
        if division_count == 20:
            return round(20 - 2 * t_value, 2)
        if division_count == 30:
            return round(20 - (4 / 3) * t_value, 2)
        return round(20 - t_value, 2)

    def _firegate_star_percent(self, t_value, target_profit=None, symbol="", division_count=20):
        if symbol:
            return self._firegate_v4_star_percent(symbol, division_count, t_value)
        try:
            target_profit = float(target_profit or 0)
        except Exception:
            target_profit = 0.0
        if target_profit > 0:
            return round(target_profit, 2)
        return self._firegate_v4_star_percent("SOXL", division_count, t_value)

    def _firegate_v4_buy_decision(self, cycle, prev_close, buy_amount):
        current_round = int(cycle["current_round"])
        division_count = int(cycle["division_count"])
        total_investment = float(cycle["total_investment"])
        avg_price = float(cycle.get("avg_price", 0) or 0)
        total_qty = int(float(cycle.get("total_qty", 0) or 0))
        symbol = str(cycle.get("symbol", "") or "").upper()
        t_value = self._firegate_v4_t_value(cycle)
        one_turn = self._firegate_v4_investment_per_turn(cycle)
        if one_turn <= 0:
            one_turn = total_investment / max(division_count, 1)
        buy_orders = []

        if current_round <= 0 or total_qty <= 0 or avg_price <= 0:
            start_buy_method = str(self._get_config_value("buy_method", "firegate") or "firegate").strip().lower()
            if start_buy_method not in ("firegate", "market", "loc"):
                start_buy_method = "firegate"
            order_price = self._round_nearest_cent(float(prev_close or 0) * 1.12)
            if start_buy_method == "market":
                market_reference_price = round(float(prev_close or 0), 2)
                order_qty = int(one_turn / market_reference_price) if market_reference_price > 0 else 0
                if order_qty <= 0 and market_reference_price > 0:
                    order_qty = 1
                return {
                    "should_buy": order_qty > 0,
                    "algorithm": "firegate_v4",
                    "buy_amount": buy_amount,
                    "one_turn_amount": round(one_turn, 4),
                    "star_percent": 12.0,
                    "star_price": order_price,
                    "loc_price": market_reference_price,
                    "order_type": "MARKET",
                    "order_qty": order_qty,
                    "buy_orders": [],
                    "reason": "FireGate v4 1회차 시장가 매수",
                }
            order_qty = int(one_turn / order_price) if order_price > 0 else 0
            if order_qty <= 0 and order_price > 0:
                order_qty = 1
            first_order_type = "LOC" if start_buy_method == "loc" else "LIMIT"
            first_label = "LOC" if first_order_type == "LOC" else "지정가"
            buy_orders.append({
                "label": first_label,
                "loc_price": order_price,
                "order_qty": order_qty,
                "order_type": first_order_type,
            })
            buy_orders.extend(self._firegate_v4_extra_buy_orders(one_turn, order_qty, order_price))
            return {
                "should_buy": order_qty > 0,
                "algorithm": "firegate_v4",
                "buy_amount": buy_amount,
                "one_turn_amount": round(one_turn, 4),
                "star_percent": 12.0,
                "star_price": order_price,
                "loc_price": order_price,
                "order_type": first_order_type,
                "order_qty": order_qty,
                "buy_orders": buy_orders,
                "reason": (
                    "FireGate v4 1회차 LOC 매수 (전일종가 +12.00%)"
                    if first_order_type == "LOC"
                    else "FireGate v4 1회차 지정가 매수 (전일종가 +12.00%)"
                ),
            }

        avg_price = self._firegate_v4_reservation_avg_price(cycle)
        star_percent = self._firegate_star_percent(t_value, symbol=symbol, division_count=division_count)
        raw_star = avg_price * (1 + star_percent / 100)
        star_price = self._round_nearest_cent(raw_star)
        star_loc_price = self._round_nearest_cent(max(0.01, star_price - 0.01))

        is_first_half = t_value < (division_count / 2)
        if is_first_half:
            base_qty = int(one_turn / avg_price) if avg_price > 0 else 0
            star_qty = int((one_turn / 2) / star_loc_price) if star_loc_price > 0 else 0
            avg_qty = max(0, base_qty - star_qty)
            if avg_qty > 0:
                buy_orders.append({"label": "LOC 평단", "loc_price": round(avg_price, 2), "order_qty": avg_qty})
            if star_qty > 0:
                buy_orders.append({
                    "label": f"LOC ★{star_percent:g}%",
                    "loc_price": star_loc_price,
                    "order_qty": star_qty,
                })
            buy_orders.extend(self._firegate_v4_extra_buy_orders(one_turn, base_qty, star_loc_price, avg_price))
        else:
            star_qty = int(one_turn / star_loc_price) if star_loc_price > 0 else 0
            if star_qty > 0:
                buy_orders.append({
                    "label": f"LOC ★{star_percent:g}%",
                    "loc_price": star_loc_price,
                    "order_qty": star_qty,
                })
            buy_orders.extend(self._firegate_v4_extra_buy_orders(one_turn, star_qty, star_loc_price, avg_price))

        primary = buy_orders[0] if buy_orders else {}
        return {
            "should_buy": len(buy_orders) > 0 and int(primary.get("order_qty", 0) or 0) > 0,
            "algorithm": "firegate_v4",
            "buy_amount": buy_amount,
            "one_turn_amount": round(one_turn, 4),
            "star_percent": star_percent,
            "star_price": star_price,
            "loc_price": float(primary.get("loc_price", 0) or 0),
            "order_type": "LOC",
            "order_qty": int(primary.get("order_qty", 0) or 0),
            "buy_orders": buy_orders,
            "reason": f"FireGate v4 LOC 매수 계획 (★{star_percent:g}%)",
        }

    def calculate_buy_decision(self, cycle, prev_close):
        """
        매수 판단
        - cycle: trading_cycle 레코드
        - prev_close: 전일 종가
        반환: dict {should_buy, buy_amount, loc_price, order_type, reason}
        """
        current_round = int(cycle["current_round"])
        division_count = int(cycle["division_count"])
        total_investment = float(cycle["total_investment"])
        total_spent = float(cycle["total_spent"])
        avg_price = float(cycle["avg_price"])
        remaining_investment = float(cycle["remaining_investment"])

        # 40분할 소진 확인
        if current_round >= division_count:
            return {
                "should_buy": False,
                "buy_amount": 0,
                "loc_price": 0,
                "order_type": None,
                "order_qty": 0,
                "reason": f"분할 횟수 소진 ({current_round}/{division_count})",
            }

        next_round = current_round + 1
        remaining_rounds = division_count - current_round

        # 매수 예정금 계산
        buy_amount = remaining_investment / remaining_rounds if remaining_rounds > 0 else 0

        if buy_amount <= 0:
            return {
                "should_buy": False,
                "buy_amount": 0,
                "loc_price": 0,
                "order_type": None,
                "order_qty": 0,
                "reason": "잔여 투자금 없음",
            }

        if prev_close <= 0:
            return {
                "should_buy": False,
                "buy_amount": buy_amount,
                "loc_price": 0,
                "order_type": None,
                "order_qty": 0,
                "reason": "전일종가 없음",
            }

        return self._firegate_v4_buy_decision(cycle, prev_close, buy_amount)

    # =========================================================================
    # 매도 판단 로직
    # =========================================================================

    def calculate_target_sell_price(self, cycle):
        total_spent = float((cycle or {}).get("total_spent", 0) or 0)
        total_qty = int(float((cycle or {}).get("total_qty", 0) or 0))
        target_profit = float((cycle or {}).get("target_profit", 0) or 0)
        if total_spent <= 0 or total_qty <= 0:
            return 0
        rates = self._get_commission_rates()
        sell_rate = float(rates.get("sell_rate", 0) or 0) + float(rates.get("tax_rate", 0) or 0)
        target_net = total_spent * (1 + target_profit / 100)
        gross_required = target_net / max(1 - sell_rate, 0.000001)
        return round(gross_required / total_qty, 2)

    def _firegate_v4_target_sell_percent(self, symbol):
        return 15.0 if str(symbol or "").upper() == "TQQQ" else 20.0

    def _loc_sell_target_price(self, cycle):
        params = self._get_strategy_params()
        if str(params.get("sell_strategy", "firegate") or "firegate").lower() == "firegate":
            symbol = str((cycle or {}).get("symbol", "") or "").upper()
            avg_price = self._firegate_v4_reservation_avg_price(cycle)
            target_profit = (
                self._firegate_v4_target_sell_percent(symbol)
                if symbol in ("SOXL", "TQQQ")
                else float((cycle or {}).get("target_profit", 0) or 0)
            )
            if avg_price <= 0:
                total_spent = float((cycle or {}).get("total_spent", 0) or 0)
                total_qty = int(float((cycle or {}).get("total_qty", 0) or 0))
                avg_price = (total_spent / total_qty) if total_spent > 0 and total_qty > 0 else 0
            if avg_price > 0:
                return self._round_nearest_cent(avg_price * (1 + target_profit / 100))

        target_price = self.calculate_target_sell_price(cycle)
        if target_price > 0:
            return target_price
        avg_price = float((cycle or {}).get("avg_price", 0) or 0)
        target_profit = float((cycle or {}).get("target_profit", 0) or 0)
        if avg_price <= 0:
            return 0
        return round(avg_price * (1 + target_profit / 100), 2)

    def _firegate_v4_sell_orders(self, cycle):
        total_qty = int(float((cycle or {}).get("total_qty", 0) or 0))
        avg_price = self._firegate_v4_reservation_avg_price(cycle)
        if avg_price <= 0:
            total_spent = float((cycle or {}).get("total_spent", 0) or 0)
            avg_price = (total_spent / total_qty) if total_spent > 0 and total_qty > 0 else 0
        if total_qty <= 0 or avg_price <= 0:
            return []

        symbol = str((cycle or {}).get("symbol", "") or "").upper()
        division_count = max(int(float((cycle or {}).get("division_count", 20) or 20)), 1)
        t_value = self._firegate_v4_t_value(cycle)
        star_percent = self._firegate_v4_star_percent(symbol, division_count, t_value)
        star_price = self._round_nearest_cent(avg_price * (1 + star_percent / 100))
        target_percent = self._firegate_v4_target_sell_percent(symbol)
        target_price = self._round_nearest_cent(avg_price * (1 + target_percent / 100))
        force_loc_sell = str(self._get_config_value("sell_method", "firegate") or "firegate").lower() == "loc"

        loc_qty = int(math.floor(total_qty / 4))
        limit_qty = max(0, total_qty - loc_qty)
        orders = []
        if force_loc_sell:
            if loc_qty > 0 and star_price > 0:
                orders.append({
                    "label": f"FireGate LOC ★{star_percent:.2f}%",
                    "order_type": "LOC",
                    "order_qty": loc_qty,
                    "price": star_price,
                    "source": "firegate_loc_override",
                })
            if limit_qty > 0 and target_price > 0:
                orders.append({
                    "label": f"FireGate LOC +{target_percent:g}%",
                    "order_type": "LOC",
                    "order_qty": limit_qty,
                    "price": target_price,
                    "source": "firegate_loc_override",
                })
            return orders

        if loc_qty > 0 and star_price > 0:
            orders.append({
                "label": f"LOC ★{star_percent:.2f}%",
                "order_type": "LOC",
                "order_qty": loc_qty,
                "price": star_price,
            })
        if limit_qty > 0 and target_price > 0:
            orders.append({
                "label": f"지정가 +{target_percent:g}%",
                "order_type": "LIMIT",
                "order_qty": limit_qty,
                "price": target_price,
            })
        return orders

    def calculate_sell_decision(self, cycle, current_price):
        """
        매도 판단 (수수료 차감 후 순수익률 기준, 전략 반영)
        - cycle: trading_cycle 레코드
        - current_price: 현재가
        반환: dict {should_sell, sell_type, sell_qty, profit_rate, current_eval, reason}
            sell_type: "FULL_SELL" | "PARTIAL_SELL"
        """
        total_spent = float(cycle["total_spent"])
        total_qty = int(cycle["total_qty"])
        target_profit = float(cycle["target_profit"])
        total_commission = float(cycle.get("total_commission", 0))

        if total_qty <= 0 or total_spent <= 0:
            return {
                "should_sell": False,
                "sell_type": None,
                "sell_qty": 0,
                "profit_rate": 0.0,
                "current_eval": 0.0,
                "reason": "보유수량 없음",
            }

        current_eval = total_qty * current_price

        # 매도 시 예상 수수료 계산
        rates = self._get_commission_rates()
        sell_commission = self._calc_sell_commission(current_eval, rates)

        # 순수익 = 매도금액 - 총투입 - 누적매수수수료 - 매도수수료
        net_profit = current_eval - total_spent - total_commission - sell_commission
        profit_rate = (net_profit / total_spent) * 100

        params = self._get_strategy_params()
        sell_strategy = params.get("sell_strategy", "firegate")

        if sell_strategy == "partial":
            strat_mod = self._load_strategy_module()
            ps = strat_mod["PartialSellStrategy"](params)
            decision = ps.evaluate(cycle, profit_rate, target_profit)

            if decision["action"] in (STRATEGY_PARTIAL_SELL, STRATEGY_FULL_SELL):
                return {
                    "should_sell": True,
                    "sell_type": decision["action"],
                    "sell_qty": decision["sell_qty"],
                    "profit_rate": round(profit_rate, 2),
                    "current_eval": round(current_eval, 2),
                    "reason": decision["reason"],
                }

            return {
                "should_sell": False,
                "sell_type": None,
                "sell_qty": 0,
                "profit_rate": round(profit_rate, 2),
                "current_eval": round(current_eval, 2),
                "reason": decision["reason"],
            }

        is_firegate_default = sell_strategy == "firegate"
        if profit_rate < target_profit:
            return {
                "should_sell": False,
                "sell_type": None,
                "sell_qty": 0,
                "profit_rate": round(profit_rate, 2),
                "current_eval": round(current_eval, 2),
                "reason": f"{'FireGate 기본 · ' if is_firegate_default else ''}수익률 {profit_rate:.2f}% (목표: {target_profit}%)",
            }

        # 기본: 전량 매도
        return {
            "should_sell": True,
            "sell_type": STRATEGY_FULL_SELL,
            "sell_qty": total_qty,
            "profit_rate": round(profit_rate, 2),
            "current_eval": round(current_eval, 2),
            "reason": f"{'FireGate 기본 목표 도달' if is_firegate_default else '목표 수익률 도달'}! ({profit_rate:.2f}% >= {target_profit}%)",
        }

    # =========================================================================
    # 거래 실행 (매수)
    # =========================================================================

    def execute_buy(self, cycle_id, filled_price, filled_qty, order_type="LOC", order_price=0, trade_date="", broker_order_no="", source="", memo=""):
        """
        매수 체결 처리 (DB 업데이트)
        - 실제 주문은 kis_api를 통해 별도 실행
        - 이 메서드는 체결 후 DB 기록 용도
        """
        self._ensure_runtime_schema()
        cycle_db = self._cycle_db()
        trade_db = self._trade_db()
        cycle = cycle_db.get(id=cycle_id)
        if not cycle:
            raise Exception(f"사이클을 찾을 수 없습니다: {cycle_id}")

        now = self._now()
        trade_date = trade_date or now.strftime("%Y-%m-%d")

        filled_amount = filled_price * filled_qty

        # 수수료 계산
        rates = self._get_commission_rates()
        commission = self._calc_buy_commission(filled_amount, rates)

        current_round = int(cycle["current_round"]) + 1
        # 실비용 = 체결금액 + 수수료
        total_spent = float(cycle["total_spent"]) + filled_amount + commission
        total_qty = int(cycle["total_qty"]) + filled_qty
        avg_price = total_spent / total_qty if total_qty > 0 else 0
        remaining_investment = float(cycle["total_investment"]) - total_spent
        remaining_rounds = int(cycle["division_count"]) - current_round
        total_commission = float(cycle.get("total_commission", 0)) + commission

        # cycle_trade 기록
        trade_data = {
            "cycle_id": cycle_id,
            "symbol": cycle["symbol"],
            "round": current_round,
            "trade_date": trade_date,
            "action": ACTION_BUY,
            "order_type": order_type,
            "order_price": order_price,
            "order_qty": filled_qty,
            "filled_price": filled_price,
            "filled_qty": filled_qty,
            "filled_amount": round(filled_amount, 2),
            "commission": commission,
            "avg_buy_price": round(avg_price, 4),
            "total_qty_after": total_qty,
            "total_spent_after": round(total_spent, 2),
            "current_eval": 0,
            "profit_rate": 0,
            "remaining_investment": round(remaining_investment, 2),
            "remaining_rounds": max(remaining_rounds, 0),
            "strategy_type": STRATEGY_NORMAL,
            "status": ORDER_FILLED,
            "broker_order_no": str(broker_order_no or ""),
            "source": str(source or ""),
            "memo": str(memo or ""),
            "created": now,
        }
        trade_id = self._insert_trade_record(trade_db, trade_data)
        if trade_id:
            trade_data["id"] = trade_id

        # 사이클 상태 결정: 분할 소진 시 PENDING_EXTENSION
        new_status = STATUS_ACTIVE
        if current_round >= int(cycle["division_count"]):
            new_status = STATUS_PENDING_EXTENSION

        cycle_db.update({
            "current_round": current_round,
            "total_spent": round(total_spent, 2),
            "total_qty": total_qty,
            "avg_price": round(avg_price, 4),
            "remaining_investment": round(remaining_investment, 2),
            "total_commission": round(total_commission, 2),
            "status": new_status,
            "updated": now,
        }, id=cycle_id)

        self._log_event(cycle["symbol"], cycle_id, "BUY_FILLED",
                        action=ACTION_BUY,
                        message=f"R{current_round} 매수 체결: {filled_qty}주 @ ${filled_price:.2f}, 수수료 ${commission:.2f}")
        self._sync_trade_to_firegate(cycle_id, trade_data)

        # 분할 소진 시 알림 로그
        if new_status == STATUS_PENDING_EXTENSION:
            self._log_event(cycle["symbol"], cycle_id, "PENDING_EXTENSION",
                            message=f"사이클 #{cycle.get('cycle_number', '?')}: {int(cycle['division_count'])}회차 완료, 추가 매수 여부 선택 필요")

        return trade_data

    # =========================================================================
    # 거래 실행 (미체결 처리)
    # =========================================================================

    def record_skip(self, cycle_id, reason="미체결"):
        """
        미체결/스킵 기록 (회차 미진행, 투자금 유지)
        - SKIP은 매수 시도를 했으나 체결되지 않은 것이므로 회차를 소진하지 않음
        - cycle_trade에 SKIP 기록만 남기고, current_round는 유지
        """
        cycle_db = self._cycle_db()
        trade_db = self._trade_db()
        cycle = cycle_db.get(id=cycle_id)
        if not cycle:
            return

        now = self._now()
        current_round = int(cycle["current_round"])

        trade_data = {
            "cycle_id": cycle_id,
            "symbol": cycle["symbol"],
            "round": current_round,
            "trade_date": now.strftime("%Y-%m-%d"),
            "action": ACTION_SKIP,
            "order_type": "",
            "order_price": 0,
            "order_qty": 0,
            "filled_price": None,
            "filled_qty": 0,
            "filled_amount": 0,
            "commission": 0,
            "avg_buy_price": float(cycle["avg_price"]),
            "total_qty_after": int(cycle["total_qty"]),
            "total_spent_after": float(cycle["total_spent"]),
            "current_eval": 0,
            "profit_rate": 0,
            "remaining_investment": float(cycle["remaining_investment"]),
            "remaining_rounds": max(int(cycle["division_count"]) - current_round, 0),
            "status": ORDER_EXPIRED,
            "memo": reason,
            "created": now,
        }
        trade_id = self._insert_trade_record(trade_db, trade_data)
        if trade_id:
            trade_data["id"] = trade_id

        # SKIP은 회차를 소진하지 않으므로 current_round 업데이트 안 함
        # 상태도 변경하지 않음 (ACTIVE 유지)
        cycle_db.update({
            "updated": now,
        }, id=cycle_id)

        self._log_event(cycle["symbol"], cycle_id, "SKIP",
                        action=ACTION_SKIP,
                        message=f"R{current_round} SKIP: {reason}")

    # =========================================================================
    # 거래 실행 (매도)
    # =========================================================================

    def execute_sell(self, cycle_id, filled_price, filled_qty, order_type="MARKET", trade_date="", broker_order_no="", source="", memo=""):
        """
        매도 체결 처리 → 사이클 완료
        수수료/세금을 차감한 순수익으로 profit_rate 산출
        """
        self._ensure_runtime_schema()
        cycle_db = self._cycle_db()
        trade_db = self._trade_db()
        cycle = cycle_db.get(id=cycle_id)
        if not cycle:
            raise Exception(f"사이클을 찾을 수 없습니다: {cycle_id}")

        now = self._now()
        trade_date = trade_date or now.strftime("%Y-%m-%d")

        sell_amount = filled_price * filled_qty
        total_spent = float(cycle["total_spent"])
        total_commission_before = float(cycle.get("total_commission", 0))

        # 매도 수수료 + 세금 계산
        rates = self._get_commission_rates()
        sell_commission = self._calc_sell_commission(sell_amount, rates)
        total_commission = total_commission_before + sell_commission

        # 순수익률 = (매도금 - 매도수수료 - 총투입) / 총투입
        net_proceeds = sell_amount - sell_commission
        profit_rate = ((net_proceeds - total_spent) / total_spent * 100) if total_spent > 0 else 0

        trade_data = {
            "cycle_id": cycle_id,
            "symbol": cycle["symbol"],
            "round": int(cycle["current_round"]),
            "trade_date": trade_date,
            "action": ACTION_SELL,
            "order_type": order_type,
            "order_price": filled_price,
            "order_qty": filled_qty,
            "filled_price": filled_price,
            "filled_qty": filled_qty,
            "filled_amount": round(sell_amount, 2),
            "commission": sell_commission,
            "avg_buy_price": float(cycle["avg_price"]),
            "total_qty_after": 0,
            "total_spent_after": 0,
            "current_eval": round(net_proceeds, 2),
            "profit_rate": round(profit_rate, 2),
            "remaining_investment": 0,
            "remaining_rounds": 0,
            "strategy_type": STRATEGY_FULL_SELL,
            "status": ORDER_FILLED,
            "broker_order_no": str(broker_order_no or ""),
            "source": str(source or ""),
            "memo": str(memo or ""),
            "created": now,
        }
        trade_id = self._insert_trade_record(trade_db, trade_data)
        if trade_id:
            trade_data["id"] = trade_id

        # 사이클 완료
        cycle_db.update({
            "total_qty": 0,
            "total_spent": 0,
            "avg_price": 0,
            "current_price": filled_price,
            "current_eval": round(net_proceeds, 2),
            "profit_rate": round(profit_rate, 2),
            "total_commission": round(total_commission, 2),
            "remaining_investment": 0,
            "status": STATUS_COMPLETED,
            "completed_at": now,
            "updated": now,
        }, id=cycle_id)

        self._log_event(cycle["symbol"], cycle_id, "SELL_FILLED",
                        action=ACTION_SELL,
                        message=f"전량 매도 체결: {filled_qty}주 @ ${filled_price:.2f}, 수수료 ${sell_commission:.2f}, 순수익률 {profit_rate:.2f}%")
        self._sync_trade_to_firegate(cycle_id, trade_data)
        next_cycle = self._auto_start_next_cycle_after_completion(cycle_db.get(id=cycle_id))
        if next_cycle:
            trade_data["next_cycle_id"] = next_cycle.get("id", "")
            trade_data["next_cycle_number"] = next_cycle.get("cycle_number", "")

        return trade_data

    # =========================================================================
    # 거래 실행 (분할 매도 — 일부만 매도, 사이클 유지)
    # =========================================================================

    def execute_partial_sell(self, cycle_id, filled_price, filled_qty, order_type="MARKET", trade_date="", broker_order_no="", source="", memo=""):
        """
        분할 매도 체결 처리 → 사이클 유지
        - 매도된 수량만큼 total_qty, total_spent 비례 차감
        - 사이클 상태는 유지 (ACTIVE/HOLDING)
        """
        self._ensure_runtime_schema()
        cycle_db = self._cycle_db()
        trade_db = self._trade_db()
        cycle = cycle_db.get(id=cycle_id)
        if not cycle:
            raise Exception(f"사이클을 찾을 수 없습니다: {cycle_id}")

        now = self._now()
        trade_date = trade_date or now.strftime("%Y-%m-%d")

        total_qty = int(cycle["total_qty"])
        total_spent = float(cycle["total_spent"])
        total_commission_before = float(cycle.get("total_commission", 0))
        partial_sold_count = int(cycle.get("partial_sold_count", 0))
        remaining_investment_before = float(cycle.get("remaining_investment", 0))

        sell_amount = filled_price * filled_qty

        # 매도 수수료
        rates = self._get_commission_rates()
        sell_commission = self._calc_sell_commission(sell_amount, rates)
        net_proceeds = sell_amount - sell_commission

        # 매도 비율에 비례하여 비용 차감
        sell_ratio = filled_qty / total_qty if total_qty > 0 else 1
        sold_cost = total_spent * sell_ratio
        realized_profit = net_proceeds - sold_cost
        profit_rate = (realized_profit / sold_cost * 100) if sold_cost > 0 else 0

        # 잔량 상태
        remaining_qty = total_qty - filled_qty
        remaining_spent = total_spent - sold_cost
        remaining_avg = remaining_spent / remaining_qty if remaining_qty > 0 else 0
        total_commission = total_commission_before + sell_commission
        updated_remaining_investment = remaining_investment_before + net_proceeds
        updated_total_investment = remaining_spent + updated_remaining_investment

        trade_data = {
            "cycle_id": cycle_id,
            "symbol": cycle["symbol"],
            "round": int(cycle["current_round"]),
            "trade_date": trade_date,
            "action": ACTION_SELL,
            "order_type": order_type,
            "order_price": filled_price,
            "order_qty": filled_qty,
            "filled_price": filled_price,
            "filled_qty": filled_qty,
            "filled_amount": round(sell_amount, 2),
            "commission": sell_commission,
            "avg_buy_price": float(cycle["avg_price"]),
            "total_qty_after": remaining_qty,
            "total_spent_after": round(remaining_spent, 2),
            "current_eval": round(net_proceeds, 2),
            "profit_rate": round(profit_rate, 2),
            "remaining_investment": round(updated_remaining_investment, 2),
            "remaining_rounds": max(int(cycle["division_count"]) - int(cycle["current_round"]), 0),
            "strategy_type": STRATEGY_PARTIAL_SELL,
            "status": ORDER_FILLED,
            "broker_order_no": str(broker_order_no or ""),
            "source": str(source or ""),
            "memo": str(memo or ""),
            "created": now,
        }
        trade_id = self._insert_trade_record(trade_db, trade_data)
        if trade_id:
            trade_data["id"] = trade_id

        # 사이클 갱신 (유지)
        cycle_db.update({
            "total_investment": round(updated_total_investment, 2),
            "total_qty": remaining_qty,
            "total_spent": round(remaining_spent, 2),
            "avg_price": round(remaining_avg, 4),
            "current_price": filled_price,
            "remaining_investment": round(updated_remaining_investment, 2),
            "total_commission": round(total_commission, 2),
            "partial_sold_count": partial_sold_count + 1,
            "updated": now,
        }, id=cycle_id)

        self._log_event(cycle["symbol"], cycle_id, "PARTIAL_SELL_FILLED",
                        action=ACTION_SELL,
                        message=f"분할 매도 체결: {filled_qty}/{total_qty}주 @ ${filled_price:.2f}, "
                                f"수수료 ${sell_commission:.2f}, 실현수익 ${realized_profit:.2f}, "
                    f"재투입 가능금 ${updated_remaining_investment:.2f}, 잔량 {remaining_qty}주")
        self._sync_trade_to_firegate(cycle_id, trade_data)

        return trade_data

    # =========================================================================
    # 거래 실행 (폭락장 추가 매입 — 회차 소진 안 함)
    # =========================================================================

    def execute_crash_buy(self, cycle_id, filled_price, filled_qty):
        """
        폭락장 추가 매입 체결 처리
        - 회차(current_round)를 소진하지 않음
        - total_qty, total_spent 증가
        """
        cycle_db = self._cycle_db()
        trade_db = self._trade_db()
        cycle = cycle_db.get(id=cycle_id)
        if not cycle:
            raise Exception(f"사이클을 찾을 수 없습니다: {cycle_id}")

        now = self._now()
        trade_date = now.strftime("%Y-%m-%d")

        filled_amount = filled_price * filled_qty

        rates = self._get_commission_rates()
        commission = self._calc_buy_commission(filled_amount, rates)

        # 회차 소진 안 함 (current_round 유지)
        total_spent = float(cycle["total_spent"]) + filled_amount + commission
        total_qty = int(cycle["total_qty"]) + filled_qty
        avg_price = total_spent / total_qty if total_qty > 0 else 0
        remaining = float(cycle["remaining_investment"]) - (filled_amount + commission)
        total_commission = float(cycle.get("total_commission", 0)) + commission
        crash_buy_count = int(cycle.get("crash_buy_count", 0))

        trade_data = {
            "cycle_id": cycle_id,
            "symbol": cycle["symbol"],
            "round": int(cycle["current_round"]),  # 같은 회차
            "trade_date": trade_date,
            "action": ACTION_BUY,
            "order_type": "LOC",
            "order_price": filled_price,
            "order_qty": filled_qty,
            "filled_price": filled_price,
            "filled_qty": filled_qty,
            "filled_amount": round(filled_amount, 2),
            "commission": commission,
            "avg_buy_price": round(avg_price, 4),
            "total_qty_after": total_qty,
            "total_spent_after": round(total_spent, 2),
            "current_eval": 0,
            "profit_rate": 0,
            "remaining_investment": round(remaining, 2),
            "remaining_rounds": max(int(cycle["division_count"]) - int(cycle["current_round"]), 0),
            "strategy_type": STRATEGY_CRASH_BUY,
            "status": ORDER_FILLED,
            "memo": "폭락장 추가 매입",
            "created": now,
        }
        trade_id = self._insert_trade_record(trade_db, trade_data)
        if trade_id:
            trade_data["id"] = trade_id

        cycle_db.update({
            "total_spent": round(total_spent, 2),
            "total_qty": total_qty,
            "avg_price": round(avg_price, 4),
            "remaining_investment": round(remaining, 2),
            "total_commission": round(total_commission, 2),
            "crash_buy_count": crash_buy_count + 1,
            "updated": now,
        }, id=cycle_id)

        self._log_event(cycle["symbol"], cycle_id, "CRASH_BUY_FILLED",
                        action=ACTION_BUY,
                        message=f"폭락장 추가 매입: {filled_qty}주 @ ${filled_price:.2f}, "
                                f"수수료 ${commission:.2f}, 잔여금 ${remaining:.2f}")
        self._sync_trade_to_firegate(cycle_id, trade_data)

        return trade_data

    def _sync_trade_to_firegate(self, cycle_id, trade):
        """Best-effort FireGate transaction sync after a local fill is recorded."""
        try:
            fg = wiz.model("portal/trading/struct/firegate_bridge")
            cycle = self._cycle_db().get(id=cycle_id)
            result = fg.sync_cycle_trade(self.struct, cycle, trade) if cycle else {"synced": False, "reason": "cycle_missing"}
            if result and result.get("synced"):
                self._log_event((trade or {}).get("symbol", ""), cycle_id, "FIREGATE_TRADE_SYNCED",
                                action=(trade or {}).get("action", ""),
                                message=f"FireGate 거래 자동 반영: portfolio={result.get('portfolio_id')}, tx={result.get('transaction_id')}")
            elif result and result.get("reason") not in ("disabled", "not_configured", "unsupported_trade", "duplicate"):
                self._log_event((trade or {}).get("symbol", ""), cycle_id, "FIREGATE_TRADE_SYNC_SKIPPED",
                                action=(trade or {}).get("action", ""),
                                message=f"FireGate 거래 자동 반영 보류: {result.get('reason')}")
        except Exception as e:
            try:
                self._log_event((trade or {}).get("symbol", ""), cycle_id, "FIREGATE_TRADE_SYNC_ERROR",
                                action=(trade or {}).get("action", ""),
                                message=f"FireGate 거래 자동 반영 실패: {str(e)}")
            except Exception:
                pass

    # =========================================================================
    # 사이클 현재가/수익률 갱신
    # =========================================================================

    def update_cycle_price(self, cycle_id, current_price):
        """사이클의 현재가/평가금액/수익률 갱신 (수수료 고려)"""
        cycle_db = self._cycle_db()
        cycle = cycle_db.get(id=cycle_id)
        if not cycle:
            return

        total_qty = int(cycle["total_qty"])
        total_spent = float(cycle["total_spent"])
        total_commission = float(cycle.get("total_commission", 0))
        current_eval = total_qty * current_price

        # 예상 매도 수수료 반영한 순수익률
        rates = self._get_commission_rates()
        est_sell_commission = self._calc_sell_commission(current_eval, rates)
        net_profit = current_eval - total_spent - total_commission - est_sell_commission
        profit_rate = (net_profit / total_spent * 100) if total_spent > 0 else 0

        cycle_db.update({
            "current_price": current_price,
            "current_eval": round(current_eval, 2),
            "profit_rate": round(profit_rate, 2),
            "updated": self._now(),
        }, id=cycle_id)

    # =========================================================================
    # 일일 매매 판단 실행 (종목별)
    # =========================================================================

    def run_daily(self, symbol):
        """
        종목별 일일 매매 판단 및 실행 (전략 반영)
        1. 현재가 조회
        2. 매도 판단 (전량 매도 or 분할 매도)
        3. 폭락장 추가 매입 판단
        4. 매수 판단 (회차에 따라 시장가/LOC)
        반환: dict {action, detail}
        """
        kis_api = self._load_kis_api()

        # 활성 사이클 조회 (PENDING_EXTENSION도 매도 체크 대상)
        cycle_db = self._cycle_db()
        cycle = cycle_db.get(symbol=symbol, status=STATUS_ACTIVE)
        if not cycle:
            cycle = cycle_db.get(symbol=symbol, status=STATUS_HOLDING)
        if not cycle:
            cycle = cycle_db.get(symbol=symbol, status=STATUS_PENDING_EXTENSION)
        if not cycle:
            return {"action": "NONE", "detail": "활성 사이클 없음"}

        # 거래소 코드 조회
        order_exchange = self._get_exchange(symbol)
        price_exchange = self._price_exchange(order_exchange)
        resolved_order_exchange = order_exchange

        # 현재가 조회
        try:
            price_data = kis_api.get_current_price(symbol, exchange=price_exchange)
            current_price = price_data["price"]
            prev_close = price_data["prev_close"]
            resolved_order_exchange = price_data.get("order_exchange", order_exchange)
            if resolved_order_exchange != order_exchange:
                watchlist = self._watchlist_db()
                etf = watchlist.get(symbol=symbol)
                if etf:
                    watchlist.update({"exchange": resolved_order_exchange, "updated": self._now()}, id=etf["id"])
                order_exchange = resolved_order_exchange
        except Exception as e:
            self._log_event(symbol, cycle["id"], "ERROR", message=f"시세 조회 실패: {str(e)}")
            return {"action": "ERROR", "detail": str(e)}

        # 현재가 갱신
        self.update_cycle_price(cycle["id"], current_price)

        # 1) 매도 판단 (전략 반영 — 전량 or 분할)
        sell_decision = self.calculate_sell_decision(cycle, current_price)
        if sell_decision["should_sell"]:
            sell_type = sell_decision.get("sell_type", STRATEGY_FULL_SELL)
            sell_qty = sell_decision.get("sell_qty", int(cycle["total_qty"]))

            try:
                configured_sell_method = str(self._get_config_value("sell_method", "firegate") or "firegate").lower()
                sell_method = "LOC" if configured_sell_method == "loc" else "MARKET"
                sell_price = current_price if sell_method == "LOC" else 0
                order_result = kis_api.sell_order(symbol, sell_qty, price=sell_price, order_type=sell_method, exchange=order_exchange)

                if sell_type == STRATEGY_PARTIAL_SELL:
                    trade = self.execute_partial_sell(cycle["id"], current_price, sell_qty, order_type=sell_method)
                    return {
                        "action": "PARTIAL_SELL",
                        "detail": sell_decision["reason"],
                        "trade": trade,
                        "order": order_result,
                    }
                else:
                    trade = self.execute_sell(cycle["id"], current_price, sell_qty, order_type=sell_method)
                    return {
                        "action": "SELL",
                        "detail": sell_decision["reason"],
                        "trade": trade,
                        "order": order_result,
                    }
            except Exception as e:
                err_msg = str(e)
                detail_msg = (
                    f"매도 실패: {err_msg} | "
                    f"symbol={symbol}, qty={sell_decision.get('sell_qty')}, "
                    f"type={sell_decision.get('sell_type')}, "
                    f"exchange={order_exchange}"
                )
                self._log_event(symbol, cycle["id"], "SELL_ERROR", message=detail_msg)
                return {"action": "SELL_ERROR", "detail": detail_msg}

        # 2) 폭락장 추가 매입 판단
        params = self._get_strategy_params()
        if params.get("crash_buy_enabled"):
            strat_mod = self._load_strategy_module()
            crash_strat = strat_mod["CrashBuyStrategy"](params)
            crash_count = int(cycle.get("crash_buy_count", 0))

            # 5일 이동평균은 간이 계산 (prev_close 기준)
            crash_decision = crash_strat.evaluate(cycle, current_price, prev_close, ma5=None, crash_count=crash_count)
            if crash_decision["should_buy"]:
                try:
                    crash_qty = int(crash_decision["buy_amount"] / crash_decision["loc_price"]) if crash_decision["loc_price"] > 0 else 0
                    if crash_qty > 0:
                        order_result = kis_api.buy_order(symbol, crash_qty, price=crash_decision["loc_price"], order_type="LOC", exchange=order_exchange)
                        trade = self.execute_crash_buy(cycle["id"], crash_decision["loc_price"], crash_qty)
                        self._log_event(symbol, cycle["id"], "CRASH_BUY_ORDER",
                                        action=ACTION_BUY,
                                        message=f"폭락장 추가 매입 주문: {crash_qty}주 @ ${crash_decision['loc_price']:.2f}")
                except Exception as e:
                    self._log_event(symbol, cycle["id"], "CRASH_BUY_ERROR", message=str(e))

        # 3) PENDING_EXTENSION 또는 HOLDING 상태면 매수 안 함
        if cycle["status"] in [STATUS_HOLDING, STATUS_PENDING_EXTENSION]:
            label = "추가 매수 대기 중" if cycle["status"] == STATUS_PENDING_EXTENSION else "홀딩 중"
            return {
                "action": "HOLD",
                "detail": f"{label} - 수익률 {sell_decision['profit_rate']:.2f}%",
            }

        buy_decision = self.calculate_buy_decision(cycle, prev_close)
        if not buy_decision["should_buy"]:
            self.record_skip(cycle["id"], buy_decision["reason"])
            return {
                "action": "SKIP",
                "detail": buy_decision["reason"],
            }

        # 매수 주문 실행
        orderable_amount = 0.0
        try:
            buying_power_info = kis_api.get_buying_power_info(
                symbol=symbol,
                price=buy_decision["loc_price"],
                exchange=order_exchange,
            )
            max_qty = int(buying_power_info.get("executable_qty", buying_power_info.get("broker_qty", buying_power_info.get("qty", 0))) or 0)
            orderable_amount = float(buying_power_info.get("executable_amount", buying_power_info.get("broker_amount", buying_power_info.get("amount", 0))) or 0)
            estimated_amount = float(buying_power_info.get("amount", orderable_amount) or 0)
            auto_exchange_usd = float(buying_power_info.get("auto_exchange_usd", 0) or 0)
            requested_amount = float(buy_decision.get("order_qty", 0) or 0) * float(buy_decision.get("loc_price", 0) or 0)

            if buy_decision["order_qty"] > 0 and max_qty > 0 and buy_decision["order_qty"] > max_qty:
                buy_decision["order_qty"] = max_qty

            if buy_decision["order_qty"] <= 0 or orderable_amount + 1e-9 < requested_amount:
                detail_msg = (
                    f"주문 실패: 실제 해외 주문가능수량/금액이 부족합니다 | "
                    f"symbol={symbol}, orderable_amount=${orderable_amount:.2f}, "
                    f"requested_amount=${requested_amount:.2f}, exchange={order_exchange}"
                )
                if estimated_amount > orderable_amount + 0.01 or auto_exchange_usd > 0.01:
                    detail_msg += (
                        f", estimated_amount=${estimated_amount:.2f}, auto_exchange_usd=${auto_exchange_usd:.2f}"
                    )
                self._log_event(symbol, cycle["id"], "BUY_ERROR", message=detail_msg)
                self.record_skip(cycle["id"], detail_msg)
                return {"action": "BUY_ERROR", "detail": detail_msg}

            order_result = kis_api.buy_order(
                symbol,
                buy_decision["order_qty"],
                price=buy_decision["loc_price"],
                order_type=buy_decision["order_type"],
                exchange=order_exchange,
            )
            trade = self.execute_buy(
                cycle["id"],
                filled_price=buy_decision["loc_price"],
                filled_qty=buy_decision["order_qty"],
                order_type=buy_decision["order_type"],
                order_price=buy_decision["loc_price"],
            )
            return {
                "action": "BUY",
                "detail": buy_decision["reason"],
                "trade": trade,
                "order": order_result,
            }
        except Exception as e:
            err_msg = str(e)
            detail_msg = (
                f"주문 실패: {err_msg} | "
                f"symbol={symbol}, qty={buy_decision.get('order_qty')}, "
                f"price={buy_decision.get('loc_price')}, "
                f"type={buy_decision.get('order_type')}, "
                f"exchange={order_exchange}, "
                f"orderable_amount=${orderable_amount:.2f}"
            )
            self._log_event(symbol, cycle["id"], "BUY_ERROR", message=detail_msg)
            self.record_skip(cycle["id"], detail_msg)
            return {"action": "BUY_ERROR", "detail": detail_msg}

    # =========================================================================
    # LOC 매수 예약 (사전 접수)
    # =========================================================================

    def _loc_buy_auto_exchange_attempt_enabled(self):
        try:
            return str(self._get_config_value("us_auto_exchange_order_attempt_enabled", "true") or "true").lower() in ("1", "true", "yes", "y", "on")
        except Exception:
            return True

    def _reservation_order_exchange(self, exchange=""):
        code = str(exchange or "NASD").upper().strip()
        aliases = {
            "NAS": "NASD",
            "NASD": "NASD",
            "NASDAQ": "NASD",
            "NYS": "NYSE",
            "NYSE": "NYSE",
            "AMS": "AMEX",
            "AMEX": "AMEX",
        }
        return aliases.get(code, code or "NASD")

    def _reservation_order_symbol_key(self, symbol="", exchange=""):
        return f"{str(symbol or '').upper()}:{self._reservation_order_exchange(exchange)}"

    def _reservation_order_line_key(self, symbol="", exchange="", price=0):
        try:
            price = round(float(price or 0), 4)
        except Exception:
            price = 0.0
        return f"{self._reservation_order_symbol_key(symbol, exchange)}:{price:.4f}"

    def _reservation_query_start_date(self):
        now = self._now()
        if int(getattr(now, "hour", 0) or 0) < 7:
            now = now - datetime.timedelta(days=1)
        return now.strftime("%Y%m%d")

    def _reservation_order_no(self, order):
        for key in ("reserve_order_no", "order_no", "ovrs_rsvn_odno", "OVRS_RSVN_ODNO", "odno", "ODNO"):
            value = (order or {}).get(key)
            if value not in (None, ""):
                return str(value).strip()
        raw = (order or {}).get("raw", {}) or {}
        for key in ("OVRS_RSVN_ODNO", "ovrs_rsvn_odno", "ODNO", "odno"):
            value = raw.get(key)
            if value not in (None, ""):
                return str(value).strip()
        return ""

    def _reservation_order_is_active(self, order):
        cancel_yn = str((order or {}).get("cancel_yn", "") or "").strip().upper()
        if cancel_yn in ("Y", "YES", "CANCEL", "CANCELLED", "02", "2"):
            return False

        reject_reason = str((order or {}).get("reject_reason", "") or "").strip()
        if reject_reason != "":
            return False

        status_name = str((order or {}).get("status_name", "") or "")
        trade_status_name = str((order or {}).get("trade_status_name", "") or "")
        status_blob = f"{status_name} {trade_status_name}".lower()
        inactive_tokens = ["취소", "거부", "실패", "전송거부", "reject", "cancel", "fail", "expired"]
        return not any(token in status_blob for token in inactive_tokens)

    def _reservation_order_amount(self, order):
        qty = max(0, int(float((order or {}).get("qty", 0) or 0)) - int(float((order or {}).get("filled_qty", 0) or 0)))
        price = float((order or {}).get("price", 0) or 0)
        return round(qty * price, 4)

    def _reservation_order_remaining_qty(self, order):
        try:
            qty = int(float((order or {}).get("qty", 0) or 0))
            filled_qty = int(float((order or {}).get("filled_qty", 0) or 0))
        except Exception:
            return 0
        return max(0, qty - filled_qty)

    def _reservation_order_type(self, order):
        row = order or {}
        raw = row.get("raw", {}) or {}
        for key in ("order_type", "ord_dvsn", "ORD_DVSN", "ovrs_ord_dvsn", "OVRS_ORD_DVSN"):
            value = row.get(key)
            if value in (None, ""):
                value = raw.get(key)
            text = str(value or "").upper().strip()
            if text in ("LOC", "RESERVE_LOC", "34"):
                return "LOC"
            if text in ("LIMIT", "RESERVE_LIMIT", "00"):
                return "LIMIT"
        return ""

    def _append_extra_reservation_skips(self, skipped, expected_orders, reserved_line_map, side_label):
        expected_by_line = {}
        expected_types_by_line = {}
        expected_symbol_keys = set()
        for plan in expected_orders or []:
            line_key = str((plan or {}).get("line_key", "") or "")
            if not line_key:
                continue
            expected_by_line[line_key] = expected_by_line.get(line_key, 0) + int((plan or {}).get("order_qty", 0) or 0)
            order_type = str((plan or {}).get("order_type", "") or "").upper().strip()
            if order_type:
                expected_types_by_line.setdefault(line_key, set()).add(order_type)
            expected_symbol_keys.add(self._reservation_order_symbol_key((plan or {}).get("symbol", ""), (plan or {}).get("exchange", "NASD")))

        seen_extra_lines = {
            str((item or {}).get("line_key", "") or "")
            for item in (skipped or [])
            if isinstance(item, dict) and str((item or {}).get("line_key", "") or "")
        }
        for line_key, reservations in (reserved_line_map or {}).items():
            if not reservations:
                continue
            first = reservations[0] or {}
            symbol = str(first.get("symbol", "") or "").upper()
            exchange = str(first.get("exchange", "NASD") or "NASD").upper()
            symbol_key = self._reservation_order_symbol_key(symbol, exchange)
            if symbol_key not in expected_symbol_keys:
                continue
            if line_key in seen_extra_lines:
                continue
            seen_extra_lines.add(line_key)

            expected_qty = int(expected_by_line.get(line_key, 0) or 0)
            existing_qty = sum(self._reservation_order_remaining_qty(order) for order in reservations)
            expected_types = expected_types_by_line.get(line_key, set())
            wrong_type = ""
            if expected_types:
                for order in reservations:
                    reservation_type = self._reservation_order_type(order)
                    if reservation_type and reservation_type not in expected_types:
                        wrong_type = reservation_type
                        break
            if expected_qty > 0 and existing_qty == expected_qty:
                if not wrong_type:
                    continue
            price = float(first.get("price", 0) or 0)
            if wrong_type:
                reason = (
                    f"FireGate {side_label} 예약 주문방식 불일치: symbol={symbol}, price=${price:.2f}, "
                    f"expected_type={','.join(sorted(expected_types))}, active_type={wrong_type}. "
                    f"전체 취소 후 FireGate 표대로 재예약 필요"
                )
            elif expected_qty > 0:
                reason = (
                    f"FireGate {side_label} 예약 수량 불일치: symbol={symbol}, price=${price:.2f}, "
                    f"expected_qty={expected_qty}, active_qty={existing_qty}. 전체 취소 후 FireGate 표대로 재예약 필요"
                )
            else:
                reason = (
                    f"FireGate {side_label} 표에 없는 예약 감지: symbol={symbol}, price=${price:.2f}, "
                    f"active_qty={existing_qty}. 전체 취소 후 FireGate 표대로 재예약 필요"
                )
            skipped.append({
                "symbol": symbol,
                "exchange": exchange,
                "label": f"EXTRA_{side_label}",
                "price": price,
                "expected_qty": expected_qty,
                "active_qty": existing_qty,
                "expected_order_type": ",".join(sorted(expected_types)),
                "active_order_type": wrong_type,
                "force_rebuild": True,
                "reason": reason,
            })

    def _reservation_mismatch_skips(self, symbol, exchange, expected_orders, reserved_line_map, side_label, cycle_id=""):
        symbol = str(symbol or "").upper().strip()
        symbol_key = self._reservation_order_symbol_key(symbol, exchange)
        expected_by_line = {}
        expected_types_by_line = {}
        for plan in expected_orders or []:
            line_key = str((plan or {}).get("line_key", "") or "")
            if not line_key:
                continue
            expected_by_line[line_key] = expected_by_line.get(line_key, 0) + int((plan or {}).get("order_qty", 0) or 0)
            order_type = str((plan or {}).get("order_type", "") or "").upper().strip()
            if order_type:
                expected_types_by_line.setdefault(line_key, set()).add(order_type)

        skipped = []
        seen = set()

        def append_skip(line_key, reservations, expected_qty=0, expected_types=None, reason_kind="qty"):
            if line_key in seen:
                return
            seen.add(line_key)
            first = (reservations or [{}])[0] or {}
            price = float(first.get("price", 0) or 0)
            existing_qty = sum(self._reservation_order_remaining_qty(order) for order in (reservations or []))
            active_types = {
                self._reservation_order_type(order)
                for order in (reservations or [])
                if self._reservation_order_type(order)
            }
            expected_type_text = ",".join(sorted(expected_types or []))
            active_type_text = ",".join(sorted(active_types))
            if reason_kind == "type":
                reason = (
                    f"FireGate {side_label} 예약 주문방식 불일치: symbol={symbol}, price=${price:.2f}, "
                    f"expected_type={expected_type_text}, active_type={active_type_text or 'unknown'}. "
                    f"전체 취소 후 FireGate 표대로 재예약 필요"
                )
            elif expected_qty > 0:
                reason = (
                    f"FireGate {side_label} 예약 수량 불일치: symbol={symbol}, price=${price:.2f}, "
                    f"expected_qty={expected_qty}, active_qty={existing_qty}, "
                    f"expected_type={expected_type_text or 'unknown'}, active_type={active_type_text or 'unknown'}. "
                    f"전체 취소 후 FireGate 표대로 재예약 필요"
                )
            else:
                reason = (
                    f"FireGate {side_label} 표에 없는 예약 감지: symbol={symbol}, price=${price:.2f}, "
                    f"active_qty={existing_qty}. 전체 취소 후 FireGate 표대로 재예약 필요"
                )
            skipped.append({
                "symbol": symbol,
                "exchange": self._reservation_order_exchange(exchange),
                "cycle_id": cycle_id,
                "label": f"MISMATCH_{side_label}",
                "price": price,
                "expected_qty": expected_qty,
                "active_qty": existing_qty,
                "expected_order_type": expected_type_text,
                "active_order_type": active_type_text,
                "line_key": line_key,
                "force_rebuild": True,
                "reason": reason,
            })

        for line_key, expected_qty in expected_by_line.items():
            reservations = reserved_line_map.get(line_key, [])
            if not reservations:
                continue
            expected_types = expected_types_by_line.get(line_key, set())
            existing_qty = sum(self._reservation_order_remaining_qty(order) for order in reservations)
            active_types = {
                self._reservation_order_type(order)
                for order in reservations
                if self._reservation_order_type(order)
            }
            wrong_type = bool(active_types and expected_types and any(order_type not in expected_types for order_type in active_types))
            if wrong_type:
                append_skip(line_key, reservations, expected_qty, expected_types, reason_kind="type")
            elif existing_qty != expected_qty:
                append_skip(line_key, reservations, expected_qty, expected_types, reason_kind="qty")

        for line_key, reservations in (reserved_line_map or {}).items():
            if line_key in expected_by_line or not reservations:
                continue
            first = reservations[0] or {}
            reserved_symbol_key = self._reservation_order_symbol_key(first.get("symbol", ""), first.get("exchange", exchange))
            if reserved_symbol_key != symbol_key:
                continue
            append_skip(line_key, reservations, 0, set(), reason_kind="extra")

        return skipped

    def cancel_active_loc_reservations(self, symbols=None, side="", start_date=None):
        kis_api = self._load_kis_api()
        if not kis_api:
            return {"status": "error", "cancelled_count": 0, "error_count": 1, "errors": [{"reason": "브로커 API 미설정"}]}

        cancel_fn = getattr(kis_api, "cancel_overseas_reservation_order", None)
        if not callable(cancel_fn):
            return {"status": "error", "cancelled_count": 0, "error_count": 1, "errors": [{"reason": "해외 예약주문 취소 API 미지원"}]}

        symbol_set = {str(symbol or "").upper().strip() for symbol in (symbols or []) if str(symbol or "").strip()}
        side = str(side or "").upper().strip()
        start_date = start_date or self._reservation_query_start_date()
        cancelled = []
        skipped = []
        errors = []
        self._clear_reservation_order_cache()
        try:
            with self._broker_request_options(kis_api, timeout=4.0, retries=0):
                reservation_orders = kis_api.get_overseas_reservation_orders(start_date=start_date) or []
        except Exception as e:
            return {"status": "error", "cancelled_count": 0, "error_count": 1, "errors": [{"reason": str(e)}]}

        for order in reservation_orders:
            order_symbol = str((order or {}).get("symbol", "") or "").upper()
            order_side = str((order or {}).get("side", "") or "").upper()
            if symbol_set and order_symbol not in symbol_set:
                continue
            if side and order_side != side:
                continue
            if self._reservation_order_is_active(order) is False:
                skipped.append({"symbol": order_symbol, "side": order_side, "reason": "inactive"})
                continue
            order_no = self._reservation_order_no(order)
            if not order_no:
                errors.append({"symbol": order_symbol, "side": order_side, "reason": "예약주문번호 없음"})
                continue
            try:
                qty = self._reservation_order_remaining_qty(order)
                result = cancel_fn(
                    order_no,
                    symbol=order_symbol,
                    qty=qty,
                    exchange=(order or {}).get("exchange", "NASD"),
                    side=order_side,
                    receipt_date=(order or {}).get("receipt_date", (order or {}).get("order_date", "")),
                )
                cancelled.append({
                    "symbol": order_symbol,
                    "side": order_side,
                    "order_no": order_no,
                    "receipt_date": (order or {}).get("receipt_date", (order or {}).get("order_date", "")),
                    "qty": qty,
                    "price": float((order or {}).get("price", 0) or 0),
                    "result": result,
                })
                self._log_event(
                    order_symbol,
                    "",
                    "LOC_RESERVATION_CANCELLED",
                    action=order_side,
                    message=f"예약 재구성을 위해 기존 {order_side or '주문'} 예약 취소: {order_no}",
                )
            except Exception as e:
                reason = str(e)
                reason_lower = reason.lower()
                already_cancelled = (
                    "이미 취소처리" in reason
                    or "이미 취소" in reason
                    or ("already" in reason_lower and "cancel" in reason_lower)
                )
                if already_cancelled:
                    skipped.append({
                        "symbol": order_symbol,
                        "side": order_side,
                        "order_no": order_no,
                        "reason": reason,
                        "inactive": True,
                    })
                    continue
                errors.append({"symbol": order_symbol, "side": order_side, "order_no": order_no, "reason": reason})

        self._clear_reservation_order_cache()
        status = "completed" if not errors else ("partial_error" if cancelled else "error")
        return {
            "status": status,
            "cancelled_count": len(cancelled),
            "skipped_count": len(skipped),
            "error_count": len(errors),
            "cancelled": cancelled,
            "skipped": skipped,
            "errors": errors,
        }

    def _active_reservations_for_symbols(self, symbols=None, side="", start_date=None):
        kis_api = self._load_kis_api()
        if not kis_api:
            return []
        symbol_set = {str(symbol or "").upper().strip() for symbol in (symbols or []) if str(symbol or "").strip()}
        side = str(side or "").upper().strip()
        start_date = start_date or self._reservation_query_start_date()
        try:
            reservation_orders = self._load_reservation_orders(kis_api, start_date=start_date, timeout=4.0)
        except Exception as e:
            return None

        active = []
        for order in reservation_orders:
            order_symbol = str((order or {}).get("symbol", "") or "").upper()
            order_side = str((order or {}).get("side", "") or "").upper()
            if symbol_set and order_symbol not in symbol_set:
                continue
            if side and order_side != side:
                continue
            if self._reservation_order_is_active(order) is False:
                continue
            active.append(order)
        return active

    def rebuild_loc_reservations(self, symbols=None):
        symbols = [str(symbol or "").upper().strip() for symbol in (symbols or []) if str(symbol or "").strip()]
        symbols = list(dict.fromkeys(symbols))
        if not symbols:
            derived = []
            try:
                for item in self._watchlist_db().rows(is_active=True, orderby="created", order="ASC", dump=500) or []:
                    symbol = str((item or {}).get("symbol", "") or "").upper().strip()
                    if symbol:
                        derived.append(symbol)
            except Exception:
                pass
            try:
                for status in [STATUS_ACTIVE, STATUS_HOLDING, STATUS_PENDING_EXTENSION]:
                    for cycle in self._cycle_db().rows(status=status, orderby="created", order="ASC", dump=500) or []:
                        symbol = str((cycle or {}).get("symbol", "") or "").upper().strip()
                        if symbol:
                            derived.append(symbol)
            except Exception:
                pass
            symbols = list(dict.fromkeys(derived))
        if not symbols:
            return {"status": "skipped", "message": "재예약 대상 종목 없음", "symbols": []}

        cancel_result = self.cancel_active_loc_reservations(symbols=symbols)
        cancel_result["passes"] = [dict(cancel_result)]
        if int(cancel_result.get("error_count", 0) or 0) > 0:
            return {
                "status": "error",
                "symbols": symbols,
                "message": "기존 예약 취소 실패로 새 예약을 접수하지 않았습니다.",
                "cancel": cancel_result,
                "buy": [],
                "sell": [],
                "error_count": int(cancel_result.get("error_count", 0) or 0),
            }

        remaining_active = []
        empty_confirmations = 0
        for attempt in range(6):
            remaining_active = self._active_reservations_for_symbols(symbols=symbols)
            if remaining_active is None:
                return {
                    "status": "partial_pending",
                    "symbols": symbols,
                    "message": "기존 예약 취소 확인 조회가 실패해 새 예약을 접수하지 않았습니다. 다음 주기에 다시 확인합니다.",
                    "cancel": cancel_result,
                    "remaining_active_count": 0,
                    "empty_confirmations": empty_confirmations,
                    "buy": [],
                    "sell": [],
                    "error_count": 0,
                    "reservation_query_failed": True,
                }
            if not remaining_active:
                empty_confirmations += 1
                if empty_confirmations >= 2:
                    break
            else:
                empty_confirmations = 0
                extra_cancel = self.cancel_active_loc_reservations(symbols=symbols)
                cancel_result.setdefault("passes", []).append(dict(extra_cancel))
                for key in ("cancelled", "skipped", "errors"):
                    cancel_result.setdefault(key, [])
                    cancel_result[key].extend(extra_cancel.get(key, []) or [])
                cancel_result["cancelled_count"] = int(cancel_result.get("cancelled_count", 0) or 0) + int(extra_cancel.get("cancelled_count", 0) or 0)
                cancel_result["skipped_count"] = int(cancel_result.get("skipped_count", 0) or 0) + int(extra_cancel.get("skipped_count", 0) or 0)
                cancel_result["error_count"] = int(cancel_result.get("error_count", 0) or 0) + int(extra_cancel.get("error_count", 0) or 0)
                if int(extra_cancel.get("error_count", 0) or 0) > 0:
                    return {
                        "status": "error",
                        "symbols": symbols,
                        "message": "기존 예약 추가 취소 실패로 새 예약을 접수하지 않았습니다.",
                        "cancel": cancel_result,
                        "buy": [],
                        "sell": [],
                        "error_count": int(cancel_result.get("error_count", 0) or 0),
                    }
            if attempt < 5:
                time.sleep(1.0)
        if remaining_active or empty_confirmations < 2:
            return {
                "status": "partial_pending",
                "symbols": symbols,
                "message": "기존 예약 취소가 아직 브로커 조회에 안정적으로 반영되지 않아 새 예약을 보류했습니다.",
                "cancel": cancel_result,
                "remaining_active_count": len(remaining_active),
                "empty_confirmations": empty_confirmations,
                "remaining_active": remaining_active,
                "buy": [],
                "sell": [],
                "error_count": 0,
            }

        expected_preview = self._loc_reservation_expected_order_preview(symbols)
        max_order_count = int(expected_preview.get("max_order_count", 60) or 60)
        expected_order_count = int(expected_preview.get("expected_order_count", 0) or 0)
        if expected_order_count > max_order_count:
            message = (
                f"FireGate 기준 기대 예약 {expected_order_count}건이 안전 한도 {max_order_count}건을 초과해 "
                "새 예약을 접수하지 않았습니다. 중복 사이클/관심종목을 먼저 정리해야 합니다."
            )
            for symbol in symbols:
                self._log_event(symbol, "", "LOC_RESERVATION_SAFETY_BLOCK", message=message)
            return {
                "status": "safety_blocked",
                "symbols": symbols,
                "message": message,
                "cancel": cancel_result,
                "expected_preview": expected_preview,
                "buy": [],
                "sell": [],
                "error_count": 1,
            }

        buy_results = []
        sell_results = []
        for symbol in symbols:
            buy_results.append({"symbol": symbol, "result": self.schedule_loc_buys(symbol_filter=symbol)})
            sell_results.append({"symbol": symbol, "result": self.schedule_loc_sells(symbol_filter=symbol)})

        error_count = int(cancel_result.get("error_count", 0) or 0)
        for group in (buy_results, sell_results):
            for item in group:
                result = item.get("result") or {}
                error_count += int(result.get("error_count", 0) or 0)
                error_count += int(result.get("missing_count", 0) or 0)

        status = "completed" if error_count <= 0 else "partial_error"
        return {
            "status": status,
            "symbols": symbols,
            "cancel": cancel_result,
            "expected_preview": expected_preview,
            "buy": buy_results,
            "sell": sell_results,
            "error_count": error_count,
        }

    def _loc_schedule_result(self, orders, already_scheduled, skipped, errors, expected_orders, satisfied_line_keys, extra=None):
        expected_orders = list(expected_orders or [])
        satisfied = set(satisfied_line_keys or [])
        missing = []
        for plan in expected_orders:
            if plan.get("line_key") not in satisfied:
                missing.append({k: v for k, v in plan.items() if k != "line_key"})
        missing_count = len(missing)
        error_count = len(errors or [])
        force_rebuild_count = sum(1 for item in (skipped or []) if bool((item or {}).get("force_rebuild", False)))
        if error_count > 0:
            status = "partial_error" if len(satisfied) > 0 or len(already_scheduled or []) > 0 or len(orders or []) > 0 else "error"
        elif missing_count > 0 or force_rebuild_count > 0:
            status = "partial_pending"
        else:
            status = "completed"
        payload = {
            "status": status,
            "complete": status == "completed" and error_count == 0 and missing_count == 0,
            "scheduled_count": len(orders or []),
            "already_scheduled_count": len(already_scheduled or []),
            "skipped_count": len(skipped or []),
            "error_count": error_count,
            "expected_count": len(expected_orders),
            "satisfied_count": len(satisfied),
            "missing_count": missing_count,
            "force_rebuild_count": force_rebuild_count,
            "orders": orders or [],
            "already_scheduled": already_scheduled or [],
            "skipped": skipped or [],
            "errors": errors or [],
            "missing": missing,
            "expected": [{k: v for k, v in (plan or {}).items() if k != "line_key"} for plan in expected_orders],
        }
        if extra:
            payload.update(extra)
        return payload

    def _loc_reservation_max_orders_per_rebuild(self):
        try:
            return max(1, int(float(self.struct.get_config("loc_reservation_max_orders_per_rebuild", "60") or 60)))
        except Exception:
            return 60

    def _loc_reservation_expected_order_preview(self, symbols):
        previews = []
        total_expected = 0
        total_force_rebuild = 0
        for symbol in symbols or []:
            try:
                buy = self.schedule_loc_buys(symbol_filter=symbol, allow_new_orders=False)
            except Exception as e:
                buy = {"status": "error", "expected_count": 0, "error_count": 1, "errors": [{"reason": str(e)}]}
            try:
                sell = self.schedule_loc_sells(symbol_filter=symbol, allow_new_orders=False)
            except Exception as e:
                sell = {"status": "error", "expected_count": 0, "error_count": 1, "errors": [{"reason": str(e)}]}
            buy_expected = int((buy or {}).get("expected_count", 0) or 0)
            sell_expected = int((sell or {}).get("expected_count", 0) or 0)
            total_expected += buy_expected + sell_expected
            total_force_rebuild += int((buy or {}).get("force_rebuild_count", 0) or 0)
            total_force_rebuild += int((sell or {}).get("force_rebuild_count", 0) or 0)
            previews.append({
                "symbol": symbol,
                "buy_expected_count": buy_expected,
                "sell_expected_count": sell_expected,
                "buy_status": (buy or {}).get("status", ""),
                "sell_status": (sell or {}).get("status", ""),
                "buy_error_count": int((buy or {}).get("error_count", 0) or 0),
                "sell_error_count": int((sell or {}).get("error_count", 0) or 0),
            })
        return {
            "symbols": list(symbols or []),
            "expected_order_count": total_expected,
            "force_rebuild_count": total_force_rebuild,
            "max_order_count": self._loc_reservation_max_orders_per_rebuild(),
            "previews": previews,
        }

    def _display_trade_date(self, value):
        text = str(value or "").strip().replace("-", "")[:8]
        if len(text) == 8:
            return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        return self._now().strftime("%Y-%m-%d")

    def _find_external_cycle(self, symbol):
        cycle_db = self._cycle_db()
        for status in [STATUS_ACTIVE, STATUS_HOLDING, STATUS_PENDING_EXTENSION, STATUS_PAUSED]:
            cycle = cycle_db.get(symbol=symbol, status=status)
            if cycle:
                return cycle
        return None

    def _external_sync_target_symbols(self, symbol_filter=""):
        symbol_filter = str(symbol_filter or "").upper().strip()
        symbols = []
        seen = set()

        def add_symbol(value):
            symbol = str(value or "").upper().strip()
            if not symbol or symbol in seen:
                return
            if symbol_filter and symbol != symbol_filter:
                return
            seen.add(symbol)
            symbols.append(symbol)

        for cycle in self.get_active_cycles() or []:
            add_symbol((cycle or {}).get("symbol", ""))
        try:
            for item in self._watchlist_db().rows(orderby="created", order="ASC") or []:
                add_symbol((item or {}).get("symbol", ""))
        except Exception:
            pass

        for default_symbol in DEFAULT_INFINITY_SYMBOLS.keys():
            add_symbol(default_symbol)
        return symbols, seen

    def _default_infinity_watchlist_item(self, symbol):
        symbol = str(symbol or "").upper().strip()
        base = dict(DEFAULT_INFINITY_SYMBOLS.get(symbol) or {})
        if not base:
            return None
        try:
            default_division = int(float(self._get_config_value("default_division_count", base.get("division_count", 20)) or base.get("division_count", 20)))
        except Exception:
            default_division = int(base.get("division_count", 20) or 20)
        try:
            default_target = float(self._get_config_value("default_target_profit", base.get("target_profit", 10)) or base.get("target_profit", 10))
        except Exception:
            default_target = float(base.get("target_profit", 10) or 10)
        return {
            "symbol": symbol,
            "name": base.get("name", symbol),
            "exchange": base.get("exchange", "NASD"),
            "total_investment": float(base.get("total_investment", 10000.0) or 10000.0),
            "division_count": max(default_division, 1),
            "target_profit": default_target,
            "cycle_mode": CYCLE_MODE_AUTO,
            "is_active": True,
            "memo": "브로커 매수 체결 확인으로 자동 생성된 무한매수 기본 관심종목입니다.",
        }

    def _ensure_watchlist_for_external_fill(self, symbol):
        symbol = str(symbol or "").upper().strip()
        watchlist = self._watchlist_db()
        item = watchlist.get(symbol=symbol)
        now = self._now()
        if item:
            if not bool(item.get("is_active", False)):
                watchlist.update({"is_active": True, "updated": now}, id=item["id"])
                self._log_event(symbol, "", "WATCHLIST_AUTO_ACTIVATE",
                                message="브로커 매수 체결이 확인되어 무한매수 관심종목을 자동 활성화했습니다.")
                item = watchlist.get(symbol=symbol) or item
            return item

        data = self._default_infinity_watchlist_item(symbol)
        if not data:
            return None
        try:
            watchlist.insert({**data, "created": now, "updated": now})
            self._log_event(symbol, "", "WATCHLIST_AUTO_CREATE",
                            message="브로커 매수 체결이 확인되어 무한매수 관심종목과 사이클을 자동 생성합니다.")
        except Exception as e:
            self._log_event(symbol, "", "WATCHLIST_AUTO_CREATE_ERROR",
                            message=f"브로커 체결용 관심종목 자동 생성 실패: {str(e)}")
            return None
        return watchlist.get(symbol=symbol)

    def _ensure_external_buy_cycle(self, symbol):
        cycle = self._find_external_cycle(symbol)
        if cycle:
            return cycle, False
        try:
            item = self._ensure_watchlist_for_external_fill(symbol)
            if not item:
                return None, False
            return self.start_cycle(symbol), True
        except Exception as e:
            self._log_event(symbol, "", "EXTERNAL_CYCLE_START_ERROR", message=f"외부 매수 체결용 사이클 자동 생성 실패: {str(e)}")
            return None, False

    def _external_cycle_trade_seen(self, trade_db, order, trade_date):
        symbol = str((order or {}).get("symbol", "") or "").upper()
        action = str((order or {}).get("action", (order or {}).get("side", "")) or "").upper()
        order_no = str((order or {}).get("order_no", "") or "").strip()
        qty = int(float((order or {}).get("filled_qty", 0) or 0))
        price = round(float((order or {}).get("filled_price", 0) or 0), 4)
        if order_no:
            try:
                row = trade_db.get(broker_order_no=order_no)
                if row and not self._is_synthetic_external_trade(row):
                    return True
            except Exception:
                pass
        try:
            rows = trade_db.rows(symbol=symbol, action=action, trade_date=trade_date, orderby="created", order="DESC", dump=200) or []
        except Exception:
            rows = []
        for row in rows:
            if self._is_synthetic_external_trade(row):
                continue
            row_order_no = str(row.get("broker_order_no", "") or "").strip()
            if order_no and row_order_no == order_no:
                return True
            if order_no and row_order_no and row_order_no != order_no:
                continue
            same_qty = int(row.get("filled_qty", 0) or 0) == qty
            same_price = abs(float(row.get("filled_price", 0) or 0) - price) < 0.0001
            source = str(row.get("source", "") or "").upper()
            memo = str(row.get("memo", "") or "")
            if order_no and order_no in memo:
                return True
            if same_qty and same_price and (source in ("KIS", "TOSS", "BROKER", "") or "외부 체결 동기화" in memo):
                return True
        return False

    def _external_cycle_trade_existing(self, trade_db, order, trade_date):
        symbol = str((order or {}).get("symbol", "") or "").upper()
        action = str((order or {}).get("action", (order or {}).get("side", "")) or "").upper()
        order_no = str((order or {}).get("order_no", "") or "").strip()
        qty = int(float((order or {}).get("filled_qty", 0) or 0))
        price = round(float((order or {}).get("filled_price", 0) or 0), 4)
        if order_no:
            try:
                row = trade_db.get(broker_order_no=order_no)
                if row and not self._is_synthetic_external_trade(row):
                    return row
            except Exception:
                pass
        try:
            rows = trade_db.rows(symbol=symbol, action=action, trade_date=trade_date, orderby="created", order="DESC", dump=200) or []
        except Exception:
            rows = []
        for row in rows:
            if self._is_synthetic_external_trade(row):
                continue
            row_order_no = str((row or {}).get("broker_order_no", "") or "").strip()
            if order_no and row_order_no and row_order_no != order_no:
                continue
            if order_no and order_no in str((row or {}).get("memo", "") or ""):
                return row
            if not row_order_no:
                try:
                    row_qty = int(float((row or {}).get("filled_qty", 0) or (row or {}).get("order_qty", 0) or 0))
                except Exception:
                    row_qty = 0
                try:
                    row_price = round(float((row or {}).get("filled_price", 0) or (row or {}).get("order_price", 0) or 0), 4)
                except Exception:
                    row_price = 0.0
                if row_qty == qty and abs(row_price - price) < 0.0001:
                    return row
        return None

    def _external_order_created_at(self, order, trade_date):
        date_text = str(trade_date or "").strip()[:10]
        time_text = str((order or {}).get("order_time", "") or "").replace(":", "").strip()
        if len(time_text) < 6:
            time_text = (time_text + "000000")[:6]
        else:
            time_text = time_text[:6]
        try:
            return datetime.datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H%M%S")
        except Exception:
            try:
                return datetime.datetime.strptime(date_text, "%Y-%m-%d")
            except Exception:
                return self._now()

    def _external_order_sort_key(self, order):
        row = order or {}
        date_text = str(row.get("order_date", row.get("trade_date", row.get("date", ""))) or "").replace("-", "")[:8]
        time_text = str(row.get("order_time", row.get("filled_time", row.get("time", ""))) or "").replace(":", "")[:6]
        return f"{date_text}{time_text}{str(row.get('order_no', ''))}"

    def _external_order_history_key(self, order):
        row = order or {}
        try:
            filled_qty = int(float(row.get("filled_qty", 0) or 0))
        except Exception:
            filled_qty = 0
        try:
            filled_price = round(float(row.get("filled_price", 0) or 0), 4)
        except Exception:
            filled_price = 0.0
        return ":".join([
            str(row.get("exchange", "")),
            str(row.get("order_no", "")),
            str(row.get("symbol", "")).upper(),
            str(row.get("action", row.get("side", ""))).upper(),
            str(row.get("order_date", "")),
            str(row.get("order_time", "")),
            str(filled_qty),
            f"{filled_price:.4f}",
        ])

    def _collect_external_order_history_once(self, kis_api, symbols, start, today, exchanges):
        orders = []
        errors = []
        seen_history_keys = set()
        for target_symbol in symbols:
            current_day = start
            while current_day <= today:
                day_text = current_day.strftime("%Y%m%d")
                try:
                    symbol_orders = kis_api.get_overseas_order_history(
                        start_date=day_text,
                        end_date=day_text,
                        symbol=target_symbol,
                        exchanges=exchanges,
                    ) or []
                except Exception as e:
                    errors.append(f"{target_symbol}/{day_text}: {e}")
                    current_day += datetime.timedelta(days=1)
                    continue
                for order in symbol_orders:
                    key = self._external_order_history_key(order)
                    if key in seen_history_keys:
                        continue
                    seen_history_keys.add(key)
                    orders.append(order)
                current_day += datetime.timedelta(days=1)
        return orders, errors

    def _verified_external_order_history(self, kis_api, symbols, start, today, exchanges, passes=3):
        passes = max(1, int(passes or 3))
        snapshots = []
        all_orders = []
        for attempt in range(passes):
            orders, errors = self._collect_external_order_history_once(kis_api, symbols, start, today, exchanges)
            if errors:
                return {
                    "verified": False,
                    "orders": [],
                    "pass_count": attempt + 1,
                    "errors": errors,
                    "reason": "history_query_failed",
                }
            keys = tuple(sorted(self._external_order_history_key(order) for order in orders))
            snapshots.append(keys)
            all_orders = orders
            if attempt < passes - 1:
                time.sleep(0.15)
        stable = len({snapshot for snapshot in snapshots}) == 1
        if not stable:
            return {
                "verified": False,
                "orders": [],
                "pass_count": passes,
                "errors": [],
                "reason": "history_unstable",
                "snapshot_counts": [len(snapshot) for snapshot in snapshots],
            }
        return {
            "verified": True,
            "orders": all_orders,
            "pass_count": passes,
            "errors": [],
            "reason": "stable",
            "snapshot_counts": [len(snapshot) for snapshot in snapshots],
        }

    def _broker_holdings_by_symbol(self, kis_api, symbols):
        symbol_set = {str(symbol or "").upper().strip() for symbol in (symbols or []) if str(symbol or "").strip()}
        if not symbol_set:
            return {}
        try:
            balance = kis_api.get_balance() or {}
        except Exception:
            return {}
        holdings_by_symbol = {}
        for holding in (balance.get("holdings", []) or []):
            symbol = str((holding or {}).get("symbol", "") or "").upper().strip()
            if symbol not in symbol_set:
                continue
            try:
                qty = int(float((holding or {}).get("qty", 0) or 0))
            except Exception:
                qty = 0
            item = dict(holding or {})
            item["qty"] = qty
            holdings_by_symbol[symbol] = item
        return holdings_by_symbol

    def _broker_holding_qty_by_symbol(self, kis_api, symbols):
        holdings = self._broker_holdings_by_symbol(kis_api, symbols)
        return {symbol: int((holding or {}).get("qty", 0) or 0) for symbol, holding in holdings.items()}

    def _align_cycle_snapshot_to_broker_holdings(self, broker_holdings, symbols):
        """Align cycle position snapshot to broker balance without fabricating trade rows."""
        reconciled = []
        aligned = []
        unresolved = []
        errors = []
        for symbol in symbols or []:
            symbol = str(symbol or "").upper().strip()
            holding = broker_holdings.get(symbol, {}) if isinstance(broker_holdings, dict) else {}
            try:
                broker_qty = int(float((holding or {}).get("qty", 0) or 0))
            except Exception:
                broker_qty = 0
            cycle = self._find_external_cycle(symbol)
            try:
                local_qty = int(float((cycle or {}).get("total_qty", 0) or 0)) if cycle else 0
            except Exception:
                local_qty = 0
            diff = broker_qty - local_qty
            if diff == 0:
                continue
            if not cycle:
                unresolved.append({
                    "symbol": symbol,
                    "broker_qty": broker_qty,
                    "local_cycle_qty": local_qty,
                    "diff": diff,
                    "reason": "active_cycle_missing",
                    "source_of_truth": "broker_order_history",
                })
                continue
            reason = "broker_history_missing_buy_fill" if diff > 0 else "broker_history_missing_sell_fill_or_local_overcount"
            try:
                broker_avg = float((holding or {}).get("avg_price", 0) or 0)
            except Exception:
                broker_avg = 0.0
            try:
                current_price = float((holding or {}).get("current_price", 0) or 0)
            except Exception:
                current_price = 0.0
            old_avg = float((cycle or {}).get("avg_price", 0) or 0)
            avg_price = broker_avg if broker_avg > 0 else old_avg
            if avg_price > 0 and broker_qty > 0:
                total_spent = avg_price * broker_qty
            else:
                total_spent = float((cycle or {}).get("total_spent", 0) or 0)
            total_investment = float((cycle or {}).get("total_investment", 0) or 0)
            status = str((cycle or {}).get("status", STATUS_ACTIVE) or STATUS_ACTIVE)
            if broker_qty > 0 and status == STATUS_COMPLETED:
                status = STATUS_ACTIVE
            elif broker_qty <= 0:
                status = STATUS_COMPLETED
            update_data = {
                "total_qty": broker_qty,
                "total_spent": round(max(total_spent, 0.0), 2),
                "avg_price": round(avg_price, 4) if broker_qty > 0 else 0,
                "remaining_investment": round(max(total_investment - max(total_spent, 0.0), 0.0), 2),
                "status": status,
                "updated": self._now(),
            }
            if current_price > 0:
                update_data["current_price"] = current_price
                update_data["current_eval"] = round(current_price * broker_qty, 2)
                if total_spent > 0:
                    update_data["profit_rate"] = round(((current_price * broker_qty) - total_spent) / total_spent * 100, 2)
            try:
                self._cycle_db().update(update_data, id=cycle["id"])
                aligned.append({
                    "symbol": symbol,
                    "broker_qty": broker_qty,
                    "local_qty_before": local_qty,
                    "diff": diff,
                    "avg_price": update_data["avg_price"],
                    "total_spent": update_data["total_spent"],
                    "reason": reason,
                })
                self._log_event(
                    symbol,
                    cycle["id"],
                    "BROKER_HOLDING_SNAPSHOT_ALIGNED",
                    message=(
                        f"브로커 잔고 기준 사이클 스냅샷 정렬: "
                        f"broker_qty={broker_qty}, local_qty={local_qty}, diff={diff}"
                    ),
                )
            except Exception as e:
                errors.append({"symbol": symbol, "broker_qty": broker_qty, "local_cycle_qty": local_qty, "diff": diff, "reason": str(e)})
                continue
            unresolved.append({
                "symbol": symbol,
                "broker_qty": broker_qty,
                "local_cycle_qty": local_qty,
                "diff": diff,
                "reason": reason,
                "source_of_truth": "broker_order_history",
            })
        return {"reconciled": reconciled, "aligned": aligned, "unresolved": unresolved, "errors": errors}

    def sync_external_cycle_trades(self, lookback_days=7, symbol_filter=""):
        """
        KIS 해외 체결내역 중 사이트 밖에서 체결된 SOXL/TQQQ 등 무한매수 보유 종목을
        현재 사이클에 반영한다. broker_order_no 기준으로 중복 반영을 막는다.
        """
        self._ensure_runtime_schema()
        kis_api = self._load_kis_api()
        if not kis_api:
            return {"status": "skipped", "message": "브로커 API 미설정", "synced_count": 0, "orders": []}

        symbol_filter = str(symbol_filter or "").upper().strip()
        symbols, seen_symbols = self._external_sync_target_symbols(symbol_filter=symbol_filter)
        if not symbols:
            return {
                "status": "completed",
                "verified": True,
                "message": "동기화 대상 종목 없음",
                "synced_count": 0,
                "eligible_order_count": 0,
                "orders": [],
            }

        today = self._now().date()
        start = today - datetime.timedelta(days=max(1, int(lookback_days or 7)))
        try:
            cycle_db = self._cycle_db()
            for status in [STATUS_ACTIVE, STATUS_HOLDING, STATUS_PAUSED, STATUS_PENDING_EXTENSION]:
                for cycle in cycle_db.rows(status=status, orderby="created", order="ASC", dump=500) or []:
                    symbol = str((cycle or {}).get("symbol", "") or "").upper().strip()
                    if symbol not in seen_symbols:
                        continue
                    date_source = (cycle or {}).get("started_at") or (cycle or {}).get("created") or ""
                    if hasattr(date_source, "date"):
                        cycle_date = date_source.date()
                    else:
                        text = str(date_source or "")[:10]
                        cycle_date = datetime.datetime.strptime(text, "%Y-%m-%d").date() if text else None
                    if cycle_date:
                        start = min(start, cycle_date - datetime.timedelta(days=2))
        except Exception:
            pass
        start_date = start.strftime("%Y%m%d")
        end_date = today.strftime("%Y%m%d")
        trade_db = self._trade_db()
        synced = []
        skipped = []
        errors = []

        exchanges = ["NASD", "NYSE", "AMEX"]
        history_check = self._verified_external_order_history(kis_api, symbols, start, today, exchanges, passes=3)
        if not history_check.get("verified"):
            return {
                "status": "error",
                "verified": False,
                "message": "브로커 해외 체결 3회 교차 검증 실패로 로컬 기록을 변경하지 않았습니다.",
                "synced_count": 0,
                "orders": [],
                "errors": history_check.get("errors", []),
                "history_verification": history_check,
            }
        orders = history_check.get("orders", []) or []

        raw_order_count = len(orders)
        broker_holdings = self._broker_holdings_by_symbol(kis_api, symbols)
        broker_holding_qty = {symbol: int((holding or {}).get("qty", 0) or 0) for symbol, holding in broker_holdings.items()}
        eligible_order_count = 0
        already_synced_count = 0
        corrected_count = 0
        audited_count = 0
        unresolved = []
        audited = []
        for order in sorted(orders, key=self._external_order_sort_key):
            symbol = str((order or {}).get("symbol", "") or "").upper()
            if symbol not in seen_symbols:
                continue
            status = str((order or {}).get("status", "") or "").upper()
            filled_qty = int(float((order or {}).get("filled_qty", 0) or 0))
            filled_price = float((order or {}).get("filled_price", 0) or 0)
            if filled_qty <= 0 or filled_price <= 0 or status not in ("FILLED", "PARTIAL"):
                continue
            action = str((order or {}).get("action", (order or {}).get("side", "")) or "").upper()
            if action not in (ACTION_BUY, ACTION_SELL):
                continue
            eligible_order_count += 1
            trade_date = self._display_trade_date((order or {}).get("order_date", ""))
            order_no = str(order.get("order_no", "") or "")
            existing_trade = self._external_cycle_trade_existing(trade_db, order, trade_date)
            if existing_trade:
                try:
                    existing_qty = int(float((existing_trade or {}).get("filled_qty", 0) or 0))
                except Exception:
                    existing_qty = 0
                try:
                    existing_price = round(float((existing_trade or {}).get("filled_price", 0) or 0), 4)
                except Exception:
                    existing_price = 0.0
                existing_action = str((existing_trade or {}).get("action", "") or "").upper()
                if existing_qty == filled_qty and abs(existing_price - round(filled_price, 4)) < 0.0001 and existing_action == action:
                    existing_order_no = str((existing_trade or {}).get("broker_order_no", "") or "").strip()
                    if order_no and not existing_order_no:
                        try:
                            trade_db.update({
                                "broker_order_no": order_no,
                                "source": str((order or {}).get("broker", "") or getattr(kis_api, "broker_name", "KIS") or "KIS").upper(),
                                "order_type": str((existing_trade or {}).get("order_type", "") or "EXTERNAL"),
                                "created": self._external_order_created_at(order, trade_date),
                                "memo": (str((existing_trade or {}).get("memo", "") or "") + " | 브로커 주문번호 연결").strip(" |"),
                            }, id=existing_trade["id"])
                            corrected_count += 1
                            synced.append({
                                "symbol": symbol,
                                "action": action,
                                "qty": filled_qty,
                                "price": filled_price,
                                "order_no": order_no,
                                "linked": True,
                            })
                        except Exception as e:
                            errors.append({"symbol": symbol, "order_no": order_no, "reason": f"existing_trade_link_failed: {e}"})
                        continue
                    already_synced_count += 1
                    skipped.append({"symbol": symbol, "order_no": order_no, "reason": "already_synced"})
                    continue
                try:
                    filled_amount = filled_qty * filled_price
                    rates = self._get_commission_rates()
                    commission = self._calc_buy_commission(filled_amount, rates) if action == ACTION_BUY else self._calc_sell_commission(filled_amount, rates)
                    trade_db.update({
                        "trade_date": trade_date,
                        "action": action,
                        "order_type": "EXTERNAL",
                        "order_price": float(order.get("order_price", 0) or filled_price),
                        "order_qty": filled_qty,
                        "filled_price": filled_price,
                        "filled_qty": filled_qty,
                        "filled_amount": round(filled_amount, 2),
                        "commission": commission,
                        "status": ORDER_FILLED,
                        "broker_order_no": order_no,
                        "source": str((order or {}).get("broker", "") or getattr(kis_api, "broker_name", "KIS") or "KIS").upper(),
                        "memo": (str((existing_trade or {}).get("memo", "") or "") + " | 브로커 3회 검증 기준으로 체결 수량/가격 보정").strip(" |"),
                        "created": self._external_order_created_at(order, trade_date),
                    }, id=existing_trade["id"])
                    recalc = self._recalculate_cycle_from_trades(existing_trade.get("cycle_id", ""))
                    corrected_count += 1
                    self._log_event(symbol, existing_trade.get("cycle_id", ""), "EXTERNAL_TRADE_CORRECTED",
                                    action=action,
                                    message=f"브로커 3회 검증 기준 거래 보정: {order_no or '-'} | {action} {filled_qty}주 @ ${filled_price:.2f}")
                    synced.append({
                        "symbol": symbol,
                        "action": action,
                        "qty": filled_qty,
                        "price": filled_price,
                        "order_no": order_no,
                        "corrected": True,
                        "recalculation": recalc,
                    })
                except Exception as e:
                    errors.append({"symbol": symbol, "order_no": order_no, "reason": f"existing_trade_correction_failed: {e}"})
                continue

            if action == ACTION_BUY:
                cycle, created_cycle = self._ensure_external_buy_cycle(symbol)
            else:
                cycle = self._find_external_cycle(symbol)
                created_cycle = False
            if not cycle:
                item = {"symbol": symbol, "order_no": order.get("order_no", ""), "action": action, "reason": "active_cycle_missing"}
                skipped.append(item)
                unresolved.append(item)
                continue

            source_name = str((order or {}).get("broker", "") or getattr(kis_api, "broker_name", "KIS") or "KIS").upper()
            memo = f"{source_name} 외부 체결 동기화: {order_no or '-'}"
            if created_cycle:
                memo += " | 사이클 자동 생성"
            try:
                if action == ACTION_BUY:
                    trade = self.execute_buy(
                        cycle["id"],
                        filled_price=filled_price,
                        filled_qty=filled_qty,
                        order_type="EXTERNAL",
                        order_price=float(order.get("order_price", 0) or filled_price),
                        trade_date=trade_date,
                        broker_order_no=order_no,
                        source=source_name,
                        memo=memo,
                    )
                else:
                    current_qty = int(cycle.get("total_qty", 0) or 0)
                    sell_qty = min(filled_qty, current_qty)
                    if sell_qty <= 0:
                        item = {"symbol": symbol, "order_no": order_no, "action": action, "reason": "cycle_qty_empty"}
                        skipped.append(item)
                        unresolved.append(item)
                        continue
                    if sell_qty >= current_qty:
                        trade = self.execute_sell(
                            cycle["id"],
                            filled_price=filled_price,
                            filled_qty=sell_qty,
                            order_type="EXTERNAL",
                            trade_date=trade_date,
                            broker_order_no=order_no,
                            source=source_name,
                            memo=memo,
                        )
                    else:
                        trade = self.execute_partial_sell(
                            cycle["id"],
                            filled_price=filled_price,
                            filled_qty=sell_qty,
                            order_type="EXTERNAL",
                            trade_date=trade_date,
                            broker_order_no=order_no,
                            source=source_name,
                            memo=memo,
                        )
                self._log_event(symbol, cycle["id"], "EXTERNAL_TRADE_SYNCED", action=action, message=f"{memo} | {action} {filled_qty}주 @ ${filled_price:.2f}")
                order_created = self._external_order_created_at(order, trade_date)
                if (trade or {}).get("id") and order_created:
                    try:
                        trade_db.update({"created": order_created}, id=trade["id"])
                        trade["created"] = order_created
                    except Exception:
                        pass
                recalc = self._recalculate_cycle_from_trades(cycle["id"])
                synced.append({
                    "symbol": symbol,
                    "action": action,
                    "qty": filled_qty,
                    "price": filled_price,
                    "order_no": order_no,
                    "trade": trade,
                    "recalculation": recalc,
                })
            except Exception as e:
                errors.append({"symbol": symbol, "order_no": order_no, "reason": str(e)})

        local_holding_qty = {}
        holding_mismatches = []
        for symbol in symbols:
            cycle = self._find_external_cycle(symbol)
            try:
                local_qty = int(float((cycle or {}).get("total_qty", 0) or 0)) if cycle else 0
            except Exception:
                local_qty = 0
            local_holding_qty[symbol] = local_qty
            broker_qty = broker_holding_qty.get(symbol, None)
            if broker_qty is not None and int(broker_qty) != local_qty:
                holding_mismatches.append({
                    "symbol": symbol,
                    "broker_qty": int(broker_qty),
                    "local_cycle_qty": local_qty,
                    "diff": int(broker_qty) - local_qty,
                })

        reconciliation = {"reconciled": [], "aligned": [], "unresolved": [], "errors": []}
        if holding_mismatches:
            reconciliation = self._align_cycle_snapshot_to_broker_holdings(broker_holdings, symbols)
            if reconciliation.get("aligned") or reconciliation.get("reconciled"):
                local_holding_qty = {}
                holding_mismatches = []
                for symbol in symbols:
                    cycle = self._find_external_cycle(symbol)
                    try:
                        local_qty = int(float((cycle or {}).get("total_qty", 0) or 0)) if cycle else 0
                    except Exception:
                        local_qty = 0
                    local_holding_qty[symbol] = local_qty
                    broker_qty = broker_holding_qty.get(symbol, None)
                    if broker_qty is not None and int(broker_qty) != local_qty:
                        holding_mismatches.append({
                            "symbol": symbol,
                            "broker_qty": int(broker_qty),
                            "local_cycle_qty": local_qty,
                            "diff": int(broker_qty) - local_qty,
                        })
            if reconciliation.get("errors"):
                errors.extend(reconciliation.get("errors") or [])
            if reconciliation.get("unresolved"):
                unresolved.extend(reconciliation.get("unresolved") or [])

        status = "completed"
        if errors:
            status = "partial_error" if synced else "error"
        elif holding_mismatches:
            status = "partial_pending"
        elif unresolved:
            status = "partial_pending"
        verified = status == "completed" and len(errors) == 0 and len(unresolved) == 0 and len(holding_mismatches) == 0
        return {
            "status": status,
            "verified": verified,
            "synced_count": len(synced),
            "corrected_count": corrected_count,
            "audited_count": audited_count,
            "reconciled_count": len(reconciliation.get("reconciled", []) or []),
            "balance_aligned_count": len(reconciliation.get("aligned", []) or []),
            "raw_order_count": raw_order_count,
            "target_symbols": symbols,
            "eligible_order_count": eligible_order_count,
            "already_synced_count": already_synced_count,
            "skipped_count": len(skipped),
            "unresolved_count": len(unresolved),
            "holding_mismatch_count": len(holding_mismatches),
            "error_count": len(errors),
            "broker_holding_qty": broker_holding_qty,
            "local_cycle_qty": local_holding_qty,
            "holding_mismatches": holding_mismatches,
            "holding_reconciliation": reconciliation,
            "history_verification": history_check,
            "orders": synced,
            "audited": audited,
            "skipped": skipped,
            "unresolved": unresolved,
            "errors": errors,
        }

    def schedule_loc_buys(self, symbol_filter="", allow_new_orders=True):
        """
        LOC 매수 예약 — 오늘 매수 예정 사이클 중 LOC 매수 주문을 사전 접수
        한투 미국주식 예약주문 가능시간(10:00 KST부터, 서머타임 22:20/일반 23:20까지)에 실행하여 장중 체결 유도
        1회차 포함 LOC 주문 대상은 모두 예약한다.
        """
        self._ensure_runtime_schema()
        kis_api = self._load_kis_api()
        if not kis_api:
            return {"status": "error", "reason": "브로커 API 미설정", "orders": []}

        cycle_db = self._cycle_db()
        watchlist_db = self._watchlist_db()
        active_items = watchlist_db.rows(is_active=True, orderby="created", order="ASC")
        symbol_filter = str(symbol_filter or "").upper().strip()
        firegate_required = self._firegate_reservation_authority_required()
        firegate_context = (
            self._load_firegate_authoritative_states(symbol_filter=symbol_filter)
            if firegate_required else {"states": {}, "error": ""}
        )
        firegate_states = firegate_context.get("states", {})
        firegate_error = firegate_context.get("error", "")

        orders = []
        already_scheduled = []
        skipped = []
        errors = []
        expected_orders = []
        satisfied_line_keys = set()
        reserved_symbol_map = {}
        reserved_line_map = {}
        reserved_today_amount = 0.0
        try:
            reservation_orders = self._load_reservation_orders(
                kis_api,
                start_date=self._reservation_query_start_date(),
                timeout=4.0,
            )
        except Exception as e:
            detail_msg = f"해외 예약주문 조회 실패: {str(e)}"
            return self._loc_schedule_result(
                [],
                [],
                [],
                [{"symbol": symbol_filter or "SYSTEM", "reason": detail_msg}],
                [],
                set(),
                extra={
                    "reservation_query_failed": True,
                    "firegate_authoritative": firegate_required,
                    "firegate_state_count": len(firegate_states or {}),
                },
            )
        for reserved in reservation_orders:
            if str((reserved or {}).get("side", "") or "").upper() != "BUY":
                continue
            if self._reservation_order_is_active(reserved) is False:
                continue
            symbol_key = self._reservation_order_symbol_key(reserved.get("symbol", ""), reserved.get("exchange", "NASD"))
            line_key = self._reservation_order_line_key(reserved.get("symbol", ""), reserved.get("exchange", "NASD"), reserved.get("price", 0))
            reserved_symbol_map.setdefault(symbol_key, []).append(reserved)
            reserved_line_map.setdefault(line_key, []).append(reserved)
            reserved_today_amount += self._reservation_order_amount(reserved)

        reserved_today_amount = round(reserved_today_amount, 4)
        newly_reserved_amount = 0.0
        allow_auto_exchange_attempt = self._loc_buy_auto_exchange_attempt_enabled()
        for item in active_items:
            symbol = item["symbol"]
            if symbol_filter and str(symbol or "").upper() != symbol_filter:
                continue
            order_exchange = self._resolve_order_exchange(symbol, item.get("exchange", "NASD"))
            price_exchange = self._price_exchange(order_exchange)

            cycle = cycle_db.get(symbol=symbol, status=STATUS_ACTIVE)
            if not cycle:
                continue
            local_cycle_id = cycle.get("id", "")
            cycle, authority_error = self._cycle_with_firegate_authority(
                cycle,
                firegate_states,
                required=firegate_required,
                load_error=firegate_error,
            )
            if authority_error:
                self._log_event(symbol, local_cycle_id, "LOC_BUY_FIREGATE_AUTHORITY_BLOCKED", action=ACTION_BUY, message=authority_error)
                errors.append({
                    "symbol": symbol,
                    "cycle_id": local_cycle_id,
                    "label": "FIREGATE",
                    "price": 0,
                    "reason": authority_error,
                })
                continue

            firegate_cycle_ready = bool(cycle.get("_firegate_authoritative")) and int(float(cycle.get("total_qty", 0) or 0)) > 0 and float(cycle.get("avg_price", 0) or 0) > 0
            if firegate_required and firegate_cycle_ready:
                prev_close = float(cycle.get("avg_price", 0) or 0)
                current_price = float(cycle.get("current_price", 0) or 0)
            else:
                try:
                    with self._broker_request_options(kis_api, timeout=3.0, retries=0):
                        price_data = kis_api.get_current_price(symbol, exchange=price_exchange)
                    prev_close = float(price_data.get("prev_close", 0) or 0)
                    current_price = float(price_data.get("price", 0) or 0)
                    resolved_order_exchange = price_data.get("order_exchange", order_exchange)
                    if resolved_order_exchange and resolved_order_exchange != order_exchange:
                        watchlist_db.update({"exchange": resolved_order_exchange, "updated": self._now()}, id=item["id"])
                        order_exchange = resolved_order_exchange
                except Exception as e:
                    detail_msg = f"LOC 매수 예약 시세조회 실패: {str(e)}"
                    self._log_event(symbol, cycle["id"], "LOC_BUY_ERROR", message=detail_msg)
                    errors.append({
                        "symbol": symbol,
                        "cycle_id": cycle["id"],
                        "label": "PRICE",
                        "price": 0,
                        "reason": detail_msg,
                    })
                    continue

            if current_price > 0:
                self.update_cycle_price(cycle["id"], current_price)
            if prev_close <= 0:
                detail_msg = f"LOC 매수 예약 기준가 없음: symbol={symbol}, prev_close={prev_close}"
                self._log_event(symbol, cycle["id"], "LOC_BUY_ERROR", message=detail_msg)
                errors.append({
                    "symbol": symbol,
                    "cycle_id": cycle["id"],
                    "label": "PREV_CLOSE",
                    "price": 0,
                    "reason": detail_msg,
                })
                continue

            buy_decision = self.calculate_buy_decision(cycle, prev_close)
            if not buy_decision.get("should_buy"):
                continue
            decision_order_type = str(buy_decision.get("order_type", "") or "LOC").upper()
            if decision_order_type not in ("LOC", "LIMIT"):
                continue

            raw_buy_orders = buy_decision.get("buy_orders") or [{
                "label": decision_order_type,
                "loc_price": buy_decision.get("loc_price", 0),
                "order_qty": buy_decision.get("order_qty", 0),
                "order_type": decision_order_type,
            }]
            buy_orders = []
            for order_plan in raw_buy_orders:
                order_qty = int(order_plan.get("order_qty", 0) or 0)
                loc_price = float(order_plan.get("loc_price", 0) or 0)
                order_type = str(order_plan.get("order_type", decision_order_type) or decision_order_type).upper()
                if order_qty <= 0 or loc_price <= 0:
                    continue
                if order_type not in ("LOC", "LIMIT"):
                    order_type = decision_order_type if decision_order_type in ("LOC", "LIMIT") else "LOC"
                buy_orders.append({
                    **order_plan,
                    "order_qty": order_qty,
                    "loc_price": loc_price,
                    "order_type": order_type,
                    "label": str(order_plan.get("label", "LOC") or "LOC"),
                })
            if not buy_orders:
                continue

            symbol_key = self._reservation_order_symbol_key(symbol, order_exchange)
            symbol_expected_orders = []
            for order_plan in buy_orders:
                order_qty = int(order_plan.get("order_qty", 0) or 0)
                loc_price = float(order_plan.get("loc_price", 0) or 0)
                order_type = str(order_plan.get("order_type", decision_order_type) or decision_order_type).upper()
                if order_type not in ("LOC", "LIMIT"):
                    order_type = "LOC"
                label = str(order_plan.get("label", "LOC") or "LOC")
                line_key = self._reservation_order_line_key(symbol, order_exchange, loc_price)
                symbol_expected_orders.append({
                    "symbol": symbol,
                    "cycle_id": cycle["id"],
                    "label": label,
                    "order_type": order_type,
                    "order_qty": order_qty,
                    "price": loc_price,
                    "exchange": order_exchange,
                    "line_key": line_key,
                })
            expected_orders.extend(symbol_expected_orders)
            preflight_skips = self._reservation_mismatch_skips(symbol, order_exchange, symbol_expected_orders, reserved_line_map, "매수", cycle_id=cycle["id"])
            if preflight_skips:
                for skip in preflight_skips:
                    self._log_event(symbol, cycle["id"], "LOC_BUY_PRICE_MISMATCH", action=ACTION_BUY, message=skip.get("reason", ""))
                skipped.extend(preflight_skips)
                continue

            for order_plan in buy_orders:
                order_qty = int(order_plan.get("order_qty", 0) or 0)
                loc_price = float(order_plan.get("loc_price", 0) or 0)
                order_type = str(order_plan.get("order_type", decision_order_type) or decision_order_type).upper()
                if order_type not in ("LOC", "LIMIT"):
                    order_type = "LOC"
                label = str(order_plan.get("label", "LOC") or "LOC")
                line_key = self._reservation_order_line_key(symbol, order_exchange, loc_price)
                existing_reservations = reserved_line_map.get(line_key, [])
                if len(existing_reservations) > 0:
                    existing = existing_reservations[0]
                    existing_qty = sum(self._reservation_order_remaining_qty(order) for order in existing_reservations)
                    existing_price = float(existing.get("price", loc_price) or loc_price)
                    active_types = {
                        self._reservation_order_type(order)
                        for order in existing_reservations
                        if self._reservation_order_type(order)
                    }
                    type_mismatch = bool(active_types and order_type not in active_types)
                    qty_mismatch = existing_qty != order_qty
                    if type_mismatch or qty_mismatch:
                        detail_msg = (
                            f"FireGate 예약매수 라인 불일치: symbol={symbol}, line={label}, "
                            f"price=${existing_price:.2f}, expected_type={order_type}, "
                            f"active_type={','.join(sorted(active_types)) or 'unknown'}, "
                            f"expected_qty={order_qty}, active_qty={existing_qty}. "
                            f"전체 취소 후 FireGate 표대로 재예약 필요"
                        )
                        self._log_event(symbol, cycle["id"], "LOC_BUY_PRICE_MISMATCH", action=ACTION_BUY, message=detail_msg)
                        skipped.append({
                            "symbol": symbol,
                            "cycle_id": cycle["id"],
                            "label": label,
                            "price": existing_price,
                            "expected_qty": order_qty,
                            "active_qty": existing_qty,
                            "expected_order_type": order_type,
                            "active_order_type": ",".join(sorted(active_types)),
                            "line_key": line_key,
                            "force_rebuild": True,
                            "reason": detail_msg,
                        })
                        continue
                    already_msg = (
                        f"FireGate 예약매수 이미 접수됨: symbol={symbol}, line={label}, type={order_type}, qty={existing_qty}, "
                        f"price=${existing_price:.2f}, "
                        f"order_no={existing.get('order_no', existing.get('reserve_order_no', '')) or 'N/A'}"
                    )
                    self._log_event(symbol, cycle["id"], "LOC_BUY_ALREADY_SCHEDULED", action=ACTION_BUY, message=already_msg)
                    already_scheduled.append({
                        "symbol": symbol,
                        "cycle_id": cycle["id"],
                        "buy_qty": existing_qty,
                        "price": existing_price,
                        "label": label,
                        "order_type": order_type,
                        "order_no": existing.get("order_no", existing.get("reserve_order_no", "")),
                        "reason": buy_decision.get("reason", ""),
                    })
                    satisfied_line_keys.add(line_key)
                    continue

                if allow_new_orders is False:
                    detail_msg = (
                        f"FireGate 예약매수 누락 감지: symbol={symbol}, line={label}, "
                        f"type={order_type}, qty={order_qty}, price=${loc_price:.2f}. "
                        f"검증 모드에서는 개별 추가 주문 없이 전체 취소 후 FireGate 표대로 재예약 필요"
                    )
                    self._log_event(symbol, cycle["id"], "LOC_BUY_MISSING_FOR_REBUILD", action=ACTION_BUY, message=detail_msg)
                    skipped.append({
                        "symbol": symbol,
                        "cycle_id": cycle["id"],
                        "label": label,
                        "price": loc_price,
                        "expected_qty": order_qty,
                        "expected_order_type": order_type,
                        "line_key": line_key,
                        "force_rebuild": True,
                        "reason": detail_msg,
                    })
                    continue

                orderable_amount = 0.0
                try:
                    with self._broker_request_options(kis_api, timeout=4.0, retries=0):
                        buying_power_info = kis_api.get_buying_power_info(
                            symbol=symbol,
                            price=loc_price,
                            exchange=order_exchange,
                        )
                    max_qty = int(buying_power_info.get("executable_qty", buying_power_info.get("broker_qty", buying_power_info.get("qty", 0))) or 0)
                    orderable_amount = float(buying_power_info.get("executable_amount", buying_power_info.get("broker_amount", buying_power_info.get("amount", 0))) or 0)
                    estimated_amount = float(buying_power_info.get("estimated_amount", buying_power_info.get("amount", orderable_amount)) or 0)
                    estimated_qty = int(buying_power_info.get("estimated_qty", buying_power_info.get("qty", max_qty)) or 0)
                    auto_exchange_usd = float(buying_power_info.get("auto_exchange_usd", 0) or 0)
                    krw_auto_exchange_estimate_usd = float(buying_power_info.get("krw_auto_exchange_estimate_usd", 0) or 0)
                    auto_exchange_ready = bool(buying_power_info.get("auto_exchange_ready", False))

                    planning_amount = orderable_amount
                    planning_qty = max_qty
                    if auto_exchange_ready or (allow_auto_exchange_attempt and estimated_amount > orderable_amount + 0.01):
                        planning_amount = max(orderable_amount, estimated_amount)
                        planning_qty = max(max_qty, estimated_qty)

                    reserved_offset = round(reserved_today_amount + newly_reserved_amount, 4)
                    available_planning_amount = max(0.0, planning_amount - reserved_offset)
                    available_planning_qty = planning_qty
                    if loc_price > 0:
                        available_planning_qty = min(planning_qty, int(available_planning_amount / loc_price))

                    if order_qty > 0 and available_planning_qty > 0 and order_qty > available_planning_qty:
                        order_qty = available_planning_qty

                    requested_amount = float(order_qty) * loc_price
                    if order_qty <= 0 or available_planning_amount + 1e-9 < requested_amount:
                        if reserved_offset > 0 and planning_amount > 0.01:
                            detail_msg = (
                                f"LOC 예약매수 스킵: 오늘 이미 접수된 예약금이 주문가능예산을 대부분 사용했습니다 | "
                                f"symbol={symbol}, line={label}, planning_amount=${planning_amount:.2f}, "
                                f"reserved_today=${reserved_offset:.2f}, available_orderable=${available_planning_amount:.2f}, "
                                f"exchange={order_exchange}"
                            )
                            if estimated_amount > orderable_amount + 0.01 or auto_exchange_usd > 0.01 or krw_auto_exchange_estimate_usd > 0.01:
                                detail_msg += (
                                    f", estimated_amount=${estimated_amount:.2f}, auto_exchange_usd=${auto_exchange_usd:.2f}, "
                                    f"krw_auto_exchange_estimate_usd=${krw_auto_exchange_estimate_usd:.2f}"
                                )
                            self._log_event(symbol, cycle["id"], "LOC_BUY_SKIPPED", message=detail_msg)
                            skipped.append({
                                "symbol": symbol,
                                "cycle_id": cycle["id"],
                                "label": label,
                                "price": loc_price,
                                "reason": detail_msg,
                            })
                            continue

                        detail_msg = (
                            f"LOC 예약매수 실패: 실제 해외 주문가능수량/금액이 부족합니다 | "
                            f"symbol={symbol}, line={label}, orderable_amount=${orderable_amount:.2f}, "
                            f"requested_amount=${requested_amount:.2f}, exchange={order_exchange}"
                        )
                        if planning_amount > orderable_amount + 0.01 or planning_qty > max_qty:
                            detail_msg += (
                                f", planning_amount=${planning_amount:.2f}, planning_qty={planning_qty}"
                            )
                        if estimated_amount > orderable_amount + 0.01 or auto_exchange_usd > 0.01 or krw_auto_exchange_estimate_usd > 0.01:
                            detail_msg += (
                                f", estimated_amount=${estimated_amount:.2f}, auto_exchange_usd=${auto_exchange_usd:.2f}, "
                                f"krw_auto_exchange_estimate_usd=${krw_auto_exchange_estimate_usd:.2f}"
                            )
                        self._log_event(symbol, cycle["id"], "LOC_BUY_ERROR", message=detail_msg)
                        errors.append({
                            "symbol": symbol,
                            "cycle_id": cycle["id"],
                            "label": label,
                            "price": loc_price,
                            "reason": detail_msg,
                        })
                        continue

                    order_result = kis_api.buy_reservation_order(
                        symbol,
                        order_qty,
                        price=loc_price,
                        order_type=order_type,
                        exchange=order_exchange,
                    )
                    self._log_event(symbol, cycle["id"], "LOC_BUY_SCHEDULED",
                                    action=ACTION_BUY,
                                    message=f"FireGate 매수 예약: {label} {order_qty}주 @ ${loc_price:.2f}, 주문방식 {order_type}, 주문번호 {order_result.get('order_no', 'N/A')}, 사유: {buy_decision.get('reason', '')}")
                    orders.append({
                        "symbol": symbol,
                        "cycle_id": cycle["id"],
                        "buy_qty": order_qty,
                        "price": loc_price,
                        "label": label,
                        "order_type": order_type,
                        "order_no": order_result.get("order_no", ""),
                        "reason": buy_decision.get("reason", ""),
                    })
                    satisfied_line_keys.add(line_key)
                    requested_amount = float(order_qty) * loc_price
                    newly_reserved_amount = round(newly_reserved_amount + requested_amount, 4)
                    new_reserved = {
                        "symbol": symbol,
                        "exchange": order_exchange,
                        "qty": order_qty,
                        "price": loc_price,
                        "order_type": order_type,
                        "filled_qty": 0,
                        "order_no": order_result.get("order_no", ""),
                        "cancel_yn": "N",
                    }
                    reserved_symbol_map.setdefault(symbol_key, []).append(new_reserved)
                    reserved_line_map.setdefault(line_key, []).append(new_reserved)
                except Exception as e:
                    detail_msg = f"LOC 매수 예약 주문 실패: {label} ${loc_price:.2f} x {order_qty}주 | {str(e)}"
                    self._log_event(symbol, cycle["id"], "LOC_BUY_ERROR", message=detail_msg)
                    errors.append({
                        "symbol": symbol,
                        "cycle_id": cycle["id"],
                        "label": label,
                        "price": loc_price,
                        "reason": detail_msg,
                    })
        self._append_extra_reservation_skips(skipped, expected_orders, reserved_line_map, "매수")
        return self._loc_schedule_result(
            orders,
            already_scheduled,
            skipped,
            errors,
            expected_orders,
            satisfied_line_keys,
            extra={
                "reserved_order_amount": round(reserved_today_amount + newly_reserved_amount, 4),
                "firegate_authoritative": firegate_required,
                "firegate_state_count": len(firegate_states or {}),
            },
        )

    # =========================================================================
    # LOC 매도 예약 (사전 접수)
    # =========================================================================

    def schedule_loc_sells(self, symbol_filter="", allow_new_orders=True):
        """
        LOC 매도 예약 — 목표 매도가를 미리 예약 접수한다.
        한투 미국주식 예약주문 가능시간(10:00 KST부터, 서머타임 22:20/일반 23:20까지)에 실행하여, 장중/종가 목표 도달 시 체결 유도
        이 함수는 예약 매매 전용 경로라서 설정의 일반 매도 방식과 분리해 LOC로 접수한다.
        """
        self._ensure_runtime_schema()
        kis_api = self._load_kis_api()
        if not kis_api:
            return {"status": "error", "reason": "브로커 API 미설정", "orders": []}

        cycle_db = self._cycle_db()
        watchlist_db = self._watchlist_db()
        watchlist_rows = watchlist_db.rows(orderby="created", order="ASC") or []
        watchlist_by_symbol = {str((item or {}).get("symbol", "") or "").upper(): item for item in watchlist_rows}
        symbol_filter = str(symbol_filter or "").upper().strip()
        firegate_required = self._firegate_reservation_authority_required()
        firegate_context = (
            self._load_firegate_authoritative_states(symbol_filter=symbol_filter)
            if firegate_required else {"states": {}, "error": ""}
        )
        firegate_states = firegate_context.get("states", {})
        firegate_error = firegate_context.get("error", "")

        orders = []
        already_scheduled = []
        skipped = []
        errors = []
        expected_orders = []
        satisfied_line_keys = set()
        reserved_symbol_map = {}
        reserved_line_map = {}
        try:
            reservation_orders = self._load_reservation_orders(
                kis_api,
                start_date=self._reservation_query_start_date(),
                timeout=4.0,
            )
        except Exception as e:
            detail_msg = f"해외 예약주문 조회 실패: {str(e)}"
            return self._loc_schedule_result(
                [],
                [],
                [],
                [{"symbol": symbol_filter or "SYSTEM", "reason": detail_msg}],
                [],
                set(),
                extra={
                    "reservation_query_failed": True,
                    "sell_method": str(self._get_config_value("sell_method", "firegate") or "firegate").lower(),
                    "firegate_authoritative": firegate_required,
                    "firegate_state_count": len(firegate_states or {}),
                },
            )
        for reserved in reservation_orders:
            if str((reserved or {}).get("side", "") or "").upper() != "SELL":
                continue
            if self._reservation_order_is_active(reserved) is False:
                continue
            symbol_key = self._reservation_order_symbol_key(reserved.get("symbol", ""), reserved.get("exchange", "NASD"))
            reserved_symbol_map.setdefault(symbol_key, []).append(reserved)
            line_key = self._reservation_order_line_key(reserved.get("symbol", ""), reserved.get("exchange", "NASD"), reserved.get("price", 0))
            reserved_line_map.setdefault(line_key, []).append(reserved)

        cycle_candidates = []
        seen_cycle_ids = set()
        for status in (STATUS_ACTIVE, STATUS_HOLDING, STATUS_PENDING_EXTENSION):
            for cycle_row in cycle_db.rows(status=status, orderby="created", order="ASC", dump=500) or []:
                cycle_id = str((cycle_row or {}).get("id", "") or "")
                if not cycle_id or cycle_id in seen_cycle_ids:
                    continue
                seen_cycle_ids.add(cycle_id)
                cycle_candidates.append(cycle_row)

        for cycle in cycle_candidates:
            symbol = str(cycle.get("symbol", "") or "").upper()
            if symbol_filter and str(symbol or "").upper() != symbol_filter:
                continue
            local_cycle_id = cycle.get("id", "")
            cycle, authority_error = self._cycle_with_firegate_authority(
                cycle,
                firegate_states,
                required=firegate_required,
                load_error=firegate_error,
            )
            if authority_error:
                self._log_event(symbol, local_cycle_id, "LOC_SELL_FIREGATE_AUTHORITY_BLOCKED", action=ACTION_SELL, message=authority_error)
                errors.append({
                    "symbol": symbol,
                    "cycle_id": local_cycle_id,
                    "label": "FIREGATE",
                    "price": 0,
                    "reason": authority_error,
                })
                continue
            item = watchlist_by_symbol.get(symbol, {})
            order_exchange = self._resolve_order_exchange(symbol, (item or {}).get("exchange") or self._get_exchange(symbol) or "NASD")
            price_exchange = self._price_exchange(order_exchange)

            total_qty = int(cycle["total_qty"])
            if total_qty <= 0:
                continue

            current_price = 0.0
            if firegate_required and bool(cycle.get("_firegate_authoritative")):
                current_price = float(cycle.get("current_price", 0) or 0)
            else:
                try:
                    with self._broker_request_options(kis_api, timeout=3.0, retries=0):
                        price_data = kis_api.get_current_price(symbol, exchange=price_exchange)
                    current_price = float(price_data.get("price", 0) or 0)
                    resolved_order_exchange = price_data.get("order_exchange", order_exchange)
                    if resolved_order_exchange and resolved_order_exchange != order_exchange and item:
                        watchlist_db.update({"exchange": resolved_order_exchange, "updated": self._now()}, id=item["id"])
                        order_exchange = resolved_order_exchange
                except Exception as e:
                    detail_msg = f"LOC 매도 예약 시세조회 실패: {str(e)}"
                    self._log_event(symbol, cycle["id"], "LOC_SELL_ERROR", message=detail_msg)
                    current_price = 0.0

            if current_price > 0:
                self.update_cycle_price(cycle["id"], current_price)

            sell_orders = self._firegate_v4_sell_orders(cycle)
            if not sell_orders:
                target_price = self._loc_sell_target_price(cycle)
                if target_price > 0:
                    sell_orders = [{
                        "label": "LOC 매도",
                        "order_type": "LOC",
                        "order_qty": total_qty,
                        "price": target_price,
                    }]
            if not sell_orders:
                detail_msg = f"LOC 매도 예약 목표가 계산 실패: symbol={symbol}, qty={total_qty}, avg={cycle.get('avg_price', 0)}"
                self._log_event(symbol, cycle["id"], "LOC_SELL_ERROR", message=detail_msg)
                errors.append({
                    "symbol": symbol,
                    "cycle_id": cycle["id"],
                    "price": 0,
                    "reason": detail_msg,
                })
                continue

            sell_type = STRATEGY_FULL_SELL
            sell_qty = total_qty
            profit_rate = 0.0
            if current_price > 0:
                try:
                    sell_decision = self.calculate_sell_decision(cycle, current_price)
                    profit_rate = float(sell_decision.get("profit_rate", 0) or 0)
                    if sell_decision.get("should_sell"):
                        sell_type = sell_decision.get("sell_type", STRATEGY_FULL_SELL)
                        sell_qty = int(sell_decision.get("sell_qty", total_qty) or total_qty)
                except Exception:
                    pass

            symbol_key = self._reservation_order_symbol_key(symbol, order_exchange)
            total_existing_qty = sum(self._reservation_order_remaining_qty(order) for order in reserved_symbol_map.get(symbol_key, []))
            symbol_expected_orders = []
            for order_plan in sell_orders:
                target_price = float(order_plan.get("price", 0) or 0)
                planned_qty = int(order_plan.get("order_qty", 0) or 0)
                order_type = str(order_plan.get("order_type", "LOC") or "LOC").upper()
                label = str(order_plan.get("label", order_type) or order_type)
                if planned_qty <= 0 or target_price <= 0:
                    continue
                line_key = self._reservation_order_line_key(symbol, order_exchange, target_price)
                symbol_expected_orders.append({
                    "symbol": symbol,
                    "cycle_id": cycle["id"],
                    "label": label,
                    "order_type": order_type,
                    "order_qty": planned_qty,
                    "price": target_price,
                    "exchange": order_exchange,
                    "line_key": line_key,
                })
            expected_orders.extend(symbol_expected_orders)
            preflight_skips = self._reservation_mismatch_skips(symbol, order_exchange, symbol_expected_orders, reserved_line_map, "매도", cycle_id=cycle["id"])
            if preflight_skips:
                for skip in preflight_skips:
                    self._log_event(symbol, cycle["id"], "LOC_SELL_PRICE_MISMATCH", action=ACTION_SELL, message=skip.get("reason", ""))
                skipped.extend(preflight_skips)
                continue

            for order_plan in sell_orders:
                target_price = float(order_plan.get("price", 0) or 0)
                planned_qty = int(order_plan.get("order_qty", 0) or 0)
                order_type = str(order_plan.get("order_type", "LOC") or "LOC").upper()
                label = str(order_plan.get("label", order_type) or order_type)
                if planned_qty <= 0 or target_price <= 0:
                    continue
                line_key = self._reservation_order_line_key(symbol, order_exchange, target_price)
                reason = f"FireGate 매도 예약: {label} ${target_price:.2f} x {planned_qty}주"

                existing_reservations = reserved_line_map.get(line_key, [])
                if len(existing_reservations) > 0:
                    existing = existing_reservations[0]
                    existing_qty = sum(self._reservation_order_remaining_qty(order) for order in existing_reservations)
                    existing_price = float(existing.get("price", target_price) or target_price)
                    active_types = {
                        self._reservation_order_type(order)
                        for order in existing_reservations
                        if self._reservation_order_type(order)
                    }
                    type_mismatch = bool(active_types and order_type not in active_types)
                    qty_mismatch = existing_qty != planned_qty
                    if type_mismatch or qty_mismatch:
                        detail_msg = (
                            f"FireGate 예약매도 라인 불일치: symbol={symbol}, line={label}, "
                            f"price=${existing_price:.2f}, expected_type={order_type}, "
                            f"active_type={','.join(sorted(active_types)) or 'unknown'}, "
                            f"expected_qty={planned_qty}, active_qty={existing_qty}. "
                            f"전체 취소 후 FireGate 표대로 재예약 필요"
                        )
                        self._log_event(symbol, cycle["id"], "LOC_SELL_PRICE_MISMATCH", action=ACTION_SELL, message=detail_msg)
                        skipped.append({
                            "symbol": symbol,
                            "cycle_id": cycle["id"],
                            "label": label,
                            "price": existing_price,
                            "expected_qty": planned_qty,
                            "active_qty": existing_qty,
                            "expected_order_type": order_type,
                            "active_order_type": ",".join(sorted(active_types)),
                            "line_key": line_key,
                            "force_rebuild": True,
                            "reason": detail_msg,
                        })
                        continue
                    already_msg = (
                        f"FireGate 라인 예약매도 이미 접수됨: symbol={symbol}, line={label}, "
                        f"qty={existing_qty}, price=${existing_price:.2f}, "
                        f"order_no={existing.get('order_no', existing.get('reserve_order_no', '')) or 'N/A'}"
                    )
                    self._log_event(symbol, cycle["id"], "LOC_SELL_ALREADY_SCHEDULED", action=ACTION_SELL, message=already_msg)
                    already_scheduled.append({
                        "symbol": symbol,
                        "cycle_id": cycle["id"],
                        "sell_qty": existing_qty,
                        "price": existing_price,
                        "target_price": target_price,
                        "label": label,
                        "order_type": order_type,
                        "order_no": existing.get("order_no", existing.get("reserve_order_no", "")),
                        "reason": reason,
                    })
                    satisfied_line_keys.add(line_key)
                    continue

                if allow_new_orders is False:
                    detail_msg = (
                        f"FireGate 예약매도 누락 감지: symbol={symbol}, line={label}, "
                        f"type={order_type}, qty={planned_qty}, price=${target_price:.2f}. "
                        f"검증 모드에서는 개별 추가 주문 없이 전체 취소 후 FireGate 표대로 재예약 필요"
                    )
                    self._log_event(symbol, cycle["id"], "LOC_SELL_MISSING_FOR_REBUILD", action=ACTION_SELL, message=detail_msg)
                    skipped.append({
                        "symbol": symbol,
                        "cycle_id": cycle["id"],
                        "label": label,
                        "price": target_price,
                        "expected_qty": planned_qty,
                        "expected_order_type": order_type,
                        "line_key": line_key,
                        "force_rebuild": True,
                        "reason": detail_msg,
                    })
                    continue

                if total_existing_qty >= total_qty:
                    skipped_msg = (
                        f"기존 예약매도가 보유수량 전체를 이미 점유 중입니다: symbol={symbol}, "
                        f"missing_line={label}, target=${target_price:.2f}"
                    )
                    self._log_event(symbol, cycle["id"], "LOC_SELL_PRICE_MISMATCH", action=ACTION_SELL, message=skipped_msg)
                    skipped.append({
                        "symbol": symbol,
                        "cycle_id": cycle["id"],
                        "label": label,
                        "price": target_price,
                        "expected_qty": planned_qty,
                        "active_qty": total_existing_qty,
                        "line_key": line_key,
                        "force_rebuild": True,
                        "reason": skipped_msg,
                    })
                    continue

                try:
                    reserve_sell = getattr(kis_api, "sell_reservation_order", None)
                    if callable(reserve_sell):
                        order_result = reserve_sell(symbol, planned_qty, price=target_price, order_type=order_type, exchange=order_exchange)
                    else:
                        order_result = kis_api.sell_order(symbol, planned_qty, price=target_price, order_type=order_type, exchange=order_exchange)

                    self._log_event(symbol, cycle["id"], "LOC_SELL_SCHEDULED",
                                    action=ACTION_SELL,
                                    message=f"FireGate 매도 예약: {label} {planned_qty}주 @ ${target_price:.2f}, "
                                            f"주문방식 {order_type}, 현재 수익률 {profit_rate:.2f}%, "
                                            f"주문번호 {order_result.get('order_no', 'N/A')}")

                    orders.append({
                        "symbol": symbol,
                        "cycle_id": cycle["id"],
                        "sell_type": sell_type,
                        "sell_qty": planned_qty,
                        "price": target_price,
                        "label": label,
                        "order_type": order_type,
                        "current_price": current_price,
                        "profit_rate": profit_rate,
                        "order_no": order_result.get("order_no", ""),
                        "reason": reason,
                    })
                    total_existing_qty += planned_qty
                    satisfied_line_keys.add(line_key)
                except Exception as e:
                    detail_msg = f"FireGate 매도 예약 주문 실패: {label} ${target_price:.2f} x {planned_qty}주 | {str(e)}"
                    self._log_event(symbol, cycle["id"], "LOC_SELL_ERROR",
                                    message=detail_msg)
                    errors.append({
                        "symbol": symbol,
                        "cycle_id": cycle["id"],
                        "label": label,
                        "price": target_price,
                        "reason": detail_msg,
                    })

        self._append_extra_reservation_skips(skipped, expected_orders, reserved_line_map, "매도")
        return self._loc_schedule_result(
            orders,
            already_scheduled,
            skipped,
            errors,
            expected_orders,
            satisfied_line_keys,
            extra={
                "sell_method": str(self._get_config_value("sell_method", "firegate") or "firegate").lower(),
                "firegate_authoritative": firegate_required,
                "firegate_state_count": len(firegate_states or {}),
            },
        )

    # =========================================================================
    # 전체 종목 일일 실행
    # =========================================================================

    def _record_daily_snapshot(self):
        """당일 계좌 스냅샷 기록 (하루 1회, upsert)"""
        today = self._now().strftime("%Y-%m-%d")
        snapshot_db = self._snapshot_db()
        cycle_db = self._cycle_db()
        existing = snapshot_db.get(snapshot_date=today)
        if existing:
            return {
                "snapshot_date": today,
                "skipped": True,
                "reason": "today_snapshot_exists",
                "id": existing.get("id", ""),
            }

        # 활성 사이클에서 평가금액 계산
        active_cycles = self.get_active_cycles()
        eval_amount = 0.0
        total_spent = 0.0
        for c in active_cycles:
            qty = int(c.get("total_qty", 0))
            price = float(c.get("current_price", 0))
            eval_amount += qty * price
            total_spent += float(c.get("total_spent", 0))

        unrealized_profit = eval_amount - total_spent

        # 실현 수익 (완료 사이클)
        completed = cycle_db.rows(status=STATUS_COMPLETED)
        realized_profit = 0.0
        for c in completed:
            c_eval = float(c.get("current_eval", 0))
            c_spent = float(c.get("total_spent", 0))
            realized_profit += (c_eval - c_spent)

        total_profit = realized_profit + unrealized_profit

        # 현금/평가자산 (KIS API 가능하면 실계좌 기준)
        cash_balance = 0.0
        eval_amount_live = 0.0
        cash_balance_krw = 0.0
        eval_amount_krw = 0.0
        exchange_rate = 0.0
        present_total_asset_krw = 0.0
        try:
            kis = getattr(self.struct, "broker_api", None) or self.struct.kis_api
            if hasattr(kis, "get_present_balance"):
                present = kis.get_present_balance()
                exchange_rate = float(present.get("usd_krw", 0) or 0)
                present_total_asset_krw = float(present.get("total_asset_krw", 0) or 0)
                krw_balance = float(present.get("withdrawable_krw", present.get("krw_balance", 0)))
                cash_balance_krw += krw_balance

            overseas_balance = kis.get_balance() or {}
            cash_balance = float(overseas_balance.get("cash_balance", 0) or 0)
            eval_amount_live = float(overseas_balance.get("total_eval", 0) or 0)
            if eval_amount_live <= 0:
                for h in (overseas_balance.get("holdings", []) or []):
                    eval_amount_live += float(h.get("eval_amount", 0) or 0)

            domestic_eval_krw = 0.0
            domestic_balance = kis.get_domestic_balance() or {}
            for h in (domestic_balance.get("holdings", []) or []):
                qty = int(float(h.get("qty", 0) or 0))
                current_price = float(h.get("current_price", 0) or 0)
                if qty > 0 and current_price > 0:
                    domestic_eval_krw += (qty * current_price)

            if exchange_rate > 0:
                cash_balance_krw += (cash_balance * exchange_rate)
                eval_amount_krw += (eval_amount_live * exchange_rate)
            eval_amount_krw += domestic_eval_krw
        except Exception:
            # API 미연결 시 잔여 투자금 합산
            for c in active_cycles:
                cash_balance += float(c.get("remaining_investment", 0))
            eval_amount_live = eval_amount

        eval_amount = eval_amount_live if eval_amount_live > 0 else eval_amount
        total_asset = cash_balance + eval_amount
        total_asset_krw = cash_balance_krw + eval_amount_krw
        if present_total_asset_krw > 0 and present_total_asset_krw >= total_asset_krw * 0.5:
            total_asset_krw = present_total_asset_krw
        profit_rate = (total_profit / total_spent * 100) if total_spent > 0 else 0.0

        # KRW 기준 손익률 (스냅샷 기반). 과거 테스트/달러 단위 스냅샷이 기준자산을
        # 지나치게 낮추지 못하게 설정 초기자산을 하한으로 사용한다.
        total_profit_krw = 0.0
        configured_base_asset = self._configured_base_asset_krw()
        initial_asset = 0.0
        first_snap = snapshot_db.rows(orderby="snapshot_date", order="ASC", page=1, dump=1)
        if first_snap:
            initial_asset = float(first_snap[0].get("total_asset", 0) or 0)
            if initial_asset > 0 and initial_asset < 100000 and exchange_rate > 0 and total_asset_krw > 100000:
                initial_asset = initial_asset * exchange_rate
        if configured_base_asset > 0 and (initial_asset <= 0 or initial_asset < configured_base_asset):
            initial_asset = configured_base_asset
        if initial_asset > 0 and total_asset_krw > 0:
            total_profit_krw = total_asset_krw - initial_asset
            profit_rate = (total_profit_krw / initial_asset * 100)

        saved_cash = cash_balance_krw if cash_balance_krw > 0 else cash_balance
        saved_eval = eval_amount_krw if eval_amount_krw > 0 else eval_amount
        saved_asset = total_asset_krw if total_asset_krw > 0 else total_asset
        saved_profit = total_profit_krw if total_asset_krw > 0 else total_profit

        snapshot_data = {
            "snapshot_date": today,
            "cash_balance": round(saved_cash, 2),
            "eval_amount": round(saved_eval, 2),
            "total_asset": round(saved_asset, 2),
            "total_profit": round(saved_profit, 2),
            "profit_rate": round(profit_rate, 2),
            "holdings_count": len([c for c in active_cycles if int(c.get("total_qty", 0)) > 0]),
            "active_cycles": len(active_cycles),
            "memo": "",
        }
        snapshot_db.insert(snapshot_data)
        return snapshot_data

    def run_all(self):
        """모든 활성 종목에 대해 일일 매매 판단 실행 (cycle_mode 반영)"""
        watchlist = self._watchlist_db()
        active_etfs = watchlist.rows(is_active=True)
        results = []

        for etf in active_etfs:
            symbol = etf["symbol"]
            cycle_mode = etf.get("cycle_mode", CYCLE_MODE_AUTO)

            # 활성 사이클 확인
            cycle_db = self._cycle_db()
            cycle = cycle_db.get(symbol=symbol, status=STATUS_ACTIVE)
            if not cycle:
                cycle = cycle_db.get(symbol=symbol, status=STATUS_HOLDING)
            if not cycle:
                cycle = cycle_db.get(symbol=symbol, status=STATUS_PENDING_EXTENSION)

            # PAUSED 사이클은 스킵
            paused = cycle_db.get(symbol=symbol, status=STATUS_PAUSED)
            if paused:
                results.append({"symbol": symbol, "action": "PAUSED", "detail": "사이클 일시 정지 중"})
                continue

            if not cycle:
                # 사이클이 없을 때: auto 모드만 자동 시작
                if cycle_mode == CYCLE_MODE_MANUAL:
                    results.append({"symbol": symbol, "action": "MANUAL_WAIT", "detail": "수동 모드 — 사이클 수동 시작 필요"})
                    continue
                elif cycle_mode == CYCLE_MODE_CONFIRM:
                    results.append({"symbol": symbol, "action": "CONFIRM_WAIT", "detail": "확인 모드 — 대시보드에서 사이클 시작 확인 필요"})
                    continue
                else:
                    # auto 모드: 자동 시작
                    try:
                        self.start_cycle(symbol)
                    except Exception as e:
                        results.append({"symbol": symbol, "action": "START_ERROR", "detail": str(e)})
                        continue

            result = self.run_daily(symbol)
            result["symbol"] = symbol
            results.append(result)

        # 엔진 실행 후 당일 스냅샷 자동 기록
        try:
            self._record_daily_snapshot()
        except Exception:
            pass  # 스냅샷 기록 실패 시 무시

        return results

    # =========================================================================
    # 엔진 상태 조회
    # =========================================================================

    def get_status(self):
        """엔진 전체 상태 조회"""
        cycle_db = self._cycle_db()
        active_count = cycle_db.count(status=STATUS_ACTIVE) or 0
        holding_count = cycle_db.count(status=STATUS_HOLDING) or 0
        paused_count = cycle_db.count(status=STATUS_PAUSED) or 0
        pending_count = cycle_db.count(status=STATUS_PENDING_EXTENSION) or 0
        completed_count = cycle_db.count(status=STATUS_COMPLETED) or 0

        auto_trade = self._get_config_value("auto_trade_enabled", "false")

        return {
            "active_cycles": active_count,
            "holding_cycles": holding_count,
            "paused_cycles": paused_count,
            "pending_extension_cycles": pending_count,
            "completed_cycles": completed_count,
            "auto_trade": auto_trade == "true",
        }

    def _get_config_value(self, key, default=""):
        """struct 레벨 config 조회 헬퍼 — 캐시 사용"""
        return self.struct.get_config(key, default)

    def _configured_base_asset_krw(self):
        for key in ["dashboard_base_asset_krw", "daytrade_default_seed"]:
            try:
                value = float(self._get_config_value(key, "0") or 0)
                if value > 0:
                    return value
            except Exception:
                pass
        return 0.0

    # =========================================================================
    # 로그 기록
    # =========================================================================

    def _log_event(self, symbol, cycle_id, event_type, action="", message=""):
        """trade_log에 이벤트 기록"""
        log_db = self._log_db()
        event_type = str(event_type or "").upper().strip()
        if event_type.startswith("IB_") is False:
            event_type = f"IB_{event_type}" if event_type else "IB_EVENT"
        log_db.insert({
            "cycle_id": cycle_id or "",
            "symbol": symbol,
            "event_type": event_type,
            "action": action,
            "order_no": "",
            "order_price": 0,
            "order_qty": 0,
            "filled_price": None,
            "filled_qty": 0,
            "message": message,
            "raw_response": "",
            "created": self._now(),
        })


Model = Engine
