# 페이지 하단 여백 제거 + 배경색 통일

- **ID**: 014
- **날짜**: 2026-04-08
- **유형**: CSS

## 작업 요약
레이아웃의 router-outlet 컨텐츠 래퍼에 min-h-full 추가하여 짧은 페이지에서도 배경이 채워지도록 수정. history 페이지의 이중 padding/높이 설정 제거.

## 변경 파일 목록
- `src/app/layout.trading/view.pug`: max-w-7xl wrapper에 min-h-full 추가
- `src/app/page.history/view.pug`: h-full, p-4, trading-scroll, overflow-auto 제거 (레이아웃이 관리)
