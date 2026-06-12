# LOC 예약 매도 주문 기능 구현

- **ID**: 004
- **날짜**: 2026-04-08
- **유형**: 기능 추가

## 작업 요약
매도 주문 방식을 기존 시장가(MARKET) 전용에서 LOC(Limit On Close) 방식까지 지원하도록 확장. Settings에서 매도 방식을 선택하고, 목표 수익률 도달 종목에 대해 LOC 매도 주문을 사전 예약할 수 있는 기능을 구현.

## 변경 파일 목록

### KIS API (백엔드)
| 파일 | 변경 내용 |
|------|----------|
| `portal/trading/model/kis_api.py` | `sell_order()`에 `order_type` 분기 추가 — MARKET="00", LOC="34", LIMIT="00" |

### 엔진 (백엔드)
| 파일 | 변경 내용 |
|------|----------|
| `portal/trading/model/engine.py` | `run_daily()` 매도 호출에서 `sell_method` config 참조하여 MARKET/LOC 분기 |
| | `execute_sell()` — `order_type` 파라미터 추가 (기본값 "MARKET") |
| | `execute_partial_sell()` — `order_type` 파라미터 추가 (기본값 "MARKET") |
| | trade_data의 `order_type` 필드를 동적으로 기록 |
| | `schedule_loc_sells()` 메서드 추가 — 활성 사이클 중 목표 수익률 도달 종목에 LOC 매도 주문 사전 접수 |

### Settings 페이지 (프론트엔드 + 백엔드)
| 파일 | 변경 내용 |
|------|----------|
| `app/page.settings/api.py` | `sell_method` config 키 추가 (load_settings, save_params) |
| `app/page.settings/view.ts` | `sellMethod` 필드 추가, loadSettings/saveParams에 연동 |
| `app/page.settings/view.pug` | Strategy 탭에 매도 주문 방식 선택 UI 추가 (Market/LOC 라디오 카드) |

### Dashboard 페이지 (프론트엔드 + 백엔드)
| 파일 | 변경 내용 |
|------|----------|
| `app/page.dashboard/api.py` | `schedule_loc_sells()` 엔드포인트 추가 |
| `app/page.dashboard/view.ts` | `scheduleLOCSells()` 메서드 추가 |
| `app/page.dashboard/view.pug` | "LOC 매도 예약" 버튼 추가 (엔진 즉시 실행 버튼 아래) |

### 다국어 (공통)
| 파일 | 변경 내용 |
|------|----------|
| `portal/trading/libs/i18n.ts` | 6개 신규 번역 키 추가 (set.sell_method, set.sell_market, set.sell_market_desc, set.sell_loc, set.sell_loc_desc, dash.loc_schedule, dash.loc_scheduling, dash.loc_schedule_desc) |
