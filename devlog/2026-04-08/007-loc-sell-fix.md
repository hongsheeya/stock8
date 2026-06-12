# LOC 매도 예약 에러 수정 + LOC 버튼 역할 정리

- **ID**: 007
- **날짜**: 2026-04-08
- **유형**: 버그 수정

## 작업 요약
engine.py의 `schedule_loc_sells()`와 `run_daily()`에서 `self._get_config()` 호출을 `self._get_config_value()`로 수정 (AttributeError 해결). LOC 매도 예약 버튼에 역할 설명 툴팁 추가.

## 변경 파일 목록
- `src/portal/trading/model/struct/engine.py`: `_get_config()` → `_get_config_value()` 2개소 수정
- `src/app/page.dashboard/view.pug`: LOC 버튼에 `[title]` 속성 추가
- `src/portal/trading/libs/i18n.ts`: `dash.loc_tooltip` 키 추가 (EN/KO)
