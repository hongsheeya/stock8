# 주당 구매 가격 상한 제한 및 종목 선별 로직 개선

- **ID**: 012
- **날짜**: 2026-04-14
- **유형**: 기능 추가

## 작업 요약
주당 구매 가능 금액의 절대 상한(50만 원) 설정 기능을 추가하고, `daytrade_engine.py`의 `auto_candidates` 로직을 수정하여 고가주(삼성바이오로직스 등 50만 원 초과 종목)가 불필요하게 신규 후보로 선정되는 것을 방지하도록 개선하였습니다.

## 변경 파일 목록
### Backend (Python)
- [src/portal/trading/model/daytrade_engine.py](src/portal/trading/model/daytrade_engine.py): `auto_candidates` 메서드 수정. 시드 기반 계산값과 설정된 절대 상한값(500,000원) 중 최소값을 기준으로 종목을 선별하도록 로직 개선.
