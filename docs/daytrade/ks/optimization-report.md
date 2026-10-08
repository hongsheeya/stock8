# Domestic Daytrade Optimization Report

- Generated: 2026-10-08 09:21:52
- Symbol: 252670
- Market: KS
- Strategy: V-REV 역추세
- Period/Interval: 10d / 5m
- Seed: 1,000,000

## Selection Criteria
- Score: summary_score*0.45 + robustness_score*0.35 + graph_stability_score*0.20
- Objective: maximize net return while controlling drawdown, turnover, fee drag, and overfitting.

## Strategy State Machine
- Summary: 전일종가 앵커, VWAP, 거래량 지배력을 이용한 눌림-반등형 전략
- Entry: 전일종가 대비 1차/2차 눌림 구간에서 분할 진입
- Entry: VWAP과 거래량 지배력으로 횡보/추세 레짐 구분
- Exit: 평단가 잭팟 전량 청산
- Exit: 기준가 회복 방어 청산 및 구조 복구 청산

## Best Candidate
- Total Return: 8.9651%
- Total Profit: 89651.44
- Win Rate: 30.0%
- Max Drawdown: 0.0%
- Avg Trades/Day: 2.1
- Profit Factor: 12.3999
- Fee Total: 26465.57
- Avg Holding Minutes: 6.2
- Score: 12.2042

## Validation
- Train/Test Split: 5:5
- Robustness Score: 4.5377
- Overfit Gap: 6.5619
- Graph Stability Score: 1.0072
- Graph Holdout Avg Return: 0.0%
- Graph Negative Fold Ratio: 0.0

## Best Parameters
- breakout_lookback: 20
- breakout_stop_loss_pct: 0.8
- breakout_take_profit_pct: 1.4
- breakout_volume_ratio: 1.2
- budget_ratio: 1.0
- buy_split_ratio: 1.0
- buy_trigger_1_pct: -0.1
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
- jackpot_take_profit_pct: 1.5
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
- rsi_exit_overbought: 70
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
1. strategy=vrev selection=7.2815, score=12.2042, return=8.9651%, mdd=0.0%, robust=4.5377
2. strategy=vrev selection=7.2815, score=12.2042, return=8.9651%, mdd=0.0%, robust=4.5377
3. strategy=vrev selection=7.2815, score=12.2042, return=8.9651%, mdd=0.0%, robust=4.5377
4. strategy=vrev selection=7.2815, score=12.2042, return=8.9651%, mdd=0.0%, robust=4.5377
5. strategy=vrev selection=7.2815, score=12.2042, return=8.9651%, mdd=0.0%, robust=4.5377