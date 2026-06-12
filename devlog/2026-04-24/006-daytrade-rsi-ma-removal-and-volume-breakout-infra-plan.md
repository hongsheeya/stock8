# 단타 RSI/MA 전략 제거 및 Volume Breakout 인프라 계획

- **ID**: 006
- **날짜**: 2026-04-24
- **유형**: 리팩토링

## 작업 요약
국내 단타 전략군에서 `ma_trend`, `rsi_reversion` 모델을 제거하고, 추천/캐시/UI/라이브 시그널 경로가 더 이상 두 전략을 노출하거나 재사용하지 않도록 정리했다.
동시에 `volume_breakout`를 다음 실주문 후보로 올리기 위한 인프라 보강 방향을 정리했다.

## 변경 파일 목록
### 전략/추천 엔진
- `src/portal/trading/model/struct/daytrade.py`
  - `STRATEGIES`에서 `ma_trend`, `rsi_reversion` 제거
  - 시뮬레이션 분기와 프로파일 최적화 그리드에서 두 전략 제거
  - 추천 캐시 키에 `strategy_catalog`를 추가해 구전략 캐시 자동 무효화
  - 기존 추천 산출물 로드 시 제거된 전략이 섞여 있으면 필터링 또는 재학습 유도

### 라이브 엔진
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 라이브 시그널 생성/청산 로직에서 `ma_trend`, `rsi_reversion` 분기 제거
  - 운영 대상 전략을 `vrev`, `volume_breakout` 중심으로 축소

### 프론트엔드
- `src/app/page.daytrade/view.ts`
  - 리더보드 진입 조건 설명에서 삭제된 두 전략 문구 제거

## Volume Breakout 인프라 계획
1. **실시간 분봉 신뢰도 보강**
   - 현재 `volume_breakout`는 분봉 고점/저점/거래량 급증률 품질에 민감하므로, KIS 현재가뿐 아니라 최근 n봉 OHLCV를 KIS 체결/호가 기반으로 보강하는 별도 장중 캔들 조립 계층이 필요하다.
2. **돌파 전용 체결 가드 추가**
   - 돌파 직후 추격매수는 슬리피지에 취약하므로, 주문 직전 `돌파폭`, `VWAP 괴리`, `직전 1~3분 거래대금 증가율`, `호가 스프레드`를 점검하는 `breakout_preflight` 가드가 필요하다.
3. **실주문 제한 단계적 해제**
   - 초기에는 추천/모의 시그널만 기록하고, 일정 기간 동안 `가상 체결가 대비 실제 체결가 오차`, `돌파 실패율`, `첫 3분 되밀림 비율`을 수집한 뒤 조건 충족 시 실주문을 허용하는 단계적 롤아웃이 적합하다.
4. **로그/리포트 분리**
   - `volume_breakout` 전용 런타임 메타(`breakout_high_20`, `breakout_low_20`, `volume_surge_ratio`, `vwap_gap_pct`)를 별도 기록해 실패 원인을 빠르게 분해할 수 있어야 한다.
5. **추천 점수 보정**
   - 현재 공통 점수식 외에 `돌파 유지율`, `시가 후 첫 15분 변동성`, `거래대금 지속성` 같은 돌파 전용 품질 지표를 추가해 `vrev`와 다른 기준으로 후보를 평가하는 것이 바람직하다.
