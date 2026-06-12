# 학습 실패 fallback 처리 및 실거래 매커니즘 문서화

- **ID**: 015
- **날짜**: 2026-04-14
- **유형**: 버그 수정 / 문서 업데이트

## 작업 요약
추천/학습 과정에서 `학습 가능한 국내 종목 후보를 찾지 못했습니다.` 예외가 발생하더라도 화면 전체를 실패로 만들지 않도록 fallback을 추가했습니다. 자동 추천은 기존 추천 또는 기본 종목 유지로 폴백하고, 개별 종목 학습 실패는 오류 대신 제외 처리로 반환하도록 변경했습니다.

또한 실제 매수부터 매도, 예약 매도, 손절, 수수료 손익분기 방어, 워커 동작까지 포함한 실거래 매커니즘 상세 문서를 별도 파일로 작성했습니다.

## 변경 파일 목록

### 백엔드
- `src/portal/trading/model/struct/daytrade.py`
  - `read_docs()`에 `live-trading-mechanism.md` 노출 추가
  - `_fallback_recommendation()` 추가
  - `recommend()` 예외 시 fallback 추천 반환
  - `auto_train()` 전체 실패 시 예외 대신 fallback 추천 저장/반환
- `src/app/page.daytrade/api.py`
  - `train_symbol()` 실패 시 400 대신 `skipped=true` 결과 반환

### 프론트엔드
- `src/app/page.daytrade/view.ts`
  - 추천 fallback 사유 메시지 노출
  - 개별 종목 학습 실패 시 제외 처리 메시지 노출

### 문서
- `docs/daytrade/live-trading-mechanism.md`
  - 예산 계산, 진입/청산 규칙, 예약 매도, 손절, 수수료 손익분기, 위험 제어, 워커 동작 정리

## 검증
- 일반 빌드 성공
- `train_symbol(symbol=999999)` → `skipped=true` 정상 반환
- `recommend(force=true)` → 500 없이 정상 응답
