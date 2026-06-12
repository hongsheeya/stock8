# FN-20260429-0004: 미장 단타 장마감 청산 로직 개선

## 작업 번호
- **ID**: FN-20260429-0004
- **날짜**: 2026-04-29
- **유형**: 알고리즘 개선

## 현재 문제

### 증상
- 시장 마감 시간(ET 16:00, KST 05:00)이 빠르게 다가올 때, 보유 포지션을 **무조건 전량 매도**
- 문제: 손절이 되어도 내일 갭업 기회를 놓칠 수 있음
- 목표: 손익 상황에 따라 **선택적 청산** 정책 적용

## 개선 목표

### 새로운 청산 정책

```
장 마감 15분 전 (ET 15:45)
├─ 수익 +5% 이상 → **전량 매도 (이익 실현)**
├─ 손실 -3% ~ +5% → **부분 매도 (50% 청산, 50% 유지)**
│   └─ 유지되는 50%는 내일 갭업 기대
└─ 손실 -3% 이하 → **전량 유지 (내일 역전 기대)**
     └─ 단, 손절가(<-8%) 도달 시 즉시 전량 매도
```

## 구현 상세

### 1. 개념 정의

| 상테잇 | 수익률 범위 | 액션 | 이유 |
|--------|-----------|------|------|
| PROFIT_STRONG | >= +5% | FULL_SELL | 이익 고정 |
| PROFIT_WEAK | +3% ~ +5% | PARTIAL_SELL | 추가 상승 기대 |
| WITHIN_MARGIN | -3% ~ +3% | PARTIAL_SELL | 손절 방지 + 상승가능성 확보 |
| LOSS_MINOR | -3% ~ -8% | FULL_HOLD | 내일 갭업 기대 |
| LOSS_SEVERE | < -8% | FULL_SELL | 손절 집행 |

### 2. 코드 위치

#### 수정할 파일
- **`src/portal/trading/model/struct/daytrade_engine.py`**
  - 메서드: `execute_market_close()` (라인 미상)
  - 새 메서드: `calculate_market_close_policy()`

### 3. 구현 로직

```python
# daytrade_engine.py 추가 메서드

def calculate_market_close_policy(self, position_profit_rate, position_cost_qty):
    """
    market close 시 청산 정책 결정
    
    Args:
        position_profit_rate: 현재 수익률 (%)
        position_cost_qty: 보유 수량
    
    Returns:
        {
            "action": "FULL_SELL" | "PARTIAL_SELL" | "FULL_HOLD",
            "sell_qty": <int>,  # 매도할 수량 (0이면 매도 안 함)
            "reason": <str>
        }
    """
    
    # 경계값 정의
    PROFIT_STRONG_THRESHOLD = 5.0      # +5%
    PROFIT_WEAK_THRESHOLD = 3.0        # +3%
    WITHIN_MARGIN_THRESHOLD = -3.0     # -3%
    LOSS_SEVERE_THRESHOLD = -8.0       # -8%
    
    profit_rate = float(position_profit_rate or 0.0)
    
    if profit_rate >= PROFIT_STRONG_THRESHOLD:
        # 강한 수익: 전량 매도
        return {
            "action": "FULL_SELL",
            "sell_qty": position_cost_qty,
            "reason": f"장마감 강한수익({profit_rate:.2f}%) 전량 청산"
        }
    
    elif profit_rate >= PROFIT_WEAK_THRESHOLD:
        # 약한 수익: 절반 매도
        sell_qty = int(position_cost_qty * 0.5)
        return {
            "action": "PARTIAL_SELL",
            "sell_qty": sell_qty,
            "reason": f"장마감 약한수익({profit_rate:.2f}%) 50% 부분청산, 50% 유지"
        }
    
    elif profit_rate >= WITHIN_MARGIN_THRESHOLD:
        # 손절 방지 범위: 절반 매도
        sell_qty = int(position_cost_qty * 0.5)
        return {
            "action": "PARTIAL_SELL",
            "sell_qty": sell_qty,
            "reason": f"장마감 한계손미({profit_rate:.2f}%) 50% 부분청산"
        }
    
    elif profit_rate > LOSS_SEVERE_THRESHOLD:
        # 경미한 손실: 유지
        return {
            "action": "FULL_HOLD",
            "sell_qty": 0,
            "reason": f"장마감 손실({profit_rate:.2f}%) 내일 갭업 기대 유지"
        }
    
    else:
        # 심각한 손실: 손절 집행
        return {
            "action": "FULL_SELL",
            "sell_qty": position_cost_qty,
            "reason": f"장마감 심각손실({profit_rate:.2f}%) 손절 집행"
        }


def execute_market_close(self, symbol, market="US"):
    """
    시장 마감 시 청산 로직
    
    기존: 무조건 전량 매도
    개선: calculate_market_close_policy() 결과 기반 선택적 청산
    """
    
    # 현재 포지션 정보 조회
    position = self._get_position(symbol, market)
    if not position or position.get("qty", 0) == 0:
        return {"action": "NO_POSITION", "reason": "보유 포지션 없음"}
    
    # 손익률 계산
    current_price = self._get_current_price(symbol, market)
    avg_price = position.get("avg_price", 0.0)
    profit_rate = ((current_price - avg_price) / avg_price) * 100
    
    # 정책 결정
    policy = self.calculate_market_close_policy(profit_rate, position.get("qty", 0))
    
    # 액션 실행
    if policy["action"] == "FULL_SELL":
        self._execute_sell_order(symbol, market, policy["sell_qty"], "LOC", policy["reason"])
        return {"action": "FULL_SELL", "reason": policy["reason"]}
    
    elif policy["action"] == "PARTIAL_SELL":
        self._execute_sell_order(symbol, market, policy["sell_qty"], "LOC", policy["reason"])
        return {"action": "PARTIAL_SELL", "sell_qty": policy["sell_qty"], "reason": policy["reason"]}
    
    else:  # FULL_HOLD
        self._log_runtime(symbol, market, policy["reason"])
        return {"action": "FULL_HOLD", "reason": policy["reason"]}
```

### 4. 테스트 케이스

```
테스트 1: 강한 수익 (+6%)
- 입력: profit_rate=6.0, position_qty=100
- 예상: action=FULL_SELL, sell_qty=100 ✓

테스트 2: 약한 수익 (+4%)
- 입력: profit_rate=4.0, position_qty=100
- 예상: action=PARTIAL_SELL, sell_qty=50 ✓

테스트 3: 한계 손실 (-2%)
- 입력: profit_rate=-2.0, position_qty=100
- 예상: action=PARTIAL_SELL, sell_qty=50 ✓

테스트 4: 경미 손실 (-5%)
- 입력: profit_rate=-5.0, position_qty=100
- 예상: action=FULL_HOLD, sell_qty=0 ✓

테스트 5: 심각 손실 (-10%)
- 입력: profit_rate=-10.0, position_qty=100
- 예상: action=FULL_SELL, sell_qty=100 ✓
```

## 구현 계획

### Phase 1: 코드 작성 (1시간)
- [ ] `calculate_market_close_policy()` 메서드 구현
- [ ] `execute_market_close()` 메서드 수정
- [ ] 로깅 추가

### Phase 2: 단위 테스트 (1시간)
- [ ] 5가지 케이스 수동 테스트
- [ ] edge case (0원, 극단치) 테스트
- [ ] 에러 핸들링 검증

### Phase 3: 통합 테스트 (1시간)
- [ ] 실시간 장마감 시나리오 테스트
- [ ] UI에서 live_state.json 반영 확인
- [ ] 기존 KS 로직과의 호환성 확인

## 예상 효과

**목표**:
- ✅ 불필요한 전량 매도 방지
- ✅ 손실 포지션 내일 기대 회복 가능
- ✅ 수익 포지션 이익 고정

**부작용 방지**:
- 내일 갭다운 시 손실 추가 가능 → 손절 정책으로 대응
-ラウ내 가격 급락 시 심각 손실 → -8% 손절로 방지

**총 투입 시간**: 약 3시간
