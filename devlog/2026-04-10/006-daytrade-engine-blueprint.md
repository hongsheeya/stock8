# 국내 주간장 자동매매 엔진/무결성 보정 연동

- **ID**: 006
- **날짜**: 2026-04-10
- **유형**: 기능 추가

## 작업 요약
실거래 전 단계로 국내 단타 엔진 청사진과 장후 검증 규칙을 구현했다. 장전 준비, 장중 스캔, 종가 집중, CALIB 비파괴 보정, 복리 시드 계산 로직을 구조화했다.

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade_engine.py` — 라이브 플랜/무결성 체크리스트 구현
- `src/app/page.daytrade/api.py` — 라이브 플랜 조회 API 추가
- `src/app/page.daytrade/view.pug` — 실행 청사진 UI 추가
