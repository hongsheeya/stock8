"""Offline target-position replay. No broker, filesystem, or account access.

Signals at completed close fill at next same-session open. Long-only integer
shares, no leverage, no overnight exposure. Costs are research assumptions.
"""
import math


def replay(bars, targets, seed=1_000_000, buy_bps=4, sell_bps=22):
    if len(bars) != len(targets) or seed <= 0:
        raise ValueError('Invalid bars/targets or seed')
    cash = peak = float(seed)
    qty = 0
    basis = 0.0
    pending = None
    previous = ''
    curve, exits, orders = [], [], []
    mdd = low_mdd = costs = 0.0
    br, sr = buy_bps / 10000, sell_bps / 10000
    if min(br, sr) < 0 or max(br, sr) >= 1:
        raise ValueError('Invalid costs')
    for i, (bar, target) in enumerate(zip(bars, targets)):
        ts = str(bar['timestamp'])
        o, h, l, c = (float(bar[k]) for k in ('open','high','low','close'))
        if ts <= previous or not all(math.isfinite(v) for v in (o,h,l,c,target)):
            raise ValueError('Nonfinite or unordered bars')
        if not 0 < l <= min(o,c) <= max(o,c) <= h or not 0 <= target <= 1:
            raise ValueError('Invalid OHLC or target')
        final = i == len(bars)-1 or str(bars[i+1]['timestamp'])[:10] != ts[:10]
        if pending is not None:
            weight, signal_time = pending
            if signal_time[:10] != ts[:10]:
                raise ValueError('Cross-session pending signal')
            # Target weight of CURRENT equity; no borrowed cash.
            desired = int((cash + qty*o) * weight / (o*(1+br)))
            if desired < qty:
                sold = qty-desired
                cost_basis = basis * sold/qty
                proceeds = sold*o*(1-sr)
                pnl = proceeds-cost_basis
                cash += proceeds
                basis -= cost_basis
                qty -= sold
                costs += sold*o*sr
                exits.append(pnl)
                orders.append(dict(side='SELL', time=ts, signal_time=signal_time, qty=sold, price=o, pnl=pnl))
            elif desired > qty:
                bought = min(desired-qty, int(max(0,cash)/(o*(1+br))))
                debit = bought*o*(1+br)
                cash -= debit
                basis += debit
                qty += bought
                costs += bought*o*br
                if bought:
                    orders.append(dict(side='BUY', time=ts, signal_time=signal_time, qty=bought, price=o))
            pending = None
        # Low-mark risk is separate from executable stop fills; OHLC cannot
        # establish whether this bar's high occurred before its low.
        low_equity = cash + qty*l*(1-sr)
        equity = cash + qty*c*(1-sr)
        low_mdd = max(low_mdd, (peak-low_equity)/peak*100)
        peak = max(peak,equity)
        mdd = max(mdd,(peak-equity)/peak*100)
        if final and qty:
            proceeds = qty*c*(1-sr)
            pnl = proceeds-basis
            cash += proceeds
            costs += qty*c*sr
            exits.append(pnl)
            orders.append(dict(side='SELL',time=ts,signal_time=None,qty=qty,price=c,pnl=pnl,reason='scheduled_session_close'))
            qty, basis = 0,0.0
            equity = cash
        curve.append(dict(time=ts,equity=equity,low_equity=low_equity))
        # Rebalance only on changed target; stable signal means hold shares.
        if not final and (i == 0 or ts[:10] != previous[:10] or target != targets[i-1]):
            pending = (float(target),ts)
        previous = ts
        if cash < -1e-6:
            raise AssertionError('Negative cash')
    if abs(cash-seed-sum(exits)) > 1e-5:
        raise AssertionError('Cash/P&L reconciliation failed')
    wins = [x for x in exits if x>0]
    losses = [x for x in exits if x<0]
    return dict(return_pct=(cash/seed-1)*100, pnl=cash-seed,
                close_mdd_pct=mdd, low_mark_mdd_pct=low_mdd,
                sell_events=len(exits), win_rate_pct=len(wins)/len(exits)*100 if exits else None,
                profit_factor=sum(wins)/-sum(losses) if losses else None,
                no_losses=bool(wins and not losses),
                avg_win=sum(wins)/len(wins) if wins else 0,
                avg_loss=sum(losses)/len(losses) if losses else 0,
                costs=costs, orders=orders, curve=curve)


def aggregate(results, seed=1_000_000):
    """Equal independent sleeves on EXACT common timestamps, not pooled cash."""
    if not results:
        raise ValueError('Empty results')
    stamps = [x['time'] for x in results[0]['curve']]
    if any([x['time'] for x in r['curve']] != stamps for r in results):
        raise ValueError('Align basket timestamps before replay')
    initial = seed*len(results)
    peak = initial
    mdd = low_mdd = 0.0
    for i in range(len(stamps)):
        eq = sum(r['curve'][i]['equity'] for r in results)
        low = sum(r['curve'][i]['low_equity'] for r in results)
        low_mdd = max(low_mdd,(peak-low)/peak*100)
        peak = max(peak,eq)
        mdd = max(mdd,(peak-eq)/peak*100)
    pnl = sum(r['pnl'] for r in results)
    exits = [o['pnl'] for r in results for o in r['orders'] if o['side']=='SELL']
    gain = sum(max(0,x) for x in exits)
    loss = -sum(min(0,x) for x in exits)
    return dict(return_pct=pnl/initial*100,pnl=pnl,close_mdd_pct=mdd,
                low_mark_mdd_pct=low_mdd,sell_events=len(exits),
                profit_factor=gain/loss if loss else None,
                costs=sum(r['costs'] for r in results))
