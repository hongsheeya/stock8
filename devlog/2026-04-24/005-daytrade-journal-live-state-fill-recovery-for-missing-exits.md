# 단타 일지 live_state 체결 복원 보강

- **ID**: 005
- **날짜**: 2026-04-24
- **유형**: 버그 수정

## 작업 요약
포스코인터내셔널(047050) 사례를 추가 추적한 결과, 사전예약 지정가 매도 체결은 live_state의 `last_exit_*` 필드와 `orders` 목록에는 남아 있었지만, 이미 지나간 체결은 코드 수정 이후에도 로컬 `trade_log`에 소급 저장되지 않아 오늘 일지에서 여전히 빠질 수 있었다.

이에 오늘 일지의 빠른 요약 경로에서 KIS/로컬 로그에 없는 체결이라도 live_state에 `체결` 흔적이 남아 있으면 synthetic SELL row로 복원하도록 추가 보정했다. 덕분에 이미 누락된 예약매도 체결도 오늘 일지에서 다시 보이게 정리했다.

## 변경 파일 목록
### 일지 API
- `src/app/page.daytrade/api.py`
  - live_state의 `last_exit_action`, `last_exit_order_no`, `last_exit_reason`, `orders`를 이용해 누락된 오늘 체결 SELL row 복원 추가

### 검증
- 일반 빌드 수행 완료
