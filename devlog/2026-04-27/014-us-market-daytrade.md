# 미장(US) 단타 기능 개발 및 프리마켓 갭업 전략 구현

- **ID**: 014
- **날짜**: 2026-04-27
- **유형**: 기능 추가

## 작업 요약

미장(US) 단타 기능을 기존 국장 단타(`page.daytrade`) 에 통합 탭 형태로 추가했다.  
KIS 해외주식 API(`buy_order`, `sell_order`)를 활용하고, ET 장 시간 처리 및 DST 자동 반영을 구현했다.  
DC Inside 해주갤 참고 전략 기반의 `us_premarket` 전략(프리마켓 갭업 후 되밀림 진입)을 신설했다.

## 변경 파일 목록

### Model/Struct
- `src/portal/trading/model/struct/daytrade.py`
  - `STRATEGIES`에 `us_premarket` 전략 등록 (market="US", live_supported=True)
  - `US_DEFAULT_CANDIDATES` (TQQQ, SOXL, NVDA, TSLA 등 20개 종목)
  - `US_DEFAULT_PROFILE` (commission_bps=25.0, stop_loss_pct=8.0, premarket_gap_min_pct=5.0 등)
  - `us_candidate_universe()`, `us_strategy_options()`, `us_profile()` 메서드 추가
  - `search_symbols(query, limit, market="")` — market="US" 분기

- `src/portal/trading/model/struct/daytrade_engine.py`
  - 헬퍼: `_is_us_market()`, `_round_usd_price()`, `_us_exchange()`, `_is_us_dst()`, `_us_market_open()`, `_us_premarket_open()` 추가
  - `_daytrade_market_open(market)` — US 분기 처리
  - `_latest_snapshot()` — US 종목 KIS 해외 시세 조회 (`kis_overseas_quote`)
  - `_guardrails()` — `kis_overseas_quote` 허용
  - `_signal_from_state()` — `us_premarket` 전략 신호 로직 추가 (갭업 %, 되밀림 %, 거래대금 조건)
  - `execute_live()` — US 주문 라우팅 (`buy_order`/`sell_order`) + USD 수수료 계산 (매수/매도 0.25% + SEC fee)
  - `_profile_for(symbol, strategy_id, market)` — US 프로파일 기본값 분기

### API
- `src/app/page.daytrade/api.py`
  - `us_candidate_universe()`, `us_search_symbols()`, `us_bootstrap()`, `us_live_status()`, `us_execute_live()` 추가 (5개 함수)

### Frontend
- `src/app/page.daytrade/view.ts`
  - US 프로퍼티 추가 (marketMode, usSymbol, usStatus, usProfile 등 20개)
  - US 메서드 추가: `switchMarketMode()`, `usBootstrap()`, `usLoadLiveStatus()`, `usSelectSymbol()`, `usSearchSymbols()`, `usExecuteLive()`, `formatUsd()`, Getters (usSignalAction, usSignalReason, usCurrentPrice, usPositionQty, usAvgPrice)

- `src/app/page.daytrade/view.pug`
  - 상단 국장/미장 탭 스위처 추가
  - 기존 KS 섹션에 `*ngIf="marketMode === 'KS'"` 조건 적용
  - US 전용 섹션 추가: 심볼 검색 드롭다운, 실시간 신호 카드, 후보 종목 그리드, 전략 안내
