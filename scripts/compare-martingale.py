"""Research only. Public bars, no broker imports, credentials or order endpoints.

Compares sizing on a common VREV-entry proxy, not the full live engine or an
unidentified vendor product. Signals on completed bar, fills on next bar open.
"""
import importlib.util
import json
from pathlib import Path
import math

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('research_daytrade', ROOT / 'src/portal/trading/model/struct/daytrade.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
research = module.Daytrade.__new__(module.Daytrade)


def run(sessions, fraction=.1, multiplier=1, cap=1, cost_scale=1):
    initial = cash = 5_000_000.0
    peak = initial
    mdd = max_alloc = fees = 0.0
    streak = max_streak = capped = 0
    events = []
    # Constant base notional isolates sizing. Losses do NOT create extra signals.
    for session in sessions:
        qty = 0
        entry = cost = 0.0
        stopped = False
        bars = session['bars']
        profile = dict(research.DEFAULT_PROFILE)
        buy_rate = (profile['commission_bps'] + profile['slippage_bps']) / 10000 * cost_scale
        sell_rate = (profile['commission_bps'] + profile['sell_tax_bps'] + profile['slippage_bps']) / 10000 * cost_scale
        for i in range(len(bars)-1):
            bar, nxt = bars[i], bars[i+1]
            close, price = bar['close'], nxt['open']
            if min(close, price) <= 0: continue
            if qty:
                reason = ('stop' if close <= entry*(1-profile['stop_loss_pct']/100) else
                          'target' if close >= entry*(1+profile['jackpot_take_profit_pct']/100) else
                          'bb' if close >= bar.get('bb_upper', math.inf) and close >= entry else
                          'rsi' if bar.get('rsi14', 0) >= profile['rsi_exit_overbought'] and close >= entry else '')
                if reason:
                    value = qty*price
                    pnl = value*(1-sell_rate)-cost
                    cash += value*(1-sell_rate)
                    fees += value*sell_rate
                    events.append({'time': nxt['timestamp'], 'pnl': round(pnl, 2), 'reason': reason})
                    streak = streak+1 if pnl < 0 else 0
                    max_streak = max(streak, max_streak)
                    stopped = reason == 'stop'
                    qty = 0
            elif not stopped and i < len(bars)-2:
                if close <= session['prev_close'] and not research.vrev_entry_issues(bar, profile):
                    factor = min(multiplier**min(streak, 20), cap)
                    wanted = initial*fraction*factor
                    if wanted*(1+buy_rate) > cash: capped += 1
                    budget = min(wanted, cash/(1+buy_rate))
                    qty = int(budget/price)
                    if qty:
                        entry = price
                        cost = qty*price*(1+buy_rate)
                        cash -= cost
                        fees += qty*price*buy_rate
                        max_alloc = max(max_alloc, cost/initial*100)
            equity = cash + qty*nxt['close']*(1-sell_rate)
            peak = max(peak, equity)
            mdd = max(mdd, (peak-equity)/peak*100)
        if qty:
            value = qty*bars[-1]['close']
            pnl = value*(1-sell_rate)-cost
            cash += value*(1-sell_rate)
            fees += value*sell_rate
            events.append({'time': bars[-1]['timestamp'], 'pnl': round(pnl,2), 'reason':'session_close'})
            streak = streak+1 if pnl < 0 else 0
            max_streak = max(streak, max_streak)
        peak = max(peak, cash)
        mdd = max(mdd, (peak-cash)/peak*100)
    wins = sum(e['pnl'] > 0 for e in events)
    gain = sum(max(e['pnl'],0) for e in events)
    loss = -sum(min(e['pnl'],0) for e in events)
    return {'return_pct':round((cash/initial-1)*100,3), 'mdd_pct':round(mdd,3),
            'trades':len(events), 'win_rate_pct':round(wins/len(events)*100,2) if events else None,
            'profit_factor':round(gain/loss,3) if loss else None,
            'max_allocation_pct':round(max_alloc,2), 'cash_capped_entries':capped,
            'max_loss_streak':max_streak, 'costs_krw':round(fees), 'events':events}


def download(symbol):
    snapshot = ROOT / 'data/reconciliation-audits' / ('martin-bars-20261004-' + symbol + '.json')
    if snapshot.exists():
        return json.loads(snapshot.read_text(encoding='utf-8'))
    import yfinance as yf
    frame = yf.Ticker(symbol).history(period='60d', interval='5m', auto_adjust=True, prepost=False, timeout=15)
    if frame.empty: raise ValueError('No bars')
    grouped = {}
    for timestamp, row in frame.iterrows():
        ts = timestamp.tz_convert('Asia/Seoul')
        values = {k.lower():float(row[k]) for k in ('Open','High','Low','Close','Volume')}
        if not all(math.isfinite(v) for v in values.values()): continue
        grouped.setdefault(ts.strftime('%Y-%m-%d'), []).append(dict(values, timestamp=ts.isoformat()))
    sessions, prev = [], None
    for day, bars in sorted(grouped.items()):
        if prev and len(bars) >= 20:
            sessions.append({'date':day, 'prev_close':prev, 'bars':research._decorate_bars(bars, prev)})
        prev = bars[-1]['close']
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(json.dumps(sessions, ensure_ascii=False), encoding='utf-8')
    return sessions


def main():
    out = {'scope':'VREV-entry sizing proxy, NOT full live engine / vendor backtest',
           'requested_period':'60d', 'interval':'5m', 'seed_per_symbol':5000000,
           'caveats':['Fixed selected symbols: selection/survivorship bias',
             'No bid/ask depth, price limits, halts, queue fills, impact or NXT',
             'Configured costs are assumptions, not account-specific fee verification',
             'Day-flat proxy differs from live carry and alternative exits',
             'Last 30% chronological holdout has no tuning; short sample is not proof of edge'], 'symbols':{}}
    modes = {'fixed_10pct':(.1,1,1), 'martin_2x_cap4':(.1,2,4),
             'martin_2x_cap8':(.1,2,8), 'fixed_100pct_proxy':(1,1,1)}
    for symbol in ('005930.KS','000660.KS','047920.KQ','161890.KS','069500.KS'):
        try:
            sessions = download(symbol)
            split = int(len(sessions)*.7)
            result = {'days':len(sessions),'start':sessions[0]['date'],'end':sessions[-1]['date'],
                      'holdout_start':sessions[split]['date'],'results':{}}
            for period, subset in [('full',sessions), ('holdout',sessions[split:])]:
                result['results'][period] = {name:run(subset,*params) for name,params in modes.items()}
            result['results']['holdout_double_cost'] = {name:run(sessions[split:],*params,cost_scale=2) for name,params in modes.items()}
            out['symbols'][symbol] = result
            summary = {k:{a:b for a,b in v.items() if a!='events'} for k,v in result['results']['holdout'].items()}
            print(json.dumps({'symbol':symbol, 'days':len(sessions), 'holdout':summary}, ensure_ascii=False), flush=True)
        except Exception as exc:
            out['symbols'][symbol] = {'error':str(exc)[:200]}
            print(json.dumps({'symbol':symbol, 'error':str(exc)[:200]}),flush=True)
    target = ROOT / 'data/reconciliation-audits/martingale-comparison-20261004.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2),encoding='utf-8')


if __name__ == '__main__': main()
