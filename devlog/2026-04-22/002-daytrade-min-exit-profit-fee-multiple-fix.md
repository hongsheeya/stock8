# 단타 자동익절 최소 순이익을 수수료 배수 기준으로 강화

- **ID**: 002
- **날짜**: 2026-04-22
- **유형**: 버그 수정

## 작업 요약
손절이 아닌 자동 청산이 단순 손익분기 또는 고정 최소 순이익만 넘으면 실행되던 문제를 보완했다. 이제 자동 익절은 최소한 총수수료보다 충분히 큰 순이익이 예상될 때만 허용되며, 기본 기준은 총수수료의 2배 이상이다.

## 변경 파일 목록
### 단타 기본 프로필
- `src/portal/trading/model/struct/daytrade.py`
  - `min_exit_fee_multiple = 2.0` 기본값 추가

### 단타 엔진
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 예상 총수수료 계산 helper 추가
  - 자동 청산 허용 최소 순이익을 `max(min_exit_net_profit_krw, total_fee * min_exit_fee_multiple)`로 강화
  - HOLD 사유에 수수료 기준을 함께 표시하도록 수정

## 검증
- 일반 빌드를 수행해 변경 사항이 정상 반영되는 것을 확인했다.
