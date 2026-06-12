# 단타 잔고 캐시 무효화 및 D+1 총자산 검증

- **ID**: 003
- **날짜**: 2026-04-15
- **유형**: 버그 수정

## 작업 요약
`page.daytrade/debug_balance`가 이전 KIS 잔고 sys 캐시를 재사용하면서, 방금 추가한 D+1 예수금·총자산 계산 결과가 즉시 반영되지 않는 문제를 추적했다.
디버그 API 진입 시 캐시를 먼저 무효화하도록 보정한 뒤, 실제 응답에서 `d1_deposit_krw=511977`, `summary_total_asset_krw=511977`, `total_asset_krw=706597`로 갱신되는 것을 확인했다.

## 변경 파일 목록
### API
- `src/app/page.daytrade/api.py`
  - `debug_balance()` 실행 직전에 `engine._invalidate_kis_cache()`를 호출하도록 추가

### 검증
- 내부 디버그 API 재호출로 아래 값을 확인
  - `fresh_budget.d1_deposit_krw = 511977.0`
  - `fresh_budget.summary_total_asset_krw = 511977.0`
  - `fresh_budget.total_asset_krw = 706597.0`
  - `domestic_balance.raw_output2[0].nxdy_excc_amt = 511977`
