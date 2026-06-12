# 매매 프리뷰 통합 (매수 + 매도 동시 표시)

- **ID**: 010
- **날짜**: 2026-04-08
- **유형**: 기능 개선

## 작업 요약
"오늘 매수 예정" → "오늘 매매 예정"으로 변경. buy_preview() → trade_preview()로 리네이밍. 각 사이클에 대해 calculate_sell_decision()도 호출하여 매도 예정 정보 포함. UI에 매수/매도 배지 및 상세 그리드 표시.

## 변경 파일 목록
- `src/app/page.dashboard/api.py`: buy_preview → trade_preview 리네이밍, 매도 프리뷰 추가
- `src/app/page.dashboard/view.ts`: buyPreview → tradePreview 리네이밍, tradePreviewSellClass 추가
- `src/app/page.dashboard/view.pug`: 매도 프리뷰 카드 UI 추가 (현재가/수량/유형/수익률 그리드)
- `src/portal/trading/libs/i18n.ts`: dash.trade_preview, sell_current/qty/type/profit/full/partial 키 추가 (EN/KO)
