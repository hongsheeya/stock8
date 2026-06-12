# 단타 청산 우선순위 문서화 및 vrev 잭팟 예약 우선순위 보정

- **ID**: 001
- **날짜**: 2026-04-22
- **유형**: 문서 업데이트

## 작업 요약
vrev 청산 로직의 실제 우선순위와 방어/구조 부분 청산 조건을 코드 기준으로 정리한 문서를 추가했다. 또한 잭팟 근접 구간에서 볼린저 상단/RSI 익절보다 잭팟 사전예약 매도가 먼저 동작하도록 우선순위를 재정렬했다.

## 변경 파일 목록
### 문서
- `docs/daytrade/exit-priority-algorithm.md`
  - 청산 우선순위
  - 방어 부분 청산(`SELL_RECENT`) 조건
  - 구조 부분 청산(`SELL_RESCUE`) 조건
  - 잭팟 우선 전략이 조기익절처럼 보인 원인
  - 최근 수정 후 동작 방식

### 단타 엔진
- `src/portal/trading/model/struct/daytrade_engine.py`
  - vrev에서 잭팟 방어선 이상이면 soft exit보다 `PRE_SELL_JACKPOT`가 먼저 선택되도록 우선순위를 수정했다.

### 단타 프로필
- `src/portal/trading/model/struct/daytrade.py`
  - 잭팟 방어선 비율 프로필을 사용해 문서와 실제 동작을 일치시켰다.

## 검증
- 일반 빌드를 수행해 변경 사항이 정상 반영되는 것을 확인했다.
