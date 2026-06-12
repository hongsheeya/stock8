# 2026-05-20 미장 지정가/자동환전 및 재진입 차단 완화

## 배경
- 미장 무한매수에서 1주 가격이 회차 배정 예산보다 크면 수량 0으로 보류되어 진입이 누락됐다.
- 미장 단타/무한매수 주문가능액 점검이 KIS의 실주문 가능 USD만 하드 기준으로 사용해, 원화 자동환전 추정액이 있어도 로컬에서 주문을 막았다.
- 국장 단타는 `stop_reentry_same_day_block`이 학습/추천 캐시에 남아 있어 당일 손절 종목 재진입이 계속 HOLD 처리될 수 있었다.

## 변경
- 미장 무한매수 1회차/추가 회차 모두 배정 예산이 1주 가격보다 작아도 최소 1주 지정가 진입을 허용했다.
- 미장 무한매수 예약 LOC 흐름을 기본적으로 실시간 지정가 매수 주문으로 전환했다.
- 미장 단타 매수도 LOC/시장가가 아니라 현재가 기준 지정가 주문으로 실행하도록 했다.
- KIS 해외 매수 전 주문가능액 점검에서 자동환전 추정액이 요청 금액을 덮으면 로컬 차단하지 않고 실주문을 시도하도록 했다.
- 자동환전 추정액이 정확히 1주 수준일 때 보수 버퍼로 0주가 되는 계산을 제거했다.
- 국장 학습/추천 캐시의 `stop_reentry_same_day_block` 잔여 `true` 값을 `false`로 정리했다.
- VREV 손절 그리드와 캐시의 `stop_loss_pct=1.4`를 2.4 이상으로 올려 얕은 흔들림 손절을 줄였다.

## 운영 설정
- `us_auto_exchange_order_attempt_enabled=true`
- `infinite_buy_us_use_live_limit_order=true`
- `daytrade_us_limit_price_buffer_pct=0.20`
- `daytrade_symbol_stop_cooldown_days=1`
- `daytrade_symbol_max_stop_losses=4`
- `daytrade_symbol_quality_hard_block_enabled=false`

## 배포 메모
- WIZ 런타임이 `bundle/src/model/portal/trading/struct/*` 경로를 참조하고 있어 변경한 구조체 4개를 번들에도 동기화했다.
- WIZ 앱 프로세스를 재시작했고, 로컬 HTTP 응답(`GET /`, `/wiz/api/page.dashboard/overview`)을 확인했다.
