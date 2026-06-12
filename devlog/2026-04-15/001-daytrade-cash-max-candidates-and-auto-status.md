# 단타 현금최대가능 기준 적용 및 자동대기 상태 복원

- **ID**: 001
- **날짜**: 2026-04-15
- **유형**: 기능 개선 / UI 개선

## 작업 요약
단타 실주문 예산 기준을 예수금 총액이 아니라 한국투자증권 주문가능금액 기반의 현금최대가능 금액으로 정리하고, 자동추천/자동매매에서 더 많은 후보 종목을 비교할 수 있도록 프리스크리닝/랭킹 개수를 확대하였습니다. 또한 자동매매 상태 패널에 어떤 종목을 대기 중인지, 현재가 대비 얼마 더 내려오면 `BUY1` 진입인지 다시 설명되도록 대기 설명 UI를 복원하였습니다.

## 변경 파일 목록

### 1. 백엔드
- **[src/portal/trading/model/struct/daytrade_engine.py](project/main/src/portal/trading/model/struct/daytrade_engine.py)**
	- 자동매매 후보 수 상한을 확대
	- 현금최대가능(`TTTC8908R`) 기준 실주문 시드 `live_order_seed` 추가
	- 자동매매 결과에 `current_price`, `buy1_trigger`, `signal_reason` 포함
- **[src/portal/trading/model/struct/daytrade.py](project/main/src/portal/trading/model/struct/daytrade.py)**
	- 추천 프리스크리닝/백테스트 대상 개수 확대
	- 랭킹 노출 개수 확대
- **[src/app/page.daytrade/api.py](project/main/src/app/page.daytrade/api.py)**
	- bootstrap/live_status/chart_data/실주문 관련 API가 `live_order_seed`를 사용하도록 정리

### 2. 프론트엔드
- **[src/app/page.daytrade/view.ts](project/main/src/app/page.daytrade/view.ts)**
	- 현금최대가능 표시용 getter 추가
	- 자동매매 마지막 워커 결과를 대기 설명으로 가공하는 helper 추가
	- 저장된 낮은 시드가 현금최대가능 시드를 덮어쓰지 않도록 조정
- **[src/app/page.daytrade/view.pug](project/main/src/app/page.daytrade/view.pug)**
	- 예산 패널을 현금최대가능/실주문 적용 시드 기준으로 수정
	- 자동매매 상태 패널에 `BUY1` 대기 설명, 현재가, 트리거가 복원
	- 추천 안내 문구를 더 넓은 후보군 기준으로 수정

## 검증
- 일반 빌드 성공 (`clean: false`)
- 변경 파일 `get_errors` 확인 결과 오류 없음
