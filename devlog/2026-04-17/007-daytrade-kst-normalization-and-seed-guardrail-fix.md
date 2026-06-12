# 단타 KST 로그 정규화 및 시드 가드레일 오탐 수정

- **ID**: 007
- **날짜**: 2026-04-17
- **유형**: 버그 수정

## 작업 요약
단타 운영 로그와 워커 마지막 실행 시각이 UTC 흔적을 그대로 보여주던 문제를 KST 정규화로 보정했다.
또한 단타 사용 시드 계산이 평가금액 기준으로 잡혀 수익 난 보유분까지 사용 시드로 간주되던 문제와, 주문 예산 상한이 실제 배정 시드보다 낮게 계산되어 오탐 차단되던 문제를 수정했다.

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct.py`
  - `worker_status()`에서 이전 UTC 형식 `last_run_at`을 KST로 정규화하도록 수정
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 런타임 로그/최근 오류의 UTC 흔적을 KST로 정규화
  - 오래된 `여유 시드 한도 초과` 메시지를 표시 대상에서 제거
  - 포트폴리오 사용 시드를 평가금액이 아닌 원가(`active_entry_seed_krw`) 기준으로 추가 집계
  - `shared_budget_status()`와 자동 후보 계산이 비용 기준 사용 시드를 쓰도록 수정
  - `_guardrails()`의 주문 금액 상한을 실제 배정 시드 기준으로 재정렬하고 과도한 초과 경고를 제거
  - 상태 저장 시 obsolete 최근 오류를 정리하도록 수정

### 프론트엔드
- `src/app/page.daytrade/view.ts`
  - 랭킹에서 워커 결과가 없을 때도 전략별 진입 조건을 직접 설명하도록 fallback 문구 개선

## 검증
- 변경 파일 diagnostics 확인: 오류 없음
- WIZ 일반 빌드 성공 (`clean: false`)
