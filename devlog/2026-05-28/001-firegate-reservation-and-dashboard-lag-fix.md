# FireGate 재인증·무한매수 예약매수·대시보드 재진입 지연 보정

- **ID**: 001
- **날짜**: 2026-05-28
- **유형**: 버그 수정

## 작업 요약
실수로 생성된 무한매수 `T` 사이클과 워치리스트를 운영 DB에서 삭제했다.
FireGate 브릿지 토큰을 만료 직전 선제 갱신하도록 보강했고, 무한매수 LOC 예약매수를 일반 매수 주문이 아니라 KIS 예약주문 API로 보내도록 수정했다. 또한 부분 성공 상태에서도 같은 날 자동예약이 반복 재시도되지 않도록 처리하고, 대시보드 재진입 시 직전 상태를 즉시 복원해 체감 지연을 줄였다.

## 원문 요청사항
```text
무한매수 사이클 T 삭제해줘. 실수로 만든거야
무한매수 예약 제대로 된거야? 매수가 안되어있잖아
승률 또 왤케 개판이야. 종목 선정 API 붙여줄까?
pull_fire_gate_portfolios failed: FireGate auth failed: 401 ... 무한매수 가져오기 오류
FireGate auth failed: 401 ... 무한매수 동기화 오류
다른 페이지에서 대시보드로 넘어가면 너무 렉이 많이 걸려... 대시보드 계속 작동하게 ... 동기화 시간 좀 줄여
너 진짜 레전드로 주식 못한다. 뭔 집는거마다 떨어지냐
미실현 수익에서 단타랑 무한매수 분류해놔.
미장 단타는 왜 진행안되는건데. 되는걸 한번도 본적이 없어
```

## 변경 파일 목록
### 코드 수정
- `src/app/page.infinitebuy/api.py`
  - FireGate `id_token` 만료 임박 여부를 검사해 브릿지 호출 전에 선제 재발급하도록 보강.
- `src/portal/trading/model/struct/firegate_bridge.py`
  - 저장된 FireGate 토큰이 만료 직전이면 config 로딩 단계에서 자동 재발급하도록 보강.
- `src/portal/trading/model/struct/engine.py`
  - LOC 자동예약 매수를 `buy_order()`가 아니라 `buy_reservation_order()`로 전환.
  - 주문가능금액 판단 시 KIS 환전 이후/추정 가능 수량·금액까지 반영하도록 보강.
- `src/portal/trading/model/struct.py`
  - 일부 종목 오류가 있어도 이미 예약된 주문이 있으면 해당 일자의 LOC 자동예약을 완료로 간주하도록 보강.
- `src/app/page.dashboard/view.ts`
  - 대시보드 진입 시 최근 상태를 전역 캐시에서 복원하고, overview/수익/미리보기 응답마다 캐시를 갱신하도록 보강.

### 운영 데이터 정리
- 운영 DB에서 심볼 `T` 관련 `trading_cycle`, `cycle_trade`, `trade_log`, `etf_watchlist` 데이터를 삭제.

### 검증
- `python3 -m py_compile src/app/page.infinitebuy/api.py src/portal/trading/model/struct/firegate_bridge.py src/portal/trading/model/struct/engine.py src/portal/trading/model/struct.py`
- `wiz project build --project=main`
- FireGate 저장 refresh token으로 실제 토큰 재발급 및 Firestore portfolios 조회 성공 확인.
- 운영 DB에서 `T` 삭제 후 남은 무한매수 사이클이 `SOXL`, `TQQQ`만 남았는지 확인.
