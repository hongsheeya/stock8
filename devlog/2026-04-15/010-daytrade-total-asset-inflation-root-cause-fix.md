# 단타 총자산 뻥튀기 근본 원인 수정

- **ID**: 010
- **날짜**: 2026-04-15
- **유형**: 버그 수정

## 작업 요약
단타 총자산이 `예수금 + 평가금액` 식으로 다시 합산되어 실제보다 크게 보이던 원인을 추적해 수정했다. 원인은 두 가지였다. 첫째, 국내 잔고 raw summary에 이미 총자산(`tot_evlu_amt`, `nass_amt`)이 있는데도 fallback 계산에서 `deposit_krw + domestic_eval_krw`를 다시 더해 이중 합산했다. 둘째, D+1 예수금으로 써야 할 `nxdy_excc_amt`보다 `prvs_rcdl_excc_amt`를 먼저 집어 잘못된 현금 값을 사용했다.

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 국내 평가금액을 holdings 재계산보다 raw summary의 `scts_evlu_amt`/`evlu_amt_smtl_amt` 우선 사용으로 수정
  - D+1 예수금 우선순위를 `nxdy_excc_amt` → `prvs_rcdl_excc_amt`로 교정
  - 총자산 계산을 `summary_total_asset_krw` 우선 사용으로 수정
  - fallback 총자산은 `withdrawable + 평가금액` 기반으로만 계산하고 `deposit + 평가금액` 이중합산 제거
  - `fallback_total_asset_krw` 디버그 필드 추가

## 검증
- 빌드 성공 확인
- `debug_balance` 재검증 결과
  - `summary_total_asset_krw = 1012567`
  - `fallback_total_asset_krw = 1012567`
  - `total_asset_krw = 1012567`
  - raw summary `tot_evlu_amt = 1012567`, `scts_evlu_amt = 990700`, `nxdy_excc_amt = 1011977`
- 기존처럼 `deposit_krw + domestic_eval_krw`로 168만 원대로 뻥튀기되지 않음을 확인
