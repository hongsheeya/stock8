# 국장 품질 가드 강화, 미장 전략 분산, 단타 초기 렌더 경량화

- **ID**: 002
- **날짜**: 2026-05-08
- **유형**: 버그 수정

## 작업 요약
국장 단타 추천이 검증 승률이 낮은 후보를 상위로 고르던 문제를 수정하고, 미장 자동매매가 `us_premarket` 한 전략에만 쏠려 장 상황에 따라 거래가 멈추던 구조를 완화했다. 또한 국장 단타 페이지 초기 로딩에서 부트스트랩 단계에 무거운 `signal_status`/`chart_data` 호출이 겹치던 부분을 분리해 첫 렌더를 빠르게 만들었고, 기존 학습 결과를 기준으로 국장 기본 잭팟 익절값을 2.0%에서 1.5%로 조정했다.

## 원문 요청사항
```text
아니 ㅅㅂ 지금 미장은 거래가 안되고 있고 국장이 승률 너무 낮다니까? 그리고 랜더링 시간이 너무 오래 걸려. 원인 좀 찾아서 다 해결 좀 해봐. 그리고 잭팟 2퍼는 너무 거래가 잘 안돼. 기존 데이터 학습해서 몇퍼에서 파는게 좋을지 분석해봐
```

## 변경 파일 목록

### 추천/학습 로직
- `src/portal/trading/model/struct/daytrade.py`
  - 추천 캐시 키에 `selection_version`을 추가해 기존 저품질 추천 캐시를 무효화.
  - 국장 추천에도 검증 수익률, 검증 승률, 거래 빈도, 과최적화, MDD 기준을 적용.
  - 국장/미장 모두 `trade_ready` 기반으로 상위 후보를 선택하도록 통일.
  - 국장 기본 `jackpot_take_profit_pct`를 1.5로 조정.
- `build/src/model/portal/trading/struct/daytrade.py`
- `bundle/src/model/portal/trading/struct/daytrade.py`

### 자동매매 엔진
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 미장 자동 후보 정렬 후 전략별 상위 후보를 먼저 섞어 넣어 `us_premarket` 편중을 줄임.
- `build/src/model/portal/trading/struct/daytrade_engine.py`
- `bundle/src/model/portal/trading/struct/daytrade_engine.py`

### 국장 단타 초기 로딩
- `src/app/page.daytrade/api.py`
  - 부트스트랩에서 초기 `signal_status`/`plan` 계산과 중복 추천 재조회 제거.
- `src/app/page.daytrade/view.ts`
  - 첫 렌더 이후 백그라운드에서 `chart_data` 또는 `live_status`를 로드하도록 변경.
- `build/src/app/page.daytrade/api.py`
- `build/src/app/page.daytrade/page.daytrade.component.ts`
- `bundle/src/app/page.daytrade/api.py`

### 분석 근거
- `data/daytrade/ks/profile_book.json`
  - 기존 학습 결과 집계 기준 `jackpot_take_profit_pct` 1.5가 2.0보다 거래 빈도와 검증 수익률 균형이 더 양호함을 확인.
- `data/daytrade/ks/recommendation.json`
  - 새 국장 품질 기준을 대입하면 `008770`, `105560`, `010140` 정도만 통과하고 기존 선택 `112610`은 검증 승률 부족으로 탈락함을 확인.
- `data/daytrade/runtime_logs_us.json`
  - 최근 미장 로그가 거의 전부 `us_premarket` 단일 전략에 묶여 있어 장 상황이 바뀌면 거래가 멈추는 편중을 확인.
