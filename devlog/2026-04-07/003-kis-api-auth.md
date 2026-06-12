# 한국투자증권 API 연동 - 인증 및 기본 통신

- **ID**: 003
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
한국투자증권 Open API 연동을 위한 인증 모듈을 구현했다. OAuth 토큰 발급/갱신, 실전/모의 투자 모드 분기, 공통 HTTP 래퍼, 설정 관리 기능을 포함한다.

## 변경 파일 목록

### portal/trading/model/struct/
- `kis_api.py` (수정): placeholder → 전체 인증/통신 모듈 구현
  - OAuth 토큰 발급/갱신 (DB + 메모리 이중 캐시)
  - 실전/모의 base URL 분기
  - 공통 HTTP 래퍼 (_request, _headers)
  - 설정 CRUD (save_settings, get_settings)
  - 연결 테스트 (test_connection)
