# Domestic Daytrade Architecture

## Goal
- 기존 해외 ETF 야간 무한매수 엔진과 분리된 국내 주간장 단타 연구/운영 트랙 구축
- 전략 연구, 시뮬레이션, 최적화, 운영 청사진을 한 화면과 파일로 함께 제공

## Scope
1. **Research Layer**
   - 1분봉 기반 국내장 백테스트
   - VWAP, 전일종가 앵커, 거래량 지배력 기반 신호 분석
2. **Optimization Layer**
   - 파라미터 그리드 탐색
   - 순수익률, MDD, 승률, 회전율 기준 점수화
3. **Execution Blueprint Layer**
   - 장전 준비 → 장중 스캔 → 종가 집중 → 장후 검증
   - CALIB 비파괴 보정, 복리 시드 정책
4. **Presentation Layer**
   - `/daytrade` 전용 페이지
   - 알고리즘 문서, 최적화 리포트, 라이브 플랜 동시 열람

## File Map
- `src/portal/trading/model/struct/daytrade.py`
  - 데이터 수집, 백테스트, 파라미터 탐색, 리포트 저장
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 실전 엔진 청사진, 무결성 체크리스트, 복리 시드 계산
- `src/app/page.daytrade/*`
  - 단타 전용 관리/연구 페이지
- `docs/daytrade/architecture.md`
  - 아키텍처 설명
- `docs/daytrade/vrev-model.md`
  - V-REV 해석 문서
- `docs/daytrade/optimization-report.md`
  - 최신 최적화 결과 문서
- `data/daytrade/latest_training.json`
  - 최신 학습/최적화 결과 원본

## Separation Strategy
- 기존 `engine.py`는 해외 ETF 무한매수 전용 유지
- 단타 엔진은 `daytrade.py`, `daytrade_engine.py`로 분리
- 설정 키도 `daytrade_*` prefix로 분리 가능하도록 설계
- 장부는 append-only CALIB 원칙을 따르는 별도 로컬 파일/리포트 구조로 시작

## Future Expansion
- KIS 국내주식 분봉/주문 API 직접 연동
- 국내장 실시간 종목 필터 및 종가집중 주문 자동화
- 장부 delta row 기반 CALIB 저장소 테이블 분리
