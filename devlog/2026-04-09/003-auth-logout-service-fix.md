# 공통 인증 서비스 로그아웃 메서드 누락 수정

- **ID**: 003
- **날짜**: 2026-04-09
- **유형**: 버그 수정

## 작업 요약
네비게이션에서 `service.auth.logout('/access')`를 호출하고 있었지만 Season 공통 인증 서비스 `Auth` 클래스에 실제 `logout()` 메서드가 없어 런타임 `TypeError`가 발생하던 문제를 수정했다. `/auth/logout?returnTo=...`로 이동하는 공통 메서드를 추가했고, 로컬 호출로 `302 -> /access` 리다이렉트와 세션 쿠키 삭제를 확인했다.

## 변경 파일 목록
- `src/portal/season/libs/src/auth.ts`: 공통 `logout(returnTo)` 메서드 추가
- 검증: 타입 오류 없음, 일반 빌드 성공, `/auth/logout?returnTo=/access` 응답 302 확인