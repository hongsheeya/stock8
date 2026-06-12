# 단타 라이브 분봉 fallback 및 동기화 안정화

- **ID**: 002
- **날짜**: 2026-04-20
- **유형**: 버그 수정

## 작업 요약

- `004020.KS의 분봉 데이터를 찾을 수 없습니다.` 오류를 포함한 단타 라이브 상태 불안정 문제를 전수 점검했다.
- 핵심 원인은 `yfinance` 분봉 실패 자체보다, 실패 시 복구 경로 부족, API의 임시 스레드 타임아웃 방식, struct 초기화 오류의 영구 캐시, 상태/런타임 로그 파일 동시 접근 경쟁이었다.
- 분봉 실패 시 KIS 현재가/캐시 기반 fallback을 추가하고, 신규 매수는 차단하되 보유 종목 청산 판단은 계속 가능하도록 보강했다.

## 변경 파일 목록

### 1. 라이브 분봉 fallback 추가
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `_latest_snapshot()`에서 `1d/1m` 분봉 조회 실패 시 예외로 중단하지 않고 KIS 현재가 + 기존 state 기반 축약 스냅샷 생성
  - fallback bar에 `intraday_unavailable` 플래그를 추가하여 런타임 가드레일에서 식별 가능하도록 수정
  - fallback 발생 시 런타임 로그에 원인 기록

### 2. 신규 매수 차단 / 청산 유지
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 장중 분봉이 없는 fallback 상태에서는 신규 매수는 차단하고, 보유 종목 청산 판단은 경고만 남기고 계속 진행하도록 가드레일 보강

### 3. signal_status 복원력 강화
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `signal_status()`가 예외를 그대로 던지지 않고 구조화된 오류 상태(`HALT`, `error_fallback`)를 반환하도록 수정
  - 최근 오류를 state/runtime에 남겨 UI와 로그에서 원인 추적 가능하도록 보강

### 4. 상태/로그 파일 동시 접근 직렬화
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `live_state.json`, `runtime_logs.json` 읽기/쓰기 경로를 프로세스 전역 `RLock`으로 직렬화
  - 워커/수동 API/스케줄러 동시 접근 시 파일 경합 및 덮어쓰기 위험 완화

### 5. API 타임아웃/에러 캐시 개선
- `src/app/page.daytrade/api.py`
  - `live_status()`의 임시 스레드 기반 5초 타임아웃 제거
  - struct 초기화 오류를 영구 캐시하지 않고 TTL(5초) 후 재시도하도록 수정
  - signal 계산 예외는 에러 로그에 남기고 fallback 상태를 사용하도록 정리

## 검증 내용

- 프로젝트 빌드 성공
- 번들에 fallback / error cache TTL / intraday_unavailable 반영 확인
- 기존 forkserver 자식 프로세스를 정리하고 새 자식 프로세스로 교체
  - 교체 후 스레드 수: 3
  - 교체 후 FD 수: 29

## 결론

- `004020.KS` 오류는 단일 종목 문제라기보다 분봉 공급 실패와 복구 경로 부족, 타임아웃 스레드 방식, 동시 접근 문제가 겹친 결과였다.
- 수정 후에는 분봉 실패가 발생해도 즉시 전체 상태가 무너지지 않고, 보유 종목은 계속 관리되며, 신규 진입은 안전하게 차단된다.
