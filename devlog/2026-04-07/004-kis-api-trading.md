# 한국투자증권 API 연동 - 해외주식 시세/주문/잔고

- **ID**: 004
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
한국투자증권 Open API의 해외주식 관련 8개 핵심 API를 kis_api.py에 구현했다.

## 변경 파일 목록
- `portal/trading/model/struct/kis_api.py`: 8개 API 메서드 추가
  - `get_current_price()`: 현재가 조회
  - `get_daily_prices()`: 기간별 시세 (일봉)
  - `buy_order()`: 매수 주문 (시장가/LOC/지정가)
  - `sell_order()`: 매도 주문
  - `get_balance()`: 잔고 조회 (보유종목 + 예수금)
  - `get_order_history()`: 체결/미체결 내역
  - `get_buying_power()`: 주문 가능 금액
  - `get_exchange_rate()`: USD/KRW 환율
