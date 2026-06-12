# Volume Breakout 쉐도우 모드, 로깅 및 점수식 구현

- **ID**: 012
- **날짜**: 2026-04-27
- **유형**: 기능 추가

## 작업 요약
'volume_breakout' 전략의 안정성과 분석력을 강화하기 위해 쉐도우 모드, 상세 로깅, 전용 점수식 기능을 구현했습니다.
- **쉐도우 모드**: 실주문 없이 가상 체결을 통해 전략의 성과를 검증하고 데이터를 수집합니다.
- **상세 로깅**: 백테스팅 시 실패 원인, 돌파 후 되밀림 등 핵심 지표를 기록하여 사후 분석을 용이하게 합니다.
- **전용 점수식**: 돌파 유지율, 거래량 지속성 등을 종합한 'shadow_mode_score'를 도입하여 전략의 품질을 객관적으로 평가합니다.

## 변경 파일 목록
### 모델
- `project/main/src/portal/trading/model/struct/daytrade_engine.py`
  - `_signal_from_state` 메서드에 쉐도우 모드 로직을 추가하여, 실제 매수 신호 대신 'HOLD' 신호를 보내고 가상 체결 정보를 기록하도록 수정했습니다.
- `project/main/src/portal/trading/model/struct/daytrade.py`
  - `_simulate_volume_breakout_session` 메서드에 실패 원인 분석, 되밀림 비율 계산 로직을 추가했습니다.
  - `custom_metrics`에 상세 지표들을 추가하고, 이를 기반으로 `shadow_mode_score`를 계산하는 로직을 구현했습니다.
