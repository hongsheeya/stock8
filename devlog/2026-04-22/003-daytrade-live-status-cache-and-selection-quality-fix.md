# 단타 live_status 캐시 안정화 및 추천 종목 품질 필터 강화

- **ID**: 003
- **날짜**: 2026-04-22
- **유형**: 버그 수정

## 작업 요약
`live_status`가 10초 폴링마다 예산, 보유종목, 손실현황, 추천정보를 반복적으로 계산하며 외부 KIS 조회까지 동반해 연결이 끊길 정도로 무거워지고 있었다. 또한 추천 종목 선별은 저변동/수수료 완충력이 부족한 종목과 백테스트 품질이 낮은 종목에도 상대적으로 관대해 손실 가능성이 큰 후보가 상단에 남을 여지가 있었다.

## 변경 파일 목록
### 실시간 상태 API
- `src/app/page.daytrade/api.py`
  - `live_status`에 12초 응답 캐시를 추가했다.
  - 일반 폴링에서는 예산 조회를 cache-only로 수행하도록 변경했다.
  - 일부 하위 조회(`worker_status`, `active_positions`, `daily_loss`) 실패 시 이전 캐시 응답으로 degrade 하도록 보강했다.
  - 엔진 초기화 실패 시에도 캐시가 있으면 200 응답으로 복구하도록 수정했다.

### 프론트엔드 폴링
- `src/app/page.daytrade/view.ts`
  - `live_status` 자동 폴링 주기를 10초에서 15초로 완화했다.

### 추천 종목 선별
- `src/portal/trading/model/struct/daytrade.py`
  - 프리스크리닝 단계에서 `fee_buffer_ok=False` 종목을 제외하도록 강화했다.
  - 최종 선택 점수에서 `total_return <= 0`, `win_rate < 50`, `profit_factor < 1.1`, `max_drawdown > 12` 종목에 감점을 추가했다.

## 검증
- 일반 빌드를 수행해 변경 사항이 정상 반영되는 것을 확인했다.
