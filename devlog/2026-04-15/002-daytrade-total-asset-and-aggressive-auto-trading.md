# 단타 총자산 합산 정정 및 공격적 자동매매 강화

- **ID**: 002
- **날짜**: 2026-04-15
- **유형**: 버그 수정 / 기능 개선

## 작업 요약
단타 화면의 자산 표시 기준을 정리하여 총자산을 예수금, 유가평가금액, 외화평가금액, 청약자예수금의 합으로 계산하도록 수정했습니다. 동시에 자동매매가 너무 보수적으로 동작하던 문제를 완화하기 위해 기본 진입 허들, 거래량 조건, 자동매매 대상 수, 워커 실행 주기를 공격적으로 조정했습니다.

## 변경 파일 목록

### 1. 백엔드
- **[src/portal/trading/model/struct/daytrade_engine.py](project/main/src/portal/trading/model/struct/daytrade_engine.py)**
  - 총자산 구성요소(`deposit_krw`, `domestic_eval_krw`, `foreign_eval_krw`, `subscription_deposit_krw`) 계산 추가
  - 총자산(`total_asset_krw`) 계산 및 예산 상태 응답에 포함
  - 자동매매 기본 후보 수 상향 및 `fee_buffer_ok` 필터 제거
  - 자동매매 결과에 신호 설명/현재가/트리거가 포함
- **[src/portal/trading/model/struct/daytrade.py](project/main/src/portal/trading/model/struct/daytrade.py)**
  - 기본 진입 허들 완화 (`buy_trigger_1_pct`, `buy_trigger_2_pct`, `rsi_entry`, `breakout_volume_ratio`, `dominance_threshold`)
  - 백테스트/최적화 그리드 조건 완화
- **[src/portal/trading/model/struct.py](project/main/src/portal/trading/model/struct.py)**
  - 자동매매 워커 기본 주기를 60초 → 15초로 조정

### 2. 프론트엔드
- **[src/app/page.daytrade/view.ts](project/main/src/app/page.daytrade/view.ts)**
  - 총자산 getter 추가
- **[src/app/page.daytrade/view.pug](project/main/src/app/page.daytrade/view.pug)**
  - 총자산/예수금/유가평가금액/외화평가금액/청약자예수금 표시 추가

## 검증
- 일반 빌드 성공 (`clean: false`)
- 변경 파일 오류 없음
