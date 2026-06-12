# 단타 수동 즉시 매도 버튼 및 청산 UX 보강

- **ID**: 002
- **날짜**: 2026-04-13
- **유형**: UX 개선 + 기능 추가

## 작업 요약
`/daytrade` 보유 포지션 카드와 시그널 패널에 수동 즉시 매도 버튼을 추가했다. 사용자는 시그널이 없어도 현재 선택한 보유 종목을 확인 모달을 거쳐 즉시 시장가 매도할 수 있으며, 자동청산 감시 상태와 마지막 감시 결과도 함께 확인할 수 있게 했다.

## 변경 파일 목록
- `src/app/page.daytrade/view.ts`
  - `manualSellPosition()` 추가
  - 자동청산 감시 상태 getter 및 수동 매도 가능 상태 계산 추가
- `src/app/page.daytrade/view.pug`
  - 보유 포지션 영역에 `보유분 즉시 매도` 버튼 추가
  - 자동청산 감시 상태(ARMED/IDLE), 목표 가격, 마지막 상태 문구 표시
  - HOLD 상태에서도 수동 즉시 매도 버튼 노출
- `src/app/page.daytrade/api.py`
  - `manual_sell()` API 추가
- `src/portal/trading/model/struct/daytrade_engine.py`
  - `manual_sell()` 구현 및 수동 청산 로그 기록 추가
- `.github/custom/daytrade-usage.md`
  - 수동 종료 흐름과 즉시 매도 버튼 설명 추가
