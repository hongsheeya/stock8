# 대시보드 페이지 리디자인 - 트레이딩 전용

- **ID**: 007
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
대시보드 페이지를 트레이딩 전용으로 전면 재구성했다. 글래스모피즘 다크 테마 카드 UI, 계좌 Summary, 엔진 제어 패널, 활성 사이클 진행률, 보유종목 테이블, 최근 거래 로그를 포함한다.

## 변경 파일 목록

### src/app/page.dashboard/view.ts (전면 교체)
- 트레이딩 데이터 상태 변수 (buyingPower, portfolioValue, cycles, holdings, recentLogs)
- `load()`: overview API 호출로 전체 대시보드 데이터 로드
- `toggleAutoTrade()`: 자동매매 토글
- `runEngineNow()`: 엔진 수동 실행
- `formatUSD()`, `cycleProgress()`, `profitClass()`, `statusBadge()` 유틸

### src/app/page.dashboard/view.pug (전면 교체)
- Summary 카드 4열 (Buying Power, Portfolio Value, Total Asset, System Status)
- Engine Control 패널 (Auto Trade 토글, Run Now, Refresh, 사이클 통계)
- Active Cycles 섹션 (진행률 바, avg/current price, invested/remaining)
- Holdings 테이블 (symbol, qty, avg, current, eval, P&L%)
- Recent Activity 로그

### src/app/page.dashboard/api.py (전면 교체)
- `overview()`: KIS API 연결 확인, 계좌 잔고, 환율, 엔진 상태, 활성 사이클, 보유종목, 최근 로그 통합 조회
- `toggle_auto_trade()`: trading_config 테이블 기반 자동매매 토글
- `run_engine()`: 전체 종목 엔진 수동 실행

### src/app/page.dashboard/view.scss (신규)
- `:host { display: block; height: 100%; }`
