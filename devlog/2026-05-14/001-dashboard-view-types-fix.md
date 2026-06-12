# 대시보드 view.ts 타입 선언 보강으로 2개 오류 해결

- **ID**: 001
- **날짜**: 2026-05-14
- **유형**: 버그 수정

## 작업 요약
`page.dashboard/view.ts`에서 보고되던 `Input` 미내보내기와 `@wiz/libs/portal/trading/i18n` 모듈 미인식 오류를 추적했다.
직접 소스 로직을 건드리지 않고 공용 타입 선언 파일에 누락된 Angular 데코레이터와 `i18n` 모듈 선언을 보강해 진단 오류 2개를 모두 제거했다.

## 원문 요청사항
```text
view.ts 오류 2개 완전히 고쳐줘
```

## 변경 파일 목록
### 타입 선언
- `src/types/wiz-modules.d.ts`
  - `@angular/core` 모듈 선언에 `Input()`, `HostListener()` 타입을 추가
  - `@wiz/libs/portal/trading/i18n` 모듈 선언을 추가해 `i18n.t()` 등 사용 타입을 보강

### 검증
- `src/app/page.dashboard/view.ts`
  - 오류 2개가 모두 사라진 것을 확인
