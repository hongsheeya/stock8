# 대시보드 실계좌 데이터 정합성 복구

- **ID**: 013
- **날짜**: 2026-04-29
- **유형**: 버그 수정

## 작업 요약
대시보드가 실계좌 미연결 시 mock 데이터를 반환해 실제 계좌와 괴리가 발생하던 문제를 제거했다.
실계좌 연결 시에는 KIS 보유종목 데이터를 우선 사용하고, 불가 시에만 사이클 기반으로 폴백하도록 정합성을 개선했다.

## 변경 파일 목록
- `src/app/page.dashboard/api.py`
  - `overview()`에서 API 미연결 mock 반환 제거
  - `holdings` 산출 우선순위 변경: KIS `holdings_data` 우선, 실패 시 cycle fallback
  - 응답에 `holdings_source` 추가 (`broker`/`cycle_fallback`)
  - `_profit_summary_data()`의 mock 반환 제거
  - `period_trade_summary()` 호출 시 `include_valuation`을 API 연결 상태와 연동
  - `profit_summary` 데이터에 `api_connected` 포함
