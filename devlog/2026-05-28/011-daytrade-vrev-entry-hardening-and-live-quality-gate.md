# 단타 V-REV 진입 필터 강화 및 실주문 품질 게이트 정합화

- **ID**: 011
- **날짜**: 2026-05-28
- **유형**: 버그 수정

## 작업 요약
최근 몇 주 실거래/백테스트 데이터를 기준으로 국장 단타 손실 원인을 다시 분석했다. 손실의 핵심은 V-REV가 약한 하락 추세 종목을 너무 이르게 받는 문제와, 추천 랭킹의 상위 품질이 실주문 불가 전략까지 포함해 과대평가되던 구조였다.

이에 V-REV 진입 전 RSI·VWAP 이격·추세 강도·단기/중기 이평 지지를 함께 확인하는 공통 preflight를 추가하고, 실거래 후보 계산은 실제 라이브 허용 전략만 기준으로 품질 게이트를 다시 계산하도록 정리했다.

## 원문 요청사항
```text
최근 몇주동안의 주식 데이터를 가지고 지금 너가 사용하는 알고리즘으로 진행했을때 손실율을 분석하고 원인을 찾아서 알고리즘을 개선해봐. 요즘 승률 10퍼도 안나오잖아
```

## 변경 파일 목록
### 전략/백테스트
- `src/portal/trading/model/struct/daytrade.py`
  - `DEFAULT_PROFILE`에 V-REV 진입 품질 필터 기본값을 추가했다.
  - `vrev_entry_issues()`를 추가해 RSI, VWAP 할인율, 추세 강도, MA 지지 여부를 한 곳에서 판정하도록 정리했다.
  - `_simulate_vrev_session()`에서 preflight 실패 시 진입 자체를 건너뛰도록 바꿨다.

### 실거래 엔진
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `_vrev_preflight_check()`가 전략의 `vrev_entry_issues()`를 재사용하도록 바꿔 백테스트/실거래 진입 기준을 맞췄다.
  - `_live_strategy_allowed()`를 추가해 시장별 실주문 허용 전략 집합을 명시했다.
  - `auto_candidates()`에서 실제 실주문 가능 전략만으로 `live_quality_guard`를 계산하고, 라이브 가능 후보가 없으면 신규 진입을 차단하도록 수정했다.

### 테스트
- `tests/test_daytrade_engine_regressions.py`
  - 실주문 불가 전략만 trade-ready일 때 자동 후보가 차단되는 회귀 테스트를 추가했다.
- `tests/test_daytrade_vrev_filters.py`
  - 역추세 칼날잡기 구간을 `vrev_entry_issues()`가 차단하는지 검증하는 테스트를 추가했다.
  - preflight 실패 세션에서 V-REV 시뮬레이션이 거래를 만들지 않는지 검증하는 테스트를 추가했다.

## 검증 메모
- 최근 라이브 상태 분석 결과: 상태 기준 승/패 8/29, 누적 실현손익 약 -337,257.68원, `SELL_STOP_LOSS` 56회로 손절 비중이 과도했다.
- 최근 15영업일 KS 후보 52개 기준 수정 후 집계:
  - 평균 수익률 `15.4866`
  - 중앙값 수익률 `6.7373`
  - 평균 손익비 `1.798`
  - 평균 최대낙폭 `5.3924`
  - 양수 종목 32 / 음수 종목 20
- 타깃 테스트 통과:
  - `tests.test_daytrade_engine_regressions.DaytradeEngineRegressionTests.test_auto_candidates_block_when_only_non_live_strategy_is_trade_ready`
  - `tests.test_daytrade_vrev_filters`
- 프로젝트 빌드 성공:
  - `wiz project build --project=main`
- 런타임 확인:
  - `page.daytrade/live_status`에서 `004020` 종목이 `vrev 진입 보류: VWAP 대비 하락 과다`로 응답해 새 preflight가 실제 라이브 판단에도 반영됨을 확인했다.
