# 단타 거래일지 기준 매수가 복원 및 체결 단위 분리

- **ID**: 004
- **날짜**: 2026-04-16
- **유형**: 기능 추가

## 작업 요약
오늘 거래일지를 당일 로그만 기준으로 계산하던 흐름을 확장해, 전일 매수 후 금일 매도한 물량도 FIFO 기준 매수 원가를 복원하도록 정리했다.
또한 로그 행마다 체결 회차 번호, 매칭된 매수 금액, 이월 수량, lot 분해 정보를 함께 내려주고 화면에서도 실제 체결 단위에 가깝게 보이도록 표시를 세분화했다.

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `daily_trade_summary()`가 최근 로그 전체를 ASC로 읽고 FIFO 매수 큐를 재구성하도록 수정
  - 당일 매도 로그에 `trade_no`, `matched_qty`, `matched_buy_amount`, `carry_over_qty`, `buy_lots`, `is_synthetic` 필드 추가
  - 전일 매수분이 포함된 매도 로그의 평균 매수가/손익 계산 근거를 복원

### 프론트엔드
- `src/app/page.daytrade/view.pug`
  - 거래 로그 행에 회차 번호, 기준 매수 금액, 전일보유 표시, synthetic 배지, lot 분해 내역 노출 추가
  - Pug 문법 충돌 없이 거래 번호를 렌더링하도록 템플릿 구조 보정
