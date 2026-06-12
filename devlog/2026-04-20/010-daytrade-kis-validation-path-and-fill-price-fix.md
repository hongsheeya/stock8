# 단타 일지 KIS 검증 경로 및 실체결가 반영 수정

- **ID**: 010
- **날짜**: 2026-04-20
- **유형**: 버그 수정

## 작업 요약
당일 일지에서 실체결가 검증이 실제로는 안정적으로 수행되지 않던 문제를 수정했다. 기존에는 일지 경량 요약이 종목별로 KIS를 여러 번 호출하고 잘못된 객체 경로를 참조해 검증 경로가 불안정했다.
KIS 당일 체결내역을 1회 조회해 `order_no` 기준으로 매칭하도록 바꾸고, 주문 실행 로그도 실제 체결가/체결수량 기준으로 저장되도록 보강했다.

## 변경 파일 목록
- `src/app/page.daytrade/api.py`
  - `trading.kis_api.get_domestic_fills_today()` 1회 호출로 당일 체결 검증 경로 수정
  - 잘못된 `struct.kis_api` 참조 제거
  - 일지 로그가 KIS 실체결가를 우선 사용하도록 보정
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 주문 직후 `order_no` 기반 KIS 실체결 조회 `_resolve_domestic_fill()` 추가
  - `trade_log` 저장값과 로그 메시지를 실제 체결가/체결수량 기준으로 변경
- `devlog.md`
  - 작업 이력 추가
