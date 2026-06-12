# 국내 단타 백테스트/학습 프레임워크 구축

- **ID**: 003
- **날짜**: 2026-04-10
- **유형**: 기능 추가

## 작업 요약
국내 주식 1분/5분봉 데이터를 활용하는 단타 백테스트 프레임워크를 구현했다. yfinance 기반 데이터 수집, VWAP/거래량 지배력 계산, 세션 단위 시뮬레이션, 수익률/MDD/승률/회전율 산출 기능을 추가했다.

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade.py` — 데이터 수집, 세션 시뮬레이션, 백테스트 구현
- `src/app/page.daytrade/api.py` — 백테스트 실행 API 추가
- `src/app/page.daytrade/view.ts` — 백테스트 실행/결과 로직 추가
