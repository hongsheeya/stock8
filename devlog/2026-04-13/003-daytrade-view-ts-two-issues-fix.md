# daytrade view.ts 문제 2건 복구

- **ID**: 003
- **날짜**: 2026-04-13
- **유형**: 버그 수정

## 작업 요약
`page.daytrade/view.ts` 에서 다시 보이던 TypeScript 문제 2건을 파일 상단 선언 참조 방식으로 복구했다. 이제 파일 단독 검사에서도 `@angular/core`, `@wiz/libs/portal/season/service` 모듈 선언을 정상 인식한다.

## 변경 파일 목록
- `src/app/page.daytrade/view.ts`
  - `../../types/wiz-modules.d.ts` 참조 추가
  - 이후 페이지 파일 검사 시 모듈 선언 누락 오류가 재발하지 않도록 정리

## 검증
- 파일 단위 오류 검사에서 `view.ts` 문제 2건이 모두 사라진 것 확인
