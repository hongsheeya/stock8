# 헤더 드롭다운 메뉴 스타일링 및 반응형 테스트

- **ID**: 011
- **날짜**: 2026-04-29
- **유형**: 기능 추가

## 작업 요약
헤더 네비게이션(`component.nav.trading`)의 사용자 드롭다운에 활성/비활성 스타일을 명확히 추가하고, 모바일/태블릿/데스크톱에서 레이아웃이 깨지지 않도록 반응형 구조를 보강했다. 
드롭다운 외부 클릭 닫힘 동작을 유지한 상태에서 내부 클릭 충돌 없이 동작하도록 이벤트 처리와 UI 상태 클래스를 정리했다.

## 변경 파일 목록

### Header Component
- `src/app/component.nav.trading/view.ts`
  - 네비 링크에 `shrink-0` 적용(`navClass`)으로 모바일 가로 스크롤 시 버튼 압축/깨짐 방지
  - 드롭다운 상태 기반 스타일 메서드 추가
    - `settingsButtonClass()`
    - `avatarButtonClass()`

- `src/app/component.nav.trading/view.pug`
  - 헤더 루트를 `flex-col -> lg:flex-row` 반응형 구조로 변경
  - 네비 링크 영역을 `overflow-x-auto` + `w-max`로 변경해 모바일에서 수평 스크롤 가능하도록 고정
  - 우측 상태 영역 정렬을 `justify-between -> lg:justify-end`로 분기
  - 시계/장상태 영역을 `hidden sm:flex` 처리해 초소형 화면 겹침 방지
  - 설정/아바타 버튼을 상태 기반 클래스 바인딩으로 변경

## 검증
- `wiz_project_build(clean=false)` 빌드 성공
- `component.nav.trading` 대상 에러 검사 결과 0건
