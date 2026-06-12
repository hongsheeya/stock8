# 단타 시드 변경 연동 종목 후보 재구성

- **ID**: 013
- **날짜**: 2026-04-15
- **유형**: 기능 개선

## 작업 요약
사용자가 시드를 바꿔도 기존 추천 캐시와 선택 종목이 그대로 남아 화면과 워커가 다른 후보 집합을 보는 문제를 정리했다. 추천 캐시에 `requested_seed`, `strategy_scope`, `price_cap_krw`를 포함시키고, `live_status`와 프론트 선택 상태를 현재 시드 기준 추천 결과에 맞춰 다시 동기화하도록 수정했다.

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct/daytrade.py`
  - `_recommendation_price_cap()`, `_recommendation_cache_key()` 추가
  - `latest_recommendation()`이 날짜뿐 아니라 시드/전략/주당 상한까지 검증하도록 확장
  - `recommend()`와 `auto_train()`에서 `requested_seed`, `training_seed`, `price_cap_krw`를 분리해 처리
  - 후보 프리스크리닝에 affordability(`affordable`, `near`, `expensive`) 기준을 반영
- `src/app/page.daytrade/api.py`
  - `bootstrap()`과 `live_status()`에서 현재 시드/전략/주당 상한 기준으로 추천 조회
- `src/app/page.daytrade/view.ts`
  - `loadLiveStatus()`에서 최신 추천 스냅샷을 반영
  - `syncRecommendationSelection()`을 추가해 선택 종목이 현재 추천/리더보드와 어긋날 때 재정렬

## 검증
- 수정 파일 오류 검사 통과
- 프로젝트 일반 빌드 성공 확인
- 시드/전략/주당 상한이 바뀌면 다른 캐시 키를 사용하도록 구조 정리
