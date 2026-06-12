# 단타 그래프 홀드아웃 안정성 게이트 추가

- **ID**: 012
- **날짜**: 2026-05-28
- **유형**: 기능 추가

## 작업 요약
최근 몇 주 단타 손실 원인을 단순 평균 수익이 아니라 검증 구간의 그래프 흔들림 관점에서 다시 봤다. 워크포워드 검증 곡선 일부를 홀드아웃으로 분리해 안정성 점수를 만들고, 이 점수를 프로파일 선택·종목 랭킹·실주문 품질 게이트에 함께 반영하도록 개선했다.

추가로 최근 KS 프로필 북 기준으로 그래프 홀드아웃 게이트를 적용했을 때 실주문 가능 후보가 6개 수준으로 압축되며, 과최적화가 큰 종목과 변동폭이 큰 종목이 자연스럽게 밀리는 것을 확인했다.

## 원문 요청사항
```text
어떤 방식으로 매매가 진행되어야 그동안 안정적으로 돈을 벌었을까? 정답지가 있으면 의미가 없으니까 일부 그래프 기록을 검증용으로 사용해서 알고리즘 좀 개선해봐
```

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct/daytrade.py`
  - 워크포워드 `validation_return` 그래프 일부를 홀드아웃으로 쓰는 `graph_validation` 계산 추가
  - `stability_score`, `holdout_avg_return`, `negative_fold_ratio`, `return_swing_pct` 산출 추가
  - 프로파일 최적화 `selection_score`에 그래프 안정성 반영
  - KS/US 추천 랭킹과 `trade_ready` 품질 게이트에 그래프 홀드아웃 기준 추가
  - 추천 사유와 최적화 리포트에 그래프 안정성 지표 노출

### 테스트
- `tests/test_daytrade_recommendation_cache.py`
  - 매끈한 홀드아웃 곡선이 흔들리는 곡선보다 높은 안정성 점수를 받는 테스트 추가
  - KS 추천 품질 게이트가 그래프 홀드아웃 불안정을 차단하는 회귀 테스트 추가

## 검증 메모
- 선별 테스트 실행
  - `python3 -m unittest tests.test_daytrade_recommendation_cache.DaytradeRecommendationCacheTests.test_graph_validation_metrics_prefers_smoother_holdout_curve`
  - `python3 -m unittest tests.test_daytrade_recommendation_cache.DaytradeRecommendationCacheTests.test_ks_quality_gate_flags_graph_holdout_instability`
  - `python3 -m unittest tests.test_daytrade_recommendation_cache.DaytradeRecommendationCacheTests.test_us_quality_gate_flags_low_profit_factor_and_liquidity tests.test_daytrade_vrev_filters`
- 최근 KS `profile_book.json` 기준 수동 검증
  - 그래프 홀드아웃 게이트 적용 시 실주문 가능 후보 6개로 압축
  - `004020` 같은 고과최적화/고변동 후보는 그래프 안정성 점수와 품질 게이트에서 불리해짐
