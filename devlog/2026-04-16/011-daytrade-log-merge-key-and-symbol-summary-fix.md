# 단타 거래일지 병합 키 및 기간 종목 요약 보정

- **ID**: 011
- **날짜**: 2026-04-16
- **유형**: 버그 수정

## 작업 요약
거래일지 집계가 `order_no` 단일 키로 로컬 로그와 KIS 체결을 병합하면서 서로 다른 매수/매도 건이 덮어써질 수 있던 문제를 정리했다. 날짜·종목·매수/매도 방향까지 포함한 병합 키로 바꿔 누락/수량 왜곡 가능성을 줄였다.
또한 기간 집계 화면에 종목명과 종목별 매수/매도 금액, 순손익이 함께 보이도록 보강했다.

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 거래 action 정규화 및 체결 병합 키 helper 추가
  - 로컬/KIS 거래 병합을 `date+symbol+action+order_no` 기준으로 변경
- `src/portal/trading/model/struct/kis_api.py`
  - KIS 체결 응답에 종목명 필드 포함
- `src/app/page.daytrade/view.pug`
  - 기간 집계에 종목명 및 종목별 매수/매도 금액 표시 추가
