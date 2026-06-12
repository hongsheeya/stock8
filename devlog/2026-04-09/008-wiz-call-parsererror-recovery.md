# wiz.call parsererror 복구 처리 추가

- **ID**: 008
- **날짜**: 2026-04-09
- **유형**: 버그 수정

## 작업 요약
시뮬레이션 API가 HTTP 200과 정상 JSON 본문을 반환했음에도 jQuery의 `parsererror`로 실패 객체를 반환하는 문제가 있어 공통 요청 래퍼를 보강했다.
`parsererror` 발생 시 `responseText`가 있으면 직접 `JSON.parse()`를 시도하여 정상 응답으로 복구하도록 수정했다.

## 변경 파일 목록
### 공통 프론트엔드 요청 래퍼
- `src/angular/wiz.ts`
  - `wiz.call()`에서 `parsererror` 발생 시 `responseText` 수동 파싱 복구 추가
- `src/portal/season/libs/util/request.ts`
  - 동일한 수동 파싱 복구 로직 추가

## 검증
- 변경 파일 진단 오류 없음 확인
- WIZ 프로젝트 `main` 일반 빌드 성공
