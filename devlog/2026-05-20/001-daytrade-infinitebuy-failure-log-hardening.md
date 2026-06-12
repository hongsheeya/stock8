# 단타/무한매수 실패 로그 분석 및 방어 로직 강화

- **ID**: 001
- **날짜**: 2026-05-20
- **유형**: 버그 수정

## 작업 요약
2026-05-20 국장 단타 손실, 2026-05-18 미장 단타 미체결, 무한매수 LOC 예약 실패 이력을 함께 추적했다.
국장 단타는 장 시작 직후 3분 안에 신규/추가 진입이 몰린 뒤 09:10 전 3건이 손절되어 승률 0%가 발생했다.
미장 단타는 `ASTS` 매수 신호가 반복됐지만 배정 USD 예산이 1주 가격보다 낮아 `order_qty=0`으로 보류됐고, 실체결 기록은 없었다.
무한매수는 해외 ETP 권한/주문가능금 부족/분할 씨앗금 부족/LOC 예약 거부가 누적됐고, 특히 예약 스케줄러가 추정 환전 가능액을 실제 주문가능금처럼 쓰며 같은 현금을 여러 종목에 중복 배정할 수 있었다.

## 원문 요청사항
```text
1. 미장 단타 무한매수 둘다 실패한 이유 로그 분석해서 제대로 좀 가져와. 어떻게 된게 성공한 적이 한번도 없는거야
2. 오늘도 승률 개판이네. 좀 제대로 하라고
```

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 당일 `trade_log` 기반 매수/매도/손절/승패 통계를 `daily_loss_status`와 가드레일에 연결
  - 장초반 국장 신규 진입 수 제한, 장초반 손절 발생 시 추가 신규 진입 중단, 당일 손절 횟수 기반 신규 진입 중단 추가
  - `BUY2`가 1차 진입 직후 너무 빨리 발생하면 최소 확인 시간 전에는 보류
  - 매수 신호라도 주문 수량이 0이면 `BUY`가 아니라 명시적 `HOLD` 사유로 반환
- `src/portal/trading/model/struct/engine.py`
  - 무한매수 즉시 매수/LOC 예약 매수 모두 실제 해외 주문가능수량과 금액으로 주문 수량을 재산정
  - LOC 예약에서 추정 환전 가능액을 실제 주문가능금으로 대체하던 fallback 제거
  - 같은 실행 루프에서 이미 예약한 금액을 차감해 TQQQ/SOXL 중복 예산 예약 방지

## 검증
- `python -m py_compile src/portal/trading/model/struct/daytrade_engine.py src/portal/trading/model/struct/engine.py`
- `wiz project build --project=main` 시도: 로컬 WIZ 플러그인 파일(`/mnt/data/wiz/plugin/workspace/model/builder.py`) 누락으로 빌드 도구 초기화 단계에서 실패
