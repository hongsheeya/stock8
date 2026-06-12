# 회원가입·로그인·로그아웃 및 계정 관리 흐름 정비

- **ID**: 001
- **날짜**: 2026-04-09
- **유형**: 기능 개선

## 작업 요약
기존에 일부 구현되어 있던 사용자 인증/계정 관리 기능을 `stock` DB 기반 흐름에 맞게 정비했다. 로그인·회원가입 검증을 강화하고, 첫 가입자를 관리자 계정으로 승격하며, 로그아웃 동작과 관리자 전용 멤버 관리 접근 제어를 일관되게 맞췄다.

## 변경 파일 목록
- `src/app/page.access/api.py`: 이메일 정규화/검증, 로그인/회원가입 유효성 강화, 첫 가입자 `admin` 부여, `logout()` API 추가
- `src/app/page.access/view.ts`: 이메일 소문자/trim 처리, 비밀번호 최소 길이 8자리로 조정
- `src/app/component.nav.sidebar/view.pug`: 정적 로그아웃 링크를 `service.auth.logout('/access')` 기반 동작으로 교체
- `src/app/page.members/api.py`: 초대 이메일 정규화, 역할값을 `admin`/`user`로 제한, 기본 역할을 `user`로 통일
- `src/app/page.members/view.ts`: 역할 선택 UI를 `admin`/`user` 기준으로 정리
- `src/app/page.members/app.json`: 멤버 관리 페이지를 `admin` 컨트롤러로 변경하여 관리자 전용 접근 적용
- 빌드 검증: 관련 파일 오류 점검 후 클린 빌드 성공 확인