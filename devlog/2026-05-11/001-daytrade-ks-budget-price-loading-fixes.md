# 국장 단타 총자산/현재가 표시 보정 및 미장 자동환전 예산 반영, 초기 로딩 분석

- **ID**: 001
- **날짜**: 2026-05-11
- **유형**: 버그 수정

## 작업 요약
국장 단타 페이지에서 진행 중 종목의 현재가가 평단가로 고정되어 보이던 문제와 매매계획 총자산이 0으로 보이던 문제를 수정했다.
동시에 미장 주문가능금액 계산에 원화 자동환전 가능액을 반영하도록 보강했고, 국장 단타 첫 진입 시 로딩이 오래 걸리던 원인을 실제 API 응답시간 기준으로 분석한 뒤 초기 렌더를 막지 않도록 개선했다.

## 원문 요청사항
```text
1. 아직도 주문 가능금액을 초괴 했다고 뜨잖아. 잔고 있는데 왜 그러는거야. 원화 잔고에서 자동으로 환전해서 구매하라고
2. 국장 단타 진행중인 종목에서 현재가가 평단가로 고정되어 표시되고 있는 오류 해결
3. 국장 단타 매매계획 총 자산 표시가 안됨
4. 국장 단타 처음 접속할떄 로딩 시간 너무 오래 걸리는데 어디에 오래걸리는지 제대로 분석해서 알려줘
```

## 변경 파일 목록

### `src/portal/trading/model/struct/kis_api.py`
- 해외 주문가능금액 조회 `get_buying_power_info()`에 원화 자동환전 가능액(`withdrawable_krw / usd_krw`)을 합산
- USD 현금(`cash_balance`)과 원화 자동환전 가능액을 함께 사용해 `combined_amount`와 보수적 `qty`를 계산
- 실제 해외 매수 주문 직전 payload 로그는 기존 유지

### `src/portal/trading/model/struct/daytrade_engine.py`
- US 시장 예산 계산 시 `tradable_cash_krw = us_orderable_amount_krw + us_krw_auto_exchange_krw`로 변경
- `active_positions_from_state()`에서 `current_price`를 `avg_price`가 아니라 `last_price` 우선으로 사용하도록 수정
- `pnl`, `pnl_pct`도 함께 계산해 초기 화면 카드가 실제 값에 가깝게 보이도록 변경

### `src/app/page.daytrade/api.py`
- `budget_status`가 `cache_miss`로 0이 내려올 때 워커의 마지막 예산 결과(`worker_status.last_result.budget`)로 보강하는 `_merge_budget_with_worker_cache()` 추가
- `bootstrap()`, `live_status()` 모두 이 fallback budget을 적용해 총자산/시드 값이 초기 화면에서도 보이게 수정

### `src/app/page.daytrade/view.ts`
- `bootstrap()`에서 `loadLiveStatus(false)`를 직접 await하지 않고 다음 tick으로 지연 실행하도록 변경
- 초기 전체 화면 로딩 spinner가 `bootstrap` 응답까지만 기다리고, 무거운 `live_status`는 화면 표시 후 비동기 갱신되도록 개선
- `applyBudgetStatus()`에서 `total_asset_krw`가 비어 있으면 `fallback_total_asset_krw`, `summary_total_asset_krw`를 fallback으로 사용

## 분석 메모
- 실측 결과:
  - `bootstrap`: 약 2.8초
  - `live_status(force_refresh=false)`: 약 11.8초
- 병목의 주범은 `live_status()` 내부의 `engine.signal_status()`이고, 그 안에서 `daytrade_engine._latest_snapshot()`가 캐시 미스 시 `strategy._prepare_dataset(symbol, market=market, period="1d", interval="1m")`를 호출해 1분봉 세션 데이터를 다시 준비하는 경로였다.
- 기존 프론트는 `bootstrap()` 안에서 이 느린 `live_status()`를 `await`하고 있었기 때문에 첫 진입 spinner가 두 API 전체 시간을 모두 기다렸다.
- 이번 수정으로 체감 초기 렌더는 `bootstrap` 완료 시점으로 앞당기고, 실시간 상태는 뒤에서 채우도록 바꿨다.
