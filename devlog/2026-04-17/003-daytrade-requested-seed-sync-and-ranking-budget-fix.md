# 단타 요청 시드 동기화 및 랭킹 예산 표기 수정

- **ID**: 003
- **날짜**: 2026-04-17
- **유형**: 버그 수정

## 작업 요약
단타 화면에서 사용자가 입력한 요청 시드, 서버 설정의 기본 시드, 워커가 사용하는 시드, 랭킹에 표시되는 슬롯당 상한 값이 서로 다른 경로로 흘러가면서 동기화가 깨져 있었습니다.
이번 수정으로 요청 시드를 서버 설정에 즉시 저장하고, 추천/실시간 상태/랭킹 UI가 동일한 예산 스냅샷을 기준으로 표기하도록 정리했습니다.

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct/daytrade.py`
  - 최소 시드 보정 로직을 완화하고 공통 시드 정규화 헬퍼를 추가
  - 기본 시드가 50만 원대 요청값을 500만 원으로 되돌리던 문제 수정
- `src/app/page.daytrade/api.py`
  - 추천 payload에 현재 예산 스냅샷(`requested_seed`, `price_cap_krw`, `per_symbol_seed_krw`, `slot_target_count`)을 덮어써서 동기화
  - `bootstrap()`이 요청 시드와 실가용 시드를 분리해 반환하도록 수정
  - `sync_seed()` API 추가로 UI 변경 시 서버 기본 시드와 워커 설정까지 즉시 동기화
  - `live_status()`도 동일한 상한 계산 헬퍼 사용

### 프론트엔드
- `src/app/page.daytrade/view.ts`
  - 부트스트랩 시 로컬 시드와 서버 시드를 `Math.max()`로 섞지 않도록 수정
  - `applySeed()`에서 서버 `sync_seed()` 호출 후 상태를 갱신하도록 변경
  - 랭킹 상한/요청 시드 getter를 예산 스냅샷과 추천 메타데이터 기준으로 통일
- `src/app/page.daytrade/view.pug`
  - 랭킹 헤더에 요청 시드, 남은 시드, 슬롯당 시드, 목표 슬롯 수, 1주 진입 상한을 분리 표시
  - 기존 `주당 상한` 혼동 문구를 `1주 진입 상한` 기준으로 명확화

## 검증
- `python -m py_compile src/app/page.daytrade/api.py src/portal/trading/model/struct/daytrade.py`
- WIZ 프로젝트 일반 빌드 성공
- 수정 파일 진단 오류 없음 확인
