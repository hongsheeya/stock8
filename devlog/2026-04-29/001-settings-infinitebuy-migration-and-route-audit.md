# 시스템 전체 검증 및 무한매수 설정 이전

- **ID**: 001
- **날짜**: 2026-04-29
- **유형**: 리팩토링

## 작업 요약
설정 페이지와 무한매수 서브페이지의 역할을 다시 분리하여, 무한매수 관심종목·매매 파라미터·매도전략이 `/infinite-buy`에서 관리되도록 옮겼다. 동시에 `page.settings`의 `load_settings` 경로가 import 시점 struct 로드 실패로 500을 내던 문제를 지연 로딩 구조로 완화했다.

## 변경 파일 목록
### 설정/페이지
- `src/app/page.settings/api.py` — struct/trading 지연 로딩 헬퍼 추가, 설정 API 안정화
- `src/app/page.settings/view.ts` — `mode` 입력값 추가, 일반 설정/무한매수 모드 분기
- `src/app/page.settings/view.pug` — `/settings`에서는 API만, `/infinite-buy`에서는 무한매수 설정만 노출되도록 탭 분리
- `src/app/page.infinitebuy/view.pug` — 무한매수 페이지에 설정 컴포넌트를 임베드

### 검증
- 프로젝트 빌드로 설정/페이지 라우팅 구성을 재검증
