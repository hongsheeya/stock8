# 대시보드 KIS 필드 매핑 오류 수정 및 실계좌 정합 복구

- **ID**: 016
- **날짜**: 2026-04-29
- **유형**: 버그 수정

## 작업 요약
대시보드 수치 불일치의 근본 원인을 KIS 응답 필드 오해석에서 확인하고, 잔고/평가/총자산 계산식을 실계좌 기준으로 정정했다. 특히 `평가손익`을 `평가금액`으로 쓰던 문제와 `총자산`을 `원화 현금`으로 오인하던 문제를 제거했다.

## 변경 파일 목록
- `src/portal/trading/model/struct/kis_api.py`
  - `get_balance()`에서 `tot_evlu_pfls_amt`, `frcr_pchs_amt1` 오사용 제거
  - 평가금액/현금 후보 키를 `_pick_amount_info` 기반으로 보수적으로 재선정
  - 숫자 파싱을 `_safe_*`로 통일하고 평가금액은 보유종목 합산 fallback 추가
  - `get_present_balance()`에서 현금 후보에서 `tot_asst_amt`, `tot_evlu_amt` 제외
  - `total_asset_krw` 및 `meta.total_asset_key`를 별도 반환

- `src/app/page.dashboard/api.py`
  - `overview()`에서 매수 가능액을 KIS 주문가능액(`get_buying_power_info`) 기준으로 단일화
  - 원화 환산 가능액은 참고값으로 분리 노출하고 매수가능액 본값에서 이중합산 제거
  - 총자산은 가능 시 `present.total_asset_krw / usd_krw` 우선 사용
  - `profit_summary()`의 `ALL` 기간은 실계좌 기준 실시간 수익(실현/미실현/총손익)으로 재계산
