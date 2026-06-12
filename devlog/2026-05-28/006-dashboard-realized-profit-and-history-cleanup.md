# 대시보드 실현수익 정합 및 거래이력 정리

- **ID**: 006
- **날짜**: 2026-05-28
- **유형**: 버그 수정

## 작업 요약
대시보드 수익 요약에서 ALL 기간 실현수익이 실계좌 총자산 기반 보정으로 다시 덮어써지던 경로를 제거해, 무한매수/단타 집계 합계가 그대로 유지되도록 정리했다.
거래이력 화면에서는 혼동만 주던 스냅샷 탭을 제거하고, 단타 거래 탭에 예약/0주 로그가 체결 이력처럼 섞이지 않도록 실제 체결만 남기도록 필터링했다.

## 원문 요청사항
```text
실현수익 왜 저래
거래이력 스냅샷은 왜 필요하고 값이 왜 저래. 필요없으면 삭제해
거래 이력 단타거래에 왜 무한매수 예약한게 있어? 분리해
```

## 변경 파일 목록
### 대시보드 수익 집계
- `src/app/page.dashboard/api.py`
  - 실현/미실현/총손익 합산 helper를 추가했다.
  - ALL 기간에서 실계좌 총자산으로 실현수익을 재계산하던 덮어쓰기 로직을 제거했다.
  - 브로커 미실현 fallback은 유지하되 실현수익 breakdown 정합이 깨지지 않도록 정리했다.

### 거래이력 정리
- `src/app/page.history/api.py`
  - 단타 거래이력에서 예약 매도(`PRE_*`, `*RESERVED*`)와 0주/0금액 로그를 제외하는 helper를 추가했다.
  - daytrade 로그, 브로커 동기화 레코드, live state 복원 레코드 모두 동일 필터를 적용했다.
- `src/app/page.history/view.ts`
  - 스냅샷 탭 상태/로딩 코드를 제거했다.
- `src/app/page.history/view.pug`
  - 거래이력 스냅샷 탭과 테이블 UI를 제거했다.

### 테스트
- `tests/test_dashboard_accounting_regressions.py`
  - 실현/미실현 합산 helper 회귀 테스트를 추가했다.
  - 예약 매도/0주 로그 제외 및 실제 체결 유지 테스트를 추가했다.

## 검증
- `python -m unittest tests.test_dashboard_accounting_regressions.DashboardAccountingRegressionTests.test_profit_component_totals_preserve_realized_breakdown tests.test_dashboard_accounting_regressions.DashboardAccountingRegressionTests.test_daytrade_history_excludes_pre_sell_reservations tests.test_dashboard_accounting_regressions.DashboardAccountingRegressionTests.test_daytrade_history_excludes_zero_fill_rows tests.test_dashboard_accounting_regressions.DashboardAccountingRegressionTests.test_daytrade_history_keeps_real_fills`
- `wiz project build --project=main`
- 최근 `trade_log` 실데이터 점검으로 예약 매도(`DT_KS_PRE_SELL_JACKPOT`) 및 0주 `BUY1` 로그가 새 단타 이력 필터에서 제외됨을 확인했다.
