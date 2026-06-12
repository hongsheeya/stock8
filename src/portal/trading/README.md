# Trading Package

`portal/trading`은 Stock8의 핵심 도메인 패키지다. 국내 단타, 미국 단타, 무한매수, 브로커 연동, 스케줄 실행, 유지보수 기능이 모두 이 패키지에 모여 있다.

## 담당 범위

- 한국투자증권(KIS) 인증/시세/주문/잔고 조회
- FireGate 포트폴리오 및 사이클 동기화
- 국내 단타 자동매매
- 미국 단타 자동매매
- 레버리지 ETF 무한매수 엔진
- 전략 시뮬레이션 및 결과 저장
- 거래 로그/계좌 스냅샷/일별 요약 관리

## 패키지 구조

```text
src/portal/trading/
├── model/
│   ├── db/
│   │   ├── trading_config.py
│   │   ├── etf_watchlist.py
│   │   ├── trading_cycle.py
│   │   ├── cycle_trade.py
│   │   ├── trade_log.py
│   │   ├── account_snapshot.py
│   │   ├── daily_trade_summary.py
│   │   ├── simulation_run.py
│   │   └── simulation_trade.py
│   ├── kst.py
│   ├── maintenance.py
│   ├── scheduler.py
│   └── struct/
│       ├── daytrade.py
│       ├── daytrade_engine.py
│       ├── engine.py
│       ├── firegate_bridge.py
│       ├── kis_api.py
│       └── strategy.py
├── route/scheduler/
└── libs/i18n.ts
```

## 핵심 모듈

### `model/struct.py`

트레이딩 패키지의 루트 진입점이다. 설정 DB, 워치리스트 DB, 엔진 객체, 브로커 연동 객체를 묶어 제공한다.

### `model/struct/kis_api.py`

실계좌와 직접 맞닿는 계층이다.

- KIS 인증
- 국내/해외 시세 조회
- 매수/매도 주문
- 주문가능금액/잔고 조회
- 체결/주문 상태 확인

### `model/struct/engine.py`

무한매수 엔진이다.

- 사이클 생성/재개/정지
- 회차별 분할 매수
- 목표수익 매도
- LOC 예약 매수/매도
- 추가 매수 확장
- FireGate 연동 사이클 정합성 유지

### `model/struct/daytrade.py`

단타 설정과 상태를 다루는 고수준 인터페이스다.

- 시장별 설정 조회
- 자동매매 ON/OFF 상태 관리
- 추천/활성 포지션/운영 상태 집계
- 화면에서 필요한 단타 상태 조합

### `model/struct/daytrade_engine.py`

단타 자동매매 실행기다.

- 추천 기반 진입 실행
- 자동 청산 감시
- 손절/익절/보호가 처리
- 브로커 보유 종목 동기화
- 시장별 장시간 정책 반영

### `model/struct/firegate_bridge.py`

FireGate를 권위 데이터 소스로 활용해 포트폴리오/사이클/예약 상태를 보정한다.

### `model/struct/strategy.py`

랭킹, 품질 게이트, 추천 필터, 단타 전략 비교 로직을 보조한다.

## 주요 데이터 모델

| 모델 | 설명 |
|------|------|
| `trading_config` | 전역 운용 설정 |
| `etf_watchlist` | 감시 종목/레버리지 ETF 목록 |
| `trading_cycle` | 무한매수 사이클 상태 |
| `cycle_trade` | 사이클 내 체결 기록 |
| `trade_log` | 단타/무한매수 통합 이벤트 로그 |
| `account_snapshot` | 계좌 스냅샷 |
| `daily_trade_summary` | 일별 거래 요약 |
| `simulation_run` | 시뮬레이션 실행 요약 |
| `simulation_trade` | 시뮬레이션 상세 거래 |

## 사용하는 화면

이 패키지는 다음 주요 화면이 사용한다.

- [src/app/page.dashboard](src/app/page.dashboard)
- [src/app/page.daytrade](src/app/page.daytrade)
- [src/app/page.daytrade.us](src/app/page.daytrade.us)
- [src/app/page.infinitebuy](src/app/page.infinitebuy)
- [src/app/page.history](src/app/page.history)
- [src/app/page.simulation](src/app/page.simulation)
- [src/app/page.settings](src/app/page.settings)

## 스케줄 실행

스케줄 엔드포인트는 자동 실행 워커나 외부 호출에서 사용한다.

관련 경로:
- [src/portal/trading/route/scheduler/controller.py](src/portal/trading/route/scheduler/controller.py)
- [src/portal/trading/model/scheduler.py](src/portal/trading/model/scheduler.py)

스케줄은 주로 다음을 담당한다.

- 단타 자동 실행 루프
- 무한매수 사이클 실행
- 요약/정리 배치
- 동기화 작업

## 운영 안전 규칙

- `auto_enabled = false`일 때는 자동 진입뿐 아니라 자동 청산 감시도 멈춰야 한다.
- 브로커/KIS 기준 데이터와 내부 상태가 다르면 브로커 기준을 우선 검토한다.
- 무한매수와 단타는 예산/상태를 분리해서 계산한다.
- 화면에 보이는 수익/자산 지표는 FireGate, 스냅샷, 브로커 응답과 교차 검증한다.

## 관련 테스트

- [tests/test_daytrade_engine_regressions.py](tests/test_daytrade_engine_regressions.py)
- [tests/test_daytrade_recommendation_cache.py](tests/test_daytrade_recommendation_cache.py)
- [tests/test_daytrade_vrev_filters.py](tests/test_daytrade_vrev_filters.py)
- [tests/test_infinite_buy_firegate_v4.py](tests/test_infinite_buy_firegate_v4.py)
- [tests/test_firegate_bridge.py](tests/test_firegate_bridge.py)
- [tests/test_kis_api_buying_power.py](tests/test_kis_api_buying_power.py)

## 참고 문서

- [README.md](../../../README.md)
- [DATABASE_CLEANUP_GUIDE.md](../../../DATABASE_CLEANUP_GUIDE.md)
- [docs/daytrade/architecture.md](../../../docs/daytrade/architecture.md)
- [docs/daytrade/strategy-playbook.md](../../../docs/daytrade/strategy-playbook.md)
