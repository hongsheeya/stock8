# 서버 안정화 — exec() 생존 sys 캐시 + 지연 struct 로드

- **ID**: 014
- **날짜**: 2026-04-14
- **유형**: 버그 수정

## 작업 요약

dev 모드에서 `wiz.server.cache.clear()` 매 요청 실행 → `Model = Struct()` 재실행 → `_init_tables()` + `_migrate_schema()` MySQL DDL 매 요청마다 실행 + 중복 Background Worker 스레드 대량 생성(최대 135개)으로 서버 메모리 12.8GB 폭증 및 완전 응답 불가 상태 발생. KIS 잔고 캐시도 클래스 변수에 저장했으나 클래스가 재생성되어 캐시 무효화.

모든 캐시를 `sys` 모듈 속성(프로세스 레벨)으로 이동하여 exec() 재실행 후에도 캐시가 유지되도록 수정. DB 초기화도 `sys` 기반 1회 실행 가드 적용. api.py에서 struct 지연 로드 적용(ping은 즉시 응답). signal_status 타임아웃을 SIGALRM에서 `threading.Thread.join(timeout=5)`으로 교체(멀티스레드 환경에서 SIGALRM 미동작).

## 변경 파일 목록

### 버그 수정
- `src/portal/trading/model/struct.py`
  - `_init_tables()` + `_migrate_schema()` → `sys._trading_struct_tables_ok_{pid}` 가드로 1회만 실행
  - `_ensure_background_worker()` → `threading.enumerate()`로 중복 스레드 방지
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `_fetch_kis_balance_raw()` 캐시: 클래스 변수 → `sys._trading_kis_balance_cache`
  - `shared_budget_status()` 캐시 확인: 클래스 변수 → sys 모듈
  - `_invalidate_kis_cache()`: sys 모듈 속성 초기화
  - `_latest_snapshot()` 캐시: 클래스 변수 → `sys._trading_snapshot_cache`
- `src/app/page.daytrade/api.py`
  - `struct = wiz.model("struct")` → 지연 로드 `_get_struct()` 함수로 교체 (최상위 즉시 실행 제거)
  - `ping()` 함수는 struct 없이 즉시 응답
  - `signal_status` 타임아웃: `signal.SIGALRM` → `threading.Thread.join(timeout=5)` 교체

## 결과
- ping: 즉시 응답 (0.0s)
- live_status: 0.8s (캐시 히트 시)
- run_auto_cycle: 2.0s
- withdrawable_krw: 209,460원 (TTTC8908R 기반, 정확)
- 서버 스레드: 135개 → 1개 (wiz 워커 재시작 후)
