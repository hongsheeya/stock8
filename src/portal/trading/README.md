# Trading Package

Stock8의 계정 분리, 브로커 연결, 무한매수, 관리자용 국내·미국 단타, 손익 집계를 담당합니다. 문서 기준: 2026-10-08.

## 모듈 책임

| 경로 | 책임 |
|---|---|
| `model/struct.py` | 계정 범위 설정·DB·엔진 진입점 |
| `model/account_context.py` | 사용자와 LIVE/PAPER 투자 컨텍스트 |
| `model/paper_subscription.py` | 모의투자 신청·사용 상태 |
| `model/order_policy.py` | 주문 권한과 안전 정책 |
| `model/domestic_market.py` | 국내 시장별 시간·주문 정책 |
| `model/profit_cache.py` | 계좌별 지속성 손익 집계 저장소 |
| `model/scheduler.py` | 자동 실행·동기화 스케줄 |
| `model/struct/kis_api.py` | 토큰, 시세, 주문가능금액, 잔고, 주문·체결 조회 |
| `model/struct/engine.py` | 무한매수 사이클·예약·체결 대조 |
| `model/struct/firegate_bridge.py` | FireGate 연결과 포트폴리오·전략 계획 동기화 |
| `model/struct/daytrade.py` | 추천 캐시, 백테스트·재학습, 단타 설정 |
| `model/struct/daytrade_engine.py` | 시장별 예산, 진입·청산 감시, 보유 종목 대조 |
| `model/selective_strategy.py` | 선택적 단타 전략 실험; 실거래 성능 검증 완료로 해석하지 않음 |

## 계정·데이터 경계

LIVE가 기본이며 PAPER는 별도 신청합니다. 일반 사용자의 단타 접근은 화면뿐 아니라 API에서도 제한합니다. 무한매수·KS 단타·US 단타 활성화는 서로 독립적입니다.

`trading_config`는 단일 전역 설정이 아닙니다. 사용자·투자 모드·계좌 컨텍스트에 맞는 설정, 캐시, DB를 사용해야 합니다. 손익 저장 키도 컨텍스트로 분리합니다. 계정 전환 때 다른 계좌의 토큰·잔고·추천·체결을 재사용하면 안 됩니다.

주요 DB 모델은 `trading_cycle`, `cycle_trade`, `trade_log`, `account_snapshot`, `daily_trade_summary`, `etf_watchlist`, `simulation_run`, `simulation_trade`입니다. 새 실행 데이터와 비밀 정보는 Git에 추가하지 않습니다.

## 데이터의 기준

1. FireGate: 사이클과 주문 **계획**의 입력.
2. KIS: 실제 계좌 잔고, 주문 접수, 미체결·체결 확인.
3. 로컬 DB: 확인된 체결과 상태를 저장하고 화면에 제공하는 기록.

FireGate 계획을 체결로 간주하거나, 불완전한 KIS 조회를 주문 0건으로 간주해 재접수하면 안 됩니다. 주문 대조는 전체 페이지를 확인해야 하며 불확실한 접수 결과는 중복 주문보다 보류를 우선합니다.

## 손익 조회

`profit_cache.Store.summary()`는 과거 구간(오늘 제외, TTL 6시간)과 오늘(TTL 30초)을 분리합니다. 브로커 동기화 성공 결과만 새 집계로 저장합니다. 원가·체결 매칭은 호출자가 담당하며 임의 현금 스냅샷 차액으로 실현손익을 만들지 않습니다.

저장값 읽기와 백그라운드 갱신을 분리하여 반복 조회를 줄입니다. 최초 조회, 만료 후 KIS 동기화, 계정 전환은 캐시 적중과 성능 조건이 다릅니다. 상태·갱신 시각을 함께 확인하세요.

## 단타 추천과 예산

`recommend()`는 유효한 캐시를 재사용하되 만료·누락된 캐시는 재학습으로 연결합니다. 오래된 추천을 무조건 반환하던 우회 경로는 제거했습니다. `auto_train()`의 전체 결과, 데이터 오류, `quality_guard`, `trade_ready_count`를 함께 확인해야 합니다.

자동 생성 `optimization-report.md`는 개별 학습 산출물입니다. 전체 후보의 최종 선택·현재 진입 허용 여부를 대표하지 않습니다. 최신 전체 결과는 계정별 `recommendation.json`입니다.

요청 시드, 주문가능 현금, 미체결 및 무한매수 확보금을 구분합니다. 잠긴 개인 종목이나 무한매수 자산을 임의로 단타 재원으로 전환하면 안 됩니다. 워커 RUNNING은 루프 생존 상태이지 주문 가능·체결 성공을 뜻하지 않습니다.

## 주문 안전 규칙

- OFF에서 자동 진입·청산·정정·취소를 실행하지 않습니다. OFF 전 접수된 주문은 증권사에 남을 수 있습니다.
- 종목 잠금, 전략 소유권, LIVE 동의, 관리자 권한, 시장시간, 예산, 중복 주문 검사를 유지합니다.
- SOXL 무한매수를 단타와 혼용하지 않습니다.
- 테스트·문서 수정·재학습을 위해 실제 계좌 스위치를 켜거나 잠금을 해제하지 않습니다.

## 화면·배포·테스트

- [대시보드](../../app/page.dashboard), [국장 단타](../../app/page.daytrade), [미장 단타](../../app/page.daytrade.us)
- [무한매수](../../app/page.infinitebuy), [이력](../../app/page.history), [설정](../../app/page.settings)
- [스케줄 진입점](route/scheduler/controller.py)
- [회귀 테스트](../../../tests)

실행 서버는 빌드된 `bundle/src`를 사용합니다. 원본 Python 수정만으로 운영 코드가 갱신되었다고 판단하지 마세요. 빌드와 재시작 조건은 [운영 문서](../../../docs/operations.md)를 참고하세요.

남은 문제와 검증 범위는 [2026-10-08 상태](../../../docs/latest-state-2026-10-08.md), 프로젝트 개요는 [루트 README](../../../README.md)에 정리합니다.
