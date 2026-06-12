# 단타 구매 상한 캐시 동기화 수정

- **ID**: 009
- **날짜**: 2026-04-17
- **유형**: 버그 수정

## 작업 요약
단타 화면의 구매 상한이 실제 계좌 상태와 어긋나던 원인을 추적한 결과, 사용자 응답 경로에서 `shared_budget_status(..., use_cache_only=True)`를 사용해 cache miss 시 0원 또는 오래된 값으로 계산되는 문제가 있었다.
이를 TTL 캐시 기반 실제 조회(`use_cache_only=False`)로 통일하여 bootstrap/live_status/recommend/chart_data 경로의 구매 상한과 남은 시드가 같은 기준으로 계산되도록 수정했다.

## 변경 파일 목록
### 백엔드
- `src/app/page.daytrade/api.py`
  - bootstrap / chart_data / recommend / live_status 의 예산 조회를 `use_cache_only=False`로 변경
  - 구매 상한(`max_affordable_per_share`)과 recommendation 동기화 데이터가 동일한 예산 스냅샷을 사용하도록 정리

## 검증
- 변경 파일 diagnostics 확인: 오류 없음
- WIZ 일반 빌드 성공 (`clean: false`)
