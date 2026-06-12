# FireGate 자동 동기화 통합 및 대시보드 단타 보유 표시 복구

- **ID**: 003
- **날짜**: 2026-05-28
- **유형**: 기능 추가

## 작업 요약
FireGate 포트폴리오를 무한매수 종목별 시드/분할/목표수익의 권위 원본으로 두고, 로컬 watchlist·cycle을 주기적으로 자동 반영하도록 백그라운드 워커를 확장했다.
동시에 FireGate 화면의 가져오기/동기화 버튼을 하나의 동기화 기능으로 통합했고, 대시보드 overview 응답에 단타 보유 포지션 데이터를 추가해 단타 보유중 섹션이 다시 표시되도록 수정했다.

## 원문 요청사항
```text
1. 무한매수 종목당 시드 조정하는건 대시보드가 아니라 firegate 포트폴리오에서 하는걸로 하자. 포트폴리오 수정하면 자동으로 동기화해서 사이클 정보 수정해야해. 일정 시간마다 자동으로 동기화하게 해줘
2. 단타 보유중인게 안보여. 수정해
3. 동기화랑 가져오기 해도 내 사이클 바뀌는게 하나도 없잖아. 대체 뭔 기능이야. 그리고 가능하면 자동화 시켜두고 두 기능을 하나로 합쳐
```

## 변경 파일 목록
### FireGate 자동 동기화
- `src/portal/trading/model/struct/firegate_bridge.py`
  - FireGate 포트폴리오를 로컬 watchlist/trading_cycle로 반영하는 공용 동기화 함수 추가
  - FireGate `isRunning=false` 포트폴리오를 로컬에서 `PAUSED` 또는 `COMPLETED`로 더 정확히 매핑하도록 보강
- `src/portal/trading/model/struct.py`
  - 백그라운드 워커에 FireGate 자동 동기화 주기 실행 추가
  - 워커 상태에 FireGate 자동 동기화 활성 여부와 마지막 동기화 시각 노출 추가
- `src/app/page.infinitebuy/api.py`
  - `sync_fire_gate` 단일 API 추가
  - 기존 가져오기/동기화 API를 동일한 로컬 반영 동작으로 통합
  - 브릿지 저장 시 자동 워커가 즉시 돌도록 연결
- `src/app/page.infinitebuy/view.ts`
  - 초기 브릿지 연결 및 수동 실행이 모두 단일 동기화 API를 호출하도록 정리
- `src/app/page.infinitebuy/view.pug`
  - 가져오기/동기화 버튼을 하나의 동기화 버튼으로 통합

### 대시보드 단타 보유 표시 및 FireGate 권한 모델 반영
- `src/app/page.dashboard/api.py`
  - overview 응답에 `daytrade_positions`, `daytrade_position_summary`, `fire_gate_bridge` 포함
- `src/app/page.dashboard/view.ts`
  - FireGate 브릿지 상태를 받아 무한매수 시드 직접 저장을 차단
- `src/app/page.dashboard/view.pug`
  - FireGate 연결 시 무한매수 종목별 시드를 읽기 전용으로 표기하고 FireGate 관리 문구 노출

### 테스트
- `tests/test_firegate_bridge.py`
  - FireGate 포트폴리오 자동 동기화가 로컬 watchlist/cycle을 갱신하는 회귀 테스트 추가
