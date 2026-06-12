# 단타 view.ts 잔여 49개 타입 오류 정리 및 빌드 재검증

- **ID**: 006
- **날짜**: 2026-05-08
- **유형**: 버그 수정

## 작업 요약
단타 페이지 소스는 정상처럼 보여도 생성된 Angular 컴포넌트에서 `unknown` 응답 타입, 누락된 필드 선언, 잘못된 `Service.init()` 호출 때문에 대량 타입 오류가 남아 있었다.
`view.ts`를 생성 코드 기준으로 다시 맞추고 빌드를 재실행해, 문제로 지적된 49개 오류가 모두 사라진 것을 확인했다.

## 원문 요청사항
```text
지금 view.ts 오류 49개가 있잖아. 중복 데이터 삭제하면서 나타난거 같은데 다 정리해서 해결해
```

## 변경 파일 목록
### 프런트엔드
- `src/app/page.daytrade/view.ts`
  - 인덱스 시그니처를 제거하고 실제로 쓰는 상태 필드를 명시적으로 선언
  - `service.init(this)`로 실제 `Service` 시그니처와 맞춤
  - `wiz.call()` 공통 래퍼 `api()`에 명시적 반환 타입을 부여해 `unknown` 분해 오류 제거
  - 존재하지 않던 `usSignalAction` 참조를 현재 시그널 기반으로 정리
- `src/types/wiz-modules.d.ts`
  - `Service.init(app?)`, `Service.href()`, `auth.allow()` 및 전역 `wiz.call()` 선언을 현재 사용 방식에 맞게 보강

## 검증 내용
- [src/app/page.daytrade/view.ts](src/app/page.daytrade/view.ts) 진단 결과 오류 없음
- [build/src/app/page.daytrade/page.daytrade.component.ts](build/src/app/page.daytrade/page.daytrade.component.ts) 진단 결과 오류 없음
- 프로젝트 빌드 재실행 후 `Project 'main' build completed.` 확인

## 변경 원인 정리
- 소스 파일은 느슨한 선언 덕분에 조용했지만, 생성된 컴포넌트는 실제 서비스 타입과 TS 옵션을 적용받으면서 오류가 드러난 상태였다.
- 이번 정리는 중복 데이터 삭제 자체보다, 그 이후 재생성된 컴포넌트가 실제 타입 검사에 걸리던 부분을 맞춘 작업이다.
