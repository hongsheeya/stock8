# 단타 수익 하한선 반영 및 국장 breakout 실주문 허용

- **ID**: 013
- **날짜**: 2026-05-28
- **유형**: 기능 추가

## 작업 요약
사용자 요청에 맞춰 단타 추천이 단순 퍼센트 수익률이 아니라 실제 원화 일평균 수익을 우선 보도록 조정했다. 국장 추천 품질 게이트에 일평균 수익 최소 기준을 추가하고, 랭킹에도 `avg_profit`/`validation_avg_profit`를 반영했다.

또한 엔진의 실주문 허용 전략 판정이 KS에서 `vrev`만 허용하던 하드코딩을 제거하고, 전략 스펙의 `live_supported`를 기준으로 판정하도록 바꿨다. 이로써 실제로 성과가 나오는 `volume_breakout`도 국장에서 실주문 후보로 사용할 수 있게 했다.

## 원문 요청사항
```text
매매 알고리즘 바꾼거야? 바뀐 알고리즘으로는 승률이랑 수익 어느정도 나오는지 계속 분석하고 수익이 의미 있는 수치가 나올때까지 알고리즘 학습을 반복해. 수익은 하루에 최소 몇만원은 벌어야해.
```

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct/daytrade.py`
  - KS 추천 품질 게이트에 `daytrade_ks_min_avg_profit_krw`, `daytrade_ks_min_validation_avg_profit_krw` 기준 추가
  - KS/US 랭킹 점수에 `avg_profit`, `validation_avg_profit` 반영
  - 추천 결과 상단 row/aggregate에 평균 수익 지표 노출 추가
  - 추천 사유 문구에 검증 일평균 수익 포함
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `_live_strategy_allowed()`를 전략 스펙 기반 판정으로 변경
  - KS `volume_breakout` 같은 `live_supported` 전략이 실주문 후보가 될 수 있도록 수정

### 테스트
- `tests/test_daytrade_recommendation_cache.py`
  - 검증 일평균 수익 부족 시 KS 품질 게이트가 차단하는 회귀 테스트 추가
- `tests/test_daytrade_engine_regressions.py`
  - 전략 스펙 기반 실주문 허용 판정 회귀 테스트로 갱신

## 검증 메모
- 직접 관련 테스트 8건 통과
- `profile_book.json` 수동 분석 결과, 새 기준을 동시에 만족하는 국장 후보 5개 확인
  - `018260 volume_breakout`: 일평균 약 `27,616원`, 검증 일평균 약 `56,598원`, 검증 승률 `80%`
  - `079550 vrev`: 일평균 약 `62,819원`, 검증 일평균 약 `31,897원`, 검증 승률 `60%`
  - `009150 volume_breakout`: 일평균 약 `33,522원`, 검증 일평균 약 `28,530원`, 검증 승률 `60%`
