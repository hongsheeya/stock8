# 국장 단타 브로커 기간손익 동기화 정합 보정

- **ID**: 011
- **날짜**: 2026-05-04
- **유형**: 버그 수정

## 작업 요약
KIS `기간별매매손익현황조회` 값을 직접 조회하는 경로를 추가하고, 국장 단타 일지의 종목별/총 손익 표시가 브로커 집계값을 우선 따르도록 보정했다.
당일 잔여 포지션이 있는 종목도 수수료만 반영된 브로커 손익(`-20`, `-30` 같은 값)이 그대로 내려가도록 API 응답 계산식을 수정했다.

## 원문 요청사항
```text
아니 더 안맞잖아. 아니 뭐가 문젠데. 오늘 매매손익 동양파일 +3189, 포스코인터내셔널 +3188, 삼성중공업 -20, 호텔신라 -9015, 포스코퓨처엠 -30원이야. 그래서 총 -2688원이야. 이 값들 제대로 찾아서 분석하고 앞으로 제대로 동기화 해
```

## 변경 파일 목록
- `src/portal/trading/model/struct/kis_api.py`
  - KIS `inquire-period-trade-profit` 호출용 `get_domestic_period_trade_profit()` 메서드 추가
  - 종목별 손익(`rlzt_pfls`), 수수료, 세금, 합계 손익을 구조화해 반환하도록 구현
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 국내 기간손익 API 결과를 일지 요약에 병합
  - `symbol_summary`를 종목 집계 기준으로 재구성하고 국내 종목은 브로커 손익으로 override
  - `broker_trade_profit`, `broker_trade_profit_cost_total`, `broker_trade_profit_authoritative` 메타데이터 추가
- `src/app/page.daytrade/api.py`
  - 브로커 기간손익이 존재할 때 `daily_log()`의 `realized_profit_net`, `total_pnl`, `total_fee`가 브로커 값을 우선 사용하도록 수정
- `build/src/app/page.daytrade/api.py`
  - 런타임 반영용 동일 수정 적용
- `bundle/src/app/page.daytrade/api.py`
  - 런타임 반영용 동일 수정 적용

## 검증
- KIS `inquire-period-trade-profit` 실조회로 아래 브로커 기준 값 확인
  - 동양파일 `+3189`
  - 포스코인터내셔널 `+3188`
  - 삼성중공업 `-20`
  - 호텔신라 `-9015`
  - 포스코퓨처엠 `-30`
  - 총합 `-2688`
- `python -m py_compile`로 수정한 Python 파일 문법 검증 완료
- 에디터 진단 기준 수정 파일 오류 없음 확인
