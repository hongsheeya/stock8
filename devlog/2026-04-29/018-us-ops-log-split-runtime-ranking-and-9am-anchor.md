# 미장 운영 로그 분리·검증/랭킹 강화·09시 기준 집계 보정

- **ID**: 018
- **날짜**: 2026-04-29
- **유형**: 기능 추가

## 작업 요약
무한매수/단타 운영 로그를 채널별로 분리할 수 있도록 이벤트 타입 네임스페이스를 정리했다.
미장 단타 전용 페이지를 실제 운영 UI로 교체하고, 실행 검증(체크리스트) 및 전략 랭킹(승률/수익률/낙폭 기반)을 API와 함께 추가했다.
대시보드 수익 집계는 09:00 KST 세션 앵커를 도입하고 환율/총자산 계산 시 KIS 원천 KRW 값을 우선 사용하도록 보정했다.

## 변경 파일 목록
### 로그 분리
- `src/portal/trading/model/struct/engine.py`
  - `_log_event`에서 무한매수 이벤트를 `IB_*` 네임스페이스로 강제 정규화.
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 시장 추론(`KS/US`) 헬퍼 추가.
  - daytrade 실행 로그를 `DT_KS_*`, `DT_US_*`로 분리 기록.
  - runtime 로그 파일을 시장별(`runtime_logs_ks.json`, `runtime_logs_us.json`)로 분리.
  - 거래 요약 로그에 `market` 필드 포함하여 미장 필터 정합성 개선.

### 미장 검증/랭킹 API
- `src/app/page.daytrade/api.py`
  - `us_verify_runtime` 체크 항목 강화(가용 시드/자동매매 토글/하드 실패 목록/최근 로그).
  - `us_model_ranking` 추가(전략별 평균 수익률·승률·낙폭·랭크 점수·설명).
  - 미장 일지 기준일을 09:00 KST 세션 앵커로 보정.

### 미장 전용 페이지
- `src/app/page.daytrade.us/api.py` (신규)
  - 미장 부트스트랩/실시간상태/일지/실행검증/모델랭킹 API 구현.
- `src/app/page.daytrade.us/view.ts`
  - 서비스 초기화, 데이터 로딩, 종목 선택, 검증/랭킹 갱신 로직 구현.
- `src/app/page.daytrade.us/view.html`
  - 기존 `Hello, World`를 운영 대시보드형 UI로 교체.

### 환율·수익 집계 보정
- `src/app/page.dashboard/api.py`
  - 09:00 KST 세션 앵커(`session_anchor_9am`) 추가.
  - 기간 기본 종료일을 세션 앵커 기준으로 변경.
  - `ALL` 실계좌 집계에서 KIS `present_balance`의 KRW 원천 필드 우선 사용(환율 이중변환 방지).
  - `profit_summary` 응답에 `session_anchor_9am`, `exchange_rate` 포함.
