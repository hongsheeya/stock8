# 단타 엔진 레거시 중복 정리 후 누락된 실운용 로직 복구

- **ID**: 002
- **날짜**: 2026-05-29
- **유형**: 버그 수정

## 작업 요약
`daytrade_engine.py` 내부의 오래된 중복 메서드 정리 이후 빠졌던 실운용 헬퍼와 상태 동기화 로직을 복구했다.
국내 자동매매 후보 필터, 브로커 보유분 동기화, 최소 진입 시드, 후보 확장/대기 사유 요약을 다시 맞춰서 회귀 테스트 기준 동작을 회복했다.

## 원문 요청사항
```text
오래된 로직들 전부 찾아내서 불필요하면 삭제해. 지금 옛 로직때문에 꼬인게 한두번이 아니잖아. 제발 좀 한번에 잘하자
```

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 정리 과정에서 누락된 `_vrev_preflight_check`, `_live_strategy_allowed` 복구
  - `_state_order_open_position`, `_cached_recommendation_narrow_for_auto`, `_expand_recommendation_with_candidate_universe`, `_auto_cycle_wait_summary` 복구
  - 브로커 보유분 동기화 시 로컬 주문 이력 기반 복원, unmanaged 보유 표시, `auto_managed` 상태 반영
  - 국내 자동매매 최소 진입 시드와 최대 종목 수 하한 보정
- `devlog.md`
  - 2026-05-29 작업 요약 행 추가
- `devlog/2026-05-29/002-daytrade-engine-legacy-dedupe-and-runtime-restore.md`
  - 상세 작업 기록 추가