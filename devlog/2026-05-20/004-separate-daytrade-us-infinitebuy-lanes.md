# 국장 단타 / 미장 단타 / 미장 무한매수 병목 분리

## 배경
- 미장 단타 예산 계산이 미장 무한매수 당일 예약금을 차감하고 있었다.
- 미장 단타 화면/API가 전체 단타 포트폴리오 사용액을 다시 `used_seed_krw`로 덮어써서, 실제 가용 현금과 다르게 주문가능액 부족처럼 보일 수 있었다.
- 일일 손실 정지선과 자동환전 사용 여부가 전역 설정에 묶여 있어 국장 단타, 미장 단타, 미장 무한매수가 서로 다른 전략임에도 같은 게이트를 공유했다.

## 변경
- 단타 예산 lane을 `KS_DAYTRADE`, `US_DAYTRADE`로 분리했다.
- 미장 단타는 기본적으로 무한매수 예약금을 신규 단타 예산에서 차감하지 않는다.
- 미장 단타는 전체 단타 포트폴리오 사용액이 아니라 미장 단타 포지션 사용액만 `used_seed_krw`로 반영한다.
- 미장 단타 예산 계획에는 KIS 원화 자동환전 추정치를 포함할 수 있게 했다.
- 자동환전 주문 시도 설정을 미장 단타와 무한매수로 분리했다.
  - `daytrade_us_auto_exchange_order_attempt_enabled`
  - `infinite_buy_us_auto_exchange_order_attempt_enabled`
- 일일 손실 제한과 손절 횟수 정지선을 국장/미장별 설정으로 분리했다.
  - `daytrade_ks_daily_loss_limit_krw`
  - `daytrade_us_daily_loss_limit_krw`
  - `daytrade_ks_daily_stop_loss_halt_count`
  - `daytrade_us_daily_stop_loss_halt_count`
- 국장/미장 청산 감시 lock을 시장별로 분리했다.

## 검증
- `python -m py_compile` 통과
  - `src/portal/trading/model/struct/daytrade_engine.py`
  - `src/portal/trading/model/struct/engine.py`
  - `src/portal/trading/model/struct/kis_api.py`
  - `src/app/page.daytrade.us/api.py`
  - 동일 bundle 파일

## 추가: 국장 단타 재가동 조정
- 국장 일일 손실 정지선을 5만원에서 15만원으로 완화했다.
- 국장 일일 손절 횟수 정지선을 3회에서 6회로 완화했다.
- 국장 탐색 진입을 다시 활성화했다.
- VREV 시가 대비 약세 차단선을 aggressive 모드 기준 약 -5.4%까지 완화했다.
- VREV VWAP 이탈 차단선이 학습 프로필에 따라 너무 낮아지지 않도록 국장 최소 기준을 추가했다.
- 국장/미장 일일 손실 계산이 서로 섞이지 않도록 `daily_loss_status(..., market=...)` 경로를 분리했다.
- 런타임이 `build/` 파일을 참조하는 케이스까지 확인해 source/bundle/build 세 경로를 동기화했다.
- 국장 시장가 매수 직전에 KIS 국내 주문가능수량/주문가능금액을 다시 조회해 수량을 축소하도록 했다.
- 국장 신규 후보는 `trade_ready` 및 실전용 검증승률/PF/추세정합/과최적화 기준을 통과하지 못하면 제외하도록 했다.
- `trade_ready_count=0`인데도 best-effort 후보를 억지로 쓰던 기본값을 껐다.
- 후보가 부족할 때 품질 게이트를 완화하는 경로를 껐다.
- VREV 2차 진입은 VWAP, 시가대비 낙폭, 장중 추세, RSI, 미실현 손실 기준을 통과해야만 허용하도록 했다.
- 국장 VREV 2차 진입은 1차 진입이 손실 중이면 금지하도록 설정했다.
