# 거래이력 화이트모드 색상 개선 및 LOC 예약매수 예산 소진 처리 보강

- **ID**: 015
- **날짜**: 2026-05-28
- **유형**: 버그 수정

## 작업 요약
화이트 모드의 거래이력 화면이 다크 테마용 회색 팔레트에 끌려가던 문제를 제거하고, 테마 변수 기반의 대비/표면색 체계로 다시 정리했다.
또한 미국 LOC 예약매수에서 이미 접수된 예약주문과 당일 예약금 소진 상태를 구분하지 못해 같은 날 반복 오류를 쌓던 문제를 보완해, 중복 예약은 `already_scheduled`, 예산 소진은 `skipped`로 처리하도록 수정했다.

## 원문 요청사항
```text
ㅅㅂ 화이트 모드일때 거래이력 색상 회색 겁나 구려. 색 조합 좀 제대로 해
LOC 매수 예약 실패: 실제 해외 주문가능수량/금액이 부족합니다 이건 또 왜 계속 뜨는데. 이것때문에 미장 단타랑 무한매수가 안되는거잖아. 좀 원인 좀 찾아서 해결방안 구상하고 고쳐봐
```

## 변경 파일 목록
### 프론트엔드
- `src/app/page.history/view.scss`
  - 거래이력 전용 팔레트를 다크/화이트 공용 CSS 변수 구조로 재작성
  - 화이트 모드에서 `text-slate-*`, 카드/테이블 표면색, 필터 버튼, 입력창 대비를 개선
  - 기존 바이낸스 다크 전용 강제 회색/검정 오버라이드를 제거하고 테마별 가독성을 복원

### 백엔드
- `src/portal/trading/model/struct/engine.py`
  - KIS 예약주문 목록을 조회해 동일 종목의 기존 BUY 예약을 `already_scheduled`로 처리
  - 이미 접수된 당일 예약금(`reserved_today`)을 고려해 추가 예약 가능 금액을 계산
  - 예약금이 이미 소진된 경우 하드 에러 대신 `LOC_BUY_SKIPPED` 로그와 `skipped` 결과로 분류
  - 자동환전 시도 허용 시 `estimated_amount` 기반으로 예약매수를 계획할 수 있도록 보강

### 테스트
- `tests/test_infinitebuy_loc_schedule_regressions.py`
  - 이미 예약된 주문이 있을 때 중복 주문 대신 `already_scheduled`/`skipped`로 처리되는 회귀 테스트 추가
  - 실제 주문가능금액이 0이어도 자동환전 추정 예산으로 예약매수가 가능한 경로 회귀 테스트 추가

## 검증
- `python -m unittest tests.test_infinitebuy_loc_schedule_regressions`
