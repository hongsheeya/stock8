# 모의투자 시뮬레이터 페이지 (Admin Only)

- **ID**: 009
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
`/simulation` 페이지를 Admin 전용(controller: admin)으로 구현했다. 과거 시세 데이터 기반 무한매수법 백테스트 엔진, 설정 폼(종목/기간/투자금/분할/수익률), 결과 표시(Summary 카드, Cycle 테이블, Trade Detail 테이블)를 포함한다.

## 변경 파일 목록

### src/app/page.simulation/ (신규 생성)
- `app.json`: page, viewuri=/simulation, controller=admin, layout=layout.trading
- `view.ts`: 시뮬레이션 폼 관리, runSimulation 호출, 결과 표시
- `view.pug`: 설정 폼, Summary 카드(Total Cycles/Return/Avg Days/MDD), Cycle 테이블, Trade Detail 테이블
- `view.scss`: :host block height 100%
- `api.py`: run_simulation (과거 시세→알고리즘 적용→사이클별 매수/매도/스킵 시뮬레이션→DB 기록), load_watchlist
