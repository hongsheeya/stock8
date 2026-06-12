# 활성 사이클 파라미터 수정 기능

- **ID**: 015
- **날짜**: 2026-04-08
- **유형**: 기능 추가

## 작업 요약
ACTIVE/PAUSED/HOLDING/PENDING 상태의 사이클에서 목표수익률, 분할횟수, 투자금을 수정할 수 있는 편집 모달 구현. 유효성 검증 포함.

## 변경 파일 목록
- `src/portal/trading/model/struct/engine.py`: `update_cycle_params()` 메서드 추가
- `src/app/page.dashboard/api.py`: `update_cycle()` API 함수 추가
- `src/app/page.dashboard/view.ts`: 편집 모달 상태 + openEditModal/closeEditModal/saveEditCycle 메서드
- `src/app/page.dashboard/view.pug`: 편집 아이콘 버튼 + 편집 모달 UI
- `src/portal/trading/libs/i18n.ts`: cycle.edit_title/save/saved/min_division/min_investment 키 추가 (EN/KO)
