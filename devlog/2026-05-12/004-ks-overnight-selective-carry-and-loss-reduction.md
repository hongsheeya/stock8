# 국장 오버나잇 선택 허용 및 반복 손실 축소 조정

- **ID**: 004
- **날짜**: 2026-05-12
- **유형**: 버그 수정

## 작업 요약
최근 국장 손실 케이스를 전수 확인한 결과, 전일 보유 종목이 다음날 시초 자동손절로 정리되거나, 오버나잇 보유 상태에서 다시 추가매수 성격의 `BUY2`가 열릴 수 있는 구조가 손실 누적의 핵심 원인이었다.
이에 따라 국장은 약한 종목만 장마감에 정리하고 강한 종목만 선별적으로 오버나잇을 허용하도록 바꾸고, 다음날 시초에는 완화 구간을 두되 급락은 즉시 차단하도록 조정했다. 동시에 추천 품질 기준도 강화해 최근 손실 기여 종목이 덜 선택되도록 보강했다.

## 원문 요청사항
```text
오버나잇 일부 허용해. 지금 너무 이해 안갈정도로 종목을 구매하고 계속 손해보면서 매도 반복하고 있잖아. 모든 케이스를 분석해서 알고리즘 수치 조절해서 승률좀 높여봐. 최근 들어서 계속 손해밖에 안보고 있는데 그 금액도 만만치 않아
```

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade.py`
  - 국장 기본 프로필에 선택적 오버나잇 허용 값(`carry_overnight_enabled`, `carry_max_loss_pct`, `carry_min_vwap_ratio`, `carry_min_close_strength_pct`, `overnight_open_grace_minutes`, `overnight_panic_stop_loss_pct`) 추가
  - 국장 추천 기본 품질 기준을 강화 (`daytrade_ks_min_live_win_rate` 40, `daytrade_ks_min_validation_win_rate` 50, `daytrade_ks_min_profit_factor` 1.25, `daytrade_ks_min_validation_profit_factor` 1.25)
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 장마감 약세 종목은 강제 정리하고 종가 강도 유지 종목만 오버나잇 허용하는 정책 추가
  - 오버나잇 보유 종목은 시초 `18`분 완화 구간을 두고, 급락(`3.2%`)만 즉시 차단하도록 보강
  - 세션 전환 시 오버나잇 보유 종목의 `buy1_used`/`buy2_used` 플래그를 유지해 다음날 추가 `BUY2` 물타기가 열리지 않도록 수정
  - `carried_overnight` 상태값을 저장해 실거래와 일중 재진입을 구분하도록 수정
  - 누락돼 있던 `_today_close_kst()` / `_today_open_kst()` / `_minutes_since_market_open()` 보조 함수를 추가해 재진입 차단과 시초 완화 로직을 안정화

## 분석 근거
- `data/daytrade/live_state.json`
  - `000720.KS`: 2026-05-11 매수 후 2026-05-12 09:00 `SELL_STOP_LOSS`, 같은 날 재진입 후 재손절
  - `008770.KS`: 2026-05-11 매수 후 2026-05-12 09:11 `SELL_STOP_LOSS`
  - `010140.KS`: 2026-05-12 장초 매수 후 10:21 `SELL_STOP_LOSS`
- `data/daytrade/ks/profile_book.json`
  - 손실 기여 종목 다수가 `stop_loss_pct = 2.0` 학습 프로필을 사용하고 있어, 오버나잇 갭하락이 바로 손절로 연결되고 있었음

## 검증
- `wiz project build --project=main`
- 국장 품질 기준 강화 후에도 추천 가능 후보 4개(`004020`, `105560`, `008770`, `001450`) 유지 확인
- 라이브 상태 API 호출로 빌드 후 응답 정상 확인
