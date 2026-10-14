# Domestic Daytrade Optimization Report

- Generated: 2026-10-14 15:15:15
- Symbol: 114800
- Market: KS
- Strategy: 거래량 돌파
- Period/Interval: 10d / 5m
- Seed: 5,000,000

## Selection Criteria
- Score: summary_score*0.45 + robustness_score*0.35 + graph_stability_score*0.20
- Objective: maximize net return while controlling drawdown, turnover, fee drag, and overfitting.

## Strategy State Machine
- Summary: 오프닝레인지/직전 고점 돌파와 거래량 급증이 함께 나오는 구간을 추종
- Entry: 거래량 급증률 임계치 초과
- Entry: 직전 n봉 고점 돌파 + VWAP 상단 유지
- Exit: 돌파 실패 재이탈
- Exit: 트레일링/장마감 평탄화

## Best Candidate
- Total Return: 0.8905%
- Total Profit: 44524.08
- Win Rate: 50.0%
- Max Drawdown: 1.4563%
- Avg Trades/Day: 1.75
- Profit Factor: 1.6458
- Fee Total: 91217.93
- Avg Holding Minutes: 107.75
- Score: 11.1411

## Validation
- Train/Test Split: 4:4
- Robustness Score: 13.2723
- Overfit Gap: 0.3124
- Graph Stability Score: 4.8973
- Graph Holdout Avg Return: 0.4623%
- Graph Negative Fold Ratio: 0.25

## Best Parameters
- breakout_lookback: 20
- breakout_stop_loss_pct: 0.6
- breakout_take_profit_pct: 1.0
- breakout_volume_ratio: 2.2
- budget_ratio: 1.0
- buy_split_ratio: 1.0
- buy_trigger_1_pct: 0.0
- buy_trigger_2_pct: -0.35
- carry_max_loss_pct: 0.8
- carry_min_close_strength_pct: -1.2
- carry_min_vwap_ratio: 0.997
- carry_overnight_enabled: True
- close_liquidity_take_profit_pct: 0.4
- commission_bps: 1.5
- compound_factor: 0.35
- dominance_threshold: 0.45
- force_cut_loss_pct: 8.0
- jackpot_soft_exit_guard_ratio: 0.995
- jackpot_take_profit_pct: 1.2
- ma_fast: 5
- ma_slow: 20
- ma_trend: 60
- ma_trend_min_trend_alignment_score: 0.12
- max_hold_days: 5
- max_live_day_range_pct: 8.5
- max_live_gap_pct: 5.5
- max_live_vwap_discount_pct: 0.8
- max_order_cooldown_sec: 12
- min_exit_fee_multiple: 1.5
- min_exit_net_profit_krw: 300
- min_live_entry_rsi: 30
- overnight_open_grace_minutes: 18
- overnight_panic_stop_loss_pct: 3.2
- profit_reentry_min_pullback_pct: 0.7
- recent_lot_take_profit_pct: 0.6
- rescue_take_profit_pct: 0.5
- rsi_entry: 34
- rsi_exit: 64
- rsi_exit_overbought: 75
- rsi_period: 14
- rsi_reversion_min_trend_alignment_score: -0.1
- sell_tax_bps: 18.0
- slippage_bps: 2.5
- stop_loss_pct: 1.5
- stop_reentry_same_day_block: True
- transferred_take_profit_pct: 0.5
- trend_stop_loss_pct: 0.8
- trend_take_profit_pct: 1.2
- volume_breakout_min_trend_alignment_score: 0.08
- vrev_entry_max_vwap_discount_pct: 0.5
- vrev_entry_min_rsi: 35
- vrev_entry_min_trend_strength_pct: 0.0
- vrev_entry_require_ma_support: True
- vrev_min_trend_alignment_score: -0.18

## Top Candidates
1. strategy=volume_breakout selection=10.6383, score=11.1411, return=0.8905%, mdd=1.4563%, robust=13.2723
2. strategy=volume_breakout selection=10.6383, score=11.1411, return=0.8905%, mdd=1.4563%, robust=13.2723
3. strategy=volume_breakout selection=10.6383, score=11.1411, return=0.8905%, mdd=1.4563%, robust=13.2723
4. strategy=volume_breakout selection=9.3467, score=9.1855, return=-0.2725%, mdd=1.8142%, robust=12.175
5. strategy=volume_breakout selection=9.3467, score=9.1855, return=-0.2725%, mdd=1.8142%, robust=12.175