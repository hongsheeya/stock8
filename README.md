# Stock8

Stock8은 한국투자증권(KIS) 연동을 기반으로 국내·미국 주식 자동매매를 운영하는 WIZ 프로젝트다. 이 저장소의 중심은 프레임워크 소개가 아니라, 실제 매매 전략을 실행·관찰·검증하는 주식 자동화 시스템 자체에 있다.

## 한눈에 보는 프로젝트

- 국내 단타 자동매매 운영
- 미국 단타 자동매매 운영
- 레버리지 ETF 무한매수 사이클 운영
- 대시보드 기반 실계좌/전략 상태 모니터링
- 거래 이력, 시뮬레이션, 설정, 유지보수 도구 제공
- FireGate 동기화 및 한국투자증권 API 연동

## 핵심 기능

### 1. 대시보드

대시보드는 전체 운용 현황을 한 화면에서 보는 운영 콘솔이다.

- 총자산, 실현손익, 미실현손익, 오늘 손익 요약
- 국내/미국 단타 상태 카드
- 무한매수 진행 사이클과 예약 주문 현황
- FireGate 기준 포트폴리오 동기화 상태 확인
- 자동매매 ON/OFF, 즉시 실행, 수동 제어 진입점 제공

관련 화면:
- [src/app/page.dashboard](src/app/page.dashboard)

### 2. 국내 단타 자동매매

국내 단타 모듈은 장중 추천, 진입, 재진입 쿨다운, 손절/익절, 실시간 상태 추적을 포함한다.

- 학습 기반 추천 종목 캐시
- 자동 진입/자동 청산 감시
- 수동 매도/보호가/목표가 보정
- 일중 로그 및 거래일지 추적
- OFF 시 매도 감시까지 중단하는 안전 가드 적용

관련 화면/로직:
- [src/app/page.daytrade](src/app/page.daytrade)
- [src/portal/trading/model/struct/daytrade.py](src/portal/trading/model/struct/daytrade.py)
- [src/portal/trading/model/struct/daytrade_engine.py](src/portal/trading/model/struct/daytrade_engine.py)

### 3. 미국 단타 자동매매

미국 단타는 국내 단타와 분리된 화면과 운용 설정을 가지며, 해외 주문가능금액·환전·시장시간 차이를 반영한다.

- 미국장 전용 추천/랭킹
- USD/KRW 예산 반영
- 장 마감 정책 및 자동 청산 정책 분리
- 국내 단타와 독립적인 ON/OFF 및 운영 로그

관련 화면:
- [src/app/page.daytrade.us](src/app/page.daytrade.us)

### 4. 무한매수 엔진

레버리지 ETF 중심의 사이클형 자동매매 엔진이다.

- 분할 매수 사이클 관리
- LOC 예약 매수/매도
- 추가 매수 확장(PENDING_EXTENSION)
- 분할 매도, 폭락장 추가매수, 수수료 반영
- FireGate 포트폴리오와 정합성 유지

관련 화면/로직:
- [src/app/page.infinitebuy](src/app/page.infinitebuy)
- [src/portal/trading/model/struct/engine.py](src/portal/trading/model/struct/engine.py)
- [src/portal/trading/model/struct/firegate_bridge.py](src/portal/trading/model/struct/firegate_bridge.py)

### 5. 시뮬레이션과 연구

실매매 전 전략 검증을 위해 시뮬레이션과 알고리즘 연구 문서를 함께 유지한다.

- 전략별 백테스트 실행
- 시뮬레이션 결과 저장 및 비교
- 추천 필터, 품질 게이트, V-REV/볼륨 전략 검증

관련 화면/문서:
- [src/app/page.simulation](src/app/page.simulation)
- [docs/daytrade](docs/daytrade)
- [tests](tests)

### 6. 거래 이력과 운영 추적

거래 이력 화면은 단순 로그 모음이 아니라 운영 복기 도구다.

- 사이클 단위 거래 조회
- 일별/종목별 거래 로그 확인
- 계좌 스냅샷과 실현손익 검증
- 브로커 동기화 결과 추적

관련 화면:
- [src/app/page.history](src/app/page.history)

### 7. 설정/운영 관리

설정 화면에서 API 연결, 감시 종목, 예산, 자동매매 옵션, 데이터 유지보수 작업을 관리한다.

- KIS 연결 정보 관리
- 종목/워치리스트 관리
- 단타·무한매수 파라미터 설정
- DB 정리 및 요약 재생성 도구
- 위험한 자동매매 활성화 시 경고 모달 제공

관련 화면:
- [src/app/page.settings](src/app/page.settings)

## 주요 라우트

| 경로 | 용도 |
|------|------|
| `/dashboard` | 통합 운용 대시보드 |
| `/daytrade` | 국내 단타 운영 |
| `/daytrade/us` | 미국 단타 운영 |
| `/infinite-buy` | 무한매수 운영 |
| `/history` | 거래 이력/로그/스냅샷 |
| `/simulation` | 전략 시뮬레이션 |
| `/settings` | API/예산/감시종목/유지보수 설정 |
| `/access` | 로그인 |

## 저장소 구조

이 프로젝트에서 중요한 디렉토리는 다음과 같다.

```text
src/
├── app/
│   ├── page.dashboard/        # 통합 대시보드
│   ├── page.daytrade/         # 국내 단타
│   ├── page.daytrade.us/      # 미국 단타
│   ├── page.infinitebuy/      # 무한매수
│   ├── page.history/          # 거래 이력
│   ├── page.simulation/       # 시뮬레이션
│   ├── page.settings/         # 설정/유지보수
│   └── component.nav.trading/ # 트레이딩 전용 네비게이션
│
├── model/
│   └── struct.py              # 프로젝트 루트 모델 진입점
│
├── portal/
│   ├── season/                # 공통 프레임워크/세션/서비스
│   └── trading/               # 실질적인 자동매매 도메인 패키지
│       ├── model/db/          # 거래 DB 스키마
│       ├── model/struct/      # 엔진, 브로커 연동, 전략
│       ├── route/scheduler/   # 스케줄 실행 엔드포인트
│       └── README.md          # trading 패키지 상세 설명
│
├── assets/                    # 아이콘/정적 자산
└── types/                     # 프런트엔드 타입 선언

tests/                         # 회귀 테스트
docs/daytrade/                 # 단타 알고리즘/운영 문서
devlog/                        # 날짜별 작업 기록
```

## 아키텍처 요약

### 운영 흐름

1. 화면에서 설정/실행 요청
2. 페이지 `api.py` 또는 스케줄 route 호출
3. `portal/trading` 모델이 브로커/KIS/FireGate/DB와 상호작용
4. 엔진이 주문 계획·진입·청산·로그를 처리
5. 결과가 대시보드/이력/설정 화면에 반영

### 핵심 도메인 계층

- `kis_api.py`: 한국투자증권 API 인증, 잔고, 주문, 시세
- `engine.py`: 무한매수 엔진
- `daytrade.py`: 단타 운용 설정·상태 진입점
- `daytrade_engine.py`: 단타 매수/매도 트리거 실행기
- `firegate_bridge.py`: FireGate 포트폴리오 동기화
- `strategy.py`: 전략 규칙/랭킹 계산 보조

## 데이터 저장

주요 테이블:

- `trading_config`: 전역 운용 설정
- `etf_watchlist`: 감시 종목 목록
- `trading_cycle`: 무한매수 사이클
- `cycle_trade`: 사이클 단위 체결 기록
- `trade_log`: 단타/무한매수 통합 거래 이벤트 로그
- `account_snapshot`: 계좌 스냅샷
- `daily_trade_summary`: 일일 요약
- `simulation_run`, `simulation_trade`: 시뮬레이션 기록

데이터 정리 정책은 [DATABASE_CLEANUP_GUIDE.md](DATABASE_CLEANUP_GUIDE.md)에 정리되어 있다.

## 안전 원칙

- 자동매매 `OFF`는 “아무것도 하지 않음”이 원칙이다.
- 단타 ON 전환은 경고 모달을 통해 명시적으로 확인한다.
- 실계좌 상태는 브로커/KIS/FireGate 기준과 지속적으로 대조한다.
- 런타임 산출물과 실거래 상태 파일은 `data/` 아래에 쌓이며, Git 커밋 대상에서 제외하는 것을 기본으로 한다.

## 테스트

주요 회귀 테스트:

- [tests/test_daytrade_engine_regressions.py](tests/test_daytrade_engine_regressions.py)
- [tests/test_dashboard_accounting_regressions.py](tests/test_dashboard_accounting_regressions.py)
- [tests/test_firegate_bridge.py](tests/test_firegate_bridge.py)
- [tests/test_kis_api_buying_power.py](tests/test_kis_api_buying_power.py)
- [tests/test_infinitebuy_loc_schedule_regressions.py](tests/test_infinitebuy_loc_schedule_regressions.py)

## 함께 보면 좋은 문서

- [docs/latest-state-2026-06-30.md](docs/latest-state-2026-06-30.md)
- [src/portal/trading/README.md](src/portal/trading/README.md)
- [docs/daytrade/architecture.md](docs/daytrade/architecture.md)
- [docs/daytrade/live-trading-mechanism.md](docs/daytrade/live-trading-mechanism.md)
- [docs/daytrade/strategy-playbook.md](docs/daytrade/strategy-playbook.md)
- [devlog.md](devlog.md)

## 주의

이 저장소는 게시판/회원관리 샘플 페이지를 일부 포함하지만, 현재 프로젝트의 본체는 주식 자동화 도메인이다. 문서와 변경 설명은 반드시 자동매매 시스템 관점에서 작성한다.
