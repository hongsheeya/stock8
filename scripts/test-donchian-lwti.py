"""Fixed-parameter ablation; historical/known sample, not fresh OOS."""
import importlib.util
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def main():
    model=load('dc',ROOT/'src/portal/trading/model/donchian_lwti.py')
    replay=load('replay',ROOT/'src/portal/trading/model/research_replay.py')
    frames={}; inputs={}
    for p in sorted((ROOT/'data/reconciliation-audits').glob('martin-bars-20261004-*.json')):
        s=p.stem.removeprefix('martin-bars-20261004-')
        sessions=json.loads(p.read_text(encoding='utf-8'))
        f=pd.DataFrame([b for d in sessions for b in d['bars']]); f.index=pd.to_datetime(f.timestamp)
        frames[s]=f
        inputs[s]=hashlib.sha256(p.read_bytes()).hexdigest()
    if len(frames)!=5: raise ValueError('Expected fixed basket')
    common=sorted(set.intersection(*(set(f.index) for f in frames.values())))
    frames={s:f.loc[common].copy() for s,f in frames.items()}
    days=sorted(set(t.date() for t in common)); a=int(len(days)*.5); b=int(len(days)*.75)
    parts={'development':days[:a],'validation':days[a:b],'test':days[b:]}
    variants={'donchian':(False,False),'donchian_lwti':(True,False),'donchian_volume':(False,True),'combined':(True,True)}
    signals={name:{s:model.targets(f,*opts) for s,f in frames.items()} for name,opts in variants.items()}
    checks=mismatches=0
    for s,f in frames.items():
        for i in np.linspace(50,len(f)-2,12).astype(int):
            for name,opts in variants.items():
                checks+=1
                mismatches+=int(model.targets(f.iloc[:i+1],*opts).iloc[-1]!=signals[name][s].iloc[i])
    results={}
    for part,dates in parts.items():
        results[part]={}
        for name in variants:
            for scale in (1,2):
                runs=[]
                for s,f in frames.items():
                    segment=f.loc[[t.date() in dates for t in f.index]]
                    runs.append(replay.replay(segment.to_dict('records'),signals[name][s].loc[segment.index].tolist(),buy_bps=4*scale,sell_bps=(4 if s=='069500.KS' else 22)*scale))
                results[part][name+('_cost2' if scale==2 else '')]=replay.aggregate(runs)
    out=dict(parameters=dict(channel=20,lwti_period=8,lwti_threshold=50,volume_period=20,volume_multiple=1.5,exit='close below prior-channel midpoint or scheduled day close'),
             scope='5m long-only fixed five-symbol known sample; no parameter fitting or live orders',
             costs='research assumptions: buy 4bp, stock sell 22bp, ETF sell 4bp; doubled-cost stress',
             inputs=inputs,partitions={k:[str(v[0]),str(v[-1]),len(v)] for k,v in parts.items()},
             causality=dict(checks=checks,mismatches=mismatches),results=results)
    target=ROOT/'data/reconciliation-audits/donchian-lwti-20261010.json'
    target.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
