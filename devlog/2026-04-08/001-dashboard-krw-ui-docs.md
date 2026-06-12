# KRW 매수가능액 반영, 대시보드 시작 UI 추가, 무한매수법 문서 최신화

- **ID**: 001
- **날짜**: 2026-04-08
- **유형**: 기능 추가

## 작업 요약
대시보드의 매수 가능액 계산에 원화 자동환전 가능 금액을 포함하도록 보완했다. 또한 대시보드에서 시작 가능한 종목을 직접 선택하고 즉시 사이클을 시작할 수 있는 UI를 추가했으며, trading 패키지 README에 최신 무한매수법 매수/매도 규칙을 반영했다.

## 변경 파일 목록

### 원화 자동환전 반영
- `src/portal/trading/model/struct/kis_api.py`: 현재잔고/환율 조회 헬퍼, 원화 잔고 조회 메서드 추가
- `src/app/page.dashboard/api.py`: USD 주문가능액 + 원화 환산 금액 합산 로직 및 응답 필드 추가
- `src/portal/trading/model/struct/engine.py`: 계좌 스냅샷 현금 잔고 계산 시 원화 환산 포함
- `src/portal/trading/route/scheduler/controller.py`: 스냅샷 저장 시 원화 환산 포함

### 대시보드 제어 UI
- `src/app/page.dashboard/view.ts`: 선택 종목 상태, 시작 액션, KRW 표시용 상태값/포맷터 추가
- `src/app/page.dashboard/view.pug`: 매수 가능액 breakdown, 종목 선택 버튼/드롭다운, 매매 시작 버튼 추가
- `src/portal/trading/libs/i18n.ts`: 대시보드/엔진 제어 관련 다국어 문구 추가

### 문서 최신화
- `src/portal/trading/README.md`: 최신 무한매수법 규칙, 분할매도/폭락장 추가매입, 대시보드 수동 제어 설명 추가

### 검증
- WIZ 프로젝트 일반 빌드 성공 (`clean: false`)
- 변경 파일 전체 에러 점검 완료
