"""US fixed-universe public-data research, no broker/orders/account changes."""
import importlib.util
import json
import hashlib
from pathlib import Path
import pandas as pd
import yfinance as yf

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/reconciliation-audits'
SYMBOLS=('SPY','QQQ','AAPL','NVDA','AMD','TSLA','PLTR','COIN')

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    model=load('dc',ROOT/'src/portal/trading/model/donchian_lwti.py')
    replay=load('replay',ROOT/'src/portal/trading/model/research_replay.py')
    frames={}; inputs={}; errors={}
    for symbol in SYMBOLS:
        path=OUT/f'us-donchian-20261010-{symbol}.json'
        try:
            if path.exists():
                f=pd.read_json(path)
                f.index=pd.to_datetime(f.pop('timestamp'),utc=True).dt.tz_convert('America/New_York')
            else:
                f=yf.Ticker(symbol).history(period='60d',interval='5m',auto_adjust=True,prepost=False,timeout=20)
                if f.empty: raise ValueError('No public bars')
                f=f.rename(columns=str.lower)[['open','high','low','close','volume']]
                f.index=f.index.tz_convert('America/New_York')
                f=f.loc[(f.index.strftime('%H:%M')>='09:30')&(f.index.strftime('%H:%M')<'16:00')]
                f=f.loc[f.index.date<pd.Timestamp('2026-10-10').date()]
                f.assign(timestamp=[t.isoformat() for t in f.index]).to_json(path,orient='records',double_precision=12)
            if f.empty or not f.index.is_unique or not f.index.is_monotonic_increasing:
                raise ValueError('Invalid data')
            frames[symbol]=f
            inputs[symbol]=dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bars=len(f),start=str(f.index[0]),end=str(f.index[-1]))
            print(symbol,len(f),str(f.index[0]),str(f.index[-1]),flush=True)
        except Exception as exc:
            errors[symbol]=str(exc)
    if errors:
        print(json.dumps({'errors':errors})); raise RuntimeError('Incomplete predeclared universe; refusing survivor-only aggregate')
    common=sorted(set.intersection(*(set(f.index) for f in frames.values())))
    # Only complete 78-bar regular sessions; no synthetic/fill-forward prices.
    counts=pd.Series([t.date() for t in common]).value_counts()
    days=sorted(d for d,n in counts.items() if n==78)
    if len(days)<20: raise ValueError('Fewer than 20 complete sessions')
    frames={s:f.loc[[t for t in common if t.date() in days]].copy() for s,f in frames.items()}
    split=int(len(days)*.7)
    parts={'first70':days[:split],'last30':days[split:],'full':days}
    variants={'donchian':(False,False),'lwti':(True,False),'volume':(False,True),'combined':(True,True)}
    signals={n:{s:model.targets(f,*opts) for s,f in frames.items()} for n,opts in variants.items()}
    results={}; details={}
    for part,dates in parts.items():
        results[part]={}; details[part]={}
        for name in variants:
            for bp in (4,8,15):
                runs=[]; details[part][f'{name}_{bp}bp']={}
                for s,f in frames.items():
                    segment=f.loc[[t.date() in dates for t in f.index]]
                    bars=segment.assign(timestamp=[t.isoformat() for t in segment.index]).to_dict('records')
                    r=replay.replay(bars,signals[name][s].loc[segment.index].tolist(),seed=10000,buy_bps=bp,sell_bps=bp)
                    runs.append(r)
                    details[part][f'{name}_{bp}bp'][s]={k:v for k,v in r.items() if k not in ('orders','curve')}
                results[part][f'{name}_{bp}bp']=replay.aggregate(runs,seed=10000)
    out=dict(universe=list(SYMBOLS),inputs=inputs,complete_sessions=len(days),partitions={k:[str(v[0]),str(v[-1]),len(v)] for k,v in parts.items()},
             rules='Donchian20 LWTI8>50 RVOL20>=1.5; 09:30-14:30 New York entries, midpoint or scheduled close exit; next open fills',
             limitations=['fixed basket not point-in-time top movers','short public adjusted bars','cost assumptions not broker tariff','not original Williams strategy or fresh independent OOS','no halt/queue/partial fill model','USD excludes FX'],
             results=results,per_symbol=details)
    (OUT/'donchian-us-20261010.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({'partitions':out['partitions'],'results':results},indent=2))

if __name__=='__main__': main()
