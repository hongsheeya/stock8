# 단타 수동 판매가, 요청시드 수정, KIS 실시간 가격, 후보군 확대

- **ID**: 012
- **날짜**: 2026-04-10
- **유형**: 기능 추가 + 성능 개선 + 테스트 확대

## 작업 요약
단타 페이지에서 사용자가 요청 시드를 직접 수정할 수 있도록 UI를 추가하고, 보유 포지션에 대해 사용자 지정 판매가를 입력/저장할 수 있도록 구현했다. 실시간 가격은 기존 yfinance 마지막 분봉값 대신 KIS 국내주식 현재가 API를 우선 사용하도록 변경하여 체감 반응 속도를 높였다. 또한 변동성 우선 추천 후보군을 대폭 확대하고, 추가 백테스트를 통해 상위 후보 성능을 검증했다.

## 변경 파일 목록

### KIS API
- `src/portal/trading/model/struct/kis_api.py`
  - `get_domestic_current_price()` 추가
  - 국내주식 현재가를 KIS 시세 API로 직접 조회 가능하게 확장

### 단타 라이브 엔진
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `manual_sell_target_price` 상태 추가
  - `update_trade_settings()` 추가
  - 라이브 스냅샷에서 KIS 국내 현재가 우선 사용
  - 사용자 지정 판매가 도달 시 `SELL_MANUAL` 우선 시그널 지원

### 단타 추천 엔진
- `src/portal/trading/model/struct/daytrade.py`
  - 변동성 높은 국내 종목 후보군 대폭 확대
  - 한화에어로스페이스, HD현대일렉트릭, 포스코퓨처엠, 알테오젠, 레인보우로보틱스 등 추가

### API
- `src/app/page.daytrade/api.py`
  - `update_trade_settings()` 신규 API 추가
  - 차트 응답에 `manual_sell` 트리거, 사용자 지정 판매가 청산 계획 포함

### UI
- `src/app/page.daytrade/view.ts`
  - 요청시드 적용 버튼, 자동 3초 새로고침, 수동 판매가 저장/해제 로직 추가
  - KIS 실시간/지연값 표시 라벨 추가
- `src/app/page.daytrade/view.pug`
  - 요청시드 입력 UI 추가
  - 사용자 지정 판매가 입력/저장/해제 UI 추가
  - 차트 상단에 실시간 가격 소스 표시

## 추가 테스트
- `recommend(force=true, seed=7000000)` 실행: 상위 추천 `포스코퓨처엠`, 평균 일중 변동폭 4.1075%
- `train_symbol(seed=7000000)` 추가 검증:
  - 포스코퓨처엠: 수익률 0.2714%, 승률 80%, 점수 11.4714
  - 두산에너빌리티: 수익률 0.1786%, 승률 80%, 점수 11.3786
  - 현대차: 수익률 0.1893%, 승률 60%, 점수 8.4893
