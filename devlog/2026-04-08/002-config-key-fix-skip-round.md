# 원화 잔고 미인식 원인 분석 및 수정 + SKIP 회차 미진행 처리

- **ID**: 002
- **날짜**: 2026-04-08
- **유형**: 버그 수정

## 작업 요약
Settings에서 `kis_is_mock` 키로 저장하지만 `kis_api.py`에서 `kis_is_real` 키를 조회하는 설정 키 불일치 버그를 수정. 이로 인해 실전/모의 구분이 작동하지 않아 원화 잔고가 인식되지 않았음. 또한 `record_skip()`에서 회차가 증가하던 로직을 수정하여 SKIP 시 회차를 소진하지 않도록 변경.

## 변경 파일 목록

### Settings API (키 불일치 수정)
- `src/app/page.settings/api.py`
  - `load_settings()`: `kis_is_mock` → `kis_is_real` 조회로 변경, `is_mock = is_real != "true"` 로 변환
  - `save_api_settings()`: `kis_is_mock` 대신 `kis_is_real` 키로 저장 (is_mock 값을 반전), 기존 `kis_is_mock` 키 삭제, 토큰 초기화 추가

### Engine (SKIP 회차 미진행)
- `src/portal/trading/model/struct/engine.py`
  - `record_skip()`: `current_round + 1` → `current_round` 유지, PENDING_EXTENSION 전환 로직 제거, SKIP 로그 이벤트 추가
  - `run_daily()` 마지막의 중복 return 라인 제거
