# 대시보드 overview 복구 및 미장 공유 시드 보정

- **ID**: 013
- **날짜**: 2026-05-11
- **유형**: 버그 수정

## 작업 요약
대시보드 `overview` API가 깨진 소스 조각 때문에 컴파일 단계에서 실패하던 문제를 복구했다. 동시에 overview 경로의 과도한 동기화 호출을 줄이고, 미장 단타 예산 계산에서 국장 사용 시드를 함께 반영하도록 공유 시드 기준을 보강했다.

## 원문 요청사항
```text
reviewops-sdk.js:940  POST https://stock8.seasonai.net/wiz/api/page.dashboard/overview 500 (Internal Server Error)
XMLHttpRequest.send @ reviewops-sdk.js:940
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
load @ page.dashboard.component.ts:229
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
detectChangesInComponent @ change_detection.ts:433
(anonymous) @ change_detection.ts:514
refreshView @ change_detection.ts:305
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
detectChangesInViewIfAttached @ change_detection.ts:445
detectChangesInComponent @ change_detection.ts:433
(anonymous) @ change_detection.ts:514
refreshView @ change_detection.ts:305
detectChangesInView @ change_detection.ts:497
detectChangesInViewWhileDirty @ change_detection.ts:116
detectChangesInternal @ change_detection.ts:95
detectChangesInViewIfRequired @ application_ref.ts:923
synchronizeOnce @ application_ref.ts:667
synchronize @ application_ref.ts:629
_tick @ application_ref.ts:596
tick @ application_ref.ts:580
(anonymous) @ ng_zone_scheduling.ts:57
invoke @ zone.js:369
(anonymous) @ ng_zone.ts:470
invoke @ zone.js:368
run @ zone.js:111
run @ ng_zone.ts:229
(anonymous) @ ng_zone_scheduling.ts:56
(anonymous) @ Subscriber.ts:155
(anonymous) @ Subscriber.ts:113
(anonymous) @ Subscriber.ts:71
(anonymous) @ Subject.ts:67
errorContext @ errorContext.ts:29
(anonymous) @ Subject.ts:60
emit @ event_emitter.ts:135
checkStable @ ng_zone.ts:367
(anonymous) @ ng_zone.ts:505
hasTask @ zone.js:422
_updateTaskCount @ zone.js:443
_updateTaskCount @ zone.js:264
runTask @ zone.js:177
drainMicroTaskQueue @ zone.js:581
Promise.then
nativeScheduleMicroTask @ zone.js:557
scheduleMicroTask @ zone.js:568
scheduleTask @ zone.js:391
(anonymous) @ zone.js:271
scheduleTask @ zone.js:382
scheduleTask @ zone.js:205
scheduleMicroTask @ zone.js:225
scheduleResolveOrReject @ zone.js:2528
resolvePromise @ zone.js:2462
(anonymous) @ zone.js:2370
(anonymous) @ zone.js:2386
Promise.then
(anonymous) @ zone.js:2780
constructor @ zone.js:2702
(anonymous) @ zone.js:2779
init @ service.ts:76
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
reviewops-sdk.js:959 Dashboard load error: {readyState: 4, getResponseHeader: ƒ, getAllResponseHeaders: ƒ, setRequestHeader: ƒ, overrideMimeType: ƒ, …}

무한매수랑 대시보드에 나타난 오류 해결해줘. 동기화에서 오류 생기는거 같아
미장 단타 남은 시드에서 국장에서 이미 사용한 시드는 빼야해서 매매계획의 남은 시드를 표시하면 될거야
```

## 변경 파일 목록
- **대시보드 API**
  - `src/app/page.dashboard/api.py`
    - 손상된 상단 코드 조각 제거 및 누락된 내부 헬퍼 함수 복구
    - `overview` 응답 캐시 복구
    - overview 경로의 `shared_budget_status()` 호출을 cache-only fast path로 조정
- **단타 엔진**
  - `src/portal/trading/model/struct/daytrade_engine.py`
    - 미장 예산 계산 시 국장 포함 전체 단타 사용 시드도 고려하도록 보정
    - 시장별 사용 시드와 교차 시장 사용 시드 메타값 추가

## 검증
- Python `compile(..., 'exec')`로 수정 파일 문법 검증
- `wiz project build --project=main`
- 관리자 세션으로 아래 API 확인
  - `page.dashboard/overview` → 200
  - `page.dashboard/trade_preview` → 200
  - `page.daytrade.us/us_snapshot` → 200
