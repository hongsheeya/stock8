# 네비게이션 테마 버튼 이동 및 전체 트레이딩 페이지 화이트 모드 전역화

- **ID**: 010
- **날짜**: 2026-05-28
- **유형**: 기능 추가

## 작업 요약
테마 토글 버튼을 대시보드 헤더에서 제거하고 상단 네비게이션의 언어 선택 버튼 옆으로 이동했다.
대시보드 한정이던 화이트 모드를 `layout.trading` 루트 기준 전역 테마로 확장해, 같은 레이아웃을 쓰는 전체 페이지에 동일하게 적용되도록 변경했다.

## 원문 요청사항
```text
화이트 모드 버튼을 언어 선택 옆에다가 두고 지금은 대시보드만 화이트 모드인데 전체 페이지기 디 화이트 모드 적용해야해
```

## 변경 파일 목록
- 네비게이션
  - `src/app/component.nav.trading/view.ts`
    - 전역 테마 상태/토글 및 이벤트 브로드캐스트 추가
  - `src/app/component.nav.trading/view.pug`
    - 언어 버튼 옆에 화이트/다크 토글 버튼 배치
- 레이아웃 전역 테마
  - `src/app/layout.trading/view.ts`
    - 로컬 스토리지 테마 로드 및 `dashboard-theme-changed` 이벤트 수신 처리 추가
  - `src/app/layout.trading/view.pug`
    - 레이아웃 루트에 `theme-light` 클래스 바인딩 추가
  - `src/app/layout.trading/view.scss`
    - 전역 테마 변수 다크/화이트 정의 및 공통 카드/스크롤 스타일 변수화
- 대시보드 정리
  - `src/app/page.dashboard/view.ts`
    - 대시보드 전용 테마 상태/토글 코드 제거
  - `src/app/page.dashboard/view.pug`
    - 대시보드 헤더 테마 버튼 제거
  - `src/app/page.dashboard/view.scss`
    - 대시보드 전용 테마 클래스 의존을 전역 `theme-light` 컨텍스트로 전환
