# 단타 미실행 사유·로그 시간·진입 상한 동기화 수정

- **ID**: 006
- **날짜**: 2026-04-17
- **유형**: 버그 수정

## 작업 요약
단타 워커/랭킹 UI에서 미실행 사유가 너무 일반적으로 보이던 문제를 보완하고, 워커 실행 시각을 KST 기준으로 통일했다.
또한 stale 추천 캐시가 예전 `21,539원` 상한을 계속 우선 표시하던 문제를 수정하고, 구형 `구매 가능 상한` 로그를 정리했다.

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct.py`
  - 워커 `last_run_at` 및 config 저장 시간을 KST 기준으로 기록하도록 수정
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `runtime_logs.json` 로딩 시 구형 `구매 가능 상한` 로그를 정리
  - 활성 `auto_candidates()`에 현재 시드/슬롯 스냅샷 로그 추가
  - `auto_cycle()`의 신규 진입 보류 결과에 `runtime_warnings`, `decision_reason` 등을 포함하도록 보강

### 프론트엔드
- `src/app/page.daytrade/view.ts`
  - 추천 예산/상한을 현재 `budgetStatus`, `maxAffordable` 기준으로 로컬 동기화하는 헬퍼 추가
  - bootstrap/recommend/sync_seed/live_status 경로에서 stale 상한값이 남지 않도록 동기화
  - 랭킹/워커 사유 문구가 `runtime_issues`, `runtime_warnings`를 우선 표시하도록 개선

## 검증
- 변경 파일 diagnostics 확인: 오류 없음
- WIZ 일반 빌드 성공 (`clean: false`)
