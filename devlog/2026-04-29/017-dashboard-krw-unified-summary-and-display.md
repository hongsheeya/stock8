# 대시보드 수익현황/자산 KRW 단일 단위 통일

- **ID**: 017
- **날짜**: 2026-04-29
- **유형**: 버그 수정

## 작업 요약
대시보드에서 USD/KRW가 혼합되어 수치가 맞지 않던 문제를 수정했다. `overview`와 `profit_summary`를 KRW 기준으로 통일하고, 화면 표기도 `$` 대신 `₩` 중심으로 변경해 국장 단타 요약과 동일한 단위 체계를 적용했다.

## 변경 파일 목록
- `src/app/page.dashboard/api.py`
  - `overview()`의 `buying_power`, `portfolio_value`, `total_asset`를 KRW로 정규화
  - `profit_summary` 집계 시 무한매수(USD) 값을 환율로 KRW 환산 후 단타(KRW)와 합산
  - 스냅샷 차트 값도 KRW 기준으로 결합
  - 응답에 `currency="KRW"` 필드 추가

- `src/app/page.dashboard/view.pug`
  - 요약 카드/수익현황/자산 추이 금액 표기 `$` → `₩`
  - 금액 포맷을 `formatUSD`에서 `formatKRW`로 교체
  - USD 가능금액 표시도 환율 적용 KRW로 노출
