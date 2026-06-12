# 미장 단타 자동환전 예약매수를 KIS 예약주문 API로 전환

- **ID**: 008
- **날짜**: 2026-05-12
- **유형**: 버그 수정

## 원인
화면과 런타임 문구는 17:40 KST 이후 “예약매수”라고 안내했지만, 실제 미장 단타 매수 실행은 일반 해외주식 주문 API(`/uapi/overseas-stock/v1/trading/order`)를 호출하고 있었다.

일반 주문 API는 즉시 USD 주문가능금액을 검사하므로, 원화 자동환전 가능액을 앱에서 `executable_amount`에 합산해도 브로커 서버에서는 `주문가능금액을 초과 했습니다`로 거절될 수 있다.

KIS 공식 샘플 기준 미국 예약주문은 별도 API(`/uapi/overseas-stock/v1/trading/order-resv`, TR `TTTT3014U`)를 사용해야 하며, 예약 접수 시점에는 증거금/잔고를 체크하지 않고 정규장 전송 시점에 판단한다.

## 변경 파일

### `src/portal/trading/model/struct/kis_api.py`
- `buy_reservation_order()` 추가
  - 미국 예약매수 전용 `/trading/order-resv` 호출
  - `FT_ORD_QTY`, `FT_ORD_UNPR3`, `ORD_DVSN=00` payload 로깅
  - 예약주문번호를 `reserve_order_no`로 반환

### `src/portal/trading/model/struct/daytrade_engine.py`
- 17:40 KST 이후, 미국 정규장 전에는 일반 주문 대신 예약매수 API를 사용
- DST 기준 예약주문 cutoff를 노출 (`22:20 KST`, 비서머타임 `23:20 KST`)
- 예약주문 cutoff 이후 정규장 시작 전에는 일반 주문을 보내지 않고 대기
- 예약매수 접수 후 `pending_buy_*` 상태를 저장해 워커 반복 실행으로 같은 주문이 중복 접수되지 않도록 방지
- 브로커 보유 수량 동기화에서 실제 포지션이 확인되면 pending buy 상태를 해제

### `src/portal/trading/model/struct/engine.py`
- 무한매수 R0/일일 매수 실행도 정규장 전에는 일반 주문 대신 예약매수 API를 사용
- 무한매수 17:40 LOC 자동예약 경로도 KIS 예약주문 API로 접수
- `cycle_trade`에 `PENDING` 예약매수 기록을 남겨 같은 사이클의 중복 예약매수를 방지

## 검증
- `python3 -m py_compile src/portal/trading/model/struct/kis_api.py src/portal/trading/model/struct/daytrade_engine.py src/portal/trading/model/struct/engine.py`
- `wiz project build --project=main`은 로컬 `wiz` 플러그인 파일 누락으로 실패
  - 누락 파일: `/mnt/data/wiz/plugin/workspace/model/builder.py`
