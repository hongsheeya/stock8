# PAUSED 사이클 삭제 기능 구현

- **ID**: 009
- **날짜**: 2026-04-08
- **유형**: 기능 추가

## 작업 요약
PAUSED 상태의 사이클을 DB에서 완전 삭제하는 기능 구현. 관련 거래/로그 레코드도 함께 삭제.

## 변경 파일 목록
- `src/portal/trading/model/struct/engine.py`: `delete_cycle()` 메서드 추가
- `src/app/page.dashboard/api.py`: `delete_cycle()` API 함수 추가
- `src/app/page.dashboard/view.ts`: `deleteCycle()` 메서드 + 확인 다이얼로그
- `src/app/page.dashboard/view.pug`: PAUSED 사이클에 휴지통 삭제 버튼 추가
- `src/portal/trading/libs/i18n.ts`: cycle.delete_title/btn/confirm/deleted 키 추가 (EN/KO)
