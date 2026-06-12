# 단타 연구실 UI 고도화 및 라이브 실행 기능 추가

- **ID**: 008
- **날짜**: 2026-04-10
- **유형**: 기능 추가

## 작업 요약
단타 연구실 페이지를 단순 문서 뷰 수준에서 실제 연구/운영 화면으로 재구성했다. 국내 종목 검색, 후보 자동 학습, 승률/수익률 집계, 라이브 시그널 상태, 실거래 실행 버튼, 최근 주문 이력 표시를 추가했고, 백엔드에는 자동 학습/시그널/실행 API와 국내주식 주문 래퍼를 연결했다.

## 변경 파일 목록
- `src/app/page.daytrade/view.ts`
  - 종목 검색, 후보 자동 학습, 라이브 시그널 조회, 실거래 실행 상태 관리 로직 추가
- `src/app/page.daytrade/view.pug`
  - 단타 연구실 UI를 연구 설정 + 후보 리더보드 + 실거래 상태 화면으로 전면 개편
- `src/app/page.daytrade/api.py`
  - `search_symbols`, `run_auto_training`, `live_status`, `execute_live` API 추가
  - bootstrap/backtest/training 응답에 라이브 상태/후보 정보 포함
- `src/portal/trading/model/struct/daytrade.py`
  - 국내 종목 후보군/검색 지원
  - 데이터 재사용 기반 최적화 루틴 추가
  - 후보 전체 자동 학습 및 성공률/평균 수익률 집계 기능 추가
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 라이브 상태 파일 관리, 실시간 시그널 계산, 주문 상태 저장, 주문 로그 기록 추가
- `src/portal/trading/model/struct/kis_api.py`
  - 국내주식 현금 주문용 매수/매도 래퍼 추가

## 검증 내용
- 클린 빌드 1회 + 일반 빌드 2회 성공
- `bootstrap`, `search_symbols`, `live_status`, `run_backtest`, `run_training`, `run_auto_training` API 응답 200 확인
- `run_auto_training` 집계 결과 확인
  - 테스트 후보 10개
  - 성공률 60.0%
  - 평균 수익률 0.0591%
  - 최고 종목 `035420 (NAVER)`
- `execute_live`는 현재 HOLD 상태에서 안전하게 실행되어 실제 주문 없이 제어 흐름만 검증
