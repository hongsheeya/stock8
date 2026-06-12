# 미장 단타 UI를 국장 단타 수준으로 통일

- **ID**: 015
- **날짜**: 2026-04-29
- **유형**: 기능 추가

## 작업 요약
미장 단타 화면에 국장과 유사한 운영 패널(자동매매 상태, 일지 요약, 실행 검증)을 추가했다.
미장 자동매매 ON/OFF, 자동순환 점검, 일지 조회, 런타임 검증을 화면에서 즉시 실행할 수 있도록 UX를 정리했다.

## 변경 파일 목록
- `src/app/page.daytrade/view.ts`
  - US 전용 상태 변수 추가(`usAutoEnabled`, `usDailyLog`, `usRuntimeVerify` 등)
  - US 액션 추가
    - `usLoadAutoStatus()`
    - `usToggleAuto()`
    - `usRunAutoCycle()`
    - `usLoadDailyLog()`
    - `usVerifyRuntime()`
  - `usBootstrap()` 후 상태/일지/검증 자동 로드
  - 배지용 getter 추가: `usSignalBadgeClass`, `usDailyWinRate`
- `src/app/page.daytrade/view.pug`
  - 미장 제어 버튼군 추가 (자동매매 토글/자동순환/일지/실행검증)
  - 미장 자동매매 상태 카드 추가
  - 미장 오늘 일지 요약 카드 추가
  - 미장 실행 검증 결과 카드 추가
