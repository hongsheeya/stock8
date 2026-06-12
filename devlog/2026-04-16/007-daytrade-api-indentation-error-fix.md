# 단타 API 들여쓰기 오류 복구

- **ID**: 007
- **날짜**: 2026-04-16
- **유형**: 버그 수정

## 작업 요약
`page.daytrade/api.py` 수정 중 잘못 들어간 들여쓰기 라인 때문에 모듈 import 시 `IndentationError`가 발생했고, 이 영향으로 `bootstrap`과 `live_status`가 모두 500으로 실패했다.
문제 라인을 제거해 API 모듈이 정상 로드되도록 복구했고, 일반 빌드와 파서 검증을 다시 통과시켰다.

## 변경 파일 목록
### 백엔드
- `src/app/page.daytrade/api.py`
  - `debug_balance()` 내부에 잘못 삽입된 `rec = service.latest_recommendation(...)` 라인을 제거
  - `live_state.json` 로딩용 `try` 블록 구조를 정상화

## 검증
- `api.py` 오류 검사 통과
- 프로젝트 일반 빌드 성공
- 더 이상 `IndentationError`로 인한 500이 발생하지 않도록 복구
