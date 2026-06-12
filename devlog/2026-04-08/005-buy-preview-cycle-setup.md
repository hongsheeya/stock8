# 매수 프리뷰 + 사이클 시작 설정 기능

- **ID**: 005
- **날짜**: 2026-04-08
- **유형**: 기능 추가

## 작업 요약
대시보드에 "오늘 매수 예정" 프리뷰 패널을 추가하여 활성 사이클별 매수 판단(금액, LOC 가격, 수량, 사유)을 미리 확인할 수 있게 함. 새 사이클 시작 시 투자금·분할횟수·목표수익률을 사용자가 직접 설정할 수 있는 확인 모달 추가.

## 변경 파일 목록

### 백엔드
- `src/portal/trading/model/struct/engine.py`: `start_cycle()` 메서드에 `total_investment`, `division_count`, `target_profit` 선택적 파라미터 추가
- `src/app/page.dashboard/api.py`: `start_cycle()` 사용자 지정 파라미터 전달, `buy_preview()` 엔드포인트 신규, `get_watchlist_defaults()` 엔드포인트 신규

### 프론트엔드
- `src/app/page.dashboard/view.ts`: 매수 프리뷰 상태(buyPreviews, showBuyPreview 등), 사이클 시작 모달 상태(showStartModal, startModal* 등), `openStartModal()`, `confirmStartCycle()`, `loadBuyPreview()`, `toggleBuyPreview()`, `buyPreviewOrderClass()` 메서드 추가. `startCycle()` 및 `startSelectedCycle()` 모달 방식으로 변경.
- `src/app/page.dashboard/view.pug`: "Start Cycle Confirmation Modal" UI 추가(투자금/분할횟수/목표수익률 편집 가능), "Today's Buy Preview" 섹션 추가(접기/펼치기, 종목별 매수 판단 카드)

### i18n
- `src/portal/trading/libs/i18n.ts`: 19개 키 추가 (EN+KO) — engine.start_modal_title/desc, engine.investment/division_count/target_profit/per_round_amount/total_rounds/start_confirm/start_cancel, dash.buy_preview/preview_show/preview_hide/preview_no_api/no_preview/preview_price/preview_qty/preview_amount
