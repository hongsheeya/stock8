# 단타 정체 종목 교체(로테이션) 전략 추가

- **ID**: 006
- **날짜**: 2026-04-15
- **유형**: 기능 추가

## 작업 요약
보유 종목이 일정 시간 이상 정체되고 본전 이상 청산이 가능하면서, 더 높은 점수의 대체 후보가 즉시 진입 가능한 경우 자동으로 교체 매도를 검토하도록 로직을 추가했다. 교체 매도 후에는 대체 종목을 자동순환 우선순위의 맨 앞으로 올려 다음 진입을 먼저 점검한다.

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `_break_even_price()`, `_last_buy_order()`, `_minutes_since()` 추가
  - `_rotation_opportunity()` 추가로 정체 종목 교체 후보 판단
  - `auto_cycle()`에 교체 매도 실행 및 후속 타깃 우선 점검 로직 추가

## 검증
- 빌드 성공 확인
- 자동순환 결과 구조에 `rotation_exit`, `rotation_target` 필드 추가 확인
