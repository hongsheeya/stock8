# 대시보드 미리보기 연결 복구 및 무한매수 17:40 LOC 예약매수 자동화

- **ID**: 007
- **날짜**: 2026-05-12
- **유형**: 버그 수정

## 작업 요약
대시보드의 KIS 연결 상태가 일시 실패 후 너무 오래 실패로 캐시되어 오늘 매매 예정 프리뷰가 새로고침 전까지 API 미연결처럼 보이던 문제를 줄였다.
동시에 무한매수 17:40 자동예약이 기존에는 LOC 예약매도만 처리하던 한계를 보완해, 2회차 이후 LOC 예약매수도 자동 접수되도록 경로를 추가하고 대시보드 폴링에서 due tick을 수행하도록 연결했다.

## 원문 요청사항
```text
왜 무한매수 오늘매매 예정 사이클 새로고침 안하면 API연결 실패하는거야? 그리고 왜 예약매수 안거는건데. 오후 5시40분에 자동으로 진행되도록 설정했잖아
```

## 변경 파일 목록
- `src/app/page.dashboard/api.py`
  - KIS 연결 상태 캐시를 성공/실패 TTL로 분리해 일시 실패가 오래 고착되지 않도록 조정
  - `run_due_automation()` API를 추가해 대시보드 폴링 시 17:40 이후 LOC 자동예약 due 작업을 수행하도록 추가
- `src/app/page.dashboard/view.ts`
  - 대시보드 로드/폴링 시 `run_due_automation()`을 먼저 호출하도록 연결
- `src/portal/trading/model/struct/engine.py`
  - `schedule_loc_buys()`를 추가해 활성 무한매수 사이클의 2회차 이후 LOC 예약매수를 자동 접수하도록 구현
- `src/portal/trading/route/scheduler/controller.py`
  - `schedule_loc_buy_if_due()`와 `loc-buy` 라우트를 추가
  - 스케줄러 `run` 경로에서 17:40 이후 자동 예약매수와 예약매도를 함께 처리하도록 확장
- `src/app/page.settings/view.pug`
  - 설정 문구를 LOC 예약매수/예약매도 동작에 맞게 정정
