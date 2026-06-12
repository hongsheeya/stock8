# 단타 판매 시그널 가시성 및 자동청산 감시 복구

- **ID**: 001
- **날짜**: 2026-04-16
- **유형**: 버그 수정

## 작업 요약
단타 화면에서 장중 폴링 이후 청산 계획이 비어 보이던 문제와, 스케줄러 전용 자동청산 감시 메서드가 실제로 정의되지 않아 자동 매도 경로가 일부 동작하지 않던 문제를 함께 수정했다. `live_status`/`bootstrap`이 반환하는 `tradePlan`에 청산 조건과 자동청산 상태를 항상 포함시키고, 서버에서 `execute_exit_watch()` 메서드를 정상 복구했다.

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 클래스 내부에 `execute_exit_watch()` 메서드를 정식 추가
  - 이전에 함수 헤더 없이 남아 있던 자동청산 감시 로직을 정상 메서드로 복구
- `src/app/page.daytrade/api.py`
  - `_build_live_plan_payload()`가 사용자 지정 판매가/손절가, 잭팟 청산가, 방어/구조 청산가, 자동 손절가, `auto_exit` 상태를 항상 포함하도록 수정
  - `live_status` 폴링 후에도 청산 계획이 빈 배열로 덮어쓰이지 않도록 정리

### 프론트엔드
- `src/app/page.daytrade/view.ts`
  - `bootstrap`/`live_status` 응답을 반영할 때 `jackpot`, `recent`, `rescue`, `manual_sell`, `stop_loss` 트리거를 함께 동기화하도록 수정

## 검증
- 수정 파일 오류 검사 통과
- `main` 프로젝트 일반 빌드 성공
- `bootstrap` 응답에서 `tradePlan`에 `auto_exit`, `exits` 키가 포함되는 것 확인
