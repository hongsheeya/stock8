# 단타 백테스트 검증 체계 및 과최적화 방지 강화

- **ID**: 016
- **날짜**: 2026-04-10
- **유형**: 기능 추가

## 작업 요약
백테스트 결과를 총수익률 중심에서 수수료 차감 순이익, Profit Factor, 회전율, 평균 보유시간까지 포함하는 구조로 확장했다. 기간 분리 기반 train/validation, 워크포워드 검증, 추천 단계의 종목군 교차 검증 정보를 추가해 과최적화 신호를 더 빨리 파악할 수 있게 만들었다.

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade.py` — 거래 비용 모델, 세션/백테스트 집계 확장, validation/워크포워드/교차검증 추가
- `src/app/page.daytrade/view.pug` — Profit Factor, 평균 보유시간, 수수료/세금 지표 표시 추가
- `docs/daytrade/optimization-report.md` — 검증/강건성 지표 포함 포맷으로 자동 갱신
- `data/daytrade/latest_training.json` — 확장된 학습 결과 저장 포맷 반영
- `data/daytrade/recommendation.json` — 전략/검증 포함 추천 결과 저장 포맷 반영
