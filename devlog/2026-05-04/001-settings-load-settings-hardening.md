# 설정 페이지 load_settings 장애 복구 및 로딩 안정화

- **ID**: 001
- **날짜**: 2026-05-04
- **유형**: 버그 수정

## 작업 요약
`page.settings/load_settings` API에 잘못 들어간 들여쓰기 때문에 서버에서 `IndentationError`가 발생하며 500 응답이 반환되고 있었습니다.
동시에 설정 로딩 경로를 캐시 기반으로 바꾸고, 숫자 파싱/응답 처리/프론트 예외 처리를 보강하여 동일 유형의 로딩 장애가 다시 500과 uncaught promise로 번지지 않도록 정리했습니다.

## 원문 요청사항
```text
reviewops-sdk.js:741  POST https://stock8.seasonai.net/wiz/api/page.settings/load_settings 500 (Internal Server Error)
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
loadSettings @ page.settings.component.ts:133
await in loadSettings
ngOnInit @ page.settings.component.ts:109
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
page.settings.component.ts:110 Uncaught (in promise) {readyState: 4, getResponseHeader: ƒ, getAllResponseHeaders: ƒ, setRequestHeader: ƒ, overrideMimeType: ƒ, …}

이 에러 해결해주고 앞으로 안나오게 제대로 최적화 해놔
```

## 변경 파일 목록
- `src/app/page.settings/api.py`
  - `load_settings()`의 잘못된 들여쓰기를 바로잡아 실제 500 원인이던 `IndentationError`를 제거
  - `trading.get_config()` 캐시를 우선 사용하도록 바꿔 설정 조회 쿼리 수를 줄임
  - `_safe_int()`, `_safe_float()`를 추가해 빈 값/비정상 값으로 인한 형변환 예외를 차단
  - 워치리스트 조회 실패 시 빈 배열로 안전하게 처리하고, 로드 실패 시 API 메시지를 명시적으로 반환
- `src/app/page.settings/view.ts`
  - `loadSettings()`에 `try/catch`를 추가해 `Uncaught (in promise)`가 콘솔로 그대로 전파되지 않도록 수정
  - 실패 시 `loadError`에 사용자 표시용 메시지를 남기고 로딩 상태를 정상 해제하도록 정리
- `src/app/page.settings/view.pug`
  - 설정 로드 실패 메시지를 상단 경고 박스로 표시하도록 UI 추가

## 검증
- `python -m py_compile /opt/app/project/main/src/app/page.settings/api.py /opt/app/project/main/src/app/page.dashboard/api.py`
- VS Code 진단 기준 `page.settings/api.py`, `page.settings/view.ts`, `page.settings/view.pug` 오류 없음 확인
