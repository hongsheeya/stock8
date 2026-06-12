# 단타 예산 제약 해결 및 유니버스 확장

- **ID**: 011
- **날짜**: 2026-04-14
- **유형**: 기능 추가

## 작업 요약
예산 부족으로 인한 매수 실패 문제를 해결하기 위해 보유 종목 매도 우선권을 부여하고 예산 관련 파라미터를 상향 조정했다. 또한 주당 단가가 낮은 종목들을 유니버스에 대거 추가하여 소액 예산에서도 원활한 순환매매가 가능하도록 개선했다.

## 변경 파일 목록

### 백엔드 (Python)
- `src/portal/trading/model/struct/daytrade.py`:
    - 보유 종목(`active_positions`)에 대한 매도 판단 우선순위 부여 로직 강화.
    - `budget_ratio`를 0.2에서 0.35로 상향하여 가용 예산 확대.
    - `buy_split_ratio`를 0.5에서 0.8로 상향하여 한 번에 매수하는 비중 증가.
    - 무한매수용 예약금(`reserve`) 무시 설정(`ignore_reserve: true`) 적용 가능하도록 수정.
- `src/portal/trading/model/struct/universe.py`:
    - `DEFAULT_CANDIDATES` 리스트에 삼성중공업, 유한양행 등 주당 단가가 낮은 우량주 30여 개 추가.
- `src/route/daytrade_scheduler.py`:
    - 가격 제한(Price Limit) 발생 시 루틴이 통째로 스킵되지 않고 다른 종목을 시도하도록 안정성 로직 추가.

### 프론트엔드 (Angular)
- `src/app/page.daytrade/view.ts`:
    - 무한매수 예약금 무시 토글 스위치 연동.
- `src/app/page.daytrade/view.pug`:
    - 설정 패널에 "무한매수 예약금 무시" 옵션 UI 추가.
