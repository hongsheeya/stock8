"""Offline, long-only STOCK adaptation of the supplied basket specification.

No broker orders, credentials, imports, or runtime account changes. Not XAUUSD,
not HK MARTIN PRO, and not the full Stock8 live engine. Fixed assumptions are
written before running; every fill and daily mark is retained for reproduction.
"""
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sizing_reference', ROOT / 'scripts/compare-martingale.py')
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)
INITIAL = 20_000_000.0
SYMBOLS = ['005930.KS', '000660.KS', '047920.KQ', '161890.KS', '069500.KS']


def prepare(sessions, minutes=5):
    """Causal EMA20/50, Wilder RSI14, ATR14; retain preceding-day warmup."""
    result = []
    fast = slow = previous = atr = gain = loss = None
    changes, ranges, atr_history = [], [], []
    n = 0
    for session in sessions:
        raw = session['bars']
        if minutes == 15:
            groups = {}
            for b in raw:
                key = b['timestamp'][:14] + str(int(b['timestamp'][14:16]) // 15)
                groups.setdefault(key, []).append(b)
            raw = [dict(timestamp=g[0]['timestamp'], open=g[0]['open'], close=g[-1]['close'],
                        high=max(x['high'] for x in g), low=min(x['low'] for x in g),
                        volume=sum(x['volume'] for x in g)) for g in groups.values() if len(g) == 3]
        bars = reference.research._decorate_bars(raw, session['prev_close'])
        for b in bars:
            c = b['close']
            old_fast = fast
            fast = c if fast is None else fast + 2 / 21 * (c-fast)
            slow = c if slow is None else slow + 2 / 51 * (c-slow)
            if previous is not None:
                delta = c-previous
                changes.append(delta)
                tr = max(b['high']-b['low'], abs(b['high']-previous), abs(b['low']-previous))
                ranges.append(tr)
                if len(changes) == 14:
                    gain = mean(max(x, 0) for x in changes)
                    loss = mean(max(-x, 0) for x in changes)
                    atr = mean(ranges)
                elif len(changes) > 14:
                    gain = (gain*13 + max(delta, 0))/14
                    loss = (loss*13 + max(-delta, 0))/14
                    atr = (atr*13 + tr)/14
            rsi = 50 if gain is None or gain == loss == 0 else (100 if loss == 0 else 100-100/(1+gain/loss))
            baseline_atr = mean(atr_history[-20:]) if atr_history else 0
            b.update(ema20=fast, ema50=slow, trend_rsi=rsi,
                     trend_rsi_prev=previous_rsi if n else 50,
                     atr14=atr or 0, warm=n >= 50,
                     protect_add=bool((baseline_atr and atr and atr > 2*baseline_atr) or fast < slow*.99))
            if atr is not None:
                atr_history.append(atr)
            previous, previous_rsi = c, rsi
            n += 1
        result.append(dict(date=session['date'], prev_close=session['prev_close'], bars=bars))
    return result


def run(sessions, mode='basket', multiplier=1, gap_pct=.5, cost_scale=1,
        etf=False, carry=False, protection=True, cap_fraction=1.0, candidate=None):
    """Each symbol is a separate 20m KRW account. No leverage or capital recycling
    between symbols. Target/loss = NET liquidation P&L / cycle acquisition cost.
    Signals at completed close, queued fills at next observed bar OPEN. Day-flat
    liquidation at final close is pre-scheduled, not a signal-generated fill.
    """
    profile = reference.research.DEFAULT_PROFILE
    buy_rate = .0004 * cost_scale
    sell_rate = (.0004 if etf else .0022) * cost_scale
    cash = peak = INITIAL
    lots, trades, orders, daily, curve = [], [], [], [], []
    pending = None
    cycle_budget = base_qty = start_index = 0
    cycle_peak = cycle_dd = max_basket_dd = max_alloc = mdd = fees = 0.0
    cooldown_until = -1
    stop_day = None
    index = -1
    rejected = protected = 0
    daily_entries = 0
    capacity = 3 if mode == 'basket' else 1

    def metrics():
        qty = sum(x['qty'] for x in lots)
        basis = sum(x['cost'] for x in lots)
        return qty, basis

    def sell(price, timestamp, reason):
        nonlocal cash, lots, fees, cooldown_until, stop_day, max_basket_dd
        qty, basis = metrics()
        proceeds = qty*price*(1-sell_rate)
        pnl = proceeds-basis
        cash += proceeds
        fees += qty*price*sell_rate
        trades.append(dict(time=timestamp, pnl=pnl, reason=reason, entries=len(lots),
                           duration_bars=index-start_index, basis=basis,
                           entry_time=lots[0]['time'], average_entry=sum(x['price']*x['qty'] for x in lots)/qty,
                           exit_price=price, qty=qty, basket_dd_pct=cycle_dd))
        orders.append(dict(time=timestamp, action='SELL', qty=qty, price=price, reason=reason))
        max_basket_dd = max(max_basket_dd, cycle_dd, max(0, -pnl/cycle_budget*100))
        lots = []
        cooldown_until = index + (3 if mode != 'vrev' else 0)
        if mode == 'vrev' and reason == 'stop':
            stop_day = timestamp[:10]

    for day_index, session in enumerate(sessions):
        daily_entries = 0
        bars = session['bars']
        for bi, b in enumerate(bars):
            index += 1
            o, c = b['open'], b['close']
            if pending:
                action, reason, signal_time = pending
                pending = None
                if action == 'SELL' and lots:
                    sell(o, b['timestamp'], reason)
                    orders[-1]['signal_time'] = signal_time
                elif action == 'BUY':
                    if not lots:
                        cycle_budget = min(cash, INITIAL*cap_fraction)
                        weights = sum(multiplier**j for j in range(capacity))
                        base_qty = int(cycle_budget/(o*(1+buy_rate)*weights))
                        start_index = index
                        cycle_peak = cycle_dd = 0
                    q = int(base_qty*multiplier**len(lots))
                    _, basis = metrics()
                    q = min(q, int(max(0, min(cash, cycle_budget-basis))/(o*(1+buy_rate))))
                    if q > 0 and len(lots) < capacity:
                        if not lots:
                            daily_entries += 1
                        cost = q*o*(1+buy_rate)
                        cash -= cost
                        fees += q*o*buy_rate
                        lots.append(dict(qty=q, price=o, cost=cost, time=b['timestamp']))
                        orders.append(dict(time=b['timestamp'], signal_time=signal_time,
                                           action='BUY', qty=q, price=o, reason=reason, entries=len(lots)))
                    else:
                        rejected += 1
            qty, basis = metrics()
            equity = cash + qty*c*(1-sell_rate)
            # Account low is a bar-low mark, NOT an assumption of stop execution.
            low_equity = cash + qty*b['low']*(1-sell_rate)
            mdd = max(mdd, max(0, (peak-low_equity)/peak*100))
            peak = max(peak, equity)
            max_alloc = max(max_alloc, basis/INITIAL*100)
            if lots:
                liquid = qty*c*(1-sell_rate)
                low_liquid = qty*b['low']*(1-sell_rate)
                cycle_peak = max(cycle_peak, liquid-basis)
                cycle_dd = max(cycle_dd, (cycle_peak - (low_liquid-basis))/cycle_budget*100)
            last = bi == len(bars)-1
            final = last and day_index == len(sessions)-1
            if lots and (final or (last and not carry)):
                sell(c, b['timestamp'], 'dataset_end' if final else 'scheduled_day_close')
                equity = cash
            if not final and (carry or not last):
                if lots:
                    pnl_pct = (qty*c*(1-sell_rate)/basis-1)*100
                    if mode == 'vrev':
                        avg = basis/qty
                        reason = ('stop' if c <= avg*(1-profile['stop_loss_pct']/100) else
                                  'target' if c >= avg*(1+profile['jackpot_take_profit_pct']/100) else
                                  'bb' if c >= b.get('bb_upper', math.inf) and c >= avg else
                                  'rsi' if b['rsi14'] >= profile['rsi_exit_overbought'] and c >= avg else '')
                    elif candidate:
                        reason = ('stop' if pnl_pct <= -candidate['stop_pct'] else
                                  'target' if pnl_pct >= candidate['target_pct'] else
                                  'time_exit' if index-start_index >= candidate['max_bars'] else '')
                    else:
                        reason = 'stop' if pnl_pct <= -5 else ('target' if pnl_pct >= 2.5 else '')
                    if reason:
                        pending = ('SELL', reason, b['timestamp'])
                    elif mode == 'basket' and len(lots) < capacity and c <= lots[-1]['price']*(1-gap_pct/100):
                        if protection and b.get('protect_add', False):
                            protected += 1
                        elif carry or bi < len(bars)-2:
                            pending = ('BUY', 'adverse_add', b['timestamp'])
                elif index >= cooldown_until and (carry or bi < len(bars)-2):
                    if candidate:
                        entry = bool(b.get('candidate_entry', False) and daily_entries < candidate['max_daily_entries'])
                    elif mode == 'vrev':
                        entry = stop_day != session['date'] and c <= session['prev_close'] and not reference.research.vrev_entry_issues(b, profile)
                    else:
                        entry = b['warm'] and b['ema20'] > b['ema50'] and b['trend_rsi'] >= 53 and b['trend_rsi'] > b['trend_rsi_prev']
                    if entry:
                        pending = ('BUY', 'initial', b['timestamp'])
            curve.append(dict(time=b['timestamp'], equity=equity))
            assert cash >= -1e-6 and len(lots) <= capacity and basis <= INITIAL*cap_fraction+1e-6
        daily.append(dict(date=session['date'], equity=equity))
    profits = [x['pnl'] for x in trades]
    wins, losses = [p for p in profits if p > 0], [p for p in profits if p < 0]
    streak = max_streak = 0
    for p in profits:
        streak = streak+1 if p < 0 else 0
        max_streak = max(max_streak, streak)
    assert abs(cash-INITIAL-sum(profits)) < 1e-5
    return dict(return_pct=(cash/INITIAL-1)*100, mdd_pct=mdd, cycles=len(trades),
                win_rate_pct=len(wins)/len(trades)*100 if trades else None,
                profit_factor=sum(wins)/-sum(losses) if losses else None,
                avg_win=mean(wins) if wins else 0, avg_loss=mean(losses) if losses else 0,
                largest_loss=min(profits, default=0), largest_win=max(profits, default=0),
                max_loss_streak=max_streak, max_basket_dd_pct=max_basket_dd,
                avg_entries=mean(t['entries'] for t in trades) if trades else 0,
                max_entries=max((t['entries'] for t in trades), default=0),
                max_entries_cycles_pct=sum(t['entries'] == capacity for t in trades)/len(trades)*100 if trades else 0,
                avg_duration_bars=mean(t['duration_bars'] for t in trades) if trades else 0,
                longest_losing_bars=max((t['duration_bars'] for t in trades if t['pnl'] < 0), default=0),
                max_allocation_pct=max_alloc, costs=fees, rejected_size=rejected, protected_bars=protected,
                trades=trades, orders=orders, daily=daily, curve=curve)


def aggregate(results):
    # Sum independently funded accounts on common dates; no retrospective rebalancing.
    dates = sorted(set.intersection(*(set(x['date'] for x in r['daily']) for r in results)))
    daily = [{x['date']:x['equity'] for x in r['daily']} for r in results]
    seed = INITIAL*len(results)
    peak = seed
    mdd = 0
    curve = []
    for d in dates:
        eq = sum(r[d] for r in daily)
        peak = max(peak, eq)
        mdd = max(mdd, (peak-eq)/peak*100)
        curve.append(dict(date=d, equity=eq))
    ts = [t for r in results for t in r['trades']]
    gain = sum(max(t['pnl'], 0) for t in ts)
    loss = -sum(min(t['pnl'], 0) for t in ts)
    return dict(return_pct=(curve[-1]['equity']/seed-1)*100, daily_close_mdd_pct=mdd,
                cycles=len(ts), win_rate_pct=sum(t['pnl'] > 0 for t in ts)/len(ts)*100 if ts else None,
                profit_factor=gain/loss if loss else None, pnl=curve[-1]['equity']-seed,
                worst_symbol_mdd_pct=max(r['mdd_pct'] for r in results), daily=curve)


def run_source(sessions, cost_scale=1, etf=False, cap_fraction=1.0):
    """Run the actual corrected Stock8 session simulator, not a rewritten proxy.
    It remains a SESSION simulator, not the live broker/overnight engine.
    """
    service = reference.module.Daytrade.__new__(reference.module.Daytrade)
    service._event_filter_snapshot = lambda *args, **kwargs: {}
    cash = peak = INITIAL
    mdd = fees = 0
    trades, daily, orders = [], [], []
    for s in sessions:
        profile = dict(commission_bps=1.5*cost_scale, slippage_bps=2.5*cost_scale,
                       sell_tax_bps=(0 if etf else 18)*cost_scale,
                       budget_ratio=min(1, INITIAL*cap_fraction/cash) if cash > 0 else 0,
                       buy_split_ratio=1, stop_reentry_same_day_block=True)
        r = service._simulate_vrev_session(s, cash, profile)
        qty = 0
        pnl = 0
        for t in r['trades']:
            qty += t['qty'] if t['side']=='BUY' else -t['qty']
            pnl += t.get('pnl', 0)
            if t['side']=='SELL' and qty == 0:
                trades.append(dict(time=t['timestamp'], pnl=pnl, reason=t['reason']))
                pnl = 0
        assert qty == 0
        orders.extend(r['trades'])
        fees += r['fees']
        for eq in r['equity_curve']:
            peak = max(peak, eq)
            mdd = max(mdd, (peak-eq)/peak*100)
        cash += r['profit']
        daily.append(dict(date=s['date'], equity=cash))
    wins = sum(t['pnl'] > 0 for t in trades)
    gain = sum(max(t['pnl'],0) for t in trades)
    loss = -sum(min(t['pnl'],0) for t in trades)
    return dict(return_pct=(cash/INITIAL-1)*100, mdd_pct=mdd, cycles=len(trades),
                win_rate_pct=wins/len(trades)*100 if trades else None,
                profit_factor=gain/loss if loss else None, costs=fees,
                trades=trades, orders=orders, daily=daily,
                scope='actual Stock8 corrected session function; no live carry/order queue replay')


def main():
    modes = {'vrev':dict(mode='vrev'), 'trend_only':dict(mode='trend'),
             'basket_equal':dict(mode='basket'), 'basket_1_5':dict(mode='basket', multiplier=1.5),
             'basket_2':dict(mode='basket', multiplier=2)}
    scenarios = {'main':{}, 'cost_x2':dict(cost_scale=2), 'gap_025':dict(gap_pct=.25),
                 'gap_1':dict(gap_pct=1), 'no_protection':dict(protection=False),
                 'carry':dict(carry=True), 'carry_cost_x2':dict(carry=True,cost_scale=2),
                 'full_carry':dict(carry=True), 'zero_cost':dict(cost_scale=0), '15m':{}, 'full':{}}
    out = dict(scope='Long-only stock adaptation; VREV core proxy, not full live engine',
               assumptions=dict(seed_per_symbol=INITIAL, max_cycle_budget_pct=100, timeframe_minutes=5,
                                target_net_cost_pct=2.5, stop_net_cost_pct=5, default_gap_pct=.5,
                                buy_cost_bps=4, stock_sell_cost_bps=22, etf_sell_cost_bps=4,
                                cooldown_bars=3, protection='ATR14 > 2x prior20 ATR mean OR EMA20 < .99*EMA50',
                                sample='previously inspected, chronological tail NOT untouched out-of-sample'),
               inputs={}, results={}, aggregates={})
    for symbol in SYMBOLS:
        path = ROOT / f'data/reconciliation-audits/martin-bars-20261004-{symbol}.json'
        sessions = json.loads(path.read_text(encoding='utf-8'))
        stamps = [b['timestamp'] for s in sessions for b in s['bars']]
        assert stamps == sorted(set(stamps)), 'duplicate or unsorted data'
        for s in sessions:
            for b in s['bars']:
                assert all(math.isfinite(b[k]) and b[k] > 0 for k in ('open','high','low','close'))
                assert b['low'] <= min(b['open'], b['close']) <= max(b['open'], b['close']) <= b['high']
        prepared = prepare(sessions)
        split = int(len(sessions)*.7)
        out['inputs'][symbol] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                    start=sessions[0]['date'], end=sessions[-1]['date'], bars=len(stamps),
                                    tail_start=sessions[split]['date'], days=len(sessions), tail_days=len(sessions)-split)
        out['results'][symbol] = {}
        for scenario, kwargs in scenarios.items():
            data = prepare(sessions, 15)[split:] if scenario == '15m' else (prepared if scenario in ('full','full_carry') else prepared[split:])
            out['results'][symbol][scenario] = {name:run(data, etf=symbol=='069500.KS', **opts, **kwargs) for name, opts in modes.items()}
            if not kwargs.get('carry'):
                out['results'][symbol][scenario]['stock8_source'] = run_source(data, etf=symbol=='069500.KS', cost_scale=kwargs.get('cost_scale',1))
        print(json.dumps({'symbol':symbol,'main':{k:{a:v[a] for a in ('return_pct','mdd_pct','cycles','win_rate_pct','profit_factor')} for k,v in out['results'][symbol]['main'].items()}}), flush=True)
    for scenario in scenarios:
        names = list(modes) + ([] if scenarios[scenario].get('carry') else ['stock8_source'])
        out['aggregates'][scenario] = {name:aggregate([out['results'][s][scenario][name] for s in SYMBOLS]) for name in names}
    target = ROOT / 'data/reconciliation-audits/basket-comparison-20261004.json'
    target.write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'aggregates':{s:{k:{a:b for a,b in v.items() if a!='daily'} for k,v in modes.items()} for s,modes in out['aggregates'].items()}}), flush=True)


if __name__ == '__main__':
    main()
