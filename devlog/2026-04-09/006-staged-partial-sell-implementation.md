# 단계형 분할 매도 실제 로직 반영

- **ID**: 006
- **날짜**: 2026-04-09
- **유형**: 기능 추가

## 작업 요약
문서로만 정리되어 있던 단계형 분할 매도 규칙을 실제 엔진과 시뮬레이션에 반영했다.
부분 익절 금액이 같은 사이클의 잔여 투자금으로 복원되도록 수정해, 이후 하락 시 기존 무한매수 규칙으로 다시 매수할 수 있게 정리했다.

## 변경 파일 목록
### 백엔드 전략/엔진
- `src/portal/trading/model/struct/strategy.py`
  - 회차별 단계형 분할 매도 규칙(11~20회차 5%/20%, 21~30회차 4%/30%, 31회차+ 3%/40%) 적용
  - 백테스트에서 부분 익절 후 자금을 같은 사이클 `cycle_remaining`으로 복원
- `src/portal/trading/model/struct/engine.py`
  - 최종 목표 수익률 이전에도 단계형 부분 익절이 가능하도록 매도 판단 로직 수정
  - 분할 매도 체결 후 `remaining_investment`와 `total_investment`를 갱신해 재매수 자금 복원

### API 연동
- `src/app/page.settings/api.py`
  - 설정 화면에 고정 단계형 분할 매도 규칙 전달
  - 더 이상 사용하지 않는 옛 분할 매도 슬라이더 저장 제거
- `src/app/page.simulation/api.py`
  - 시뮬레이션/전략 비교에서 고정 단계형 분할 매도 규칙 사용

### 프론트엔드 UI
- `src/app/page.settings/view.ts`
- `src/app/page.settings/view.pug`
  - 조절식 슬라이더 대신 고정 규칙 안내형 UI로 변경
- `src/app/page.simulation/view.ts`
- `src/app/page.simulation/view.pug`
  - 전략 비교 UI를 고정 단계 규칙 표시 방식으로 변경
- `src/portal/trading/libs/i18n.ts`
  - 단계형 부분 익절 및 재매수 설명 문구 추가

## 검증
- 변경 파일 진단 오류 없음 확인
- WIZ 프로젝트 `main` 일반 빌드 성공
