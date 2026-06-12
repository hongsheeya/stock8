# 레이아웃 리디자인 - 글래스모피즘 Trading UI

- **ID**: 006
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
글래스모피즘 디자인 기반의 트레이딩 전용 레이아웃(`layout.trading`)과 상단 네비게이션 컴포넌트(`component.nav.trading`)를 생성했다. 다크 테마 + 반투명 패널 + glow 효과 + 가격 애니메이션 CSS를 포함한다.

## 변경 파일 목록

### src/app/layout.trading/ (신규 생성)
- `view.ts`: Service 주입 + init
- `view.pug`: trading-bg 배경 + nav 컴포넌트 + router-outlet + 로딩 오버레이
- `view.scss`: :host flex 레이아웃, 글래스모피즘 카드(.glass-card), 가격 flash 애니메이션, 다크 스크롤바, glow 효과, status dot
- `app.json`: layout 모드, controller: base

### src/app/component.nav.trading/ (신규 생성)
- `view.ts`: 실시간 시계, US Market 상태(NYSE 시간 기반), navClass 활성 링크 스타일
- `view.pug`: 반투명 nav 바 — 브랜드(BESTock), 메뉴(Dashboard/Settings/History/Simulation), 마켓 상태, 시계, 사용자/로그아웃
- `app.json`: component 모드, controller: base

### src/app/page.dashboard/app.json (수정)
- `layout`: `layout.sidebar` → `layout.trading` 변경
