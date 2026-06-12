# 단타 전략 후보군 확장 및 비교 설계

- **ID**: 014
- **날짜**: 2026-04-10
- **유형**: 기능 추가

## 작업 요약
기존 V-REV 중심 국내 단타 연구 구조를 전략 레지스트리 기반으로 확장했다. 이동평균 추세추종, RSI 과매도 반등, 거래량 돌파 전략을 추가하고, `/daytrade`에서 전략을 직접 선택해 백테스트·추천·라이브 시그널을 조회할 수 있도록 연결했다.

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade.py` — 전략 메타데이터, 전략별 시뮬레이션/최적화/추천 로직 추가
- `src/portal/trading/model/struct/daytrade_engine.py` — 전략별 라이브 시그널 분기 추가
- `src/app/page.daytrade/api.py` — 전략 파라미터 전달 및 선택 전략 응답 추가
- `src/app/page.daytrade/view.ts` — 전략 선택 상태, 전략 변경 로직 추가
- `src/app/page.daytrade/view.pug` — 전략 선택 드롭다운 및 전략 표시 UI 추가
- `docs/daytrade/strategy-playbook.md` — 전략 상태 머신과 비교 기준 문서 추가
