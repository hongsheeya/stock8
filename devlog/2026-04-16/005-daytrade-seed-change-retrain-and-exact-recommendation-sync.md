# 단타 시드 변경 재훈련 및 정확 추천 동기화

- **ID**: 005
- **날짜**: 2026-04-16
- **유형**: 기능 개선

## 작업 요약
시드 변경 시 기존 일반 추천 캐시로 되돌아가던 흐름을 제거하고, 현재 시드와 슬롯 기준 가격 상한에 맞는 추천만 조회하도록 정리했다.
프론트에서는 실제 시드가 바뀐 경우 강제 재훈련을 호출하도록 바꿔 후보 목록, 화면 상태, 자동순환 기준이 같은 추천 스냅샷을 보도록 동기화했다.

## 변경 파일 목록
### 백엔드
- `src/app/page.daytrade/api.py`
  - `recommend()`가 현재 예산 상태에서 `per_symbol_seed_krw` 기반 `price_cap`을 계산해 추천 재분석에 사용
  - `bootstrap()`과 `live_status()`에서 일반 추천 캐시 fallback 제거
  - 추천 응답에 `budget_status`, `max_affordable_per_share`를 함께 반환

### 프론트엔드
- `src/app/page.daytrade/view.ts`
  - `runRecommend()`가 추천 응답과 함께 예산/가격 상한 상태를 동기화
  - `applySeed()`가 실제 시드 변경 여부를 판단해 강제 재훈련을 호출
  - `loadLiveStatus()`가 `recommendation: null` 응답도 그대로 반영해 오래된 추천 UI가 남지 않게 수정
