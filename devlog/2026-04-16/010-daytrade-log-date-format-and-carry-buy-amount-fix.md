# 단타 거래일지 날짜 포맷 및 전일 기준매수 금액 보강

- **ID**: 010
- **날짜**: 2026-04-16
- **유형**: 버그 수정

## 작업 요약
거래일지 날짜 응답이 `yyyyMMdd` 형식으로 내려가 HTML date 입력과 충돌하던 문제를 수정해, 선택한 날짜가 정확히 유지되고 과거 날짜 조회가 정상 동작하도록 정리했다.
또한 전일 매수 후 당일 매도한 물량의 기준 매수 금액을 별도 집계 필드로 추가해, 일자별/종목별 요약에서 전일 기준매수 금액까지 함께 확인할 수 있게 보강했다.

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 날짜 compact/display 헬퍼 추가
  - period 요약 출력 날짜를 `yyyy-MM-dd` 형식으로 통일
  - 매도 로그별 `carry_over_buy_amount` 계산 및 총계/종목별 집계 반영
- `src/app/page.daytrade/api.py`
  - daily_log 응답의 `session_date`를 `yyyy-MM-dd`로 보정
  - 선택일이 오늘이 아닌 경우 현재 손익 상태를 섞지 않도록 정리
- `src/app/page.daytrade/view.pug`
  - 선택일 요약 카드에 전일 기준매수 금액 표시 추가
  - 화면 문구를 오늘 기준에서 선택일 기준 표현으로 수정
