"""Bar-replay of the LIVE domestic auto path (research only, no broker calls).

What it reproduces (daytrade_engine.py, KS, auto mode), per completed bar:

Entry (_signal_from_state BUY1 + _vrev_preflight_check + market guards):
  * one slot: the first KS slot receives the whole seed, qty = int(seed*0.985/price)
  * anchor = max(session prev_close, open, VWAP); the live dataset is period=1d,
    so the session prev_close is the day's first open -> anchor = max(open, VWAP)
  * price <= anchor*(1+buy_trigger_1_pct/100) and Daytrade.vrev_entry_issues()==[]
  * |price/open-1| < max_live_gap_pct, bar range < max_live_day_range_pct
  * re-entry: 1800s after SELL_*, same-day block after a stop (3600s otherwise),
    -0.7% pullback after a profit market exit; NO cooldown after a reserved
    limit (PRE_SELL_JACKPOT) fill, because the fill is relabelled (E:895)
  * volume_breakout: PAPER only (LIVE default shadow_mode=True never orders)
Exit (kr_execute_exit_watch fast path, the only path that runs for held slots):
  * pending reserved limit sell -> HOLD (stop is NOT evaluated) until it fills;
    it expires at the session end and the next session resets the state
  * price <= avg*(1-stop_loss_pct/100) -> market sell
  * vrev: price >= avg*(1+jackpot%) -> market sell; >= jackpot*0.995 -> limit
    sell reserved at the jackpot price
  * no end-of-day flatten (loops stop at 15:20 before the close branch): carry
Execution: signal on bar t close, market fills at bar t+1 open (last bar of the
day: its close); limits fill when a later bar trades through the price.
Costs: buy 4bp (commission 1.5 + slippage 2.5); sell 22bp incl. 18bp tax for
stocks, 4bp for ETFs (no transaction tax on domestic ETFs).
"""
import math

ETF_CODES = {'069500', '229200', '114800', '252670', '251340', '122630', '233740'}


def kr_tick(price, etf=False):
    if etf:
        return 1 if price < 2000 else 5
    for limit, tick in ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500)):
        if price < limit:
            return tick
    return 1000


def tick_up(price, etf=False):
    t = kr_tick(price, etf)
    return math.ceil(price / t - 1e-9) * t


class Costs:
    def __init__(self, buy_bps=4.0, sell_bps=22.0, etf_sell_bps=4.0, scale=1.0):
        self.buy = buy_bps * scale / 1e4
        self.sell = sell_bps * scale / 1e4
        self.etf_sell = etf_sell_bps * scale / 1e4

    def sell_rate(self, code):
        return self.etf_sell if code in ETF_CODES else self.sell


def decorate_day(daytrade, raw_bars, prev_close=0.0):
    """Live-style session decoration: anchor = first open (period=1d dataset).
    The official previous close is attached as `_prev_close` for variants."""
    raw = [{k: b[k] for k in ('timestamp', 'date', 'time', 'open', 'high', 'low', 'close', 'volume')} for b in raw_bars]
    bars = daytrade._decorate_bars(raw, raw[0]['open'])
    for b in bars:
        b['_prev_close'] = prev_close or raw[0]['open']
    return bars


class LiveReplica:
    """Single-slot replay. `policy` lets variants override pieces of the logic."""

    def __init__(self, daytrade, seed=2_000_000, costs=None, mode='LIVE', policy=None, bar_minutes=1):
        self.d = daytrade
        self.bar_minutes = bar_minutes
        self.seed = float(seed)
        self.costs = costs or Costs()
        self.mode = mode
        self.policy = dict(policy or {})
        self.pos = None
        self.cool = {}
        self.trades = []
        self.daily = []
        self.cash_pnl = 0.0
        self.queue = None  # ('BUY', code, profile, strategy) or ('SELL', reason)

    # ------------------------------------------------------------ entry rules
    def _entry_ok(self, code, strategy, bar, profile, day, minute_idx):
        c = self.cool.get(code, {})
        if c.get('block_day') == day:
            return False
        if c.get('until_idx') is not None and c.get('day') == day and minute_idx < c['until_idx']:
            return False
        price = bar['close']
        if self.policy.get('entry_window'):
            start, end = self.policy['entry_window']
            if not (start <= bar['time'] < end):
                return False
        if abs(bar.get('gap_from_open_pct', 0)) >= float(profile.get('max_live_gap_pct', 5.5)):
            return False
        if bar.get('intraday_range_pct', 0) >= float(profile.get('max_live_day_range_pct', 8.5)):
            return False
        if strategy == 'vrev':
            anchor = max(x for x in (bar.get('open_price', 0), bar['open_price'], bar.get('vwap', 0)) if x > 0)
            if self.policy.get('anchor') == 'prev_close':
                anchor = bar['_prev_close']
            trigger = anchor * (1 + float(profile.get('buy_trigger_1_pct', 0.0)) / 100)
            if price > trigger:
                return False
            if c.get('profit_guard_price') and c.get('day') == day and price > c['profit_guard_price'] \
                    and c['profit_guard_price'] < trigger:
                return False
            if self.d.vrev_entry_issues(bar, profile):
                return False
            extra = self.policy.get('extra_entry_filter')
            if extra and not extra(code, bar, profile):
                return False
            return True
        if strategy == 'volume_breakout':
            if self.mode != 'PAPER':
                return False  # LIVE default shadow_mode=True
            high20 = bar.get('breakout_high_20', 0)
            vwap = bar.get('vwap', 0)
            if bar.get('volume_surge_ratio', 0) < float(profile.get('breakout_volume_ratio', 1.2)):
                return False
            if not (high20 > 0 and price >= high20 * 0.998 and price >= vwap * 0.995):
                return False
            if (price / high20 - 1) * 100 < float(profile.get('min_breakout_range_pct', 0.3)):
                return False
            if vwap > 0 and (price / vwap - 1) * 100 > float(profile.get('max_vwap_gap_pct_preflight', 1.5)):
                return False
            return True
        return False

    # ------------------------------------------------------------ exit rules
    def _exit_signal(self, bar):
        p = self.pos
        price = bar['close']
        prof = p['profile']
        if p.get('pending'):
            return None
        stop = abs(float(prof.get('stop_loss_pct', 1.5)))
        if price <= p['avg'] * (1 - stop / 100):
            return ('SELL', 'SELL_STOP_LOSS')
        if self.policy.get('custom_exit'):
            return self.policy['custom_exit'](self, bar)
        if p['strategy'] != 'vrev':
            return None  # fast path has no take-profit for other strategies
        jackpot = p['avg'] * (1 + float(prof.get('jackpot_take_profit_pct', 1.2)) / 100)
        if price >= jackpot:
            return ('SELL', 'SELL_FULL')
        if price >= jackpot * float(prof.get('jackpot_soft_exit_guard_ratio', 0.995)):
            return ('LIMIT', tick_up(jackpot, p['code'] in ETF_CODES))
        return None

    # ------------------------------------------------------------ bookkeeping
    def _buy(self, code, strategy, profile, price, ts, day):
        qty = int(self.seed * 0.985 / price)
        if qty <= 0:
            return
        self.pos = {'code': code, 'strategy': strategy, 'profile': profile, 'qty': qty, 'avg': price,
                    'cost': qty * price * (1 + self.costs.buy), 'entry_ts': ts, 'entry_day': day,
                    'pending': None, 'max_price': price, 'min_price': price}

    def _sell(self, price, ts, day, reason, minute_idx):
        p = self.pos
        proceeds = p['qty'] * price * (1 - self.costs.sell_rate(p['code']))
        pnl = proceeds - p['cost']
        self.cash_pnl += pnl
        self.trades.append({'code': p['code'], 'strategy': p['strategy'], 'entry_ts': p['entry_ts'],
                            'exit_ts': ts, 'entry': round(p['avg'], 2), 'exit': round(price, 2), 'qty': p['qty'],
                            'pnl': round(pnl, 1), 'ret_pct': round(pnl / p['cost'] * 100, 4), 'reason': reason,
                            'days_held': p.get('days', 0), 'mfe_pct': round((p['max_price'] / p['avg'] - 1) * 100, 3),
                            'mae_pct': round((p['min_price'] / p['avg'] - 1) * 100, 3)})
        c = self.cool.setdefault(p['code'], {})
        c.update(day=day, profit_guard_price=None, until_idx=None)
        if reason == 'SELL_STOP_LOSS':
            c['block_day'] = day if self.policy.get('stop_same_day_block', True) else None
        elif reason == 'SELL_FULL':
            c['until_idx'] = minute_idx + max(1, 30 // self.bar_minutes)
            pull = max(float(p['profile'].get('profit_reentry_min_pullback_pct', 0.7)), 0.25)
            c['profit_guard_price'] = price * (1 - pull / 100)
        elif reason == 'PRE_SELL_FILL' and self.policy.get('cooldown_after_limit_fill'):
            c['until_idx'] = minute_idx + max(1, 30 // self.bar_minutes)
        self.pos = None

    # ------------------------------------------------------------ main loop
    def run_day(self, day, candidates, bars_by_code):
        """candidates: ordered list of (code, strategy, profile); bars_by_code:
        code -> decorated bars for `day` (must include the held symbol)."""
        if self.pos:
            self.pos['pending'] = None          # day orders expire; state reset
            self.pos['days'] = self.pos.get('days', 0) + 1
            if self.policy.get('max_hold_days') is not None and self.pos['days'] > self.policy['max_hold_days']:
                bars = bars_by_code.get(self.pos['code'])
                if bars:
                    self._sell(bars[0]['open'], bars[0]['timestamp'], day, 'MAX_HOLD_OPEN', 0)
        times = sorted({b['time'] for bars in bars_by_code.values() for b in bars})
        index = {code: {b['time']: b for b in bars} for code, bars in bars_by_code.items()}
        self.queue = None
        for i, t in enumerate(times):
            # 1) execute what the previous bar decided, at this bar's open
            if self.queue:
                kind = self.queue[0]
                if kind == 'BUY' and self.pos is None:
                    _, code, strategy, profile = self.queue
                    bar = index.get(code, {}).get(t)
                    if bar:
                        self._buy(code, strategy, profile, bar['open'], bar['timestamp'], day)
                elif kind == 'SELL' and self.pos:
                    bar = index.get(self.pos['code'], {}).get(t)
                    if bar:
                        self._sell(bar['open'], bar['timestamp'], day, self.queue[1], i)
                self.queue = None
            # 2) manage the open position on this completed bar
            if self.pos:
                bar = index.get(self.pos['code'], {}).get(t)
                if bar:
                    p = self.pos
                    if p['pending'] and p['pending']['idx'] < i and bar['high'] >= p['pending']['price']:
                        fill = max(p['pending']['price'], bar['open'])
                        p['max_price'] = max(p['max_price'], bar['high'])
                        self._sell(fill, bar['timestamp'], day, 'PRE_SELL_FILL', i)
                    else:
                        p['max_price'] = max(p['max_price'], bar['high'])
                        p['min_price'] = min(p['min_price'], bar['low'])
                        sig = self._exit_signal(bar)
                        if sig and sig[0] == 'LIMIT':
                            p['pending'] = {'price': sig[1], 'idx': i}
                        elif sig and sig[0] == 'SELL':
                            if i + 1 < len(times):
                                self.queue = sig
                            else:
                                self._sell(bar['close'], bar['timestamp'], day, sig[1], i)
                continue
            # 3) flat: the auto cycle walks the ranked candidates
            if i + 1 >= len(times):
                continue
            for code, strategy, profile in candidates:
                bar = index.get(code, {}).get(t)
                if bar and self._entry_ok(code, strategy, bar, profile, day, i):
                    self.queue = ('BUY', code, strategy, profile)
                    break
        # end of day: mark to market (carry overnight)
        mtm = 0.0
        if self.pos:
            bars = bars_by_code.get(self.pos['code']) or []
            if bars:
                last = bars[-1]['close']
                mtm = self.pos['qty'] * last * (1 - self.costs.sell_rate(self.pos['code'])) - self.pos['cost']
        self.daily.append({'date': day, 'realized': round(self.cash_pnl, 1), 'equity_pnl': round(self.cash_pnl + mtm, 1),
                           'holding': self.pos['code'] if self.pos else None})

    def close_out(self, bars_by_code, day):
        if self.pos:
            bars = bars_by_code.get(self.pos['code']) or []
            if bars:
                self._sell(bars[-1]['close'], bars[-1]['timestamp'], day, 'END_OF_TEST', len(bars))
