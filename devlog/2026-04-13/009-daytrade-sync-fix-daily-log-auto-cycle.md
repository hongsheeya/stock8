# 단타 브로커 동기화 수정 / 당일 거래 일지 / 자동매매 즉시 실행

- **ID**: 009
- **날짜**: 2026-04-13
- **유형**: 버그 수정 / 기능 추가

## 작업 요약
1. `_sync_broker_positions()` — 브로커에 없는 종목을 로컬 state에서 qty=0으로 자동 정리 (외부 매도 후 미반영 문제 해결)
2. `execute_live()` — 전량 매도 후 buy1_used/buy2_used 초기화 (당일 재진입 허용)
3. `daily_trade_summary()` — 당일 단타 거래 로그·손익 집계 메서드 추가
4. `page.daytrade/api.py` — daily_log(), run_auto_cycle() 엔드포인트 추가
5. `view.ts/view.pug` — "오늘 일지" 버튼 + 당일 거래 내역/손익 패널 구현
6. `view.pug` — "지금 자동매매 실행" 버튼 + 결과 표시 구현

## 변경 파일 목록

### src/portal/trading/model/struct/daytrade_engine.py
- `_sync_broker_positions()`: 브로커 보유종목 기반 상태 정리 + 미보유 종목 qty→0 초기화
- `execute_live()`: 전량 매도 시 buy1_used/buy2_used = False 리셋
- `daily_trade_summary()`: 당일 DT_ 거래 로그 조회 + 손익 집계

### src/app/page.daytrade/api.py
- `daily_log()`: 당일 거래 일지 API
- `run_auto_cycle()`: 자동매매 즉시 실행 API

### src/app/page.daytrade/view.ts
- 상태 변수: `showDailyLog`, `dailyLog`, `dailyLogLoading`, `autoRunning`, `autoCycleResult`
- 메서드: `toggleDailyLog()`, `loadDailyLog()`, `runAutoCycle()`
- getter: `dailyLogDate`, `dailyPnlClass`, `autoCycleResultItems`

### src/app/page.daytrade/view.pug
- 헤더에 "📋 오늘 일지" 토글 버튼 추가
- 일지 패널: 거래횟수/매수매도/실현손익/평가손익/총손익/손실제한 표시
- 종목별 요약 + 거래 로그 표 (시간/종류/종목/수량·가격/사유)
- 시그널 패널에 "지금 자동매매 실행" 버튼 + 결과 목록 표시
