# 설정 페이지 saveParams 런타임 오류 수정

- **ID**: 004
- **날짜**: 2026-04-09
- **유형**: 버그 수정

## 작업 요약
설정 페이지의 `saveParams()`가 존재하지 않는 `service.alert.show()`를 호출해 런타임 `TypeError`를 발생시키던 문제를 수정했다. Season 공통 서비스에서 실제 제공하는 `service.modal.show()`로 변경했고, 참조 전수 검색 후 동일 패턴이 더 없는 것도 확인했다.

## 변경 파일 목록
- `src/app/page.settings/view.ts`: `service.alert.show()` → `service.modal.show()` 변경
- 검증: 타입 오류 없음, 전체 검색상 잔여 `service.alert` 호출 없음, 일반 빌드 성공