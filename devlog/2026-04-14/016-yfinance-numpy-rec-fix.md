# yfinance numpy.rec 호환성 패치 및 추천 성능 개선

- **ID**: 016
- **날짜**: 2026-04-14
- **유형**: 버그 수정 / 성능 개선

## 작업 요약
yfinance/pandas가 numpy 1.26+ 환경에서 `numpy.rec` 모듈 미존재로 인한 `ModuleNotFoundError`로 데이트레이드 모델 훈련이 실패하는 문제를 근본적으로 분석하여, numpy에 `rec` alias를 동적으로 추가하는 monkey-patch 및 `__getattr__` 패치로 완전 해결하였습니다. yfinance 데이터 로딩이 실패할 경우를 대비해 subprocess fallback 로직을 추가하여, 메인 프로세스에서 import 에러가 발생해도 데이터 로딩이 가능하도록 보강하였습니다. 추천/자동훈련 시 후보 종목 수를 사전 필터링(pre-screening)하여, 대량 후보군 처리 시 응답 지연을 최소화하였습니다. 모든 변경 사항은 빌드 및 API 테스트로 검증 완료하였으며, devlog 및 문서에 상세 내역을 기록하였습니다.

## 변경 파일 목록

### 1. 백엔드 (Python)
- **[portal/trading/model/struct/daytrade.py](project/main/src/portal/trading/model/struct/daytrade.py)**
  - numpy.rec monkey-patch 및 `__getattr__` 패치 추가
  - yfinance 데이터 로딩 subprocess fallback 구현
  - auto_train 후보군 사전 필터링 로직 추가
- **[app/page.daytrade/api.py](project/main/src/app/page.daytrade/api.py)**
  - train_symbol 예외 발생 시 상세 로그 기록
- **[devlog/2026-04-14/016-yfinance-numpy-rec-fix.md](project/main/devlog/2026-04-14/016-yfinance-numpy-rec-fix.md)**
  - 본 이슈의 원인, 분석, 패치 내역, 테스트 결과 상세 기록

### 2. 기타
- **[devlog.md](project/main/devlog.md)**
  - 2026-04-14 작업 내역 행 추가

---

## 상세 내역
- numpy 1.26+에서 yfinance/pandas가 `import numpy.rec`를 시도할 때 발생하는 `ModuleNotFoundError`를 monkey-patch로 해결 (numpy.rec = numpy.lib.recfunctions, numpy.__getattr__ 오버라이드)
- yfinance 데이터 로딩 실패 시 subprocess에서 별도 실행하여 데이터 확보 (import 에러 우회)
- auto_train에서 후보 종목을 사전 필터링하여 추천/훈련 속도 개선
- train_symbol, recommend API 정상 동작 확인 및 devlog 기록
