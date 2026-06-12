# 대시보드 overview 500 오류 수정

- **ID**: 002
- **날짜**: 2026-04-09
- **유형**: 버그 수정

## 작업 요약
`page.dashboard/overview` 호출 시 `portal/trading` 패키지가 사용하는 DB 네임스페이스 `trading`이 [config/database.py](config/database.py)에 정의되지 않아 런타임 500이 발생하던 문제를 수정했다. `trading = base`를 추가해 패키지 로딩이 정상화되었고, 로컬 세션 쿠키로 `overview` API를 직접 호출해 200 응답을 확인했다. 접근 페이지의 회원가입 비밀번호 플레이스홀더도 실제 정책(8자 이상)과 일치하도록 정리했다.

## 변경 파일 목록
- `config/database.py`: `trading` DB 네임스페이스 추가
- `src/app/page.access/view.pug`: 회원가입 비밀번호 안내 문구를 8자 이상 기준으로 수정
- 검증: 일반 빌드 성공, `page.dashboard/overview` 로컬 호출 200 확인