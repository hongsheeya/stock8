# 단타 지표 피처 파이프라인 고도화

- **ID**: 015
- **날짜**: 2026-04-10
- **유형**: 기능 추가

## 작업 요약
분봉 데이터에 공통 피처 레이어를 추가해 전략별 신호 계산 기반을 표준화했다. 이동평균선, RSI, MACD, 거래량 급증률, 장중 변동폭, 시가 괴리율, VWAP 괴리율, 돌파 기준값을 계산하고 `/daytrade` 우측 패널에서 현재 피처 스냅샷을 확인할 수 있게 했다.

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade.py` — `_decorate_bars()` 피처 계산 확장, `feature_snapshot()` 및 이벤트 필터 스냅샷 추가
- `src/portal/trading/model/struct/daytrade_engine.py` — 라이브 응답에 최신 피처 스냅샷 포함
- `src/app/page.daytrade/api.py` — `feature_snapshot` 응답 추가
- `src/app/page.daytrade/view.ts` — 피처 상태 관리 추가
- `src/app/page.daytrade/view.pug` — 피처 스냅샷 카드 추가
- `docs/daytrade/strategy-playbook.md` — 공통 피처 레이어 정의 문서화
