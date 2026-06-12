# 단타 익절 직후 동일 가격대 재진입 방지 가드 추가

- **ID**: 006
- **날짜**: 2026-05-11
- **유형**: 버그 수정

## 작업 요약
국장 V-REV 단타에서 `SELL_RECENT`·`SELL_RESCUE`·`SELL_FULL` 직후 다시 비슷한 가격에 재진입할 수 있던 흐름을 점검했다.
직전 익절가 대비 최소 눌림 폭을 확인하는 `profit_reentry_min_pullback_pct` 가드를 추가해, 수수료만 왕복으로 더 나가고 기대수익이 약한 재매수를 줄이도록 보정했다.

## 원문 요청사항
```text
1. 매매할때 올라서 판 가격에 그대로 사면 수수료만 두배고 더 오를 확률이 좀 낮지 않나?
```

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 직전 익절가 대비 최소 눌림 가격을 계산하는 `_profit_reentry_guard()` 추가
  - 상태에 `last_exit_price`를 저장하고 새 세션 초기화 시 유지하도록 보강
  - 실제 라이브 시그널 계산 경로에서 익절 직후 재진입 가격 가드를 적용
  - 자동/수동 매도 체결 시 `last_exit_price`와 종료 메타데이터를 함께 기록
- `src/portal/trading/model/struct/daytrade.py`
  - 기본 프로파일에 `profit_reentry_min_pullback_pct: 0.7` 추가
