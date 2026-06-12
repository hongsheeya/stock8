# 종목 검색 드롭다운 + 거래소 코드 동적 사용

- **ID**: 006
- **날짜**: 2026-04-08
- **유형**: 기능 추가

## 작업 요약
Settings 워치리스트에서 종목 추가 시 KIS API 기반 종목 검색 드롭다운을 추가하여 종목코드/종목명/거래소를 자동 감지·입력. 하드코딩된 "NASD" 거래소 코드를 제거하고, 워치리스트의 exchange 컬럼 값을 엔진 전체 체인(현재가 조회, 매수/매도 주문, LOC 매도 예약)에 동적 전달.

## 변경 파일 목록

### 백엔드
- `src/portal/trading/model/struct/engine.py`: `_get_exchange()`, `_price_exchange()` 헬퍼 추가, `EXCHANGE_MAP` 상수 추가. `run_daily()` 내 `get_current_price()`, `sell_order()`, `buy_order()` 호출에 exchange 파라미터 전달. `schedule_loc_sells()` 내 동일 처리.
- `src/app/page.settings/api.py`: `add_watchlist()`에서 exchange 파라미터 수신 및 유효성 확인. `search_symbol()` 엔드포인트 신규 추가 — NAS/NYS/AMS 3개 거래소에서 종목 검증.
- `src/app/page.dashboard/api.py`: `buy_preview()`에서 워치리스트의 exchange 값 조회 후 `get_current_price()` 호출 시 전달.

### 프론트엔드
- `src/app/page.settings/view.ts`: `newExchange`, `searchResults`, `searchLoading`, `showSearchResults` 상태 추가. `onSymbolInput()` debounce 검색, `searchSymbol()`, `selectSearchResult()`, `closeSearchResults()` 메서드 추가. `addSymbol()`에 exchange 전달.
- `src/app/page.settings/view.pug`: 종목 추가 폼 재설계 — 심볼 입력 필드에 검색 드롭다운 오버레이, 거래소 선택 `<select>` 추가, 워치리스트 목록에 거래소 배지 표시.

### i18n
- `src/portal/trading/libs/i18n.ts`: 6개 키 추가 (EN+KO) — set.exchange, set.no_search_result, set.search_hint
