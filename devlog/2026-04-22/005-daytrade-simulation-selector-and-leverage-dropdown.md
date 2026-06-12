# 단타 시뮬레이션 종목 선택 복구 및 3배 레버리지 드롭다운 추가

- **ID**: 005
- **날짜**: 2026-04-22
- **유형**: 버그 수정

## 작업 요약
단타 연구실에서 사라졌던 시뮬레이션 종목 선택 흐름을 다시 노출하고, SOXL·TQQQ 계열 3배 레버리지 종목을 상단 드롭다운에서 바로 고를 수 있게 복구했다.
함께 `daytrade_engine.py` 안에 남아 있던 중복 `period_trade_summary()`, `daily_trade_summary()`, `auto_enabled()` 정의를 제거해 그림자 코드 리스크를 줄였다.

## 변경 파일 목록
### 프론트엔드
- `src/app/page.daytrade/view.ts`
  - 시뮬레이션 프리셋 상태와 선택 핸들러 추가
  - 시뮬레이션 전용 종목일 때 실주문/즉시매도 차단 가드 추가
- `src/app/page.daytrade/view.pug`
  - 상단 3배 레버리지 빠른 선택 드롭다운 추가
  - 시뮬레이션 전용 배지 및 안내 문구 추가

### API / 모델
- `src/app/page.daytrade/api.py`
  - bootstrap 응답에 시뮬레이션 프리셋 목록 포함
- `src/portal/trading/model/struct/daytrade.py`
  - 3배 레버리지 시뮬레이션 프리셋 정의 및 검색 연동 추가
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 중복 정의된 기간 요약/일일 요약/자동매매 활성 상태 메서드 제거

### 기록
- `devlog.md`
  - 2026-04-22 작업 요약 행 추가
