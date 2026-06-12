# 단타 전용 페이지/시뮬레이션 UI 구현

- **ID**: 005
- **날짜**: 2026-04-10
- **유형**: 기능 추가

## 작업 요약
기존 무한매수 시뮬레이션과 분리된 `/daytrade` 전용 페이지를 구현했다. 단타 알고리즘 문서, 백테스트 실행, 학습 실행, 라이브 청사진 확인 기능을 한 페이지에 통합했다.

## 변경 파일 목록
- `src/app/page.daytrade/app.json` — 단타 전용 페이지 등록
- `src/app/page.daytrade/view.ts` — 페이지 상태/이벤트 로직 구현
- `src/app/page.daytrade/view.pug` — 단타 연구 UI 구현
- `src/app/page.daytrade/view.scss` — 호스트 스타일 추가
- `src/app/component.nav.trading/view.pug` — 네비게이션에 단타 연구실 링크 추가
- `src/portal/trading/libs/i18n.ts` — 단타 페이지 i18n 키 추가
