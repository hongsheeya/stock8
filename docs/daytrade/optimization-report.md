# Domestic Daytrade Optimization Report

- Generated: 2026-05-04 12:10:15
- Symbol: 047050
- Market: KS
- Strategy: V-REV 역추세
- Period/Interval: 10d / 5m
- Seed: 2,000,000

## Selection Criteria
- Score: summary_score*0.55 + robustness_score*0.45
- Objective: maximize net return while controlling drawdown, turnover, fee drag, and overfitting.

## Strategy State Machine
- Summary: 전일종가 앵커, VWAP, 거래량 지배력을 이용한 눌림-반등형 전략
- Entry: 전일종가 대비 1차/2차 눌림 구간에서 분할 진입
- Entry: VWAP과 거래량 지배력으로 횡보/추세 레짐 구분
- Exit: 평단가 잭팟 전량 청산
- Exit: 기준가 회복 방어 청산 및 구조 복구 청산

## Best Candidate
- Total Return: 27.0333%
- Total Profit: 540665.54
- Win Rate: 55.56%
- Max Drawdown: 0.3195%
- Avg Trades/Day: 9.44
- Profit Factor: 6.2171
- Fee Total: 224318.54
- Avg Holding Minutes: 34.78
- Score: 23.9454

## Validation
- Train/Test Split: 4:5
- Robustness Score: 7.865
- Overfit Gap: 21.6852

## Best Parameters
- breakout_lookback: 20
- breakout_stop_loss_pct: 0.8
- breakout_take_profit_pct: 1.4
- breakout_volume_ratio: 1.2
- budget_ratio: 1.0
- buy_split_ratio: 1.0
- buy_trigger_1_pct: -0.1
- buy_trigger_2_pct: -0.8
- commission_bps: 1.5
- compound_factor: 0.35
- dominance_threshold: 0.45
- force_cut_loss_pct: 8.0
- jackpot_soft_exit_guard_ratio: 0.995
- jackpot_take_profit_pct: 2.0
- ma_fast: 5
- ma_slow: 20
- ma_trend: 60
- max_hold_days: 5
- max_live_day_range_pct: 8.5
- max_live_gap_pct: 5.5
- max_order_cooldown_sec: 20
- min_exit_fee_multiple: 2.0
- min_exit_net_profit_krw: 500
- recent_lot_take_profit_pct: 0.6
- rescue_take_profit_pct: 0.5
- rsi_entry: 34
- rsi_exit: 64
- rsi_exit_overbought: 75
- rsi_period: 14
- sell_tax_bps: 18.0
- slippage_bps: 2.5
- stop_loss_pct: 2.0
- transferred_take_profit_pct: 0.5
- trend_stop_loss_pct: 0.8
- trend_take_profit_pct: 1.2

## Top Candidates
1. strategy=vrev selection=16.7092, score=23.9454, return=27.0333%, mdd=0.3195%, robust=7.865
2. strategy=vrev selection=16.3588, score=23.4106, return=26.4906%, mdd=0.3208%, robust=7.7399
3. strategy=vrev selection=16.1133, score=23.8907, return=30.574%, mdd=0.5263%, robust=6.6075
4. strategy=vrev selection=16.1133, score=23.8907, return=30.574%, mdd=0.5263%, robust=6.6075
5. strategy=vrev selection=16.0851, score=22.8672, return=25.608%, mdd=0.3231%, robust=7.7959