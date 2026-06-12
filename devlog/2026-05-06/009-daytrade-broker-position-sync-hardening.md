# 단타 브로커 포지션 동기화 및 활성 포지션 집계 보강

- **ID**: 009
- **날짜**: 2026-05-06
- **유형**: 버그 수정

## 작업 요약
단타 엔진의 브로커 포지션 동기화가 국내 잔고 위주로만 동작하던 문제를 보강했다.
국내/해외 잔고를 함께 반영하도록 수정하고, 시장별로 실제 조회된 마켓만 state 정리에 사용해 수동 매도/손절 트리거 대상 포지션이 잘못 사라지는 위험을 줄였다.

## 원문 요청사항
```text
아직 안팔리잖아. 전체적인 중복 정리 들어가고 매드 트리거 제대로 좀 고쳐놔. 매도가 도달했는데 안팔고 손절가 도달했는데 안팔잖아
```

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `_sync_broker_positions()`에서 국내/해외 브로커 잔고를 함께 읽도록 수정
  - 실제 조회된 market만 state 정리 대상으로 제한
  - `active_positions()`에서 해외 브로커 보유 종목도 병합하도록 보강
- `build/src/model/portal/trading/struct/daytrade_engine.py`
  - 런타임 반영을 위해 동일 보정 적용
- `bundle/src/model/portal/trading/struct/daytrade_engine.py`
  - 런타임 반영을 위해 동일 보정 적용
