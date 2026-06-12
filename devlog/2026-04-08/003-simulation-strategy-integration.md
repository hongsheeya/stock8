# 시뮬레이션에 사용자 매매 전략 통합

- **ID**: 003
- **날짜**: 2026-04-08
- **유형**: 기능 추가

## 작업 요약
시뮬레이션 페이지의 인라인 백테스트 로직을 `strategy.py`의 `backtest_strategy()` 기반으로 리팩토링하고, "내 전략 적용" 토글을 추가하여 Settings에서 설정한 분할매도/폭락매수 전략 파라미터를 시뮬레이션에 자동 적용할 수 있도록 구현했다. 비교 패널에도 폭락매수 파라미터 입력 및 전략별 필터 버튼을 추가했다.

## 변경 파일 목록

### 백엔드 (api.py)
| 파일 | 변경 내용 |
|------|----------|
| `src/app/page.simulation/api.py` | `run_simulation()` — 인라인 백테스트 로직을 `backtest_strategy()` 호출로 교체, `use_my_strategy` 파라미터 추가 (true 시 DB config에서 전략 로드) |
| `src/app/page.simulation/api.py` | `load_watchlist()` — 응답에 strategy 설정 (sell_strategy, partial_sell_*, crash_buy_*) 포함 |
| `src/app/page.simulation/api.py` | `run_comparison()` — crash buy 파라미터 지원, `backtest_strategy()` 직접 사용으로 리팩토링 |

### 프론트엔드 (view.ts)
| 파일 | 변경 내용 |
|------|----------|
| `src/app/page.simulation/view.ts` | `useMyStrategy`, `myStrategyLoaded`, `myStrategy` 필드 추가 |
| `src/app/page.simulation/view.ts` | `crashBuyEnabled/DropPct/MaDropPct/Ratio/MaxPerCycle` 비교 패널 필드 추가 |
| `src/app/page.simulation/view.ts` | `toggleMyStrategy()` 메서드 — 토글 시 DB에서 전략 파라미터 로드 |
| `src/app/page.simulation/view.ts` | `strategyLabel()` 메서드 — 적용 중인 전략 정보 표시 |
| `src/app/page.simulation/view.ts` | `loadWatchlist()` — 응답에서 strategy 파라미터 저장 |

### 프론트엔드 (view.pug)
| 파일 | 변경 내용 |
|------|----------|
| `src/app/page.simulation/view.pug` | "내 전략 적용" 토글 버튼 (자동 연장 토글 옆) |
| `src/app/page.simulation/view.pug` | 전략 정보 배지 — 토글 활성 시 적용된 전략 상세 표시 |
| `src/app/page.simulation/view.pug` | 비교 패널 — 폭락매수 파라미터 섹션 (토글 + 4개 입력 필드) |
| `src/app/page.simulation/view.pug` | 비교 패널 — 분할매도 "재진입 시 전량 매도" 토글 |
| `src/app/page.simulation/view.pug` | PARTIAL_SELL / CRASH_BUY 거래 필터 버튼 추가 |
| `src/app/page.simulation/view.pug` | CRASH_BUY (amber), PARTIAL_SELL (violet) 액션 색상 |

### 다국어 (i18n)
| 파일 | 변경 내용 |
|------|----------|
| `src/portal/trading/libs/i18n.ts` | `sim.use_my_strategy` 키 추가 ('Apply My Strategy' / '내 전략 적용') |
| `src/portal/trading/libs/i18n.ts` | `sim.my_strategy_applied` 키 추가 ('My Strategy Applied' / '내 전략 적용됨') |
