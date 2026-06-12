# FireGate 인증·동기화·사이클 pull 복구

- **ID**: 001
- **날짜**: 2026-05-27
- **유형**: 버그 수정

## 작업 요약
FireGate 연동에서 Firestore 요청에 API key가 빠져 인증이 반복 실패하던 문제를 보강하고, `trading_cycle.t_value` 누락 스키마가 현재 프로세스에서도 즉시 보정되도록 마이그레이션 경로를 수정했다.
또한 FireGate pull 시 실행 종료된 포트폴리오까지 로컬 사이클로 반영하도록 복구해 포트폴리오 기준 사이클 생성이 다시 동작하게 했다.

## 원문 요청사항
```text
1. 무한매수 가져오기 오류 고쳐 pull_fire_gate_portfolios failed: FireGate auth failed: 401 { "error": { "code": 401, "message": "Missing or invalid authentication.", "status": "UNAUTHENTICATED" } } 
2. 무한매수 동기화 오류 고쳐 push_fire_gate_sync failed: (1054, "Unknown column 't1.t_value' in 'field list'")
3. firegate 포트폴리오에 따라서 우리쪽 사이클을 만들어야지 어디갔어
```

## 변경 파일 목록
### 백엔드 소스
- `src/portal/trading/model/struct/firegate_bridge.py`
  - Firestore 요청에 `key` 쿼리와 `X-Goog-Api-Key` 헤더를 추가해 FireGate 인증 실패를 완화했다.
- `src/portal/trading/model/struct.py`
  - `trading_cycle.t_value` 마이그레이션을 추가하고, 프로세스 재시작 없이도 스키마 보정이 실행되도록 마이그레이션 호출 위치를 조정했다.
- `src/app/page.infinitebuy/api.py`
  - FireGate 포트폴리오 pull 시 중지된 포트폴리오도 로컬 사이클로 반영하도록 수정했다.
  - FireGate 날짜 파싱 및 실행 여부 판정을 보강했다.

### 테스트
- `tests/test_firegate_bridge.py`
  - Firestore 요청에 API key가 포함되는지 검증하는 회귀 테스트를 추가했다.
- `tests/test_infinitebuy_firegate_pull.py`
  - 실행 중/종료된 FireGate 포트폴리오가 로컬 사이클로 생성되는지 검증하는 회귀 테스트를 추가했다.

### 검증
- `python3 -m unittest tests.test_firegate_bridge tests.test_infinitebuy_firegate_pull tests.test_infinite_buy_firegate_v4`
