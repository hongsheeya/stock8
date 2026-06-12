# 002 - DB 모델 구현 - 거래 관련 테이블 스키마

- **ID**: 002
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
trading 패키지에 8개 DB 테이블 모델을 생성했다. 모든 테이블은 `trading` DB 네임스페이스(SQLite)를 사용하며, `portal/season/orm.base("trading")`로 기반 클래스를 생성한다.

## 변경 파일 목록

### portal/trading/model/db/
- `trading_config.py`: 전역 매매 설정 (키-값 저장, is_secret 플래그)
- `etf_watchlist.py`: 운용 종목 리스트 (symbol, 투자금, 분할횟수, 목표수익률)
- `trading_cycle.py`: 매매 사이클 (상태머신, 회차, 평단가, 수익률)
- `cycle_trade.py`: 사이클 내 개별 거래 (회차별 주문/체결 상세)
- `trade_log.py`: 전체 거래 로그 (이벤트 타입별 기록)
- `account_snapshot.py`: 일별 계좌 스냅샷 (현금, 평가, 총자산)
- `simulation_run.py`: 모의투자 실행 기록 (기간, 결과 지표)
- `simulation_trade.py`: 모의투자 개별 거래 기록
