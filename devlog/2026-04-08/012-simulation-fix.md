# 시뮬레이션 에러 수정 + 자동연장 토글/워딩 개선

- **ID**: 012
- **날짜**: 2026-04-08
- **유형**: 버그 수정 + 기능 개선

## 작업 요약
simulation/api.py의 _fetch_daily_prices에서 wiz.response가 try 블록 안에서 호출되어 ResponseException이 잡히는 문제 수정. 자동연장 토글에 service.render() 호출 추가. 워딩 간소화: "분할 소진 시 자동 연장" → "자동 연장".

## 변경 파일 목록
- `src/app/page.simulation/api.py`: _fetch_daily_prices ResponseException 패턴 수정
- `src/app/page.simulation/view.ts`: toggleAllowExtension() 메서드 추가
- `src/app/page.simulation/view.pug`: 인라인 토글 → toggleAllowExtension() 호출, title 속성 추가
- `src/portal/trading/libs/i18n.ts`: sim.auto_extend/desc 워딩 간소화 (EN/KO)
