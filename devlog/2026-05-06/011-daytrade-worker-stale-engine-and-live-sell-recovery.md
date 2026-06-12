# 단타 워커 stale 엔진 고정 버그 수정 및 실보유 종목 청산 복구

- **ID**: 011
- **날짜**: 2026-05-06
- **유형**: 버그 수정

## 작업 요약
단타 백그라운드 워커가 엔진 코드 변경을 감지하지 못하고 오래된 `daytrade_engine` 인스턴스를 계속 사용하던 버그를 수정했다.
이로 인해 보유 종목이 `SELL_*` 대신 계속 `BUY2`로 오판되던 상태를 확인했고, 포스코인터내셔널은 자동 손절로 실제 청산되었으며 씨에스윈드는 관리자 매도 API 경로로 실제 청산을 확인했다.

## 원문 요청사항
```text
아직도 안팔리잖아. 제대로 좀 하라고. 중복되어 있는거야 뭐야. 원인 확실하게 찾아서 고쳐봐. 불필요한 더미 파일들도 다 지워
```

## 변경 파일 목록
- `src/portal/trading/model/struct.py`
  - `_ensure_background_worker()`가 `id(self._DaytradeEngine)` 대신 실제 로드된 엔진 모델 객체 id를 비교하도록 수정
  - 코드 변경 시 새 워커 세대가 뜨도록 stale 엔진 감지 버그 수정
- `build/src/model/portal/trading/struct.py`
  - 런타임 반영용 동일 수정 적용
- `bundle/src/model/portal/trading/struct.py`
  - 런타임 반영용 동일 수정 적용
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `kr_execute_exit_watch()`의 조기 `return` 뒤에 남아 있던 사장 코드(dead code) 제거
- `build/src/model/portal/trading/struct/daytrade_engine.py`
  - 동일 dead code 제거
- `bundle/src/model/portal/trading/struct/daytrade_engine.py`
  - 동일 dead code 제거

## 운영 확인 사항
- 포스코인터내셔널(`047050`)은 `SELL_STOP_LOSS` 실행 로그와 체결 로그를 확인
- 씨에스윈드(`112610`)는 `manual_sell` API 타임아웃 후에도 실제 시장가 매도 체결 로그를 확인
- 디버깅 중 생성한 `/tmp/daytrade_scheduler_response.txt` 임시 파일 삭제
