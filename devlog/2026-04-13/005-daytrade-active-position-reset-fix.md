# 단타 보유 종목 표시 누락 원인 수정

- **ID**: 005
- **날짜**: 2026-04-13
- **유형**: 버그 수정

## 작업 요약
`/daytrade`에서 잘 보이던 보유 종목이 갑자기 사라지는 원인을 추적한 결과, 세션 날짜가 바뀔 때 라이브 상태를 기본값으로 다시 덮어쓰면서 `position_qty`, `avg_price`, `orders`까지 같이 초기화되는 문제가 확인됐다. 이로 인해 활성 포지션 목록이 빈 배열처럼 보였고, 이미 사둔 종목도 화면에서 사라질 수 있었다.

추가로, 이미 로컬 상태가 0으로 날아간 경우를 복구할 수 있도록 KIS 국내주식 잔고를 읽어 daytrade 상태에 다시 동기화하는 복구 경로를 넣었다.

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 세션 날짜 변경 시 포지션 수량/평단/주문 이력 유지
  - `active_positions()` 및 시그널 계산 전에 브로커 국내 잔고 동기화 추가
- `src/portal/trading/model/struct/kis_api.py`
  - `get_domestic_balance()` 추가
  - 국내 보유 종목을 읽어 daytrade 상태 복구에 사용할 수 있게 확장

## 원인
- `session_date`가 바뀌면 `_default_state()`를 그대로 `update()` 하면서 기존 포지션 상태까지 0으로 덮어씀
- 이후 `active_positions()`는 `position_qty > 0` 인 항목만 노출하므로, 화면에서 보유 종목이 사라짐

## 조치 결과
- 날짜가 바뀌어도 보유 종목 상태가 유지됨
- 이미 local state가 지워졌더라도 KIS 국내 잔고에서 다시 읽어 복구 가능
