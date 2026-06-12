# 대시보드 자산 정합 및 미장 공유 시드 가시화 보정

- **ID**: 014
- **날짜**: 2026-05-11
- **유형**: 버그 수정

## 작업 요약
대시보드 요약 카드가 서로 다른 기준의 값을 섞어 보여주던 문제를 정리해, 현금성 자산 + 포트폴리오 평가액 = 총 자산이 항상 맞도록 보정했다.
미장 단타 화면은 공유 시드 사용량을 별도 노출하고, 스냅샷 API에서 교차 시장 사용 시드를 강제로 보강해 국장 포지션에 묶인 시드가 즉시 반영되도록 수정했다.

## 원문 요청사항
```text
아니 ㅅㅂ 지금 국장 종목에 시드 묶여있어서 미장에 쓸 시드가 없으니까 남은 시드 제대로 표시하라고.
그리고 매수 가능액이랑 포트폴리오 평가액의 합이 총 자산이랑 안맞잖아. 저 중 하나는 무조건 틀린거잖아.
그리고 자산추이 그래프 대충 그리지 말고 실제 값에 의거해서 그래프 제대로 만들어
```

## 변경 파일 목록
- **미장 단타 API/UI**
  - `src/app/page.daytrade.us/api.py`
    - `budget_status` 응답에 `market_used_seed_krw`, `cross_market_used_seed_krw`, `used_seed_krw`를 항상 보강하도록 처리
    - `us_snapshot`이 검증 캐시와 별개로 최신 공유 시드 기준 예산을 내려주도록 수정
  - `src/app/page.daytrade.us/view.ts`
    - 공유 사용 시드, 총 계획 시드, 시드 잠김 여부 getter 추가
  - `src/app/page.daytrade.us/view.html`
    - 남은 시드 카드에 총 계획 시드/공유 사용 시드 표시 추가
    - 국장 포함 기존 포지션이 시드를 모두 점유한 경우 경고 문구 노출

- **대시보드 개요/차트**
  - `src/app/page.dashboard/api.py`
    - 현금성 자산을 총자산-포트폴리오 평가액 기준으로 정렬하고 실주문 가능액은 별도 필드로 분리
    - `profit_summary` 자산추이를 DB 스냅샷 + 오늘 실계좌 총자산만으로 구성하도록 변경
    - 차트 최신 총자산도 overview와 같은 daytrade 엔진 총자산 기준을 사용하도록 통일
  - `src/app/page.dashboard/view.ts`
    - 대시보드 카드에 현금성 자산/실주문 가능액을 반영
    - 자산추이 그래프의 마지막 점을 프론트에서 임의 보정하던 로직 제거
  - `src/app/page.dashboard/view.pug`
    - 요약 카드 상세 문구와 실주문 가능액 노출 추가
    - 자산추이 카드가 그래프의 최신 실데이터를 직접 표시하도록 수정

- **다국어 문구**
  - `src/portal/trading/libs/i18n.ts`
    - 현금성 자산 설명과 실주문 가능액 문구 추가

## 검증
- `wiz project build --project=main`
- 로컬 API 확인
  - `page.dashboard/overview` → `cash_asset_krw + portfolio_value == total_asset` 확인
  - `page.dashboard/profit_summary` → 오늘 날짜 실총자산 포함 확인
  - `page.daytrade.us/us_snapshot` → `cross_market_used_seed_krw` 노출 및 `remaining_seed_krw` 재계산 확인
