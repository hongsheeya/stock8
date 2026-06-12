# 단타 총자산 이중합산 제거 및 요청 시드 우선 적용

- **ID**: 004
- **날짜**: 2026-04-15
- **유형**: 버그 수정

## 작업 요약
단타 총자산 계산에서 예수금과 D+1 정산금을 동시에 더해 총자산이 실제보다 크게 보이던 문제를 수정했다. 또한 실주문/추천/자동매매가 항상 `live_order_seed`를 우선 사용하던 흐름을 정리하여, 사용자가 입력한 요청 시드가 있으면 `effective_daytrade_seed`를 우선 적용하도록 맞췄다.

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `total_asset_krw` 계산에서 예수금 + D+1 중복 합산 제거
  - `cash_max_krw`와 `available_for_daytrade`를 실제 정산 가능 현금 기준으로 보정
  - 자동 후보 계산에서 `effective_daytrade_seed` 우선 사용
- `src/app/page.daytrade/api.py`
  - bootstrap/chart/live 관련 시드 계산을 `effective_daytrade_seed` 우선으로 통일

### 프론트엔드
- `src/app/page.daytrade/view.pug`
  - 실주문 적용 시드 표기를 `effective_daytrade_seed` 우선으로 수정
  - 자동매매 안내 문구를 요청 시드 우선 적용 기준으로 수정

## 검증
- 빌드 성공 확인
- `debug_balance` 재검증 결과
  - `cash_max_krw = 511977`
  - `total_asset_krw = 511977`
  - `effective_daytrade_seed = 511977`
  - `domestic_balance.raw_output2[0].tot_evlu_amt = 511977`
