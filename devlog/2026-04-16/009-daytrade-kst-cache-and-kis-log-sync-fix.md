# 단타 KST 시간 통일, 추천 캐시 병목 완화, KIS 거래일지 보강

- **ID**: 009
- **날짜**: 2026-04-16
- **유형**: 버그 수정

## 작업 요약
단타 엔진과 추천 캐시가 UTC 기준 시간과 KST 기준 시간이 섞여 동작하면서 장 시간 판단, 추천 캐시 날짜 비교, 운영 로그 시간이 서로 어긋나던 문제를 정리했다.
또한 추천 가격 상한이 호출마다 너무 세밀하게 바뀌어 재훈련이 과도하게 발생하던 병목을 줄이고, 거래일지는 KIS 체결 내역을 조회 기간 이전 lookback까지 확장해 한국투자증권 앱 외부 체결 이력도 FIFO 계산에 반영하도록 보강했다.

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade_engine.py`
  - KST 현재 시각 헬퍼 추가 및 로그/시장시간/쿨다운 계산을 한국 시간 기준으로 통일
  - 추천 실패 시 최신 캐시 fallback 추가, 동일 후보 제외 로그 중복 억제, 가격 상한 버킷화 적용
  - 거래일지 KIS 조회 범위를 lookback까지 확장해 외부 앱 매수/매도 이력 기반 FIFO 복원 보강
- `src/portal/trading/model/struct/daytrade.py`
  - 추천 캐시 저장/조회 시각과 generated_date 비교를 KST 기준으로 수정
- `src/app/page.daytrade/api.py`
  - 추천 가격 상한 계산 보조 함수 추가, bootstrap/live_status/recommend 응답에서 stale 캐시 fallback 허용
  - API 디버그 로그 시각을 KST 기준으로 통일
- `src/app/page.daytrade/view.pug`
  - 종목별 거래 요약의 `~회` 문구를 제거하고 매수/매도 금액 중심 표기로 정리
