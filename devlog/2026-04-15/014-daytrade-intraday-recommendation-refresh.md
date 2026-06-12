# 단타 장중 추천 점수 최신화 정책 추가

- **ID**: 014
- **날짜**: 2026-04-15
- **유형**: 기능 추가

## 작업 요약
같은 날짜라는 이유만으로 장중 추천을 계속 재사용하던 동작을 개선해, 장중에는 stale 기준을 넘기면 추천을 다시 학습하도록 만들었다. 전체 재훈련을 매번 수행하지 않도록 시장 시간 여부와 `daytrade_recommendation_refresh_sec` 설정을 함께 사용해 자동순환 후보 갱신 주기를 제한했다.

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct/daytrade.py`
  - `latest_recommendation()`에 `max_age_sec`, `allow_stale_day` 검증을 추가
  - 추천 결과에 `refresh_policy` 메타데이터를 기록
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `_daytrade_market_open()` 추가
  - `auto_candidates()`에서 시장 시간 중에는 `daytrade_recommendation_refresh_sec`를 stale TTL로 적용
  - 자동순환 응답에 `recommendation_refresh_sec`, `total_seed_krw`를 함께 노출
- `src/app/page.daytrade/api.py`
  - `live_status()` 응답에 현재 추천 스냅샷을 함께 내려 프론트가 마지막 추천 상태를 확인할 수 있게 정리

## 검증
- 수정 파일 오류 검사 통과
- 프로젝트 일반 빌드 성공 확인
- 장중 stale refresh는 적용하고, 장외에는 기존 추천을 재사용하는 정책으로 비용을 제한
