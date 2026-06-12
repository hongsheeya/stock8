# 사이클 선택 및 관리 기능

- **ID**: 014
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
워치리스트 종목별 사이클 모드(auto/confirm/manual) 설정과 대시보드에서 사이클 수동 시작/일시정지/재개/강제종료 기능을 구현했다. 엔진이 사이클 모드에 따라 자동 시작 여부를 판단하며, PAUSED 상태의 사이클은 거래가 중지된다.

## 변경 파일 목록

### DB 스키마
- `src/portal/trading/model/db/etf_watchlist.py`: `cycle_mode` 필드 추가 (CharField, default="auto")
- `src/portal/trading/model/db/trading_cycle.py`: `cycle_number` 필드 추가 (IntegerField, default=1)

### 엔진 로직
- `src/portal/trading/model/struct/engine.py`:
  - 상수 추가: `STATUS_PAUSED`, `CYCLE_MODE_AUTO`, `CYCLE_MODE_CONFIRM`, `CYCLE_MODE_MANUAL`
  - 신규 메서드: `_next_cycle_number()`, `force_close_cycle()`, `pause_cycle()`, `resume_cycle()`
  - 수정 메서드: `start_cycle()` (cycle_number 추적, PAUSED 체크), `run_all()` (cycle_mode 필터링), `get_active_cycles()` (PAUSED 포함), `get_status()` (paused_cycles 카운트)

### Settings 페이지
- `src/app/page.settings/api.py`: `add_watchlist()` cycle_mode 기본값, `update_watchlist()` cycle_mode 저장
- `src/app/page.settings/view.ts`: `updateCycleMode()`, `cycleModeLabel()`, `cycleModeClass()` 메서드
- `src/app/page.settings/view.pug`: 워치리스트 항목별 cycle_mode 드롭다운 + 모드 설명 범례

### Dashboard 페이지
- `src/app/page.dashboard/api.py`: `start_cycle()`, `force_close_cycle()`, `pause_cycle()`, `resume_cycle()` API 함수
- `src/app/page.dashboard/view.ts`: 사이클 관리 메서드, `watchlistInfo`, `watchlistWithoutCycle` getter, `getCycleMode()`, `hasActiveCycle()`
- `src/app/page.dashboard/view.pug`: Engine Control에 Start New Cycle 섹션, 사이클 카드에 Pause/Resume/Force Close 버튼, PAUSED 상태 표시, 4열 상태 요약(Active/Holding/Paused/Done)
