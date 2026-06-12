# KRW 원화 잔고 표시 문제 재점검

- **ID**: 008
- **날짜**: 2026-04-08
- **유형**: 버그 수정

## 작업 요약
dashboard/api.py의 KIS API 호출 실패 시 무음 실패(except pass) → 로그 기록으로 변경. Mock 데이터에 누락되어 있던 krw_balance, exchange_rate 등 필드 추가.

## 변경 파일 목록
- `src/app/page.dashboard/api.py`: except pass → 로그 기록, traceback 포함. Mock 데이터에 krw_balance, krw_buying_power_usd, usd_buying_power 추가
