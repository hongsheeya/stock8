# 단타 당일 거래 일지 실제 매수/매도 필터 복구

- **ID**: 007
- **날짜**: 2026-04-20
- **유형**: 버그 수정

## 작업 요약
당일 거래 일지 요약이 runtime 로그 기반 임시 데이터로 표시되면서 실제 매수/매도 수량/금액이 빠지고, 오늘 거래하지 않은 종목까지 함께 섞여 나오던 문제를 수정했다.
당일 요약을 `trade_log` DB 기준으로 다시 계산하고, 오늘 실제 거래가 있었던 종목만 요약/잔여보유에 포함되도록 정리했다.

## 변경 파일 목록
- `src/app/page.daytrade/api.py`
  - `_quick_daily_log_summary()`를 `trade_log` 기반 경량 집계로 재작성
  - 오늘 체결된 `BUY`/`SELL` 로그만 사용해 `buy_count`, `sell_count`, `buy_amount`, `sell_amount` 계산
  - 오늘 거래한 종목만 `symbol_summary`, `remaining_positions`에 남기도록 필터링
- `devlog.md`
  - 작업 이력 추가
