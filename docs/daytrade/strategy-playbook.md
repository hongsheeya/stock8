# Domestic Daytrade Strategy Playbook

## 목적
국내 단타 연구실에서 비교하는 전략 후보군의 진입/청산 상태 머신과 공통 평가 기준을 한 곳에 정리한다.

## 공통 피처 레이어
- `ma_fast`, `ma_slow`, `ma_trend`
- `rsi14`
- `macd`, `macd_signal`, `macd_hist`
- `volume_surge_ratio`
- `intraday_range_pct`
- `gap_from_open_pct`
- `vwap_gap_pct`
- `breakout_high_20`, `breakout_low_20`

## 전략 1. V-REV 역추세
### 진입
- 전일 종가 앵커 대비 1차/2차 눌림 구간 도달
- VWAP/거래량 지배력으로 레짐 확인

### 청산
- 잭팟 전량 청산
- 기준가 회복 방어 청산
- 구조 복구 청산

## 전략 2. 이동평균 추세추종
### 진입
- `ma_fast > ma_slow > ma_trend`
- `macd_hist > 0`
- 거래량 급증과 VWAP 상단 유지

### 청산
- 데드크로스 또는 MACD 약화
- 목표 수익/손절 도달

## 전략 3. RSI 과매도 반등
### 진입
- `rsi14 <= rsi_entry`
- 시가 대비 음의 괴리 확대
- 저점 반등 확인

### 청산
- `rsi14 >= rsi_exit`
- `ma_slow` 또는 VWAP 회복
- 손절선 하향 이탈

## 전략 4. 거래량 돌파
### 진입
- 거래량 급증률 임계치 초과
- 직전 20봉 고점 돌파
- VWAP 상단 유지

### 청산
- 돌파 실패 재이탈
- 목표 수익 또는 손절
- 장마감 평탄화

## 공통 검증 지표
- 총수익률
- 수수료/세금 차감 후 순이익
- 승률
- Profit Factor
- 최대낙폭(MDD)
- 회전율
- 평균 보유시간
- 워크포워드 강건성 점수
- 종목군 교차 검증 점수

## 실거래 안전장치
- KIS 연결 실패 시 신규 주문 차단
- KIS 실시간 시세 미수신 시 실전 주문 차단
- 장중 변동폭/시가 괴리율 과열 구간 차단
- 동일 종목 주문 쿨다운 적용
- 최근 오류/중지 사유와 운영 로그 저장
