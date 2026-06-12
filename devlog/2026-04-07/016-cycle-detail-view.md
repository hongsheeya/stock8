# 사이클 상세 뷰 (클릭 시 현황·거래내역·로그 표시)

- **ID**: 016
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
대시보드에서 사이클 카드를 클릭하면 오른쪽에서 슬라이드 인되는 상세 패널 구현. Summary/Trades/Event Logs 3탭 구성. Mock 데이터 지원으로 Demo Mode에서도 완전히 동작.

## 변경 파일 목록

### 대시보드 API
- `src/app/page.dashboard/api.py`
  - `cycle_detail(cycle_id)` 함수 추가: 사이클 기본 정보 + 거래 내역(cycle_trade) + 이벤트 로그(trade_log) + 차트 데이터 반환
  - `_generate_mock_cycle_detail()` 함수 추가: Mock 사이클 상세 데이터 (trades, chart_data, logs)
  - `_generate_mock_data()`: started_at 필드 추가

### 대시보드 TypeScript
- `src/app/page.dashboard/view.ts`
  - Cycle Detail 상태: `showCycleDetail`, `detailLoading`, `detailTab`, `detailCycle`, `detailTrades`, `detailChartData`, `detailLogs`, `detailTradeFilter`
  - 메서드: `openCycleDetail()`, `closeCycleDetail()`, `setDetailTab()`, `setDetailTradeFilter()`, `filteredDetailTrades` getter
  - 헬퍼: `detailActionClass()`, `detailLogTypeClass()`, `chartBarHeight()`
  - 기존 버튼 핸들러에 `event?.stopPropagation()` 추가 (클릭 버블링 방지)

### 대시보드 Pug
- `src/app/page.dashboard/view.pug`
  - 사이클 상세 슬라이드 패널 (fixed overlay, max-w-2xl, glass-card)
  - Summary 탭: 6개 메트릭 그리드, Investment 상세, Price/Profit 바 차트
  - Trades 탭: 액션 필터 (ALL/BUY/SELL/SKIP/EXTEND), 거래 카드 리스트
  - Event Logs 탭: 이벤트 타입별 색상 배지 + 메시지
  - 사이클 카드에 `cursor-pointer` + `(click)="openCycleDetail(cycle)"` 추가
