# 국장 단타 승률 저하 원인 분석 및 손실 가드 강화

- **ID**: 003
- **날짜**: 2026-05-12
- **유형**: 버그 수정

## 작업 요약
최근 국장 실거래 손실 구간을 `runtime_logs_ks.json`과 `live_state.json` 기준으로 추적한 결과, `vrev` 전략에서 동일 거래일 `SELL_STOP_LOSS` 후 재진입이 반복되며 손실이 누적되는 패턴을 확인했다.
이에 따라 당일 손절 종목 재진입 차단, `vrev` 라이브 진입 preflight 가드, 국장 추천 손익비 품질 필터를 추가해 손실 누적 가능성을 줄였다.

## 원문 요청사항
```text
아니 요즘 승률 왤케 안좋아 원인 좀 찾아서 보완 좀 해. 너무 많이 잃잖아
```

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade.py`
  - 국장 기본 프로필에 `min_live_entry_rsi`, `max_live_vwap_discount_pct`, `stop_reentry_same_day_block` 기본값 추가
  - 국장 추천 품질 가드에 `profit_factor`, `validation_profit_factor` 최소 기준 추가
  - 국장 랭킹 점수에 손익비 가중치를 반영해 취약 후보 우선순위를 낮춤
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `SELL_STOP_LOSS` 발생 종목은 같은 거래일 재진입을 차단하도록 재진입 쿨다운 강화
  - `vrev` 라이브 진입 전 `VWAP` 과이탈·과매도 `RSI`를 점검하는 preflight 가드 추가
  - `BUY1`/`BUY2` 직전 preflight 실패 시 즉시 진입 대신 `HOLD`와 사유를 반환하도록 보강

## 검증
- `wiz project build --project=main`
- 수정 파일 정적 오류 점검 결과 이상 없음
- 최근 데이터 확인 결과 손실 집중 구간은 `000720`, `008770`, `010140`의 `SELL_STOP_LOSS` 반복 패턴이었고, 이번 보강은 해당 유형의 재진입/낙하 추세 진입을 우선 차단한다.
