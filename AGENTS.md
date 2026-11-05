# Stock8 작업 메모

이 저장소는 WIZ 예제 설명용 저장소가 아니라, 국내·미국 주식 자동매매를 운영하는 Stock8 프로젝트다.

## 우선 기준

1. 프레임워크 구조 설명보다 트레이딩 제품 동작을 우선 이해한다.
2. 문서 작성 시 WIZ 일반론이 아니라 이 프로젝트의 전략, 화면, 데이터 흐름을 기준으로 쓴다.
3. 자동매매 안전 규칙을 깨는 변경은 금지한다.

## 핵심 도메인

- 대시보드: 전체 운용 현황과 수동 제어
- 국내 단타: 실시간 추천·진입·청산
- 미국 단타: 별도 예산/시장시간/운영 정책
- 무한매수: ETF 사이클형 자동매매
- 시뮬레이션: 전략 검증
- 이력/설정: 복기, 유지보수, API 연결

## 주요 경로

- `src/app/page.dashboard/`
- `src/app/page.daytrade/`
- `src/app/page.daytrade.us/`
- `src/app/page.infinitebuy/`
- `src/app/page.history/`
- `src/app/page.settings/`
- `src/portal/trading/`

## 작업 원칙

- `OFF`는 무동작이어야 한다. 정리, 강제청산, 예약취소를 자동으로 하지 않는다.
- 브로커/KIS/FireGate 기준 데이터 정합성을 우선한다.
- 런타임 데이터(`data/`)는 기본적으로 커밋하지 않는다.
- 문서도 프로젝트 실동작 기준으로 유지한다.

## 참고

- 상세 작업 규칙은 `/opt/app/.github/copilot-instructions.md`를 따른다.
- 프로젝트 개요는 [README.md](README.md)를 먼저 본다.
- 트레이딩 패키지 설명은 [src/portal/trading/README.md](src/portal/trading/README.md)를 본다.

## 기능별 에이전트

`.claude/agents/`에 기능별 Claude Code 서브에이전트가 있다. 해당 기능을 수정·조사할 때 그 에이전트에 맡기고, 주문 경로 변경은 `stock8-order-safety` 기준으로 함께 점검한다.

| 에이전트 | 담당 |
|---|---|
| `stock8-infinitebuy` | 무한매수 사이클, LOC 예약·리버스·MOC, FireGate, 체결 동기화 |
| `stock8-daytrade-ks` | 국내 단타 추천·재학습·진입·청산, KRX/NXT 라우팅 |
| `stock8-daytrade-us` | 미국 단타, USD 예산·시장시간·MOC, PAPER 미국 추세보유 |
| `stock8-coin` | 업비트 코인 자동매매(관리자·LIVE 전용) |
| `stock8-dashboard` | 대시보드·이력·설정·계정·배당, 빌드·배포 |
| `stock8-research` | 시뮬레이션, 사전 등록 연구, 읽기 전용 감사 스크립트 |
| `stock8-order-safety` | 주문 안전 경계, 주문 건별 거래 검증·매수 보류 |

모든 에이전트는 결론을 한국어로 보고하고, OFF 무동작·브로커 기준 정합성·`data/` 비커밋 원칙을 지키며, 실계좌 스위치·잠금·재시작은 사용자 지시 없이 하지 않는다.
