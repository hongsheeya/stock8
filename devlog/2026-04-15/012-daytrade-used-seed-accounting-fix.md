# 단타 사용 시드 집계 오류 수정

- **ID**: 012
- **날짜**: 2026-04-15
- **유형**: 버그 수정

## 작업 요약
단타 `used_seed_krw`가 0이거나 실제보다 작게 잡히던 문제를 브로커 기준 활성 포지션 집계로 교체해 수정했다. 사용 시드는 로컬 임시 상태가 아니라 실제 보유 수량을 기준으로 계산하고, 각 종목별로 `평균단가 기준 원금`과 `현재 평가금액` 중 더 큰 값을 `committed_seed`로 사용하도록 바꿨다.

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `portfolio_usage()`를 브로커 동기화된 `active_positions()` 기준으로 재구성
  - `active_cost_krw`, `active_market_value_krw`, `active_committed_seed_krw`를 추가
  - 각 포지션에 `position_cost`, `committed_seed`를 노출
  - `shared_budget_status()`에서 `used_seed_krw`를 `active_committed_seed_krw` 기반으로 계산하도록 수정
  - `capacity_daytrade_seed_krw`, `total_seed_krw`, `remaining_seed_krw` 식을 보유 포지션 포함 기준으로 정렬
- `src/app/page.daytrade/api.py`
  - `debug_balance()` 응답에 `portfolio_usage`, `capacity_daytrade_seed_krw`, `used_seed_krw`, `remaining_seed_krw`를 추가해 집계 근거를 확인할 수 있게 보강
- `src/app/page.daytrade/view.pug`
  - 예산 설명 문구를 “실보유 포지션 기반 사용 시드” 의미에 맞게 수정

## 검증
- 수정 파일 오류 검사 통과
- 프로젝트 일반 빌드 성공 확인
- 디버그 응답에서 사용 시드/남은 시드/포트폴리오 근거를 함께 확인할 수 있도록 정리
