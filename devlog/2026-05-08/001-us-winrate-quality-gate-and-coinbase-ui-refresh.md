# 미장 승률 저하 분석 기반 품질 가드 강화 및 화면 리프레시

- **ID**: 001
- **날짜**: 2026-05-08
- **유형**: 버그 수정

## 작업 요약
미장 랭킹·추천 로직을 점검한 결과, 일부 전략이 낮은 승률과 낮은 거래 빈도에도 검증 수익률만으로 실거래 후보로 남아 있던 문제를 확인했다.
이에 미장 추천 품질 가드에 검증 승률·거래 빈도 기준을 추가하고, 자동 후보 정렬이 검증 중심 점수를 우선하도록 조정했다. 동시에 미장 화면을 Coinbase 계열의 차분한 카드형 UI로 재구성하고 승률 저하 원인 요약을 전면 배치했다.

## 원문 요청사항
```text
디자인 이걸 참고해서 진행해. 그리고 요즘 승률 너무 안좋은데 분석해봐. 진짜 말도 안되게 안좋아

계속 진행해
```

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct/daytrade.py`
  - 미장 추천 `trade_ready` 판단에 실거래 승률·검증 승률·거래 빈도 기준을 추가했다.
  - 추천 row에 `avg_trades`, `validation_avg_trades`를 기록하도록 확장했다.
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 자동 후보 정렬 기준을 `score` 중심에서 `trade_ready`, `rank_score`, 검증 지표 중심으로 변경했다.
- `src/app/page.daytrade.us/api.py`
  - 랭킹 품질 게이트에 검증 승률·거래 빈도 기준을 추가했다.
  - 랭킹 응답에 거래 빈도 필드와 승률 저하 분석 요약을 포함했다.

### 프론트엔드
- `src/app/page.daytrade.us/view.ts`
  - 승률 저하 분석 요약과 검증 hard fail 목록 접근 getter를 추가했다.
- `src/app/page.daytrade.us/view.html`
  - Coinbase 계열 톤의 다크 히어로 + 화이트 카드 레이아웃으로 재구성했다.
  - 예산, 상태, 랭킹, 전략 설명 영역을 카드형 정보 구조로 정리했다.
  - 승률 저하 원인 요약과 거래 빈도 지표를 상단에 노출했다.

### 검증
- 수정한 5개 파일에 대해 정적 오류 검사를 실행했고 오류 없음으로 확인했다.
- 데이터 점검 결과 최근 `runtime_logs_us.json` 300건이 전부 `HOLD`였고, `data/daytrade/us/latest_training.json` 기준 상위 전략의 최근 10일 평균 승률이 20%, 평균 거래 빈도는 0.4회/day 수준으로 약화된 상태임을 확인했다.
