# 수수료(Commission) 설정 및 반영

- **ID**: 013
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
매수/매도 수수료와 매도세를 설정하고, 트레이딩 엔진과 시뮬레이션에 반영하는 기능을 추가했다. Settings 페이지의 Parameters 탭에 수수료 입력 UI와 프리셋(US/KR/No Fee)을 추가하고, 엔진의 매수/매도 실행 시 수수료를 차감하며, 시뮬레이션에서도 동일한 수수료 로직을 적용하여 순수익률을 정확히 산출한다.

## 변경 파일 목록

### DB 스키마
- `src/portal/trading/model/db/cycle_trade.py`: `commission` 필드 추가 (FloatField, default 0.0)
- `src/portal/trading/model/db/trading_cycle.py`: `total_commission` 필드 추가 (FloatField, default 0.0)
- `src/portal/trading/model/db/simulation_run.py`: `buy_commission_rate`, `sell_commission_rate`, `tax_rate`, `total_commission` 필드 추가
- `src/portal/trading/model/db/simulation_trade.py`: `commission` 필드 추가

### 엔진
- `src/portal/trading/model/struct/engine.py`:
  - `_get_commission_rates()`: trading_config에서 수수료 설정 조회
  - `_calc_buy_commission()`, `_calc_sell_commission()`: 수수료 계산 헬퍼
  - `execute_buy()`: 매수 수수료를 total_spent에 합산, cycle.total_commission 누적
  - `execute_sell()`: 매도 수수료+세금 차감 후 순수익률 산출
  - `calculate_sell_decision()`: 예상 매도 수수료 반영한 순수익률 기준 판단
  - `update_cycle_price()`: 예상 매도 수수료 반영한 수익률 갱신

### Settings 페이지
- `src/app/page.settings/api.py`: `load_settings()`에 수수료 3종 반환, `save_parameters()`에 저장 추가
- `src/app/page.settings/view.ts`: `buyCommissionRate`, `sellCommissionRate`, `taxRate` 프로퍼티 추가
- `src/app/page.settings/view.pug`: Parameters 탭에 Commission & Tax 섹션 + US/KR/No Fee 프리셋 버튼

### Simulation 페이지
- `src/app/page.simulation/api.py`: `run_simulation()`에 수수료 파라미터 추가, 매수/매도 시 수수료 차감, summary에 total_commission 포함
- `src/app/page.simulation/view.ts`: 수수료 프로퍼티 추가, loadWatchlist에서 기본값 로드
- `src/app/page.simulation/view.pug`: 수수료 입력 필드 3개 추가, 결과에 Total Fees 카드 + Fees 컬럼 추가
