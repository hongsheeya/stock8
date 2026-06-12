# 단타 변동폭 완화 및 거래일지 시그니처/전일매수 표시 보정

- **ID**: 001
- **날짜**: 2026-04-21
- **유형**: 버그 수정

## 작업 요약
단타 자동매매의 최소 일중 변동폭 기본값을 4.0%에서 3.5%로 완화했다.
또한 거래일지의 과거 날짜 조회 시 최신 `period_trade_summary()` 시그니처와 중복 정의가 어긋나 `include_valuation` 인자를 받지 못하던 오류를 수정하고, 전일 매수 후 금일 매도 시 기준 매수금액이 계속 보이도록 유지했다.

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `daytrade_min_day_range_pct` 기본값을 `3.5`로 변경
  - 최신 `period_trade_summary()` 중복 정의에 `include_valuation` 파라미터 복원
  - 과거 날짜 선택 시 `include_valuation` 예외 없이 동작하도록 수정
- `devlog.md`
  - 작업 이력 추가
