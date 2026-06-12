# 단타 초기 로딩 및 예산 계산 성능 최적화

- **ID**: 009
- **날짜**: 2026-04-15
- **유형**: 성능 개선

## 작업 요약
초기 화면 진입 시 `bootstrap` 이후 다시 `live_status`를 호출하던 이중 로딩 구조를 줄이기 위해, `bootstrap` 응답에 초기 시그널/계획/손실 상태를 함께 포함하도록 바꿨다. 또한 예산 계산 시 포트폴리오 사용 금액을 실시간 시세가 아니라 평균 단가 기반으로 빠르게 계산하도록 정리해 잦은 예산 조회 비용을 낮췄다.

## 변경 파일 목록
### 백엔드
- `src/app/page.daytrade/api.py`
  - `_build_live_plan_payload()` 추가
  - `bootstrap()`에서 초기 `status`, `plan`, `daily_loss`, `max_affordable_per_share` 반환
  - `live_status()` 계획 생성 로직 공용 헬퍼로 정리
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `portfolio_usage(use_live_price=False)` 경로 추가
  - `shared_budget_status()`가 빠른 포트폴리오 평가값을 재사용하도록 정리

### 프론트엔드
- `src/app/page.daytrade/view.ts`
  - bootstrap에서 저장된 시드를 바로 전달하고, 초기 상태가 이미 있으면 추가 `live_status` 호출을 생략

## 검증
- 빌드 성공 확인
- `bootstrap` 응답에 `has_status=true`, `has_plan=true` 확인
