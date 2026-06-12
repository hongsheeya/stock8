# V-REV Hybrid Model Interpretation

## 핵심 해석
V-REV는 단순 추세추종이 아니라, **전일종가 앵커 + VWAP + 거래량 지배력 + LIFO 청킹 매도**를 결합한 역추세 하이브리드 모델로 해석했다.

## State Machine
1. **PREPARE**
   - 전체 시드 중 15%를 당일 활성 예산으로 잠금
   - Buy1 / Buy2를 50:50으로 나눔
   - 전일종가를 day anchor로 설정
2. **DIP ENTRY**
   - 현재가가 전일종가 대비 -0.5% 도달 시 Buy1 개방
   - 현재가가 전일종가 대비 -2.5% 도달 시 Buy2 개방
   - 횡보 구간에서는 VWAP 기준으로 분할 진입
3. **PARALLEL EXIT**
   - Jackpot: 총 평단가 +1.0%면 전량 청산
   - Fee Defense: 최근 lot는 전일종가 +0.6%, 구조대 lot는 총 평단가 +0.5%에서 LIFO 청킹 매도
   - INIT_TRANSFERRED 재고는 개별 평단 +0.5% 전용 규칙 적용 가능
4. **REGIME SWITCH**
   - 1중: 시가/현재가 방향
   - 2중: VWAP 대비 위치
   - 3중: VWAP 위/아래 거래량 55% 지배력
   - 결과를 `STRONG_UP`, `STRONG_DOWN`, `SIDEWAYS`로 단순화
5. **CLOSE / RECONCILE**
   - 강추세장은 종가 집중 모드, 횡보는 VWAP 슬라이싱 유지
   - 장후 CALIB delta만 추가하는 비파괴 보정
   - 수익 일부를 자동 복리 seed로 이관

## 현재 구현상의 적응(Adaptation)
- 실전 원문은 미국장/LOC 중심 설명이지만, 현재 모델은 국내장 연구에 맞춰 **일중 평탄화(day flat)** 중심으로 1차 구현
- `yfinance` 분봉 데이터 제한 때문에 최근 며칠 단위의 실험에 최적화
- 향후 KIS 국내주식 분봉 API로 교체하면 정확도를 높일 수 있음

## 기본 파라미터
- 활성 예산: 15%
- Buy1 Trigger: -0.5%
- Buy2 Trigger: -2.5%
- Jackpot TP: +1.0%
- Recent Lot TP: +0.6%
- Rescue Layer TP: +0.5%
- Dominance Threshold: 55%
- Compound Factor: 35%
