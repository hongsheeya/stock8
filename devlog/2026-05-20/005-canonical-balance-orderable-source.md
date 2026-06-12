# 총자산 / 매수 가능액 기준 분리

## 배경
- 국내 주문가능조회(`inquire-psbl-order`) 응답에서 주문 가능 현금, 미수 없는 매수 가능액, 출금 가능액, 참고용 최대 금액을 한 배열에 넣고 가장 큰 값을 `amount`로 사용하고 있었다.
- 이 때문에 대시보드와 예산 계산은 매수 가능액이 크게 보이지만, 실제 주문 직전 KIS 수량 검증은 더 작은 현금/no-margin 금액으로 막히는 불일치가 생겼다.
- 총자산도 직접 계산값과 브로커 요약값을 `max()`로 고르는 경로가 있어, 주문가능액이나 현금 후보가 총자산에 섞이면 큰 값이 정답처럼 표시될 수 있었다.

## 변경
- 국내 주문가능조회의 `amount`/`executable_amount`를 실주문 기준으로 고정했다.
  - 1순위: `nrcvb_buy_amt`
  - 2순위: `ord_psbl_cash`, `psbl_cash`, `cash`
  - 3순위: `ord_psbl_amt`, `buy_psbl_amt`, `max_buy_amt`
  - 마지막 fallback: `wdrw_psbl_tot_amt`
- 기존처럼 가장 큰 참고 금액은 `display_amount`/`display_source`로만 남겼다.
- 국내 주문 전 수량 축소 로직은 `executable_amount`를 기준으로 계산하도록 변경했다.
- 단타 공용 예산 스냅샷에 `orderable_krw`를 명시하고, 총자산 직접 계산은 주문가능액이 아니라 실제 현금/잔고 + 평가액을 사용하게 했다.
- 예산 진단 로그에도 `kis_orderable_krw`를 추가해 D+1/D+2 예수금과 즉시 주문가능금액을 구분했다.
- 대시보드 매수 가능액은 `executable_amount`를 표시하고, 총자산 직접 계산은 `krw_cash + usd_cash + 평가액` 기준으로 바꿨다.
- `src`, `bundle`, `build` 세 경로의 실행 파일을 동기화했다.

## 검증
- `python -m py_compile`
  - `src/portal/trading/model/struct/kis_api.py`
  - `src/portal/trading/model/struct/daytrade_engine.py`
  - `src/app/page.dashboard/api.py`
  - 동일 `bundle/`, `build/` 사본
- WIZ 앱 재시작 후 루트 응답 200 확인.
