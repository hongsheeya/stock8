# 단타엔진 슬롯 분산/변동성 필터/추가매수 제한 개선

- **ID**: 001
- **날짜**: 2026-04-17
- **유형**: 버그 수정/로직 개선

## 작업 요약

- 단타엔진이 특정 종목(예: 현대제철)에만 집중 매수되는 문제를 해결하기 위해, 슬롯별 시드 한도, 변동성 필터, 추가매수 제한 로직을 도입/강화함.
- D+0/D+1/D+2 예수금 합산, 총 자산 기반 시드 한도, 백엔드 워커 핫스왑, favicon SVG 적용 등 기존 개선사항도 포함.

## 변경 파일 목록

### 1. 엔진 로직 개선
- `src/portal/trading/model/struct/daytrade_engine.py`
  - **슬롯별 시드 한도**: slot_seed_limit_krw = total_seed_krw / slot_count
  - **변동성 필터**: min_day_range_pct(기본 4%) 미만 종목 자동 제외
  - **추가매수 제한**: 기존 보유 종목에 대해 slot_seed_limit_krw 초과 추가매수 차단
  - **진입 후보 선정**: 변동성/시드 한도 미달 종목 로그에 상세 기록

### 2. 백엔드 워커 핫스왑
- `src/portal/trading/model/struct.py`
  - 코드 변경 시 워커 스레드 자동 재시작

### 3. 브랜드/UX 개선
- `src/angular/index.pug`, `src/assets/brand/favicon.svg`
  - favicon을 인피니티 SVG로 교체, 탭 타이틀/아이콘 일원화

### 4. 진단/배포
- 빌드/pyc 캐시 정리, 번들 내 신규 로직 반영 확인
- runtime_logs.json, recommendation.json 등 진단 로그로 검증

---

**요약**: 단타엔진이 특정 종목에 집중되지 않고, 변동성 기준에 따라 다양한 종목에 분산 진입하도록 로직을 개선하였으며, 실시간 코드 반영 및 브랜드 일관성도 확보함.