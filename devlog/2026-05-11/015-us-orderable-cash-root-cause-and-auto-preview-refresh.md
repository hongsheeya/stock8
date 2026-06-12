# 미장 주문가능금액 원인 명확화 및 오늘 매매예정 자동 갱신

- **ID**: 015
- **날짜**: 2026-05-11
- **유형**: 버그 수정

## 작업 요약
미장 주문 실패가 반복되던 원인을 추적해, 화면/예산 계산에서 사용하던 추정 가용금과 브로커 실주문 가능금액이 서로 다른데도 같은 값처럼 취급하던 문제를 분리했다.
국장 단타와 대시보드 쪽은 KIS 연결 상태와 오늘 매매예정 패널이 초기 로드 후 자동으로 갱신되도록 보강했다.

## 원문 요청사항
```text
1. 무한매수든 미장 단타든 지금 미장은 한번도 거래가 안되고 있어. 항상 주문가능금액이 부족하다고만 하지 잔고도 있는거 너도 확인했을텐데 계속 저렇게만 떠. 오류 원인 좀 더 자세히 설명해줘야 뭐가 문제인지 알텐데 너무 추상적이야. 그리고 무한매수 오늘 매매예정 계속 자동으로 API 연결 안되고 내가 새로고침을 눌러야만 API가 연결이 돼. 자동으로 되게 좀 해

S
R0 SKIP: 주문 실패: 매수 주문 실패 [TQQQ]: 주문가능금액을 초과 했습니다 (rt_cd=7, CANO=44370579, ACNT_PRDT_CD=01, exchange=NASD, qty=1, price=76.28, ord_dvsn=00, tr_id=TTTT1002U, is_real=True) | symbol=TQQQ, qty=1, price=76.28, type=MARKET, exchange=NASD, orderable_amount=$157.49
TQQQ · 2026-05-11 08:42
```

## 변경 파일 목록
- **해외 주문 가능금액 정합**
  - `src/portal/trading/model/struct/kis_api.py`
    - 해외 주문가능금액 조회 결과에 `broker_amount`, `broker_qty`, `estimated_amount`, `auto_exchange_usd`를 함께 반환하도록 보강
    - 실제 매수 주문 전 검증은 브로커 실주문 가능금액/수량 기준으로 수행하도록 수정
    - 원화 자동환전 추정 금액이 화면에 보이는 값과 실제 주문 API 반영값이 다를 때 상세 원인을 예외 메시지에 포함
  - `src/portal/trading/model/struct/engine.py`
    - 무한매수 미국 주문 전 검증에서 추정 가용금이 아니라 실주문 가능금액 부족으로 실패했는지 명확히 기록
  - `src/portal/trading/model/struct/daytrade_engine.py`
    - 미장 단타 BUY 실행 전 실주문 가능 USD와 화면 추정 USD를 분리해 로그/경고 메시지에 남기도록 수정

- **자동 연결/자동 갱신 보강**
  - `src/app/page.daytrade/api.py`
    - `live_status` 응답에 최신 `kis_status` 포함
  - `src/app/page.daytrade/view.ts`
    - 라이브 상태 갱신 시 `kisStatus`도 함께 반영
  - `src/app/page.dashboard/view.ts`
    - 대시보드 초기 로드 및 이후 갱신 시 `trade_preview`를 자동 호출하도록 수정해 오늘 매매예정 패널이 수동 새로고침 없이 연결 상태를 반영하도록 보강

## 검증
- `wiz project build --project=main`
- 로컬 API 확인
  - `page.daytrade/live_status` → `kis_status` 포함, `connected=True`
  - `page.dashboard/trade_preview` → 200 응답, `api_connected=True`
