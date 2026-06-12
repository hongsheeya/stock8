# 무한매수 서브페이지 분리 및 대시보드 profit_summary 복구

- **ID**: 004
- **날짜**: 2026-04-28
- **유형**: 기능 추가

## 작업 요약
대시보드에서 무한매수 운영 영역을 별도 서브페이지로 분리할 수 있도록 `page.infinitebuy`를 추가했다. 동시에 `page.dashboard/profit_summary` 500 오류를 수정하고, 무한매수/대시보드 라우트와 주요 API를 재검증했다.

## 변경 파일 목록
### 대시보드/API 안정화
- `src/app/page.dashboard/api.py`: `profit_summary()` 계산을 헬퍼로 분리하고 예외 처리 안정화, logger fallback 추가로 500 오류 제거
- `src/portal/trading/model/struct/daytrade.py`: `recommend()`가 `market` 인자를 수용하도록 보강하여 시장별 자동 추천 갱신 경고 제거

### 무한매수 서브페이지 분리
- `src/app/page.dashboard/view.ts`: `legacyMode` 입력 추가, 일반 대시보드와 무한매수 운영 화면 재사용 가능하도록 분리
- `src/app/page.dashboard/view.pug`: 일반 대시보드에서 요약/바로가기만 노출하고 무한매수 화면은 서브페이지로 이동할 수 있도록 수정
- `src/app/page.infinitebuy/app.json`: `/infinite-buy` 신규 페이지 등록
- `src/app/page.infinitebuy/view.ts`: 무한매수 서브페이지 기본 로직 추가
- `src/app/page.infinitebuy/view.pug`: `wiz-page-dashboard([legacyMode]="true")` 래퍼 페이지 구성
- `src/app/page.infinitebuy/view.scss`: 페이지 host 높이 설정
- `src/app/component.nav.trading/view.pug`: 상단 네비게이션에 무한매수 링크 추가

### 검증
- 일반/클린 빌드 성공
- `page.dashboard/profit_summary`, `page.dashboard/overview`, `page.dashboard/get_watchlist_defaults` 응답 200 확인
- `/infinite-buy` 라우트 응답 200 확인
- 변경 파일 오류 검사 통과
