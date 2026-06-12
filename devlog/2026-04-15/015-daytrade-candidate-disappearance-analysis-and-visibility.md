# 단타 후보 급감/소실 원인 분석 및 상태 가시성 보강

- **ID**: 015
- **날짜**: 2026-04-15
- **유형**: 버그 수정

## 작업 요약
단타 후보가 잠깐 생겼다가 대부분 사라져 보이던 현상을 추천 캐시 불일치와 정상적인 시드 초과 제외로 나눠서 정리했다. 추천/화면/자동순환이 같은 데이터 기준을 보도록 맞추는 한편, 남은 시드로 살 수 없어 숨겨진 종목 수를 UI에 표시해 정상 제외와 버그를 구분할 수 있게 했다.

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `auto_candidates()`에서 주당 상한 초과 종목을 `excluded_by_price`로 분리하고 사유를 남기도록 수정
  - 자동순환이 추천 리더보드와 같은 affordability 기준을 사용하도록 정리
### 프론트엔드
- `src/app/page.daytrade/view.ts`
  - `fullLeaderboard`, `hiddenSeedExceededCount`, `recommendationRequestedSeed`, `recommendationPriceCap` 추가
  - 화면 표시용 `leaderboard`는 전체 후보에서 현재 시드 제한을 적용한 결과만 노출
- `src/app/page.daytrade/view.pug`
  - 랭킹 헤더에 요청 시드와 주당 상한을 표시
  - 시드 제한으로 숨겨진 후보 수 안내 문구 추가
### 문서
- `.github/custom/algorithm-daytrade.md`
- `.github/custom/daytrade-usage.md`
  - 후보가 사라지는 정상/비정상 케이스 설명 보강

## 검증
- 수정 파일 오류 검사 통과
- 프로젝트 일반 빌드 성공 확인
- 사용자가 숨김 개수와 주당 상한을 함께 볼 수 있도록 상태 표시 보강
