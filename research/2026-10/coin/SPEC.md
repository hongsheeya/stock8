STATUS: SHADOW ONLY. Build one code path with LIVE_ORDERS=false: compute signals, log hypothetical orders, place no orders. Flip the flag only after promotion gates G1 and G2 (section 11) pass. Parameters are FROZEN: do not tune them on shadow or new history.

RULE: breakout 4h_N55_atr2, as pre-registered and selected on TRAIN in research/breakout/breakout_wf.py.

1. MARKETS
KRW-BTC, KRW-ETH, KRW-XRP, KRW-SOL, KRW-DOGE. Each coin is an independent sleeve.
DOGE carries a cost flag: its tick is 1 KRW at about 110 KRW, about 0.9% per tick. Keep DOGE in shadow and decide on it at promotion.

2. DATA
- Source: Upbit REST GET /v1/candles/minutes/5, paged with `to`.
- Persist per market: t = candle_date_time_utc (bar open), o, h, l, c, volume.
- Keep at least 70 days of 5m history, for SMA50 daily plus 55 x 4h Donchian plus ATR warm-up.
- 4h bars: build them from 5m candles, bucket = floor(utc_epoch_seconds / 14400).
  - Boundaries are 00/04/08/12/16/20 UTC (= 09/13/17/21/01/05 KST).
  - o = first 5m open, h = max high, l = min low, c = last close.
  - Do NOT use Upbit /v1/candles/minutes/240 unless you verify its UTC boundaries are identical. A 3h phase shift moved the backtest FULL year from +1.17% to -2.09%.
- Daily close: close of the last 5m bar of each UTC day. The UTC day 00:00-24:00 is Upbit's 09:00 KST daily candle.

3. INDICATORS (per coin, closed 4h bars only, counting existing bars only)
- HH55[j] = max(high[j-55 .. j-1]). It excludes bar j.
- TR[j] = max(h-l, |h - c[j-1]|, |l - c[j-1]|).
- ATR14 = Wilder recursion (alpha = 1/14), seeded with the SMA of the first 14 TR values. With 300+ bars of history the seed is irrelevant.
- SMA50D[j] = mean of the last 50 completed daily closes whose day END <= END of bar j. The 20:00-24:00 UTC bar therefore includes that same day's close.
- A coin is "not ready" if it has fewer than 50 daily closes, fewer than 56 4h bars, or ATR is undefined. Never enter when not ready.

4. WAKE SCHEDULE
- W1, 4h decision: at every T in {00,04,08,12,16,20}:00:00 UTC, wake at T+10s.
  - Fetch 5m candles up to T. Drop any candle with start >= T, because it is in progress.
  - Bar j = [T-4h, T).
  - A 5-15 minute fill delay was tested: TEST went to +5.94% at +5m and +7.24% at +15m, so a small delay is fine. Do not exceed about 15 minutes.
- W2, stop watcher: runs continuously while any sleeve is long.
  - Primary feed: Upbit WebSocket `trade` (or `ticker`) for the held markets.
  - Fallback: REST /v1/ticker every 2 s.
- W3, daily housekeeping at 00:00:30 UTC: append the daily close, recompute SMA50D, reconcile the ledger with /v1/accounts, write the daily report.

5. DECISION AT EACH 4h CLOSE (per coin)
a) If long, ratchet the stop:
   - hh = max(hh, high[j])
   - stop = max(stop, hh - 2.0 * ATR14[j])
   - The stop is constant for the whole next 4h bar.
b) If flat, enter when all of these hold:
   - the coin is ready
   - close[j] > HH55[j]
   - close[j] > SMA50D[j]
   "Flat" includes a sleeve stopped out during bar j.
   On ENTRY:
   - Buy now. The target fill is the next 4h bar's open.
   - Set hh = high[j] and stop = high[j] - 2.0 * ATR14[j].
   - If the best bid is already <= stop at the moment of entry, SKIP and log SKIP_BELOW_STOP. The backtest would book an immediate round trip whose only loss is the costs.

6. EXIT
- The only exit is the trailing stop. There is no take-profit and no time stop.
- Live trigger: the first observed trade price <= stop. Then market-sell the sleeve's full volume.
- Also log the model fill for fidelity: min(open, stop) of the first 5m bar whose low <= stop.
- One position per coin.
- Re-entry is allowed at any later 4h close, including the close of the bar in which the stop fired.

7. ORDERS (pilot only; in shadow, log the hypothetical order plus best bid/ask and last trade at decision time)
- Entry: market buy, ord_type=price, KRW amount = floor(sleeve_cash * (1 - 0.0005)). Skip if the amount is below 5,000 KRW.
- Exit: market sell, ord_type=market, volume = sleeve volume from the ledger, capped by the available balance.
- No limit orders in v1. The P&L comes from a few breakout days, so a missed fill costs more than slippage.
- Idempotency: identifier = market + bar_end_iso + side.
- Poll GET /v1/order until state=done. Record executed volume, average price and paid fee.
- Retry at most 3 times, then alert.

8. SIZING
- Total seed S. Each sleeve starts with S/5.
- A sleeve is all-in when long and all cash when flat. It compounds independently and is never rebalanced.
- Track sleeves in the worker's own ledger, because the exchange KRW balance is shared.
- Pilot S = 1,000,000 KRW (200,000 per coin).

9. MISSING DATA / FAILURES
- 5m candles absent because nothing traded: normal. Build the 4h bar from the candles that exist.
- A 4h bucket with no 5m candles at all: no bar and no synthetic bar. Indicators count existing bars only.
- Freshness check at W1:
  - If Upbit ticker trade_timestamp shows trades in [T-5m, T) but that candle is missing, refetch up to 3 times within 60 s.
  - If it is still missing, mark the bar DATA_INCOMPLETE: no new entry for that bar, and keep the previous stop without raising it.
- Stop feed silent for more than 30 s while long:
  - Switch to REST polling.
  - If REST also fails, ALERT.
  - On recovery, if price <= stop, sell immediately and log the gap.
- Restart:
  - Backfill candles over REST.
  - Restore sleeve state from the persisted ledger: flat/long, signal bar, entry time/price/volume, hh, stop.
  - Reconcile with /v1/accounts.
  - Recompute hh = max(high) over closed 4h bars since the signal bar (inclusive), then stop = max(persisted stop, hh - 2*ATR14 at the last closed bar).
- Market warning, suspension or maintenance: no new entries in that market. If long, apply the stop as soon as trading resumes. ALERT.

10. LOGGING
- Every 4h decision, with all indicator values and signal booleans.
- Every real or hypothetical order: model price, observed best bid/ask, last trade, fill.
- Stop levels per bar.
- Daily sleeve and portfolio equity.
- Weekly: replay the same period offline with breakout_wf.simulate and report the trade-match rate and slippage versus the model.

11. PROMOTION GATES (pre-registered; both must pass, no parameter changes)
- G1, out-of-sample history:
  - Run the frozen rule unchanged on Upbit 5m data from 2019-10-21 to 2025-10-21, or from each market's KRW listing date if later.
  - Cost: 0.10% per side plus half a tick per side.
  - Pass if all three hold: portfolio CAGR > 0; at least 4 of 6 years >= 0%; portfolio MDD >= -15%.
  - If G1 fails, retire the family. No re-tuning without a new pre-registration.
- G2, shadow:
  - At least 8 weeks and at least 15 shadow entries.
  - At least 90% of shadow entries and exits match the offline replay: same entry 4h bar, and stop exit in the same 5m bar.
  - Median observed slippage versus model <= 0.15% per side on BTC/ETH/XRP/SOL.
- Pilot, once promoted:
  - S = 1,000,000 KRW.
  - Kill switch: halt new entries and alert if pilot equity falls 10% below its peak, or if the average realized round-trip cost exceeds 0.50%.
  - Review after 30 trades.

12. SECONDARY DASHBOARD (no orders)
At 00:00 UTC each day, log the regime B100 state per coin: coin daily close > SMA100(coin) AND BTC close > SMA100(BTC). It is a risk-regime indicator only.

13. AUDIT FILES
- research/breakout/breakout_wf.py: reference engine.
- My decision check: research/final/spread_check.py and spread_check_output.txt, under C:\Users\변기국~1\AppData\Local\Temp\claude\C--dev\93ae6530-93fd-4894-8774-b698a96bffc9\scratchpad\coin\.