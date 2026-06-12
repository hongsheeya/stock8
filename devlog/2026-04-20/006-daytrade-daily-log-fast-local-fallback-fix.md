# 단타 당일 거래 일지 초경량 로컬 fallback 복구

- **ID**: 006
- **날짜**: 2026-04-20
- **유형**: 버그 수정

## 작업 요약
당일 거래 일지 API가 KIS/대용량 요약 경로에 걸리며 장시간 응답하지 않아 화면에 로딩 실패가 표시되던 문제를 수정했다.
기본 당일 조회는 `live_state.json`과 `runtime_logs.json`을 직접 읽는 초경량 fallback으로 전환해 즉시 렌더링되도록 보강했다.

## 변경 파일 목록
- `src/app/page.daytrade/api.py`
  - 당일 일지 전용 `_quick_daily_log_summary()` 추가
  - `daily_log()`가 오늘 날짜 요청일 때 파일 기반 빠른 요약 경로를 사용하도록 변경
  - 실시간 valuation/daily loss 의존 없이도 요약을 반환하도록 정리
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 최신 `period_trade_summary()` 경로에 선택적 broker sync / valuation 옵션 추가
  - 누락되어 있던 잔여 포지션 집계 블록 복구
  - 당일 로컬 빠른 요약용 `_daily_trade_summary_local_fast()` 추가
