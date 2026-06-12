# 데이트레이드 수익성 강화 및 사전 예약 매도 시스템 구축

- **ID**: 010
- **날짜**: 2026-04-13
- **유형**: 기능 추가 / 버그 수정 / 리팩토링

## 작업 요약
수수료 손익분기 로직 도입으로 무의미한 매도를 방지하고, 목표가 근처 도달 시 자동으로 지정가 예약을 걸어주는 사전 예약 매도(Pre-order) 시스템을 구축하였습니다. 또한 일지 시스템을 FIFO 방식으로 개편하여 정확한 실질 수익률 확인이 가능하도록 개선하였습니다.

## 변경 파일 목록

### 1. 백엔드 (Python / Engine)
- **[portal/trading/model/struct/kis_api.py](project/main/src/portal/trading/model/struct/kis_api.py)**
    - `cancel_domestic_order`: 지정가 주문 취소 기능 추가
    - `get_domestic_fills_today`: 당일 체결 내역 상세 조회 기능 추가
- **[portal/trading/model/struct/daytrade_engine.py](project/main/src/portal/trading/model/struct/daytrade_engine.py)**
    - **수수료 로직**: 매수 0.015%, 매도 0.195% (거래세 포함) 적용 및 손익분기(1.0021배) 미달 시 매도 보류(HOLD) 처리
    - **사전 예약 시스템**: `PRE_SELL_JACKPOT` 액션 도입. 잭팟가 0.5% 이내 진입 시 자동 지정가 예약 주문 실행
    - **체결 동기화**: `_sync_pending_sell` 메서드로 예약 주문의 체결 여부 실시간 감시 및 가격 이탈 시 자동 취소
    - **주문 로그 개선**: 매도 시 "평단→매도가 | 손익 | 수수료 | 순손익"을 상세 기록하도록 변경
    - **버그 수정**: 매도 실행 시 `_pre_sell_avg`를 사전 캡처하여 평단가 초기화 후에도 정확한 P&L 로그가 남도록 수정
- **[app/page.daytrade/api.py](project/main/src/app/page.daytrade/api.py)**
    - `toggle_ignore_reserve`: 무한매수 예약금 무시 옵션 토글 API 추가
    - `live_status`: 플랜 데이터에 `stop_loss_pct`, `auto_stop_price` 필드 추가

### 2. 프론트엔드 (Angular / UI)
- **[app/page.daytrade/view.ts](project/main/src/app/page.daytrade/view.ts)**
    - `ignoreReserve`, `showLogList` 상태 관리 변수 추가
    - 일지 FIFO 계산 로직 구현 (매수-매도 매칭 방식)
    - 실시간 데이터 갱신 시 `service.render()` 누락 부분 보관
- **[app/page.daytrade/view.pug](project/main/src/app/page.daytrade/view.pug)**
    - **무한매수 카드**: 차감/무시 토글 버튼 UI 추가
    - **종목 요약**: 종목명 표시 및 수수료/수익 현황 가시성 확보
    - **거래 일지**: 로그 목록 접기/펼치기 토글 UI 및 순손익/수수료 상세 내역 표시
- **[app/page.daytrade/view.scss](project/main/src/app/page.daytrade/view.scss)**
    - 로그 목록 애니메이션 및 가독성 개선 스타일 적용

### 3. 기타
- **[config/database.py](project/main/config/database.py)**
    - `daytrade_ignore_reserve` 설정값 기본값 추가 및 관리
