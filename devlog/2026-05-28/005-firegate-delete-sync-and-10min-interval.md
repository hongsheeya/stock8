# FireGate 삭제 반영 및 자동 동기화 10분 주기 조정

- **ID**: 005
- **날짜**: 2026-05-28
- **유형**: 버그 수정

## 작업 요약
FireGate에서 포트폴리오를 삭제한 뒤 동기화해도 로컬 무한매수 watchlist/cycle이 남아 있던 문제를 수정했다.
동기화 시 FireGate에 없는 관리 대상 종목은 로컬 watchlist에서 제거하고 cycle은 `COMPLETED`로 아카이브되도록 바꿨고, 자동 동기화 기본 주기를 10분으로 조정한 뒤 실데이터로 `FGT0528` 삭제 반영까지 검증했다.

## 원문 요청사항
```text
1. firegate에서 테스트 종목 삭제하고 동기화까지 했는데 로컬 사이클에서 안사라졌어. 동기화하면 로컬쪽도 수정들어가야해
2. firegate 동기화 일정 주기마다 자동으로 진행되게 해. 대출 10분에 한번이면 될거야
3. 
```

## 변경 파일 목록
### FireGate 동기화 정합성
- `src/portal/trading/model/struct/firegate_bridge.py`
  - FireGate 메모 prefix 상수 추가
  - 삭제된 원격 포트폴리오를 로컬 watchlist/cycle에서 정리하는 cleanup 로직 추가
  - 자동 동기화 기본 주기를 600초로 변경
- `src/app/page.infinitebuy/api.py`
  - FireGate 브릿지 기본 자동 동기화 주기를 600초로 변경
- `src/portal/trading/model/struct.py`
  - 워커의 FireGate 자동 동기화 기본 간격을 600초로 변경
- `src/app/page.dashboard/api.py`
  - 대시보드에 노출되는 FireGate 자동 동기화 기본 간격을 600초로 변경

### 테스트
- `tests/test_firegate_bridge.py`
  - 원격에서 사라진 FireGate 종목이 로컬 watchlist/cycle에서도 정리되는 회귀 테스트 추가

### 실데이터 검증
- FireGate 브릿지 설정을 `auto_sync_interval_sec=600`으로 저장
- 삭제된 `FGT0528`에 대해 `sync_fire_gate` 강제 실행
- 결과 확인
  - `removed_watchlists=1`
  - `archived_cycles=1`
  - 로컬 watchlist 제거됨
  - 로컬 cycle 상태 `COMPLETED`로 변경됨
