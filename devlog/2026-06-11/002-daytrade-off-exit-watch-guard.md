# 단타 OFF 시 자동청산 잔류 실행 차단

- **ID**: 002
- **날짜**: 2026-06-11
- **유형**: 버그 수정

## 작업 요약
단타 자동매매를 꺼도 워커가 자동청산 감시를 계속 실행할 수 있던 경로를 막았다.
국장·미장 모두 자동매매 OFF 상태에서는 자동청산 감시를 유효 비활성으로 처리하도록 엔진과 워커 상태 계산을 함께 정리했다.

## 원문 요청사항
```text
ㅅㅂ 단타 껐잖아. 건들지마. 내가 알아서 하고 있는데 그걸 왜 팔아
```

## 변경 파일 목록
- `src/portal/trading/model/struct.py`
  - 단타 자동청산 감시를 자동매매 ON 상태와 묶는 유효 플래그 헬퍼 추가
  - 워커 실행 조건과 `worker_status()` 노출값을 유효 플래그 기준으로 정리
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `execute_exit_watch()`에서 국장·미장 자동매매 OFF 시 즉시 no-op 반환 가드 추가
- `tests/test_daytrade_engine_regressions.py`
  - 단타 OFF 상태에서 국장/미장 자동청산 감시가 실행되지 않는 회귀 테스트 2건 추가
