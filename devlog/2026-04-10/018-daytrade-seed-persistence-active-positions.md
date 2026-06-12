# 단타 시드 유지 및 진행 종목 표시 개선

- **ID**: 018
- **날짜**: 2026-04-10
- **유형**: 버그 수정

## 작업 요약
`page.daytrade`의 TypeScript 오류 2개를 모듈 선언 파일로 정리했고, 요청 시드를 브라우저 저장소에 유지하도록 바꿔 새로고침 후에도 초기화되지 않게 수정했다. 또한 사용자가 실제로 매수해 진행 중인 단타 종목을 별도 패널로 보여주고 바로 선택할 수 있도록 라이브 상태 집계를 추가했다.

## 변경 파일 목록
- `src/types/wiz-modules.d.ts` — `@angular/core`, `@wiz/libs/portal/season/service` 최소 선언 추가
- `src/app/page.daytrade/view.ts` — 요청 시드 localStorage 유지, 진행 종목 상태 추가
- `src/app/page.daytrade/view.pug` — 진행 중인 내 단타 종목 패널 추가
- `src/app/page.daytrade/api.py` — `active_positions` 응답 추가
- `src/portal/trading/model/struct/daytrade_engine.py` — 진행 중 보유 종목 목록 집계 추가
