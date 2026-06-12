# Domestic Daytrade Optimization Report

- Generated: 2026-06-11 04:17:26
- Symbol: IONQ
- Market: US
- Strategy: US 프리마켓 갭업 하따
- Period/Interval: 10d / 5m
- Seed: 1,000,000

## Selection Criteria
- Score: summary_score*0.45 + robustness_score*0.35 + graph_stability_score*0.20
- Objective: maximize net return while controlling drawdown, turnover, fee drag, and overfitting.

## Strategy State Machine
- Summary: 프리마켓 갭업(+5% 이상) 후 본장 초입 되밀림 구간에서 진입, 3-4% 분할 익절 전략
- Entry: 프리마켓 +5% 이상 갭업 후 본장 시작 직후 (-3~-10%) 되밀림 진입
- Entry: 5분봉 기준 거래대금 $2M 이상, VWAP 상단 유지 확인
- Exit: 1차 +3% 익절 (절반 매도)
- Exit: 2차 진입가 대비 +4~6% 잔량 청산 또는 LOC 마감 청산
- Exit: 고점 대비 -20% 또는 진입가 대비 -8% 손절

## Best Candidate
- Total Return: 4.2483%
- Total Profit: 42482.54
- Win Rate: 10.0%
- Max Drawdown: 0.0%
- Avg Trades/Day: 0.6
- Profit Factor: 4.6931
- Fee Total: 22498.48
- Avg Holding Minutes: 7.5
- Score: 7.0323

## Validation
- Train/Test Split: 5:5
- Robustness Score: 3.7039
- Overfit Gap: 4.2483
- Graph Stability Score: -0.5242
- Graph Holdout Avg Return: 0.0%
- Graph Negative Fold Ratio: 0.0

## Best Parameters
- breakout_lookback: 20
- breakout_volume_ratio: 3.0
- budget_ratio: 1.0
- buy_split_ratio: 0.5
- commission_bps: 25.0
- entry_drawdown_max_pct: 3.0
- entry_drawdown_min_pct: 0.0
- high_stop_pct: 20.0
- jackpot2_take_profit_pct: 5.0
- jackpot_take_profit_pct: 2.5
- ma_fast: 5
- ma_slow: 20
- max_live_day_range_pct: 30.0
- max_live_gap_pct: 50.0
- max_order_cooldown_sec: 30
- min_change_pct: 5.0
- min_prior_surge_pct: 10.0
- min_volume_usd: 2000000
- premarket_gap_min_pct: 2.5
- rsi_period: 14
- sec_fee_per_million_usd: 8.0
- sell_commission_bps: 25.0
- shadow_mode: False
- slippage_bps: 3.0
- stop_loss_pct: 3.0

## Top Candidates
1. strategy=us_premarket selection=4.3561, score=7.0323, return=4.2483%, mdd=0.0%, robust=3.7039
2. strategy=us_premarket selection=4.3561, score=7.0323, return=4.2483%, mdd=0.0%, robust=3.7039
3. strategy=us_premarket selection=4.3561, score=7.0323, return=4.2483%, mdd=0.0%, robust=3.7039
4. strategy=us_premarket selection=4.3561, score=7.0323, return=4.2483%, mdd=0.0%, robust=3.7039
5. strategy=us_premarket selection=4.3561, score=7.0323, return=4.2483%, mdd=0.0%, robust=3.7039