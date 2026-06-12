# 대시보드 자동운영 시드 제어 및 매수가능액 산정 복구

## 배경

- 일반 사용자는 대시보드에서 무한매수, 국장 단타, 미장 단타의 ON/OFF와 배정 시드만 조정하면 되도록 단순화가 필요했다.
- 총자산/평가액 기준이 주문가능금액 계산에 섞이면서, 실제 주문가능 현금이 있어도 대시보드 매수 가능액이 0원처럼 보이는 문제가 있었다.
- 관리자 계정에서 실제 일반 사용자 화면을 바로 확인할 수 있는 전환 장치가 필요했다.

## 변경

- 대시보드 overview에 `automation_controls`를 추가해 무한매수, 국장 단타, 미장 단타의 활성 상태와 KRW 배정 시드를 내려주도록 했다.
- `save_automation_item` API를 추가해 대시보드 카드에서 각 자동운영 항목의 ON/OFF와 시드 저장을 처리한다.
  - 무한매수는 `auto_trade_enabled`, `loc_auto_schedule_enabled`, `infinite_buy_seed_krw`를 저장한다.
  - 활성 무한매수 워치리스트가 있으면 KRW 시드를 환율 기준 USD로 균등 배분해 `total_investment`를 갱신한다.
  - 국장/미장 단타는 각각 `daytrade_auto_enabled`, `daytrade_us_auto_enabled`, 기본 시드 설정을 갱신한다.
- 대시보드 자산 산정에서 평가액 파생값보다 실제 현금/주문가능금액을 우선하도록 보정했다.
  - `cash_asset_krw`는 `krw_balance + usd_cash_balance`와 해외 주문가능금액 환산값 중 큰 값을 기준으로 시작한다.
  - 총자산 필드는 상한/표시값으로만 보정하고, 평가액을 신규 매수 가능 현금처럼 쓰지 않도록 했다.
  - 대시보드 `buying_power`도 주문가능 현금 기준으로 반환한다.
- 원화 매수가능액이 해외 USD 잔고만 남는 상황을 막기 위해 국내 주문가능금액 조회(`get_domestic_buying_power_info`)를 대시보드 overview의 1차 원화 주문가능금액 소스로 추가했다.
  - 최종 `buying_power_orderable`은 `국내 주문가능금액 + 해외 USD 주문가능금액 환산액`으로 계산한다.
  - 관리자 화면에는 `잔고 검증` 패널을 추가해 해외 현재잔고 원화, 국내 주문가능금액, 국내 잔고조회 예수금, 해외 USD 현금/주문가능을 각각 확인할 수 있게 했다.
- 실계좌 원천 응답 대조 결과를 반영해 대시보드 산정 기준을 다시 정렬했다.
  - 해외 USD 주문가능 원천값은 `0`인데 `get_buying_power_info()`의 원화 자동환전 합산값이 USD 잔고처럼 들어갈 수 있어, 대시보드는 `broker_amount`만 USD로 사용하게 했다.
  - 국내 잔고조회 `prvs_rcdl_excc_amt=1,742,720`을 원화 잔고/현금 기준으로 사용한다.
  - 국내 잔고조회 `tot_evlu_amt`/`nass_amt`는 총자산 계열이므로 평가액 fallback에서 제거했다. 보유수량/증권평가금액이 없으면 평가액은 `0`으로 둔다.
- 수익 요약의 실계좌 평가액 fallback에서도 `tot_evlu_amt`/`tot_evlu_pfls_amt`를 제거했다.
  - `scts_evlu_amt`/`evlu_amt_smtl_amt`만 국내 보유주식 평가액으로 인정한다.
- 단타 공유 예산 계산에서 `effective_daytrade_seed`를 총자산 잔여 한도가 아니라 실제 주문가능 현금으로 제한했다.
  - `remaining_asset_room_krw`를 별도로 반환해 총자산 기준 잔여 한도와 실주문 가능액을 분리했다.
  - 국내 단타 실주문 예산은 `inquire-psbl-order`의 `max_buy_amt`/`nrcvb_buy_amt`를 우선 사용한다.
  - 미장 단타 실주문 예산은 KIS 해외 주문가능 API가 내려준 `broker_amount`만 사용하고, 원화 자동환전 추정치는 `us_krw_auto_exchange_estimate_krw`로 분리했다.
- 무한매수 해외 매수 가능액도 `executable_amount=broker_amount`로 고정해 원화 자동환전 추정치가 즉시 실주문 가능 USD처럼 들어가지 않게 했다.
- 상단 거래 네비게이션에 관리자 전용 `관리자 모드 ON/OFF` 토글을 추가했다.
  - OFF 상태에서는 관리자 계정이어도 일반 사용자처럼 운영 상세 메뉴와 설정 진입을 숨긴다.
  - 대시보드도 관리자 OFF 상태에서는 운영 상세 빠른 링크를 숨긴다.
  - OFF 상태에서도 다시 돌아올 수 있도록 네비게이션과 대시보드 상단에 `관리자 모드 켜기` 버튼을 유지한다.
- `gigukbyun@gmail.com`은 DB에서 `admin`으로 확인했으며, `/auth/check`가 세션 role을 DB 사용자 정보로 재동기화하도록 보강했다.
- 추가 원인 확인: 실제 서비스는 `src`가 아니라 `bundle/src`와 `bundle/www/main.js`를 내려주고 있었다.
  - `src`만 고친 상태에서는 대시보드가 계속 예전 `cash_asset_krw`/`총자산-평가액` 로직을 사용했다.
  - `src`, `build/src`, `bundle/src`, `bundle/www/main.js`를 모두 같은 기준으로 동기화했다.
- `wdrw_psbl_tot_amt`/출금가능금액을 실주문 가능액보다 먼저 `max()`로 잡는 문제를 제거했다.
  - 국내 주문가능금액 API(`inquire-psbl-order`)가 성공하면 `krw_orderable_cash`는 그 응답값을 그대로 쓴다.
  - `wdrw_psbl_tot_amt`와 국내 잔고조회 출금가능금액은 주문가능금액 API가 실패했을 때만 fallback으로 쓴다.
  - 프론트도 `krw_orderable_cash=0`을 `krw_balance`로 되살리지 않도록 `||` fallback을 제거했다.
- 현재 계좌 기준 기대 표시값을 다음처럼 정리했다.
  - 매수 가능액/실주문 가능액: `1,672,199원`
  - 원화 잔고/총자산: `1,742,720원`
  - 달러 주문가능: `0원`
  - 포트폴리오 평가액: `0원`

## 검증

- 실계좌 KIS 직접 조회
  - `inquire-present-balance`: `tot_dncl_amt=276,862`, `wdrw_psbl_tot_amt=276,862`, `tot_asst_amt=276,862`, `output2=0건`
  - `domestic inquire-balance`: `dnca_tot_amt=276,862`, `prvs_rcdl_excc_amt=1,742,720`, `tot_evlu_amt=1,742,720`, `nass_amt=1,742,720`, `scts_evlu_amt=0`, `evlu_amt_smtl_amt=0`, 실보유수량 `0건`
  - `domestic inquire-psbl-order`: `ord_psbl_cash=276,862`, `nrcvb_buy_amt=1,672,199`, `max_buy_amt=1,672,199`
  - `overseas inquire-psamount`: `frcr_ord_psbl_amt1=0`, `ovrs_ord_psbl_amt=0`, `max_ord_psbl_qty=0`
- `gigukbyun@gmail.com` DB 사용자 role이 `admin`임을 확인
- `python3 -m py_compile src/app/page.dashboard/api.py src/portal/trading/model/struct/kis_api.py src/portal/trading/model/struct/daytrade_engine.py src/portal/season/route/auth/controller.py`
- Pug compile: `src/app/page.dashboard/view.pug`, `src/app/component.nav.trading/view.pug`
- TypeScript `transpileModule`: `src/app/page.dashboard/view.ts`, `src/app/component.nav.trading/view.ts`
- 런타임 반영 확인
  - 서버 재시작: `/opt/conda/envs/app/bin/wiz run --log /var/log/wiz/app`, 리스너 `0.0.0.0:3000`
  - `/main.js` 응답에서 새 로직 확인: `buying_power_orderable`를 메인 매수가능액으로 사용, `krw_orderable_cash` 0원 보존, 기존 `cash_asset_krw || buying_power` fallback 제거
  - `/wiz/api/page.dashboard/overview`는 비로그인 요청에서 `{"code": 401}`로 인증 보호 동작 확인
- `python3 -m py_compile` 확인 대상
  - `src/app/page.dashboard/api.py`, `build/src/app/page.dashboard/api.py`, `bundle/src/app/page.dashboard/api.py`
  - `src/portal/trading/model/struct/kis_api.py`, `build/src/model/portal/trading/struct/kis_api.py`, `bundle/src/model/portal/trading/struct/kis_api.py`
  - `src/portal/trading/model/struct/daytrade_engine.py`, `build/src/model/portal/trading/struct/daytrade_engine.py`, `bundle/src/model/portal/trading/struct/daytrade_engine.py`

## 참고

- `wiz project build --project=main`은 코드 변경과 무관하게 `/mnt/data/wiz/plugin/workspace/model/builder.py`가 없어 실패한다.
- `npm run build`도 기존 Angular/Sass/타입 오류로 실패해, 이번 변경은 `src`/`build`/`bundle`과 서비스 번들을 수동 동기화했다.
