# 단타 후보별 비진입 사유 및 다음 진입 조건 노출

- **ID**: 008
- **날짜**: 2026-04-15
- **유형**: 기능 추가 / UI 개선

## 작업 요약
자동매매가 가만히 있는 이유를 알 수 있도록, 대기 후보/제외 후보/랭킹 종목에 대해 비진입 사유와 다음 진입 조건을 함께 노출했다. 워커 결과의 배정 시드, BUY1까지 남은 거리, 교체 타깃, 제외 사유를 UI에 연결해 사용자가 정상 대기인지 무의미한 정지인지 구분할 수 있게 했다.

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 자동순환 결과에 `decision_reason`, `allocated_seed`, `remaining_seed_before/after`, 제외 사유 추가
  - `execute_live()` 응답에 `action`, `order_value` 추가

### 프론트엔드
- `src/app/page.daytrade/view.ts`
  - 랭킹/워커 결과를 합쳐 비진입 사유와 다음 행동을 보여주는 helper 추가
- `src/app/page.daytrade/view.pug`
  - 자동매수 대기 설명, 제외 종목 패널, 종목 랭킹 카드에 이유/다음 조건 표시 추가

## 검증
- 빌드 성공 확인
- `live_status` 응답에서 HOLD 사유가 `BUY1 트리거 미도달` 형태로 확인됨
