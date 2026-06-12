# 시뮬레이션 종목 선택 드롭다운 개선

- **ID**: 013
- **날짜**: 2026-04-08
- **유형**: 기능 개선

## 작업 요약
시뮬레이션 페이지의 input+select 혼합 방식을 watchlist 기반 드롭다운으로 교체. 하드코딩된 종목 옵션 제거. "직접 입력" 옵션으로 커스텀 티커 지원.

## 변경 파일 목록
- `src/app/page.simulation/view.pug`: input+select → select(watchlist) + custom input 방식으로 교체
- `src/app/page.simulation/view.ts`: customSymbol 상태 추가, runSimulation에서 __custom__ 처리, 기본 심볼 자동 선택
- `src/portal/trading/libs/i18n.ts`: sim.select_symbol, sim.custom_symbol, sim.custom_placeholder 키 추가 (EN/KO)
