# 무한매수법 알고리즘 엔진 핵심 로직 구현

- **ID**: 005
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
라오어의 무한매수법 규칙에 따른 매매 판단 엔진(`engine.py`)을 구현했다. 사이클 상태 머신(IDLE→ACTIVE→HOLDING→COMPLETED), 매수 판단(1회차 시장가, 2~40회차 LOC 지정가), 매도 판단(목표 수익률 도달 시 전량매도), 미체결 처리, 다종목 동시 운용을 포함한다.

## 변경 파일 목록

### portal/trading/model/struct/engine.py (전면 교체)
- `Engine` 클래스 구현 (~450줄)
- `start_cycle(symbol)`: 워치리스트 기반 새 사이클 생성
- `complete_cycle(cycle_id)`: 사이클 완료 처리
- `get_active_cycles()`: 활성/홀딩 사이클 조회
- `calculate_buy_decision(cycle, prev_close)`: 매수 판단 (1회차 시장가, 2~40회차 LOC 가격 계산)
- `calculate_sell_decision(cycle, current_price)`: 매도 판단 (수익률 vs 목표수익률)
- `execute_buy(cycle_id, ...)`: 매수 체결 DB 기록 + 사이클 갱신
- `execute_sell(cycle_id, ...)`: 매도 체결 DB 기록 + 사이클 완료
- `record_skip(cycle_id, reason)`: 미체결/스킵 기록
- `update_cycle_price(cycle_id, current_price)`: 현재가/수익률 갱신
- `run_daily(symbol)`: 종목별 일일 매매 판단 실행 (시세조회→매도체크→매수판단)
- `run_all()`: 전체 활성 종목 자동 실행
- `get_status()`: 엔진 상태 조회
- `_log_event(...)`: trade_log 이벤트 기록
