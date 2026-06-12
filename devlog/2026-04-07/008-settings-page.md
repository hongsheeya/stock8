# 설정 페이지 구현 - 3탭 (API/Watchlist/Parameters)

- **ID**: 008
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
`/settings` 페이지를 3탭 구조로 구현했다. API 설정(한투 API 키/시크릿/계좌/모의투자 모드), Watchlist(종목 추가/삭제/활성화/투자금·분할횟수·수익률 설정), Parameters(기본 분할/수익률/자동매매 토글).

## 변경 파일 목록

### src/app/page.settings/ (신규 생성)
- `app.json`: page, viewuri=/settings, controller=user, layout=layout.trading
- `view.ts`: 3탭 관리, API 설정 저장/테스트, Watchlist CRUD, 파라미터 저장
- `view.pug`: 글래스모피즘 탭 UI, 입력 폼, 토글 스위치, 워치리스트 인라인 편집
- `view.scss`: :host block height 100%
- `api.py`: load_settings, save_api_settings, test_connection, add/remove/toggle/update_watchlist, save_parameters
