# =============================================================================
# 고급 매도 전략 모듈 (분할 매도 + 폭락장 추가 매입)
# =============================================================================
# - PartialSellStrategy: 특정 회차 이후 목표 도달 시 일부만 LOC 매도, 잔량 보유
# - CrashBuyStrategy: 폭락장 감지 시 잔여 투자금의 일정 비율 추가 LOC 매수
# - 백테스팅 유틸: yfinance 데이터로 전량 매도 vs 분할 매도 비교 시뮬레이션
# =============================================================================
import math

# ─── 전략 타입 상수 ─────────────────────────────────────────────────
STRATEGY_FULL_SELL = "FULL_SELL"         # 기존: 전량 매도
STRATEGY_PARTIAL_SELL = "PARTIAL_SELL"   # 분할 매도 (일부만 익절)
STRATEGY_CRASH_BUY = "CRASH_BUY"        # 폭락장 추가 매입

DEFAULT_PARTIAL_SELL_STAGES = [
    {"min_round": 11, "max_round": 20, "profit_threshold": 5.0, "sell_ratio": 20.0},
    {"min_round": 21, "max_round": 30, "profit_threshold": 4.0, "sell_ratio": 30.0},
    {"min_round": 31, "max_round": None, "profit_threshold": 3.0, "sell_ratio": 40.0},
]

# ─── 기본 파라미터 (경험적 최적값) ────────────────────────────────
DEFAULT_PARAMS = {
    # 분할 매도
    "sell_strategy": "full",                     # "full" | "partial"
    "partial_sell_stages": DEFAULT_PARTIAL_SELL_STAGES,
    "partial_sell_remaining_full_exit": True,     # 잔량이 다시 목표 도달 시 전량 매도

    # 폭락장 추가 매입
    "crash_buy_enabled": False,
    "crash_buy_drop_pct": 5.0,                   # 전일 대비 하락률 기준 (%)
    "crash_buy_ma_drop_pct": 10.0,               # 5일 이동평균 대비 하락률 기준 (%)
    "crash_buy_ratio": 10,                       # 잔여 투자금의 매입 비율 (%)
    "crash_buy_max_per_cycle": 3,                # 사이클 당 최대 crash buy 횟수
}


def _normalize_partial_sell_stages(stages=None):
    normalized = []
    for stage in stages or DEFAULT_PARTIAL_SELL_STAGES:
        min_round = int(stage.get("min_round", 0))
        max_round = stage.get("max_round")
        threshold = float(stage.get("profit_threshold", 0))
        sell_ratio = float(stage.get("sell_ratio", 0))

        if max_round is not None:
            max_round = int(max_round)
        if min_round <= 0 or threshold <= 0 or sell_ratio <= 0:
            continue

        normalized.append({
            "min_round": min_round,
            "max_round": max_round,
            "profit_threshold": threshold,
            "sell_ratio": sell_ratio,
        })

    normalized.sort(key=lambda x: x["min_round"])
    return normalized


# =====================================================================
# 분할 매도 전략
# =====================================================================

class PartialSellStrategy:
    """
    특정 회차 이후 목표 수익률 도달 시 보유 수량의 일부만 매도.
    매도된 부분의 수익을 실현하고, 나머지는 계속 보유하여 추가 상승 가능성 확보.
    잔량이 다시 목표 도달하면 전량 매도 (기본 설정).
    """

    def __init__(self, params=None):
        p = {**DEFAULT_PARAMS}
        if params:
            p.update(params)
        self.stages = _normalize_partial_sell_stages(p.get("partial_sell_stages"))
        self.full_exit_remaining = bool(p.get("partial_sell_remaining_full_exit", True))

    def _get_stage(self, current_round):
        for stage in self.stages:
            max_round = stage.get("max_round")
            if current_round < stage["min_round"]:
                continue
            if max_round is not None and current_round > max_round:
                continue
            return stage
        return None

    def evaluate(self, cycle, profit_rate, target_profit):
        """
        분할 매도 판단.
        반환: dict {action, sell_qty, reason}
            action: "FULL_SELL" | "PARTIAL_SELL" | "HOLD"
        """
        current_round = int(cycle.get("current_round", 0))
        total_qty = int(cycle.get("total_qty", 0))
        partial_sold = int(cycle.get("partial_sold_count", 0))  # 이 사이클에서 분할 매도한 횟수

        if total_qty <= 0:
            return {"action": "HOLD", "sell_qty": 0, "reason": "보유 수량 없음"}

        if profit_rate >= target_profit:
            return {
                "action": STRATEGY_FULL_SELL,
                "sell_qty": total_qty,
                "reason": f"최종 목표 수익률 도달 ({profit_rate:.2f}% >= {target_profit}%) → 전량 매도",
            }

        if partial_sold > 0 and self.full_exit_remaining:
            return {
                "action": "HOLD",
                "sell_qty": 0,
                "reason": f"분할 매도 후 잔량 보유 중 (최종 목표 {target_profit}%)",
            }

        stage = self._get_stage(current_round)
        if stage is None:
            return {
                "action": "HOLD",
                "sell_qty": 0,
                "reason": f"R{current_round}: 초기 회차는 최종 목표({target_profit}%)까지 홀드",
            }

        threshold = float(stage["profit_threshold"])
        sell_ratio = float(stage["sell_ratio"])

        if profit_rate < threshold:
            return {
                "action": "HOLD",
                "sell_qty": 0,
                "reason": f"R{current_round}: {threshold:.1f}% 부분 익절 대기 ({profit_rate:.2f}%)",
            }

        sell_qty = max(1, int(total_qty * (sell_ratio / 100)))
        if sell_qty >= total_qty:
            if total_qty <= 1:
                return {
                    "action": "HOLD",
                    "sell_qty": 0,
                    "reason": "보유 수량이 1주라 분할 매도 불가",
                }
            sell_qty = total_qty - 1

        return {
            "action": STRATEGY_PARTIAL_SELL,
            "sell_qty": sell_qty,
            "reason": f"R{current_round}: +{threshold:.1f}% 도달 → {int(sell_ratio)}% 분할 매도 ({sell_qty}/{total_qty}주)",
        }


# =====================================================================
# 폭락장 추가 매입 전략
# =====================================================================

class CrashBuyStrategy:
    """
    폭락장 탐지 시 잔여 투자금의 일정 비율을 추가 LOC 매수.
    일반 회차를 소진하지 않고 별도 기록.
    """

    def __init__(self, params=None):
        p = {**DEFAULT_PARAMS}
        if params:
            p.update(params)
        self.enabled = bool(p.get("crash_buy_enabled", False))
        self.drop_pct = float(p.get("crash_buy_drop_pct", 5.0))
        self.ma_drop_pct = float(p.get("crash_buy_ma_drop_pct", 10.0))
        self.buy_ratio = float(p.get("crash_buy_ratio", 10)) / 100  # % → 소수
        self.max_per_cycle = int(p.get("crash_buy_max_per_cycle", 3))

    def detect_crash(self, current_price, prev_close, ma5=None):
        """
        폭락 여부 판단.
        조건 (OR):
          1. 전일 대비 하락률 >= drop_pct%
          2. 5일 이동평균 대비 하락률 >= ma_drop_pct%
        반환: dict {is_crash, daily_drop, ma_drop, reason}
        """
        if not self.enabled:
            return {"is_crash": False, "daily_drop": 0, "ma_drop": 0, "reason": "폭락장 매입 비활성"}

        daily_drop = 0
        ma_drop = 0

        if prev_close > 0:
            daily_drop = ((prev_close - current_price) / prev_close) * 100  # 양수 = 하락

        if ma5 and ma5 > 0:
            ma_drop = ((ma5 - current_price) / ma5) * 100  # 양수 = 하락

        is_crash = False
        reasons = []
        if daily_drop >= self.drop_pct:
            is_crash = True
            reasons.append(f"전일 대비 -{daily_drop:.1f}% (기준: -{self.drop_pct}%)")
        if ma_drop >= self.ma_drop_pct:
            is_crash = True
            reasons.append(f"5일MA 대비 -{ma_drop:.1f}% (기준: -{self.ma_drop_pct}%)")

        return {
            "is_crash": is_crash,
            "daily_drop": round(daily_drop, 2),
            "ma_drop": round(ma_drop, 2),
            "reason": " / ".join(reasons) if reasons else "정상 범위",
        }

    def evaluate(self, cycle, current_price, prev_close, ma5=None, crash_count=0):
        """
        추가 매입 판단.
        반환: dict {should_buy, buy_amount, loc_price, reason}
        """
        if not self.enabled:
            return {"should_buy": False, "buy_amount": 0, "loc_price": 0, "reason": "폭락장 매입 비활성"}

        if crash_count >= self.max_per_cycle:
            return {"should_buy": False, "buy_amount": 0, "loc_price": 0,
                    "reason": f"사이클 당 최대 crash buy 횟수 도달 ({crash_count}/{self.max_per_cycle})"}

        crash = self.detect_crash(current_price, prev_close, ma5)
        if not crash["is_crash"]:
            return {"should_buy": False, "buy_amount": 0, "loc_price": 0, "reason": crash["reason"]}

        remaining = float(cycle.get("remaining_investment", 0))
        buy_amount = remaining * self.buy_ratio

        if buy_amount < 1:
            return {"should_buy": False, "buy_amount": 0, "loc_price": 0, "reason": "잔여 투자금 부족"}

        # LOC 가격: 현재가 (폭락장이므로 현재 저가에 매수 시도)
        loc_price = current_price

        return {
            "should_buy": True,
            "buy_amount": round(buy_amount, 2),
            "loc_price": round(loc_price, 2),
            "reason": f"폭락장 감지! {crash['reason']} → 잔여금의 {int(self.buy_ratio * 100)}% 추가 매수",
        }


# =====================================================================
# 백테스팅 엔진 (전략 비교)
# =====================================================================

def backtest_strategy(daily_prices, investment, division_count, target_profit,
                      buy_commission_rate=0.0025, sell_commission_rate=0.0025, tax_rate=0,
                      sell_strategy="full", strategy_params=None, allow_extension=False):
    """
    백테스트 시뮬레이션 실행 (단일 전략).

    Args:
        daily_prices: [{date, open, high, low, close, volume}, ...]
        investment: 초기 투자금 (USD)
        division_count: 기본 분할 횟수
        target_profit: 목표 수익률 (%)
        buy_commission_rate: 매수 수수료율 (소수)
        sell_commission_rate: 매도 수수료율 (소수)
        tax_rate: 세금률 (소수)
        sell_strategy: "full" | "partial"
        strategy_params: 전략 파라미터 dict (PartialSellStrategy / CrashBuyStrategy용)
        allow_extension: 분할 소진 시 자동 연장

    Returns:
        dict {summary, trades, cycles}
    """
    params = strategy_params or {}
    partial_strategy = PartialSellStrategy(params) if sell_strategy == "partial" else None
    crash_strategy = CrashBuyStrategy(params)

    all_trades = []
    all_cycles = []
    cycle_num = 0
    total_realized_profit = 0
    total_commission_sum = 0
    current_asset = investment
    max_asset = investment
    max_drawdown = 0
    extension_count = 0

    # 사이클 상태
    remaining_total = investment
    cycle_active = False
    cycle_round = 0
    cycle_division_count = division_count
    cycle_total_spent = 0
    cycle_total_qty = 0
    cycle_avg_price = 0
    cycle_remaining = 0
    cycle_start_date = ""
    cycle_commission = 0
    partial_sold_count = 0
    crash_buy_count = 0

    # 5일 이동평균 계산용
    recent_closes = []

    for i, dp in enumerate(daily_prices):
        date = dp.get("date", "")
        close = float(dp.get("close", 0))
        prev_close = float(daily_prices[i - 1].get("close", close)) if i > 0 else close

        if close <= 0:
            continue

        # 5일 이동평균 갱신
        recent_closes.append(close)
        if len(recent_closes) > 5:
            recent_closes.pop(0)
        ma5 = sum(recent_closes) / len(recent_closes) if recent_closes else close

        # ── 새 사이클 시작 ──
        if not cycle_active and remaining_total > 10:
            cycle_active = True
            cycle_num += 1
            cycle_round = 0
            cycle_division_count = division_count
            cycle_total_spent = 0
            cycle_total_qty = 0
            cycle_avg_price = 0
            cycle_remaining = min(remaining_total, investment)
            cycle_start_date = date
            cycle_commission = 0
            partial_sold_count = 0
            crash_buy_count = 0

        if not cycle_active:
            continue

        # ── 매도 체크 ──
        if cycle_total_qty > 0 and cycle_total_spent > 0:
            current_eval = cycle_total_qty * close
            sell_fee = current_eval * (sell_commission_rate + tax_rate)
            net_proceeds = current_eval - sell_fee
            net_profit = net_proceeds - cycle_total_spent
            profit_rate = (net_profit / cycle_total_spent) * 100

            sell_action = "HOLD"
            sell_qty = 0

            if sell_strategy == "partial" and partial_strategy:
                mock_cycle = {
                    "current_round": cycle_round,
                    "total_qty": cycle_total_qty,
                    "partial_sold_count": partial_sold_count,
                }
                decision = partial_strategy.evaluate(mock_cycle, profit_rate, target_profit)
                sell_action = decision["action"]
                sell_qty = decision["sell_qty"]
            elif profit_rate >= target_profit:
                sell_action = STRATEGY_FULL_SELL
                sell_qty = cycle_total_qty

            if sell_action in (STRATEGY_FULL_SELL, STRATEGY_PARTIAL_SELL) and sell_qty > 0:
                sell_amount = sell_qty * close
                sell_fee_actual = sell_amount * (sell_commission_rate + tax_rate)
                net_sell = sell_amount - sell_fee_actual

                if sell_action == STRATEGY_FULL_SELL:
                    # 전량 매도 → 사이클 완료
                    realized = net_sell - cycle_total_spent
                    total_realized_profit += realized
                    cycle_commission += sell_fee_actual
                    total_commission_sum += sell_fee_actual
                    remaining_total += net_sell

                    all_trades.append({
                        "cycle_num": cycle_num, "date": date, "round": cycle_round,
                        "action": "SELL", "strategy_type": STRATEGY_FULL_SELL,
                        "price": close, "qty": sell_qty,
                        "amount": round(sell_amount, 2), "commission": round(sell_fee_actual, 2),
                        "net_amount": round(net_sell, 2), "avg_price": round(cycle_avg_price, 4),
                    })

                    all_cycles.append({
                        "cycle_num": cycle_num, "start_date": cycle_start_date, "end_date": date,
                        "rounds": cycle_round, "division_count": cycle_division_count,
                        "total_spent": round(cycle_total_spent, 2), "sell_price": close,
                        "sell_amount": round(sell_amount, 2), "commission": round(cycle_commission, 2),
                        "net_profit": round(realized, 2), "return_rate": round(profit_rate, 2),
                        "partial_sells": partial_sold_count, "crash_buys": crash_buy_count,
                    })

                    cycle_active = False
                    current_asset = remaining_total
                    if current_asset > max_asset:
                        max_asset = current_asset
                    dd = ((max_asset - current_asset) / max_asset) * 100 if max_asset > 0 else 0
                    if dd > max_drawdown:
                        max_drawdown = dd
                    continue

                else:
                    # 분할 매도 → 일부만 매도, 사이클 유지
                    # 매도된 부분의 비용 비례 차감
                    sell_ratio_actual = sell_qty / cycle_total_qty
                    sold_cost = cycle_total_spent * sell_ratio_actual
                    realized = net_sell - sold_cost
                    total_realized_profit += realized
                    cycle_commission += sell_fee_actual
                    total_commission_sum += sell_fee_actual
                    remaining_total += net_sell
                    cycle_remaining += net_sell

                    # 사이클 상태 갱신
                    cycle_total_qty -= sell_qty
                    cycle_total_spent -= sold_cost
                    # avg_price 유지 (비례 차감이므로 동일)
                    partial_sold_count += 1

                    all_trades.append({
                        "cycle_num": cycle_num, "date": date, "round": cycle_round,
                        "action": "SELL", "strategy_type": STRATEGY_PARTIAL_SELL,
                        "price": close, "qty": sell_qty,
                        "amount": round(sell_amount, 2), "commission": round(sell_fee_actual, 2),
                        "net_amount": round(net_sell, 2), "avg_price": round(cycle_avg_price, 4),
                    })
                    # 사이클은 계속 진행 (fall through to buy check)

        # ── 폭락장 추가 매입 체크 ──
        if cycle_active and crash_strategy.enabled and cycle_total_qty > 0:
            mock_cycle = {"remaining_investment": cycle_remaining}
            crash_decision = crash_strategy.evaluate(mock_cycle, close, prev_close, ma5, crash_buy_count)
            if crash_decision["should_buy"]:
                crash_amount = crash_decision["buy_amount"]
                crash_price = crash_decision["loc_price"]
                crash_qty = int(crash_amount / crash_price) if crash_price > 0 else 0

                if crash_qty > 0:
                    actual_cost = crash_qty * crash_price
                    buy_fee = actual_cost * buy_commission_rate
                    total_cost = actual_cost + buy_fee

                    if total_cost <= cycle_remaining:
                        cycle_total_spent += total_cost
                        cycle_total_qty += crash_qty
                        cycle_avg_price = cycle_total_spent / cycle_total_qty if cycle_total_qty > 0 else 0
                        cycle_remaining -= total_cost
                        remaining_total -= total_cost
                        cycle_commission += buy_fee
                        total_commission_sum += buy_fee
                        crash_buy_count += 1

                        all_trades.append({
                            "cycle_num": cycle_num, "date": date, "round": cycle_round,
                            "action": "BUY", "strategy_type": STRATEGY_CRASH_BUY,
                            "price": round(crash_price, 2), "qty": crash_qty,
                            "amount": round(actual_cost, 2), "commission": round(buy_fee, 2),
                            "net_amount": round(total_cost, 2), "avg_price": round(cycle_avg_price, 4),
                        })

        # ── 정규 매수 판단 ──
        if cycle_round >= cycle_division_count:
            if allow_extension:
                cycle_division_count += division_count
                extension_count += 1
                all_trades.append({
                    "cycle_num": cycle_num, "date": date, "round": cycle_round,
                    "action": "EXTEND", "strategy_type": "NORMAL",
                    "price": close, "qty": 0, "amount": 0, "commission": 0,
                    "net_amount": 0, "avg_price": round(cycle_avg_price, 4) if cycle_avg_price > 0 else 0,
                })
            else:
                continue

        cycle_round += 1
        remaining_rounds = cycle_division_count - (cycle_round - 1)
        buy_amount = cycle_remaining / remaining_rounds if remaining_rounds > 0 else 0

        if buy_amount <= 0:
            continue

        # 가격 결정
        if cycle_round == 1:
            buy_price = close
        else:
            buy_price = prev_close if prev_close <= cycle_avg_price else cycle_avg_price
            if close > buy_price:
                all_trades.append({
                    "cycle_num": cycle_num, "date": date, "round": cycle_round,
                    "action": "SKIP", "strategy_type": "NORMAL",
                    "price": buy_price, "qty": 0, "amount": 0, "commission": 0,
                    "net_amount": 0, "avg_price": round(cycle_avg_price, 4) if cycle_avg_price > 0 else 0,
                })
                continue

        buy_qty = int(buy_amount / buy_price) if buy_price > 0 else 0
        if buy_qty <= 0:
            continue

        actual_cost = buy_qty * buy_price
        buy_fee = actual_cost * buy_commission_rate
        total_cost = actual_cost + buy_fee

        cycle_total_spent += total_cost
        cycle_total_qty += buy_qty
        cycle_avg_price = cycle_total_spent / cycle_total_qty if cycle_total_qty > 0 else 0
        cycle_remaining -= total_cost
        remaining_total -= total_cost
        cycle_commission += buy_fee
        total_commission_sum += buy_fee

        all_trades.append({
            "cycle_num": cycle_num, "date": date, "round": cycle_round,
            "action": "BUY", "strategy_type": "NORMAL",
            "price": round(buy_price, 2), "qty": buy_qty,
            "amount": round(actual_cost, 2), "commission": round(buy_fee, 2),
            "net_amount": round(total_cost, 2), "avg_price": round(cycle_avg_price, 4),
        })

    # ── 미완료 사이클 처리 ──
    if cycle_active and cycle_total_qty > 0:
        last_close = float(daily_prices[-1].get("close", 0))
        current_eval = cycle_total_qty * last_close
        est_sell_fee = current_eval * (sell_commission_rate + tax_rate)
        est_net = current_eval - est_sell_fee
        profit_rate = ((est_net - cycle_total_spent) / cycle_total_spent * 100) if cycle_total_spent > 0 else 0
        current_asset = remaining_total + current_eval

        all_cycles.append({
            "cycle_num": cycle_num, "start_date": cycle_start_date,
            "end_date": daily_prices[-1].get("date", ""),
            "rounds": cycle_round, "division_count": cycle_division_count,
            "total_spent": round(cycle_total_spent, 2), "sell_price": last_close,
            "sell_amount": round(current_eval, 2), "commission": round(cycle_commission, 2),
            "net_profit": round(est_net - cycle_total_spent, 2),
            "return_rate": round(profit_rate, 2),
            "partial_sells": partial_sold_count, "crash_buys": crash_buy_count,
        })
    else:
        current_asset = remaining_total

    total_return = ((current_asset - investment) / investment * 100) if investment > 0 else 0
    completed = [c for c in all_cycles if c.get("return_rate", 0) >= target_profit]
    win_rate = (len(completed) / len(all_cycles) * 100) if all_cycles else 0

    # 평균 사이클 기간
    avg_days = 0
    if all_cycles:
        import datetime
        total_days = 0
        for c in all_cycles:
            try:
                sd = datetime.datetime.strptime(c["start_date"], "%Y-%m-%d")
                ed = datetime.datetime.strptime(c["end_date"], "%Y-%m-%d")
                total_days += (ed - sd).days
            except Exception:
                pass
        avg_days = total_days / len(all_cycles)

    total_partial_sells = sum(c.get("partial_sells", 0) for c in all_cycles)
    total_crash_buys = sum(c.get("crash_buys", 0) for c in all_cycles)

    summary = {
        "sell_strategy": sell_strategy,
        "initial_investment": investment,
        "final_asset": round(current_asset, 2),
        "total_return": round(total_return, 2),
        "total_cycles": len(all_cycles),
        "completed_cycles": len(completed),
        "win_rate": round(win_rate, 1),
        "avg_cycle_days": round(avg_days, 1),
        "max_drawdown": round(max_drawdown, 2),
        "total_commission": round(total_commission_sum, 2),
        "extension_count": extension_count,
        "partial_sells": total_partial_sells,
        "crash_buys": total_crash_buys,
    }

    return {"summary": summary, "trades": all_trades, "cycles": all_cycles}


def compare_strategies(daily_prices, investment, division_count, target_profit,
                       buy_commission_rate=0.0025, sell_commission_rate=0.0025, tax_rate=0,
                       strategy_params=None, allow_extension=False):
    """
    전량 매도 vs 분할 매도 전략 비교 백테스트.
    동일 조건에서 두 전략을 실행하여 결과를 나란히 반환.

    Returns:
        dict {full: {summary, trades, cycles}, partial: {summary, trades, cycles}}
    """
    common = dict(
        daily_prices=daily_prices,
        investment=investment,
        division_count=division_count,
        target_profit=target_profit,
        buy_commission_rate=buy_commission_rate,
        sell_commission_rate=sell_commission_rate,
        tax_rate=tax_rate,
        allow_extension=allow_extension,
    )

    full_result = backtest_strategy(**common, sell_strategy="full", strategy_params=strategy_params)
    partial_result = backtest_strategy(**common, sell_strategy="partial", strategy_params=strategy_params)

    return {
        "full": full_result,
        "partial": partial_result,
    }


Model = {
    "PartialSellStrategy": PartialSellStrategy,
    "CrashBuyStrategy": CrashBuyStrategy,
    "backtest_strategy": backtest_strategy,
    "compare_strategies": compare_strategies,
    "DEFAULT_PARAMS": DEFAULT_PARAMS,
    "STRATEGY_FULL_SELL": STRATEGY_FULL_SELL,
    "STRATEGY_PARTIAL_SELL": STRATEGY_PARTIAL_SELL,
    "STRATEGY_CRASH_BUY": STRATEGY_CRASH_BUY,
}
