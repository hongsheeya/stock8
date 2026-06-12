# 설정 페이지 개인정보 수정 기능 확장

- **ID**: 012
- **날짜**: 2026-04-29
- **유형**: 기능 추가

## 작업 요약
설정 페이지에서 아이디/이메일/비밀번호를 직접 수정할 수 있도록 API와 UI를 확장했다.
로그인 세션 기반 사용자 식별, 이메일 형식/중복 검증, 현재 비밀번호 확인 로직을 추가했다.

## 변경 파일 목록
- `src/app/page.settings/api.py`
  - 세션 사용자 조회 헬퍼 추가
  - `load_settings()` 응답에 계정 정보(`account_user_id`, `account_login_id`, `account_email`) 포함
  - `save_account_profile()` 추가 (이메일/아이디 저장 + 중복 검증)
  - `change_account_password()` 추가 (현재 비밀번호 검증 후 변경)
- `src/app/page.settings/view.ts`
  - 계정 정보/비밀번호 폼 상태 변수 추가
  - `saveAccountProfile()`, `changeAccountPassword()` 액션 추가
- `src/app/page.settings/view.pug`
  - API 탭 하단에 계정정보 편집 섹션 추가
  - 비밀번호 변경 입력/액션 UI 추가
