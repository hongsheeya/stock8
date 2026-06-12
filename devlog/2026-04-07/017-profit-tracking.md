# 잔여금·수익 표시 및 기간별 수익 조회

- **ID**: 017
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
대시보드에 Profit Overview 섹션을 추가하여 실현 수익, 미실현 수익, 총 수익, 총 수익률을 카드 형태로 표시하고, 기간별(1W/1M/3M/6M/1Y/ALL) 필터를 통해 수익 통계를 조회할 수 있도록 구현했다. 엔진 `run_all()` 실행 후 account_snapshot 테이블에 일일 자산 스냅샷을 자동 기록하는 기능도 추가했다.

## 변경 파일 목록

### 엔진 (portal/trading/model/struct/engine.py)
- `_snapshot_db()` 헬퍼 메서드 추가 — account_snapshot DB 접근
- `_record_daily_snapshot()` 메서드 추가 — 활성 사이클 평가액, 실현 수익, 현금 잔액 계산 후 당일 스냅샷 upsert
- `run_all()` 수정 — 실행 완료 후 `_record_daily_snapshot()` 호출 (try/except로 실패해도 메인 로직에 영향 없음)

### API (src/app/page.dashboard/api.py)
- `_generate_mock_profit_summary(period)` 내부 함수 추가 — Demo 모드 시 기간별 mock 수익 데이터 생성 (트렌드+노이즈 기반 snapshots 포함)
- `profit_summary()` API 함수 추가 — period/date_from/date_to 파라미터로 기간별 수익 통계 반환 (실현/미실현 수익, 총 수익률, 완료 사이클 수, 최대/최소 수익 사이클, 일별 스냅샷 배열)

### 프론트엔드 (src/app/page.dashboard/view.ts)
- `profitPeriod`, `profitLoading`, `profitData` 상태 변수 추가
- `loadProfitSummary()` — profit_summary API 호출
- `setProfitPeriod(period)` — 기간 변경 시 재로드
- `profitChangeClass(val)` — 양수/음수/0 에 따른 색상 클래스 반환
- `profitChangeIcon(val)` — 양수 시 '+' 접두사
- `snapshotBarHeight(value)` — 자산 추이 바 차트 높이 정규화
- `snapshotProfitBarHeight(value)` — 수익률 바 차트 높이 정규화 (50% 기준)
- `ngOnInit` 수정 — `loadProfitSummary()` 호출 추가

### 템플릿 (src/app/page.dashboard/view.pug)
- Profit Overview 섹션 추가 (Summary Cards와 Engine Controls 사이)
  - 기간 선택 탭 (1W/1M/3M/6M/1Y/ALL)
  - 4개 수익 카드 (Realized P/L, Unrealized P/L, Total P/L, Total Return)
  - 기간 통계 행 (완료 사이클 수, Best Cycle, Worst Cycle)
  - 자산 추이 바 차트 (Total Asset 바 + P/L Rate 바)
