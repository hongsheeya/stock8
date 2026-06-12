# 단타 committed_seed 예외 및 로그 패널 위치 복구

- **ID**: 005
- **날짜**: 2026-04-17
- **유형**: 버그 수정

## 작업 요약
가드레일 계산 중 `committed_seed`를 초기화하기 전에 참조하면서 `cannot access local variable 'committed_seed' where it is not associated with a value` 예외가 발생하고 있었습니다.
또한 운영/안전 로그 패널이 오른쪽 랭킹 영역에 남아 있어 사용자 요구와 달리 실시간 시그널 아래에서 보이지 않는 상태였습니다.

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `_guardrails()`에서 `committed_seed`를 먼저 계산한 뒤 `shared_budget_status()`에 전달하도록 순서 수정

### 프론트엔드
- `src/app/page.daytrade/view.pug`
  - 운영/안전 로그 패널을 오른쪽 랭킹 영역에서 제거
  - 실시간 시그널 카드 바로 아래로 이동하여 항상 보이도록 배치

## 검증
- `python -m py_compile src/portal/trading/model/struct/daytrade_engine.py`
- WIZ 프로젝트 일반 빌드 성공
- 수정 파일 진단 오류 없음 확인
