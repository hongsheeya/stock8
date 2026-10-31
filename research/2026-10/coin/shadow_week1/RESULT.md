# Coin shadow run, week 1 (10-24 23:01 → 10-31 11:00)

ATR×4 rule. Main = 4 coins (BTC/ETH/XRP/SOL). Probe = 10 coins, shadow only.

- **Main 4 coins: no trades.** All were below the 50-day SMA and the 55-bar high for the whole week, and the replay agrees.
  - Hold return over the week: BTC -2.8%, ETH -2.6%, XRP -0.9%, SOL -3.1%.
  - Distance to an entry today: +8% to +14% (BTC needs +8.4% for the breakout and +6.5% for the SMA).
- **Probe: 1 trade, matched the replay** (1/1).
  - KRW-TRX entered 10-30 09:00 at ₩498 and hit the stop (₩477.2) at 12:54–12:55.
  - The shadow sold at 13:23:55 at ₩469 (-5.9%).
- **Coverage: 36/39 bars (92.3%).** The PC slept 10-26 23:59 → 10-27 09:18, so 3 decision bars were missed.
- **Slippage: entry 0.40%, exit 1.72%** (gate ≤ 0.15%).
  - The exit was 29 minutes late because Windows idle sleep (Kernel-Power 42, reason 7) suspended the PC from 11:51 to 13:21.
  - The entry 0.40% is about two ticks on a ₩500 coin.
- **PC sleep since 10-24:** 0.5–14 h asleep per day, including KS hours (10-26 12:56–13:54, 10-30 11:51–13:21) and the US open (10-29 20:59 → 10-30 00:00).
  - The 'Stock8 Paper Trading' task wakes the PC about every 5 minutes, but it goes back to sleep.

Run: `python research/2026-10/coin/shadow_week1/check_shadow.py` from the deploy folder (read-only).
