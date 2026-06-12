# 단타 시드 슬롯 동기화 수정

- **ID**: 002
- **날짜**: 2026-04-17
- **유형**: 버그 수정

## 작업 요약
단타 예산 스냅샷은 `slot_target_count` 기준으로 종목당 시드를 계산하고 있었지만, 자동 후보 계산 경로는 별도로 `max_symbols` 기준으로 다시 나누고 있었습니다.
이 불일치 때문에 총 시드가 50만 원 이상이어도 자동매매 로그에는 약 3~4만 원 수준의 슬롯 상한이 표시되는 동기화 어긋남이 발생했습니다.

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `auto_candidates()`가 `shared_budget_status()`의 `slot_target_count`를 그대로 사용하도록 수정
  - `_auto_max_symbols()` 기본값을 설정 UI 기본값과 동일한 `5`로 통일
  - 자동 후보 응답에도 `slot_target_count`를 포함하도록 보강
- `src/app/page.daytrade/api.py`
  - 추천 가격 상한 계산 시 `slot_target_count`를 우선 사용하도록 수정
  - 예외 fallback 슬롯 수를 `15`에서 `5`로 조정

## 검증
- `python -m py_compile src/portal/trading/model/struct/daytrade_engine.py src/app/page.daytrade/api.py`
- 수정 파일 진단 오류 없음 확인
