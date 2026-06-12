# 자동매매 주기 최적화 및 UI 사용성 개선

- **ID**: 013
- **날짜**: 2026-04-14
- **유형**: 기능 추가 / UI 개선

## 작업 요약
자동매매(auto_cycle)의 실행 피드백을 강화하고, 실시간 데이터 반영 속도를 높이기 위해 폴링 주기를 단축했습니다. 또한 사용자 편의를 위한 수동 새로고침 버튼과 시드 변경 시의 자동 분석 연동을 추가하여 UX를 개선했습니다.

## 변경 파일 목록

### 프론트엔드 (Angular)
- [src/app/page.daytrade/view.ts](src/app/page.daytrade/view.ts)
  - `liveRefreshInterval`을 15,000ms에서 10,000ms로 단축.
  - `toggleAutoCycle` 메서드에서 활성화 시 즉시 1회 `runAutoCycle` 호출 로직 추가.
  - `updateSeed` 메서드에 시드 변경 성공 시 `runRecommend` 즉시 호출 및 안내 메시지 처리 추가.
- [src/app/page.daytrade/view.pug](src/app/page.daytrade/view.pug)
  - '실시간 시그널' 및 '오늘 일지' 섹션 헤더에 수동 새로고침 아이콘 버튼 (`lucide-rotate-cw`) 추가.
  - 시드 설정 영역에 시뮬레이션 기반 종목 선별 자동 업데이트 안내 문구 보완.

### 백엔드 (Python)
- [src/app/page.daytrade/api.py](src/app/page.daytrade/api.py)
  - `live_status` API 호출 시 KIS 실전 잔고(`position_qty`) 동기화 루틴 검증 및 예외 처리 강화.
  - `run_auto_cycle` 호출 시의 로그 기록 상세화.
