# 구매 상한 21,539원 근본 원인 분석 및 로그 개선

- **ID**: 010
- **날짜**: 2026-04-17
- **유형**: 버그 수정 + 진단 개선

## 작업 요약

사용자가 보고한 "구매 상한 21,539원" 로그가 로그 파일을 도배하며 모든 종목 매수를 막는 문제의 근본 원인을 분석하고, 코드 버그 3가지를 수정함.

## 근본 원인 분석

### 1번: 21,539원의 실제 계산 경로

```
KIS TTTC8908R(주문가능금액 조회) → withdrawable_krw
tradable_cash_krw = max(withdrawable_krw, d1_deposit_krw, d2_deposit_krw)
available_for_daytrade = tradable_cash_krw - 무한매수_예약금
remaining_seed_krw = min(available_for_daytrade, total_seed_krw - used_seed_krw)
max_affordable_per_share = remaining_seed_krw * buy_buffer_ratio(0.985)
```

**21,539 = 실제 KIS 주문가능금액(또는 무한매수 예약금 차감 후 잔액)**이며,
모든 추천 종목(삼성전자 217,500원, 엔씨소프트 265,500원 등)이 이 금액을 초과하여
전부 제외됨 → 매수 불가.

매도도 안 되는 이유: live_state.json에 모든 포지션이 qty=0 → 청산할 보유 포지션도 없음.

### 2번: 중복 auto_candidates 함수 정의

`DomesticDaytradeEngine` 클래스에 `auto_candidates` 메서드가 line 1224, line 3094 두 곳에 정의됨.
Python은 두 번째 정의로 첫 번째를 **완전히 덮어씀**. 두 함수의 코드가 111개 차이점이 있었고,
첫 번째(구버전, force=True 고정)는 데드코드였음.

### 3번: _append_runtime_log dedup 로직 버그

- 기존: 마지막 1개 항목만 비교, 60초 window
- 문제: `_load_runtime_logs()`가 타임스탬프를 KST로 정규화하여 반환 → dedup 비교 시
  "파일의 UTC 타임스탬프 정규화 = KST+9"를 `_now()`(KST)와 비교 → 차이가 항상 큼 → dedup 실패
- 또한 엔씨소프트/삼성전자/한화에어로 등 서로 다른 종목이 연속 로그되면 last-1 비교만으로는 dedup 안 됨
- 결과: 50개 슬롯 전부 동일 패턴 메시지로 채워져 "단타 후보 계산 시작" 같은 진단 로그가 안 보임

## 변경 파일 목록

### `src/portal/trading/model/struct/daytrade_engine.py`

1. **중복 `auto_candidates` 제거**: line 1224~1364(구버전) 삭제. line 3094(신버전)만 유지
2. **`_append_runtime_log` dedup 전면 개선**:
   - raw JSON 파일 직접 읽기 (normalize 없이) → 타임스탬프 shift 오류 제거
   - 최근 20개 항목 중 동일 메시지 확인 (기존: 마지막 1개)
   - dedup 창: 300초(5분) 기본값, 호출마다 `dedup_sec` 파라미터로 조정 가능
   - UTC vs KST 타임스탬프 자동 판별 후 올바른 현재 시각과 비교
3. **구매 상한 진단 로그 추가**:
   - "단타 후보 계산 시작" 메타에 `kis_withdrawable_krw`, `kis_d1_deposit_krw`,
     `kis_d2_deposit_krw`, `infinite_buy_reserve_krw`, `balance_source` 추가
   - `max_affordable < 100,000` 시 "구매 상한 낮음" warning 로그 (10분 dedup)
     → 왜 상한이 낮은지(KIS 잔고 / D1/D2 / 무한매수 예약금) 즉시 파악 가능

## 사용자 액션 필요

**21,539원 문제가 실제로 해결되려면:**
- 다음 빌드 이후 로그에서 "구매 상한 낮음" 경고 항목을 확인
- `kis_withdrawable_krw`, `kis_d1_deposit_krw`, `kis_d2_deposit_krw`, `infinite_buy_reserve_krw` 값으로 원인 식별:
  - KIS 잔고 자체가 낮다면: 무한매수 전략에 자금이 많이 묶여있거나 실제 계좌 cash 부족
  - 무한매수 예약금이 크다면: `daytrade_ignore_reserve=true` 설정 고려
  - D1/D2가 크다면: tomorrow 이후 결제될 자금이 있으므로 일시적 상황
