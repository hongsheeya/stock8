# 고급 매도 알고리즘 (분할매도 + 폭락매수)

- **ID**: 019
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
무한매수법 엔진에 고급 매도 전략(분할매도/폭락매수)을 추가하고, 설정 페이지에 Strategy 탭, 시뮬레이션 페이지에 전략 비교 기능을 구현.

## 변경 파일 목록

### Phase 1: 전략 모듈 생성
- `src/portal/trading/model/struct/strategy.py` (NEW) — PartialSellStrategy, CrashBuyStrategy 클래스, backtest_strategy(), compare_strategies() 함수

### Phase 2: 엔진 통합
- `src/portal/trading/model/struct/engine.py` — 전략 상수, _get_strategy_params(), _load_strategy_module(), calculate_sell_decision() 분할매도 지원, execute_partial_sell(), execute_crash_buy(), run_daily() 폭락매수/분할매도 로직 추가
- `src/portal/trading/model/struct.py` — _Strategy 모듈 로드 + property 추가
- `src/portal/trading/model/db/cycle_trade.py` — strategy_type 필드 추가
- `src/portal/trading/model/db/trading_cycle.py` — partial_sold_count, crash_buy_count 필드 추가

### Phase 3: UI (Settings + Simulation)
- `src/portal/trading/libs/i18n.ts` — 전략 관련 ~30개 en/ko 키 추가
- `src/app/page.settings/view.ts` — 전략 변수 9개 추가, loadSettings()/saveParams() 전략 파라미터 연동, setStrategy() 메서드
- `src/app/page.settings/view.pug` — 4번째 탭 Strategy 추가 (매도전략 선택, 분할매도 파라미터, 폭락매수 설정)
- `src/app/page.settings/api.py` — load_settings()에 전략 설정 반환, save_params() 전략 설정 저장, update_watchlist_item() 신규 함수, 필드명 정렬(division_count/target_profit/auto_trade)
- `src/app/page.simulation/api.py` — run_comparison() 엔드포인트 추가 (전량매도 vs 분할매도 비교)
- `src/app/page.simulation/view.ts` — 전략 비교 변수/메서드 추가 (runComparison, toggleComparison, diffClass)
- `src/app/page.simulation/view.pug` — Compare Strategies 버튼 + 비교 패널 (분할매도 파라미터 입력 + side-by-side 결과)
