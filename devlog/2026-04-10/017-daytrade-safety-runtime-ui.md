# 단타 실거래 안전장치 및 운영 로그 체계 정비

- **ID**: 017
- **날짜**: 2026-04-10
- **유형**: 기능 추가

## 작업 요약
실거래 엔진에 연결 상태, 지연 시세, 급변장, 주문 쿨다운, 예산 초과를 검사하는 가드레일을 추가했다. `/daytrade`에서 현재 모드, 리스크 상태, 최근 오류/중지 사유, 최근 운영 로그를 볼 수 있게 하여 실거래 전 판단 근거를 더 명확히 했다.

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade_engine.py` — 런타임 로그 저장, 리스크 가드레일, 최근 오류 상태, 실행 차단 로직 추가
- `src/app/page.daytrade/api.py` — `runtime` 리스크 상태 응답 추가
- `src/app/page.daytrade/view.ts` — 운영 모드/리스크/로그 상태 관리 추가
- `src/app/page.daytrade/view.pug` — 운영/안전 상태 패널 추가
- `data/daytrade/runtime_logs.json` — 최근 운영 로그 저장 파일 생성 구조 반영
