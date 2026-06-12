# 단타 진행 종목 카드 순서를 최초 진입 기준으로 고정

- **ID**: 007
- **날짜**: 2026-05-11
- **유형**: 버그 수정

## 작업 요약
국장 단타 화면의 진행 중 종목 카드가 시세 갱신 시각(`updated_at`) 기준으로 재정렬되면서 위치가 계속 바뀌는 문제를 점검했다.
카드 순서를 최근 갱신 순서가 아니라 최초 진입 시각(`opened_at` → `first_buy_date`) 기준의 안정적인 순서로 고정하고, 프런트 `trackBy`를 추가해 카드 흔들림을 줄였다.

## 원문 요청사항
```text
단타 종목 카드 위치 계속 바뀌는데 보기가 않좋아. 지금 어떤 기준으로 종목을 순서대로 표시하는지 알려주고 왠만하면 고정해줘
```

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 활성 포지션의 최초 진입 시각을 계산하는 `_position_opened_at()` 추가
  - 활성 포지션 정렬 키 `_active_position_sort_key()` 추가
  - `active_positions()` / `active_positions_from_state()`를 `updated_at` 내림차순 대신 최초 진입 시각 오름차순으로 정렬
  - 활성 포지션 응답에 `opened_at`, `first_buy_date` 포함
- `src/app/page.daytrade/api.py`
  - 빠른 활성 포지션 스냅샷도 동일한 안정 정렬 키를 사용하도록 변경
- `src/app/page.daytrade/view.ts`
  - 카드 DOM 재사용을 위한 `trackByPositionCard()` 추가
- `src/app/page.daytrade/view.pug`
  - 진행 종목 카드 반복 렌더링에 `trackBy` 적용
