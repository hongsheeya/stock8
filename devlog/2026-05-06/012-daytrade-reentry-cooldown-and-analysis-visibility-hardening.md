# 단타 재진입 쿨다운 및 종목 분석 차트 상시 표시·degraded fallback 보강

- **ID**: 012
- **날짜**: 2026-05-06
- **유형**: 버그 수정

## 작업 요약
단타 엔진에 최근 매도 이후 재진입 쿨다운을 추가해 손절/수동매도 직후 즉시 재매수되는 흐름을 막았다.
종목 분석 API는 봉 데이터나 feature snapshot 로드 실패 시에도 400으로 사라지지 않도록 degraded fallback 응답을 반환하게 보강했고, 프런트는 차트를 기본 표시하며 degraded 응답에서도 기존 차트 상태를 유지하도록 수정했다.

## 원문 요청사항
```text
1. 아니 대체 66700원에 팔고 66800원에 다시 들어가는거는 왜 그러는거야? 왠만하면 손해볼수밖에 없을텐데?
2. 종목 분석 좀 오류 너무 많이 나잖아. 왜 또 안보이는건데. 항상 보이게 해두라고. 최적화도 제대로 해놔
```

## 변경 파일 목록
### 엔진 재진입 쿨다운
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 최근 매도 시각 파싱 헬퍼 추가
  - `SELL_*` 이후 재진입 쿨다운 계산 로직 추가
  - `BUY1`, `BUY2` 진입 전에 쿨다운 활성 여부를 검사하도록 수정
  - HOLD 사유에 재진입 쿨다운 남은 시간을 표시
- `build/src/model/portal/trading/struct/daytrade_engine.py`
  - 위와 동일한 런타임 반영 패치 적용
- `bundle/src/model/portal/trading/struct/daytrade_engine.py`
  - 위와 동일한 런타임 반영 패치 적용

### 분석 API degraded fallback
- `src/app/page.daytrade/api.py`
  - `chart_data()`가 봉 데이터/feature snapshot 로드 실패 시에도 degraded 응답을 반환하도록 수정
  - fallback 시 `signal_status()` 기반으로 트리거/플랜을 다시 구성
  - `active_positions`, 전략 메타데이터 응답을 안전 가드와 함께 반환
- `build/src/app/page.daytrade/api.py`
  - 위와 동일한 런타임 반영 패치 적용
- `bundle/src/app/page.daytrade/api.py`
  - 위와 동일한 런타임 반영 패치 적용

### 프런트 차트 상시 표시
- `src/app/page.daytrade/view.ts`
  - 차트를 기본 표시 상태로 변경
  - 부트스트랩 완료 후 차트 데이터를 즉시 로드하도록 수정
  - degraded 응답에서 빈 봉 데이터가 와도 기존 차트 상태를 유지하도록 보강
  - degraded 메시지를 UI 오류 메시지에 반영
