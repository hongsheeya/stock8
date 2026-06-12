# 40회 초과 시 추가 매수 확인 기능

- **ID**: 015
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
분할 횟수(기본 40회) 소진 시 즉시 홀딩 전환 대신 `PENDING_EXTENSION` 상태로 전환하여 사용자에게 추가 매수 여부를 확인받는 기능 구현. 대시보드에서 "추가 매수 진행"(10/20/40회 선택 + 추가 투자금 입력) 또는 "홀딩 유지" 선택 가능. 시뮬레이션에서도 `allow_extension` 옵션으로 자동 연장 지원.

## 변경 파일 목록

### 엔진 (Backend)
- `src/portal/trading/model/struct/engine.py`
  - `STATUS_PENDING_EXTENSION` 상수 추가
  - `execute_buy()`: division_count 도달 시 PENDING_EXTENSION 전환
  - `record_skip()`: 동일 전환 로직
  - `run_daily()`: PENDING_EXTENSION 사이클 매도 체크만 수행
  - `extend_cycle(cycle_id, extra_rounds, extra_investment)`: 분할 확장 + ACTIVE 전환
  - `keep_holding(cycle_id)`: PENDING_EXTENSION → HOLDING 전환
  - `pause_cycle()`, `resume_cycle()`: PENDING_EXTENSION 상태 지원
  - `get_active_cycles()`, `get_status()`, `run_all()`: PENDING_EXTENSION 포함

### 대시보드
- `src/app/page.dashboard/api.py`: `extend_cycle()`, `keep_holding()` 함수 추가, mock 데이터에 PENDING_EXTENSION 상태 반영
- `src/app/page.dashboard/view.ts`: Extension 모달 상태/메서드, PENDING_EXTENSION 배지 스타일
- `src/app/page.dashboard/view.pug`: Extension 모달 UI (10/20/40회 선택, 추가 투자금), PENDING_EXTENSION 카드 액션 버튼, 5-col 상태 요약 그리드

### 시뮬레이션
- `src/app/page.simulation/api.py`: `allow_extension` 파라미터, 자동 연장 로직 (EXTEND 액션), `extension_count` 추적
- `src/app/page.simulation/view.ts`: `allowExtension` 필드 및 API 전달
- `src/app/page.simulation/view.pug`: Auto-Extend 토글 UI, EXTEND 필터 버튼, 연장 정보 카드, Cycle 테이블에 Div 컬럼
