# 단타 보유 포지션 청산 우선순위가 BUY2에 가려지던 문제 수정

- **ID**: 010
- **날짜**: 2026-05-06
- **유형**: 버그 수정

## 작업 요약
단타 엔진의 실효 `_signal_from_state()`가 보유 포지션에서도 `BUY2` 진입 신호를 먼저 확정해, 자동 손절/익절/예약매도 조건이 충족돼도 청산 로직이 실행되지 않던 문제를 수정했다.
국장 실포지션 사례인 포스코인터내셔널과 씨엔스윈드 기준으로, 각각 자동손절/익절 조건이 성립했지만 `BUY2`가 우선돼 미청산되던 경로를 차단했다.

## 원문 요청사항
```text
아니 된거면 왜 씨엔스윈드랑 포스코인터내셔널은 안파는거야?
```

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 중복 정의된 두 `_signal_from_state()` 모두에서 보유 포지션 청산 조건을 `BUY2`보다 우선 판정하도록 수정
  - 자동손절, 사용자 손절/매도가, 잭팟 익절, 소프트 익절, BB 상단 익절, RSI 익절, recent/rescue 청산 조건을 sell 우선 게이트에 포함
- `build/src/model/portal/trading/struct/daytrade_engine.py`
  - 런타임 반영용 동일 수정 적용
- `bundle/src/model/portal/trading/struct/daytrade_engine.py`
  - 런타임 반영용 동일 수정 적용
