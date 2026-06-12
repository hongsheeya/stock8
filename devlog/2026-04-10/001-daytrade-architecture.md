# 국내 단타 시스템 요구사항/아키텍처 설계

- **ID**: 001
- **날짜**: 2026-04-10
- **유형**: 기능 추가

## 작업 요약
해외 ETF 무한매수와 분리된 국내 주간장 단타 시스템의 기본 아키텍처를 설계했다. 트레이딩 패키지 내 `daytrade.py`, `daytrade_engine.py`를 신규 추가하고, 문서/리포트/데이터 파일 구조를 분리했다.

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade.py` — 국내 단타 백테스트/최적화 서비스 구조 추가
- `src/portal/trading/model/struct/daytrade_engine.py` — 라이브 실행 청사진, 무결성 점검, 복리 시드 계산 추가
- `docs/daytrade/architecture.md` — 국내 단타 아키텍처 문서 생성
- `data/daytrade/latest_training.json` — 단타 학습 결과 저장소 초기화
