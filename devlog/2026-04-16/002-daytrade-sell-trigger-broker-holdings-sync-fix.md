# 단타 판매 트리거 브로커 보유 동기화 수정

- **ID**: 002
- **날짜**: 2026-04-16
- **유형**: 버그 수정

## 작업 요약
단타 판매 트리거가 목표가 도달 후에도 `HOLD`로 남는 원인을 추적한 결과, 라이브 엔진이 브로커 보유 수량을 읽는 경로에서 KIS 잔고 캐시에 `holdings` 목록을 저장하지 않아 상태 파일의 `position_qty`가 0으로 유지되고 있었다.
이 문제를 수정해 캐시에도 보유 목록을 포함시키고, 캐시 누락 시 직접 잔고 조회로 보완하도록 변경했다.

## 변경 파일 목록
### 엔진
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `_fetch_kis_balance_raw()` 반환값에 `holdings` 포함
  - `_sync_broker_positions()`가 캐시에 보유 목록이 없으면 `get_domestic_balance()`로 즉시 보완하도록 수정

## 검증
- `036570` 실보유 종목 기준 `live_status` 재검증
  - 수정 전: `position_qty: 0`, `HOLD`
  - 수정 후: `position_qty: 2`, `SELL_FULL`, `jackpot_target: 252960`
- 일반 빌드 성공
