# 대시보드 초기 렌더·라우팅·체감성능 안정화

- **ID**: 010
- **날짜**: 2026-05-08
- **유형**: 버그 수정

## 작업 요약
대시보드 첫 진입 시 로딩 지연, 일부 네비게이션 버튼 지연 노출, 상호작용 이후에야 UI가 완성되어 보이는 문제를 완화하기 위해 공용 Service의 다중 컴포넌트 초기화 충돌을 보정하고 초기 로드 순서/렌더 빈도를 경량화했다.
또한 라우팅 활성 상태 판별을 Router 이벤트 기반으로 변경해 서브페이지 전환 시 표시 불안정을 줄였다.

## 원문 요청사항
```text
일단 로딩시간이 너무 오래 걸리고 대시보드 처음들어가면 일부 서브페이지 버튼이 안보여. 일부 상호작용해야 페이지가 다 보여. 대체 원인이 뭐야. 지금 계속 라우트도 꼬이는거 같고 이상해. 로딩 시간 좀 최대한 줄이고 싶은데 방법 좀 구상해봐
최대한 다 적용해봐
```

## 변경 파일 목록

### Service/공통 라이브러리
- `src/portal/season/libs/service.ts`
  - 싱글톤 Service에서 `app` 참조가 컴포넌트별로 덮어써지는 문제를 줄이기 위해 다중 앱 레지스트리(`apps`)를 도입.
  - `init()`에서 중복 재초기화 대신 최초 1회 초기화 후 공통 상태를 재사용하도록 보정.
  - `render()`가 등록된 앱들을 순회하며 stale app을 정리하도록 변경.
  - `href()`에 router 탐색 fallback을 추가해 라우팅 누락 시 직접 이동 가능하도록 보강.

- `src/portal/season/libs/util/request.ts`
  - AJAX `timeout: 5000` 추가로 백엔드 응답 지연/정지 시 프런트 무한 대기 방지.

- `src/portal/season/libs/src/auth.ts`
  - 인증 재시도 횟수/백오프를 축소(2회, 200ms)해 초기 진입 지연을 완화.

### Dashboard
- `src/app/page.dashboard/view.ts`
  - `ngOnInit()`에서 수익요약 로드를 첫 페인트 이후 지연 실행(`setTimeout`)으로 전환.
  - 초기 핵심 화면(`overview`) 우선 렌더 후 부가 데이터 로드하도록 순서 조정.
  - 초당 카운트다운에서 매초 전체 렌더를 수행하던 구조를 5초 단위(또는 종료 임박) 렌더로 경량화.

### Navigation/Route
- `src/app/component.nav.trading/view.ts`
  - `location.pathname` 직접 판별 중심에서 `Router` + `NavigationEnd` 구독 기반으로 활성 상태 갱신.
  - 현재 경로 상태(`currentPath`)를 유지해 서브페이지 전환 시 active 표시 지연/오동작 완화.
  - 컴포넌트 종료 시 router 구독 해제 추가.
