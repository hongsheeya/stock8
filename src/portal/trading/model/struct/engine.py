# =============================================================================
# 무한매수법 알고리즘 엔진 Sub-Struct
# =============================================================================
# 라오어의 무한매수법 규칙에 따라 매수/매도 판단 및 실행
# =============================================================================
import datetime
import math

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

# 사이클 모드
CYCLE_MODE_AUTO = "auto"
CYCLE_MODE_CONFIRM = "confirm"
CYCLE_MODE_MANUAL = "manual"

# 전략 타입
STRATEGY_NORMAL = "NORMAL"
STRATEGY_FULL_SELL = "FULL_SELL"
STRATEGY_PARTIAL_SELL = "PARTIAL_SELL"
STRATEGY_CRASH_BUY = "CRASH_BUY"


class Engine:
    """무한매수법 알고리즘 엔진"""

    def __init__(self, struct):
        self.struct = struct

    def _now(self):
        return _TIME.now()

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

    # =========================================================================
    # 거래소 코드 헬퍼
    # =========================================================================

    # 주문용 4글자 → 시세조회용 3글자 변환
    EXCHANGE_MAP = {"NASD": "NAS", "NYSE": "NYS", "AMEX": "AMS"}

    def _get_exchange(self, symbol):
        """워치리스트에서 종목의 주문용 거래소 코드(4글자) 조회"""
        watchlist = self._watchlist_db()
        etf = watchlist.get(symbol=symbol)
        if etf:
            return etf.get("exchange", "NASD")
        return "NASD"

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
            "sell_strategy": self._get_config_value("sell_strategy", "full"),
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
            trade_db.insert({
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

        # 1회차: 시장가 매수
        if next_round == 1:
            order_qty = int(buy_amount / prev_close) if prev_close > 0 else 0
            should_buy = order_qty > 0
            reason = f"1회차 시장가 매수 (씨앗: ${buy_amount:.2f})"
            if should_buy is False:
                if prev_close > 0:
                    # 씨앗금이 전일종가보다 작아도 1주 매수 허용 (완화 정책)
                    order_qty = 1
                    should_buy = True
                    reason = f"1회차 시장가 매수 — 씨앗금(${buy_amount:.2f}) < 전일종가(${prev_close:.2f}), 최소 1주 진입"
                else:
                    reason = f"1회차 씨앗금(${buy_amount:.2f})이 전일종가(${prev_close:.2f})보다 작아 1주도 매수할 수 없음"
            return {
                "should_buy": should_buy,
                "buy_amount": buy_amount,
                "loc_price": prev_close,
                "order_type": "MARKET",
                "order_qty": order_qty,
                "reason": reason,
            }

        # 2회차 이후: LOC 지정가
        if prev_close <= avg_price:
            loc_price = prev_close
            reason = f"전일종가(${prev_close:.2f}) <= 평단가(${avg_price:.2f}) → 전일종가로 LOC"
        else:
            loc_price = avg_price
            reason = f"전일종가(${prev_close:.2f}) > 평단가(${avg_price:.2f}) → 평단가로 LOC"

        order_qty = int(buy_amount / loc_price) if loc_price > 0 else 0
        should_buy = order_qty > 0
        if should_buy is False:
            reason = f"회차 투자금(${buy_amount:.2f})이 주문 기준가(${loc_price:.2f})보다 작아 1주도 매수할 수 없음"

        return {
            "should_buy": should_buy,
            "buy_amount": buy_amount,
            "loc_price": round(loc_price, 2),
            "order_type": "LOC",
            "order_qty": order_qty,
            "reason": reason,
        }

    # =========================================================================
    # 매도 판단 로직
    # =========================================================================

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
        sell_strategy = params.get("sell_strategy", "full")

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

        if profit_rate < target_profit:
            return {
                "should_sell": False,
                "sell_type": None,
                "sell_qty": 0,
                "profit_rate": round(profit_rate, 2),
                "current_eval": round(current_eval, 2),
                "reason": f"수익률 {profit_rate:.2f}% (목표: {target_profit}%)",
            }

        # 기본: 전량 매도
        return {
            "should_sell": True,
            "sell_type": STRATEGY_FULL_SELL,
            "sell_qty": total_qty,
            "profit_rate": round(profit_rate, 2),
            "current_eval": round(current_eval, 2),
            "reason": f"목표 수익률 도달! ({profit_rate:.2f}% >= {target_profit}%)",
        }

    # =========================================================================
    # 거래 실행 (매수)
    # =========================================================================

    def execute_buy(self, cycle_id, filled_price, filled_qty, order_type="LOC", order_price=0):
        """
        매수 체결 처리 (DB 업데이트)
        - 실제 주문은 kis_api를 통해 별도 실행
        - 이 메서드는 체결 후 DB 기록 용도
        """
        cycle_db = self._cycle_db()
        trade_db = self._trade_db()
        cycle = cycle_db.get(id=cycle_id)
        if not cycle:
            raise Exception(f"사이클을 찾을 수 없습니다: {cycle_id}")

        now = self._now()
        trade_date = now.strftime("%Y-%m-%d")

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
            "created": now,
        }
        trade_db.insert(trade_data)

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
        trade_db.insert(trade_data)

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

    def execute_sell(self, cycle_id, filled_price, filled_qty, order_type="MARKET"):
        """
        매도 체결 처리 → 사이클 완료
        수수료/세금을 차감한 순수익으로 profit_rate 산출
        """
        cycle_db = self._cycle_db()
        trade_db = self._trade_db()
        cycle = cycle_db.get(id=cycle_id)
        if not cycle:
            raise Exception(f"사이클을 찾을 수 없습니다: {cycle_id}")

        now = self._now()
        trade_date = now.strftime("%Y-%m-%d")

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
            "created": now,
        }
        trade_db.insert(trade_data)

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

        return trade_data

    # =========================================================================
    # 거래 실행 (분할 매도 — 일부만 매도, 사이클 유지)
    # =========================================================================

    def execute_partial_sell(self, cycle_id, filled_price, filled_qty, order_type="MARKET"):
        """
        분할 매도 체결 처리 → 사이클 유지
        - 매도된 수량만큼 total_qty, total_spent 비례 차감
        - 사이클 상태는 유지 (ACTIVE/HOLDING)
        """
        cycle_db = self._cycle_db()
        trade_db = self._trade_db()
        cycle = cycle_db.get(id=cycle_id)
        if not cycle:
            raise Exception(f"사이클을 찾을 수 없습니다: {cycle_id}")

        now = self._now()
        trade_date = now.strftime("%Y-%m-%d")

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
            "created": now,
        }
        trade_db.insert(trade_data)

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
        trade_db.insert(trade_data)

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

        return trade_data

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
        kis_api = self.struct.kis_api

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
                sell_method = self._get_config_value("sell_method", "market").upper()
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

    def _reservation_order_symbol_key(self, symbol="", exchange=""):
        return f"{str(symbol or '').upper()}:{str(exchange or 'NASD').upper()}"

    def _reservation_order_is_active(self, order):
        cancel_yn = str((order or {}).get("cancel_yn", "") or "").strip().upper()
        if cancel_yn == "Y":
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

    def schedule_loc_buys(self):
        """
        LOC 매수 예약 — 오늘 매수 예정 사이클 중 LOC 매수 주문을 사전 접수
        오후 5:40 KST 이후 미국 장 시작 전에 실행하여 장중 체결 유도
        2회차 이후 LOC 주문만 대상이며, 1회차 MARKET 진입은 제외한다.
        """
        kis_api = self._load_kis_api()
        if not kis_api:
            return {"status": "error", "reason": "KIS API 미설정", "orders": []}

        cycle_db = self._cycle_db()
        watchlist_db = self._watchlist_db()
        active_items = watchlist_db.rows(is_active=True, orderby="created", order="ASC")

        orders = []
        already_scheduled = []
        skipped = []
        errors = []
        reserved_symbol_map = {}
        reserved_today_amount = 0.0
        try:
            reservation_orders = kis_api.get_overseas_reservation_orders(start_date=self._now().strftime("%Y%m%d")) or []
        except Exception:
            reservation_orders = []
        for reserved in reservation_orders:
            if str((reserved or {}).get("side", "") or "").upper() != "BUY":
                continue
            if self._reservation_order_is_active(reserved) is False:
                continue
            symbol_key = self._reservation_order_symbol_key(reserved.get("symbol", ""), reserved.get("exchange", "NASD"))
            reserved_symbol_map.setdefault(symbol_key, []).append(reserved)
            reserved_today_amount += self._reservation_order_amount(reserved)

        reserved_today_amount = round(reserved_today_amount, 4)
        newly_reserved_amount = 0.0
        allow_auto_exchange_attempt = self._loc_buy_auto_exchange_attempt_enabled()
        for item in active_items:
            symbol = item["symbol"]
            order_exchange = item.get("exchange", "NASD")
            price_exchange = self._price_exchange(order_exchange)

            cycle = cycle_db.get(symbol=symbol, status=STATUS_ACTIVE)
            if not cycle:
                continue

            try:
                price_data = kis_api.get_current_price(symbol, exchange=price_exchange)
                prev_close = float(price_data.get("prev_close", 0) or 0)
                current_price = float(price_data.get("price", 0) or 0)
                resolved_order_exchange = price_data.get("order_exchange", order_exchange)
                if resolved_order_exchange and resolved_order_exchange != order_exchange:
                    watchlist_db.update({"exchange": resolved_order_exchange, "updated": self._now()}, id=item["id"])
                    order_exchange = resolved_order_exchange
            except Exception as e:
                self._log_event(symbol, cycle["id"], "LOC_BUY_ERROR",
                                message=f"LOC 매수 예약 시세조회 실패: {str(e)}")
                continue

            if current_price > 0:
                self.update_cycle_price(cycle["id"], current_price)
            if prev_close <= 0:
                continue

            buy_decision = self.calculate_buy_decision(cycle, prev_close)
            if not buy_decision.get("should_buy"):
                continue
            if str(buy_decision.get("order_type", "") or "").upper() != "LOC":
                continue

            order_qty = int(buy_decision.get("order_qty", 0) or 0)
            loc_price = float(buy_decision.get("loc_price", 0) or 0)
            if order_qty <= 0 or loc_price <= 0:
                continue

            symbol_key = self._reservation_order_symbol_key(symbol, order_exchange)
            existing_reservations = reserved_symbol_map.get(symbol_key, [])
            if len(existing_reservations) > 0:
                existing = existing_reservations[0]
                already_msg = (
                    f"LOC 예약매수 이미 접수됨: symbol={symbol}, qty={existing.get('qty', order_qty)}, "
                    f"price=${float(existing.get('price', loc_price) or loc_price):.2f}, "
                    f"order_no={existing.get('order_no', existing.get('reserve_order_no', '')) or 'N/A'}"
                )
                self._log_event(symbol, cycle["id"], "LOC_BUY_ALREADY_SCHEDULED", action=ACTION_BUY, message=already_msg)
                already_scheduled.append({
                    "symbol": symbol,
                    "cycle_id": cycle["id"],
                    "buy_qty": int(existing.get("qty", order_qty) or order_qty),
                    "price": float(existing.get("price", loc_price) or loc_price),
                    "order_no": existing.get("order_no", existing.get("reserve_order_no", "")),
                    "reason": buy_decision.get("reason", ""),
                })
                continue

            orderable_amount = 0.0
            try:
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
                            f"symbol={symbol}, planning_amount=${planning_amount:.2f}, reserved_today=${reserved_offset:.2f}, "
                            f"available_orderable=${available_planning_amount:.2f}, exchange={order_exchange}"
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
                            "reason": detail_msg,
                        })
                        continue

                    detail_msg = (
                        f"LOC 예약매수 실패: 실제 해외 주문가능수량/금액이 부족합니다 | "
                        f"symbol={symbol}, orderable_amount=${orderable_amount:.2f}, "
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
                        "reason": detail_msg,
                    })
                    continue

                order_result = kis_api.buy_reservation_order(
                    symbol,
                    order_qty,
                    price=loc_price,
                    order_type="LOC",
                    exchange=order_exchange,
                )
                self._log_event(symbol, cycle["id"], "LOC_BUY_SCHEDULED",
                                action=ACTION_BUY,
                                message=f"LOC 매수 예약: {order_qty}주 @ ${loc_price:.2f}, 주문번호 {order_result.get('order_no', 'N/A')}, 사유: {buy_decision.get('reason', '')}")
                orders.append({
                    "symbol": symbol,
                    "cycle_id": cycle["id"],
                    "buy_qty": order_qty,
                    "price": loc_price,
                    "order_no": order_result.get("order_no", ""),
                    "reason": buy_decision.get("reason", ""),
                })
                newly_reserved_amount = round(newly_reserved_amount + requested_amount, 4)
                reserved_symbol_map.setdefault(symbol_key, []).append({
                    "symbol": symbol,
                    "exchange": order_exchange,
                    "qty": order_qty,
                    "price": loc_price,
                    "filled_qty": 0,
                    "order_no": order_result.get("order_no", ""),
                    "cancel_yn": "N",
                })
            except Exception as e:
                detail_msg = f"LOC 매수 예약 주문 실패: {str(e)}"
                self._log_event(symbol, cycle["id"], "LOC_BUY_ERROR", message=detail_msg)
                errors.append({
                    "symbol": symbol,
                    "cycle_id": cycle["id"],
                    "reason": detail_msg,
                })

        status = "completed"
        if len(errors) > 0:
            status = "partial_error" if (len(orders) + len(already_scheduled) + len(skipped)) > 0 else "error"
        return {
            "status": status,
            "scheduled_count": len(orders),
            "already_scheduled_count": len(already_scheduled),
            "skipped_count": len(skipped),
            "error_count": len(errors),
            "orders": orders,
            "already_scheduled": already_scheduled,
            "skipped": skipped,
            "errors": errors,
            "reserved_order_amount": round(reserved_today_amount + newly_reserved_amount, 4),
        }

    # =========================================================================
    # LOC 매도 예약 (사전 접수)
    # =========================================================================

    def schedule_loc_sells(self):
        """
        LOC 매도 예약 — 목표 수익률 도달 시 LOC 매도 주문을 사전 접수
        오후 5:30 KST 전후 미국 장 시작 전에 실행하여, 장중 LOC 체결 유도
        sell_method가 'loc'인 경우에만 작동. 'market'이면 스킵.
        """
        sell_method = self._get_config_value("sell_method", "market")
        if sell_method != "loc":
            return {"status": "skipped", "reason": "sell_method is not LOC", "orders": []}

        kis_api = self._load_kis_api()
        if not kis_api:
            return {"status": "error", "reason": "KIS API 미설정", "orders": []}

        cycle_db = self._cycle_db()
        watchlist_db = self._watchlist_db()
        active_items = watchlist_db.rows(is_active=True, orderby="created", order="ASC")

        orders = []
        for item in active_items:
            symbol = item["symbol"]
            order_exchange = item.get("exchange", "NASD")
            price_exchange = self._price_exchange(order_exchange)

            cycle = cycle_db.get(symbol=symbol, status=STATUS_ACTIVE)
            if not cycle:
                cycle = cycle_db.get(symbol=symbol, status=STATUS_HOLDING)
            if not cycle:
                cycle = cycle_db.get(symbol=symbol, status=STATUS_PENDING_EXTENSION)
            if not cycle:
                continue

            total_qty = int(cycle["total_qty"])
            if total_qty <= 0:
                continue

            try:
                price_data = kis_api.get_current_price(symbol, exchange=price_exchange)
                current_price = price_data["price"]
            except Exception as e:
                self._log_event(symbol, cycle["id"], "LOC_SELL_ERROR",
                                message=f"LOC 매도 예약 시세조회 실패: {str(e)}")
                continue

            self.update_cycle_price(cycle["id"], current_price)

            sell_decision = self.calculate_sell_decision(cycle, current_price)
            if not sell_decision["should_sell"]:
                continue

            sell_type = sell_decision.get("sell_type", STRATEGY_FULL_SELL)
            sell_qty = sell_decision.get("sell_qty", total_qty)

            try:
                # LOC 매도 주문 — 현재가를 지정가로 설정
                order_result = kis_api.sell_order(
                    symbol, sell_qty, price=current_price, order_type="LOC", exchange=order_exchange
                )

                self._log_event(symbol, cycle["id"], "LOC_SELL_SCHEDULED",
                                action=ACTION_SELL,
                                message=f"LOC 매도 예약: {sell_qty}주 @ ${current_price:.2f}, "
                                        f"수익률 {sell_decision['profit_rate']:.2f}%, "
                                        f"주문번호 {order_result.get('order_no', 'N/A')}")

                orders.append({
                    "symbol": symbol,
                    "cycle_id": cycle["id"],
                    "sell_type": sell_type,
                    "sell_qty": sell_qty,
                    "price": current_price,
                    "profit_rate": sell_decision["profit_rate"],
                    "order_no": order_result.get("order_no", ""),
                    "reason": sell_decision["reason"],
                })
            except Exception as e:
                self._log_event(symbol, cycle["id"], "LOC_SELL_ERROR",
                                message=f"LOC 매도 예약 주문 실패: {str(e)}")

        return {
            "status": "completed",
            "sell_method": "LOC",
            "scheduled_count": len(orders),
            "orders": orders,
        }

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
            kis = self.struct.kis_api
            cash_balance = float(kis.get_buying_power())
            if hasattr(kis, "get_present_balance"):
                present = kis.get_present_balance()
                exchange_rate = float(present.get("usd_krw", 0) or 0)
                present_total_asset_krw = float(present.get("total_asset_krw", 0) or 0)
                krw_balance = float(present.get("withdrawable_krw", present.get("krw_balance", 0)))
                cash_balance_krw += krw_balance
                if krw_balance > 0 and exchange_rate > 0:
                    cash_balance += krw_balance / exchange_rate

            overseas_balance = kis.get_balance() or {}
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

        # KRW 기준 손익률 (스냅샷 기반)
        total_profit_krw = 0.0
        first_snap = snapshot_db.rows(orderby="snapshot_date", order="ASC", page=1, dump=1)
        if first_snap:
            first_asset = float(first_snap[0].get("total_asset", 0) or 0)
            if first_asset > 0 and total_asset_krw > 0:
                total_profit_krw = total_asset_krw - first_asset
                profit_rate = (total_profit_krw / first_asset * 100)

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
