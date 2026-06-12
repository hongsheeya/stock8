# 대시보드 overview DB 장애 fallback 보강으로 500 차단

- **ID**: 005
- **날짜**: 2026-05-04
- **유형**: 버그 수정

## 작업 요약
`page.dashboard/overview`가 일부 DB 조회 실패 시 전체 API를 500으로 종료하던 문제를 수정했다.
실제 로그 기준으로 `trading.engine.get_status()`/`get_active_cycles()` 등 내부 DB 접근에서 MySQL `No route to host`가 발생했고, 이 예외가 overview 최상위에서 처리되지 않아 대시보드 초기 로딩이 끊기고 있었다.

## 원문 요청사항
```text
reviewops-sdk.js:741  POST https://stock8.seasonai.net/wiz/api/page.dashboard/overview 500 (Internal Server Error)
XMLHttpRequest.send @ reviewops-sdk.js:741
scheduleTask @ zone.js:2183
scheduleTask @ zone.js:388
scheduleTask @ zone.js:205
scheduleMacroTask @ zone.js:228
scheduleMacroTaskWithCurrentZone @ zone.js:691
(anonymous) @ zone.js:2222
(anonymous) @ zone.js:1003
send @ jquery.js:9940
ajax @ jquery.js:9521
(anonymous) @ wiz.ts:90
constructor @ zone.js:2702
call @ wiz.ts:89
load @ page.dashboard.component.ts:226
await in load
ngOnInit @ page.dashboard.component.ts:207
await in ngOnInit
callHookInternal @ hooks.ts:290
(anonymous) @ hooks.ts:319
callHooks @ hooks.ts:270
executeInitAndCheckHooks @ hooks.ts:205
refreshView @ change_detection.ts:258
detectChangesInView @ change_detection.ts:497
detectChangesInViewIfAttached @ change_detection.ts:445
detectChangesInEmbeddedViews @ change_detection.ts:393
refreshView @ change_detection.ts:272
detectChangesInView @ change_detection.ts:497
detectChangesInViewIfAttached @ change_detection.ts:445
detectChangesInComponent @ change_detection.ts:433
(anonymous) @ change_detection.ts:514
refreshView @ change_detection.ts:305
detectChangesInView @ change_detection.ts:497
detectChangesInViewIfAttached @ change_detection.ts:445
detectChangesInEmbeddedViews @ change_detection.ts:393
refreshView @ change_detection.ts:272
detectChangesInView @ change_detection.ts:497
detectChangesInViewIfAttached @ change_detection.ts:445
detectChangesInEmbeddedViews @ change_detection.ts:393
refreshView @ change_detection.ts:272
detectChangesInView @ change_detection.ts:497
detectChangesInViewWhileDirty @ change_detection.ts:116
detectChangesInternal @ change_detection.ts:95
detectChanges @ view_ref.ts:314
render @ service.ts:78
init @ service.ts:56
await in init
ngOnInit @ app.component.ts:27
callHookInternal @ hooks.ts:290
(anonymous) @ hooks.ts:319
callHooks @ hooks.ts:270
executeInitAndCheckHooks @ hooks.ts:205
refreshView @ change_detection.ts:258
detectChangesInView @ change_detection.ts:497
detectChangesInViewWhileDirty @ change_detection.ts:116
detectChangesInternal @ change_detection.ts:95
detectChangesInViewIfRequired @ application_ref.ts:923
synchronizeOnce @ application_ref.ts:667
synchronize @ application_ref.ts:629
_tick @ application_ref.ts:596
tick @ application_ref.ts:580
_loadComponent @ application_ref.ts:753
bootstrap @ application_ref.ts:558
(anonymous) @ bootstrap.ts:154
moduleDoBootstrap @ bootstrap.ts:154
(anonymous) @ bootstrap.ts:140
invoke @ zone.js:369
(anonymous) @ ng_zone.ts:470
invoke @ zone.js:368
run @ zone.js:111
(anonymous) @ zone.js:2538
invokeTask @ zone.js:402
(anonymous) @ ng_zone.ts:447
invokeTask @ zone.js:401
runTask @ zone.js:159
drainMicroTaskQueue @ zone.js:581
Promise.then
nativeScheduleMicroTask @ zone.js:557
scheduleMicroTask @ zone.js:568
scheduleTask @ zone.js:391
scheduleTask @ zone.js:205
scheduleMicroTask @ zone.js:225
scheduleResolveOrReject @ zone.js:2528
then @ zone.js:2733
bootstrapModule @ platform_ref.ts:112
(anonymous) @ main.ts:8Understand this error
reviewops-sdk.js:760 Dashboard load error: {readyState: 4, getResponseHeader: ƒ, getAllResponseHeaders: ƒ, setRequestHeader: ƒ, overrideMimeType: ƒ, ...}

아니 제대로 좀 고쳐봐
```

## 변경 파일 목록
### 백엔드 API
- `src/app/page.dashboard/api.py`
  - `overview()` 내부에서 엔진 상태, 활성 사이클, 최근 로그, 워치리스트 조회를 각각 안전 fallback 함수로 분리
  - DB 연결 오류 시 빈 목록/기본 상태로 응답하도록 보강
  - `_dump_error()`와 `_log()`를 통해 fallback 원인을 별도 기록하도록 추가
- `build/src/app/page.dashboard/api.py`
  - 빌드 소스 동일 수정 동기화
- `bundle/src/app/page.dashboard/api.py`
  - 런타임 백엔드 동일 수정 동기화

## 검증
- `/tmp/wiz_dashboard_api_errors.log` 확인 결과, 기존 원인은 `peewee.OperationalError: (2003, "Can't connect to MySQL server ... No route to host")`였음을 확인
- 수정한 dashboard API 3개 파일에 대해 `python -m py_compile` 검증 완료
- 에디터 진단 기준 수정 파일 오류 없음 확인
