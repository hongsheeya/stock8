# 시뮬레이션 커스텀 종목 비교 오류 수정

- **ID**: 007
- **날짜**: 2026-04-09
- **유형**: 버그 수정

## 작업 요약
시뮬레이션 화면에서 커스텀 종목 선택 시 비교 시뮬레이션이 실제 종목코드 대신 `__custom__` 값을 전송하던 문제를 수정했다.
프론트엔드와 백엔드 모두 종목코드를 trim/uppercase 정규화하도록 보강해 TQQQ 같은 직접 입력 종목의 실패 가능성을 낮췄다.

## 변경 파일 목록
### 프론트엔드
- `src/app/page.simulation/view.ts`
  - `getSimulationSymbol()` 헬퍼 추가
  - 일반 실행/비교 실행 모두 실제 커스텀 심볼을 사용하도록 수정

### 백엔드
- `src/app/page.simulation/api.py`
  - `run_simulation()`, `run_comparison()`에서 심볼을 `strip().upper()`로 정규화

## 검증
- 변경 파일 진단 오류 없음 확인
- WIZ 프로젝트 `main` 일반 빌드 성공
