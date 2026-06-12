# 거래 이력 페이지

- **ID**: 010
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
`/history` 페이지를 생성하여 거래 사이클 목록, 사이클 상세(회차별 거래 내역), 거래 로그, 일별 자산 스냅샷을 3탭 구조로 조회할 수 있도록 구현. 상태/종목 필터, 메시지 검색, 페이징 지원.

## 변경 파일 목록

### 신규 생성
- `src/app/page.history/app.json` - 페이지 메타 (viewuri=/history, controller=user, layout=layout.trading)
- `src/app/page.history/view.ts` - 3탭 관리, 필터/검색/페이징 로직, 유틸 함수
- `src/app/page.history/view.pug` - Cycles탭(필터+테이블+상세모달), Trade Logs탭(필터+검색+테이블), Snapshots탭(테이블)
- `src/app/page.history/view.scss` - :host 블록 설정
- `src/app/page.history/api.py` - symbols(), cycles(), cycle_detail(), trade_logs(), snapshots() API
