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
