# 대시보드 overview reset 완화 및 장중 거래 저조 원인 분석

- **ID**: 001
- **날짜**: 2026-05-13
- **유형**: 버그 수정

## 작업 요약
대시보드 `overview` 폴링 중 `ERR_CONNECTION_RESET`이 발생하던 원인을 추적한 결과, 브라우저 폴링/미리보기 갱신이 겹치면서 서버 쪽 DB 연결 사용량이 순간적으로 증가하고, 에러 로그에는 `peewee.OperationalError: (1040, 'Too many connections')`가 남아 있었다.
이에 overview API를 singleflight + degraded fallback 방식으로 하드닝하고, 프론트엔드에서 중복 `load()`/`loadTradePreview()` 요청을 막아 연결 폭주를 완화했다. 동시에 무한매수 알고리즘이 장중보다 장 시작/장 끝에 거래가 몰리기 쉬운 구조적 이유도 분석했다.

## 원문 요청사항
```text
reviewops-sdk.js:907  POST https://stock8.seasonai.net/wiz/api/page.dashboard/overview net::ERR_CONNECTION_RESET
XMLHttpRequest.send @ reviewops-sdk.js:907
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
load @ page.dashboard.component.ts:235
(anonymous) @ page.dashboard.component.ts:487
(anonymous) @ zone.js:1809
invokeTask @ zone.js:402
runTask @ zone.js:159
invokeTask @ zone.js:483
(anonymous) @ zone.js:472
(anonymous) @ zone.js:1778
setInterval
scheduleTask @ zone.js:1780
scheduleTask @ zone.js:388
scheduleTask @ zone.js:205
scheduleMacroTask @ zone.js:228
scheduleMacroTaskWithCurrentZone @ zone.js:691
(anonymous) @ zone.js:1834
(anonymous) @ zone.js:1003
startPolling @ page.dashboard.component.ts:485
ngOnInit @ page.dashboard.component.ts:209
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
detectChangesInViewWhileDirty @ change_detection.ts:116
detectChangesInternal @ change_detection.ts:95
detectChanges @ view_ref.ts:314
render @ service.ts:120
(anonymous) @ component.nav.trading.component.ts:41
(anonymous) @ Subscriber.ts:155
(anonymous) @ Subscriber.ts:113
(anonymous) @ Subscriber.ts:71
(anonymous) @ Subject.ts:67
errorContext @ errorContext.ts:29
(anonymous) @ Subject.ts:60
(anonymous) @ router.ts:254
(anonymous) @ Subscriber.ts:155
(anonymous) @ Subscriber.ts:113
(anonymous) @ Subscriber.ts:71
(anonymous) @ Subject.ts:67
errorContext @ errorContext.ts:29
(anonymous) @ Subject.ts:60
(anonymous) @ navigation_transition.ts:782
(anonymous) @ tap.ts:189
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ take.ts:60
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ map.ts:57
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ tap.ts:190
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ map.ts:57
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ switchMap.ts:114
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ innerFrom.ts:78
(anonymous) @ Observable.ts:235
(anonymous) @ Observable.ts:225
errorContext @ errorContext.ts:29
(anonymous) @ Observable.ts:211
(anonymous) @ switchMap.ts:108
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ switchMap.ts:114
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ map.ts:57
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ innerFrom.ts:78
(anonymous) @ Observable.ts:235
(anonymous) @ Observable.ts:225
errorContext @ errorContext.ts:29
(anonymous) @ Observable.ts:211
(anonymous) @ map.ts:53
(anonymous) @ lift.ts:24
(anonymous) @ Observable.ts:217
errorContext @ errorContext.ts:29
(anonymous) @ Observable.ts:211
(anonymous) @ switchMap.ts:108
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ switchMap.ts:114
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ map.ts:57
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ take.ts:60
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ defaultIfEmpty.ts:52
(anonymous) @ OperatorSubscriber.ts:92
(anonymous) @ Subscriber.ts:100
(anonymous) @ innerFrom.ts:80
(anonymous) @ Observable.ts:235
(anonymous) @ Observable.ts:225
errorContext @ errorContext.ts:29
(anonymous) @ Observable.ts:211
(anonymous) @ defaultIfEmpty.ts:43
(anonymous) @ lift.ts:24
(anonymous) @ Observable.ts:217
errorContext @ errorContext.ts:29
(anonymous) @ Observable.ts:211
(anonymous) @ take.ts:54
(anonymous) @ lift.ts:24
(anonymous) @ Observable.ts:217
errorContext @ errorContext.ts:29
(anonymous) @ Observable.ts:211
(anonymous) @ map.ts:53
(anonymous) @ lift.ts:24
(anonymous) @ Observable.ts:217
errorContext @ errorContext.ts:29
(anonymous) @ Observable.ts:211
(anonymous) @ switchMap.ts:108
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ switchMap.ts:114
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ map.ts:57
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ tap.ts:190
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ switchMap.ts:114
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ tap.ts:190
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ mergeInternals.ts:85
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ mergeInternals.ts:85
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ innerFrom.ts:78Understand this error
reviewops-sdk.js:907  POST https://stock8.seasonai.net/wiz/api/page.dashboard/overview net::ERR_CONNECTION_RESET
XMLHttpRequest.send @ reviewops-sdk.js:907
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
load @ page.dashboard.component.ts:235
(anonymous) @ page.dashboard.component.ts:487
(anonymous) @ zone.js:1809
invokeTask @ zone.js:402
runTask @ zone.js:159
invokeTask @ zone.js:483
(anonymous) @ zone.js:472
(anonymous) @ zone.js:1778Understand this error
reviewops-sdk.js:926 Dashboard load error: {readyState: 0, getResponseHeader: ƒ, getAllResponseHeaders: ƒ, setRequestHeader: ƒ, overrideMimeType: ƒ, …}
window.console.<computed> @ reviewops-sdk.js:926
load @ page.dashboard.component.ts:279
await in load
(anonymous) @ page.dashboard.component.ts:487
(anonymous) @ zone.js:1809
invokeTask @ zone.js:402
runTask @ zone.js:159
invokeTask @ zone.js:483
(anonymous) @ zone.js:472
(anonymous) @ zone.js:1778
setInterval
scheduleTask @ zone.js:1780
scheduleTask @ zone.js:388
scheduleTask @ zone.js:205
scheduleMacroTask @ zone.js:228
scheduleMacroTaskWithCurrentZone @ zone.js:691
(anonymous) @ zone.js:1834
(anonymous) @ zone.js:1003
startPolling @ page.dashboard.component.ts:485
ngOnInit @ page.dashboard.component.ts:209
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
detectChangesInViewWhileDirty @ change_detection.ts:116
detectChangesInternal @ change_detection.ts:95
detectChanges @ view_ref.ts:314
render @ service.ts:120
(anonymous) @ component.nav.trading.component.ts:41
(anonymous) @ Subscriber.ts:155
(anonymous) @ Subscriber.ts:113
(anonymous) @ Subscriber.ts:71
(anonymous) @ Subject.ts:67
errorContext @ errorContext.ts:29
(anonymous) @ Subject.ts:60
(anonymous) @ router.ts:254
(anonymous) @ Subscriber.ts:155
(anonymous) @ Subscriber.ts:113
(anonymous) @ Subscriber.ts:71
(anonymous) @ Subject.ts:67
errorContext @ errorContext.ts:29
(anonymous) @ Subject.ts:60
(anonymous) @ navigation_transition.ts:782
(anonymous) @ tap.ts:189
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ take.ts:60
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ map.ts:57
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ tap.ts:190
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ map.ts:57
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ switchMap.ts:114
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ innerFrom.ts:78
(anonymous) @ Observable.ts:235
(anonymous) @ Observable.ts:225
errorContext @ errorContext.ts:29
(anonymous) @ Observable.ts:211
(anonymous) @ switchMap.ts:108
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ switchMap.ts:114
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ map.ts:57
(anonymous) @ OperatorSubscriber.ts:70
(anonymous) @ Subscriber.ts:71
(anonymous) @ innerFrom.ts:78Understand this error
reviewops-sdk.js:926 Dashboard load error: {readyState: 0, getResponseHeader: ƒ, getAllResponseHeaders: ƒ, setRequestHeader: ƒ, overrideMimeType: ƒ, …}

이 오류 해결해줘
또 매번 장 시작과 장 끝날때만 매매가 활발하고 중간에는 거래가 거의 없는데 원인이 따로 있어? 알고리즘에서 그렇게 하래?
```

## 변경 파일 목록
- `src/app/page.dashboard/api.py`
  - `overview` 응답을 singleflight + degraded fallback 구조로 바꿔 동시 요청이 겹칠 때 DB/KIS 부하가 중복되지 않도록 조정
  - overview 계산 중 예외가 나면 최근 캐시를 우선 반환하고, 캐시도 없으면 최소 fallback payload를 내려 reset 대신 복구 응답을 시도하도록 보강
- `src/app/page.dashboard/view.ts`
  - 폴링과 수동 갱신, 후속 액션 갱신이 서로 겹쳐 동시에 `overview`/`trade_preview`를 여러 번 때리지 않도록 in-flight promise 가드 추가
  - `ngOnInit()`의 초기 중복 `trade_preview` 호출 제거

## 검증
- `python3 -m py_compile src/app/page.dashboard/api.py`
- 병렬 호출 확인: `overview` 8개 동시 호출 모두 HTTP 200 응답 확인
- 에러 로그 확인: 기존 `/tmp/wiz_dashboard_api_errors.log`에는 `peewee.OperationalError: (1040, 'Too many connections')` 이력이 존재함
