# Auth 초기화 경쟁과 timeout abort 근본 원인 수정

- **ID**: 012
- **날짜**: 2026-05-08
- **유형**: 버그 수정

## 작업 요약
초기 렌더 시 여러 Angular 컴포넌트가 동시에 `service.init(this)`를 호출하면서, `Service.inited`가 `auth.init()` 완료 전까지 `false`로 남아 중복 초기화 경쟁이 발생했다.
그 결과 `/auth/check` 요청이 동시에 여러 번 발사되고, 일부 요청이 timeout/abort(`readyState=0`, `status=0`)로 종료되어 fallback session 로그가 계속 출력되었다.

## 원문 요청사항
```text
아직도 [Auth] Failed after retries, using fallback session: Error: Network error: readyState=0, status=0
    at Object.<anonymous> (request.ts:32:32)
    at $ (jquery.js:3223:31)
    at Object.fireWith [as rejectWith] (jquery.js:3353:7)
    at ad (jquery.js:9629:14)
    at Object.abort (jquery.js:9342:6)
    at jquery.js:9515:12
    at h.<computed> (zone.js:1809:37)
    at i.invokeTask (zone.js:402:33)
    at dt.runTask (zone.js:159:47)
    at invokeTask (zone.js:483:34)
    아직도 fallback session이 나타나 원인 좀 찾아서 설명좀 해봐. 왜 못잡는건데
```

## 변경 파일 목록

### `src/portal/season/libs/service.ts`
- `initPromise`를 추가해 초기화 구간을 직렬화
- 첫 번째 `service.init()`만 실제 `auth.init()`를 실행하고, 나머지 동시 호출은 같은 Promise를 기다리도록 변경
- `inited`가 `auth.init()` 완료 이후에만 true가 되도록 유지하면서도 중복 `auth.init()`는 차단

### `src/portal/season/libs/util/request.ts`
- `$.ajax().fail()`에서 `textStatus`, `errorThrown`까지 포함해 에러 메시지를 기록하도록 수정
- timeout/abort인지 다음 로그에서 즉시 식별 가능하도록 보강

## 분석 메모
- `/auth/check` 자체는 로컬에서 200 응답 확인됨
- 따라서 문제는 경로 누락이 아니라, 브라우저 쪽에서 요청이 abort/timeout되는 부트 시퀀스 경쟁이었다
- `page.infinitebuy`, `page.dashboard`, `page.settings`, `layout.trading`, `component.nav.trading` 등 다수 컴포넌트가 같은 시점에 `service.init(this)`를 호출하는 구조를 확인함
