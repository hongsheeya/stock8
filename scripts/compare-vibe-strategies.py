"""Offline comparison; never imports broker or changes deployment/account state.

Reads two reviewed examples from user ZIP, preserving their signal rules.
Long-only/day-flat adaptation is explicit, not the original daily long/short run.
Already inspected sample: chronological partitions are NOT untouched OOS.
"""
import ast
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import types
import zipfile
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load_reviewed(z,name):
    if name not in ('technical-basic','multi-factor'):
        raise ValueError('Only reviewed pure signal examples allowed')
    raw=z.read('vibe-trading-strategies/strategies/'+name+'.py')
    expected = {
        'technical-basic':'ba2fb63a0972026e9f43d1959fe0f5bc32539c9492e7e71329073633428171ba',
        'multi-factor':'439dd7abbecf5ba0655565571f805d6a41de46a0a53f0a0b86c76f1414c60dcd',
    }
    if hashlib.sha256(raw).hexdigest() != expected[name]:
        raise ValueError('Attachment changed: review source before execution')
    tree=ast.parse(raw)
    # Drop demo/network helpers and top-level execution; keep reviewed maths.
    nodes=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom,ast.ClassDef,ast.FunctionDef))
           and not (isinstance(n,ast.FunctionDef) and n.name.startswith('_fetch'))]
    for n in nodes:
        if isinstance(n,ast.Import) and any(a.name not in ('numpy','pandas') for a in n.names):
            raise ValueError('Unreviewed import')
        if isinstance(n,ast.ImportFrom) and n.module != 'typing':
            raise ValueError('Unreviewed import')
    scope={}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),name,'exec'),scope)
    return scope['SignalEngine'](),hashlib.sha256(raw).hexdigest()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--zip',default='C:/dev/vibe-trading-strategies.zip')
    ap.add_argument('--out',default='data/reconciliation-audits/vibe-comparison-20261008.json')
    args=ap.parse_args()
    replay=module('replay',ROOT/'src/portal/trading/model/research_replay.py')
    source=module('source',ROOT/'src/portal/trading/model/struct/daytrade.py')
    service=source.Daytrade.__new__(source.Daytrade)
    frames={}; inputs={}
    for path in sorted((ROOT/'data/reconciliation-audits').glob('martin-bars-20261004-*.json')):
        symbol=path.stem.removeprefix('martin-bars-20261004-')
        sessions=json.loads(path.read_text(encoding='utf-8'))
        rows=[]
        for session in sessions:
            for b in service._decorate_bars(session['bars'],session['prev_close']):
                rows.append(dict(b,anchor=session['prev_close']))
        frame=pd.DataFrame(rows)
        frame.index=pd.to_datetime(frame['timestamp'])
        if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
            raise ValueError('Invalid timestamps')
        frames[symbol]=frame
        inputs[symbol]=dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bars=len(frame))
    if len(frames)!=5: raise ValueError('Expected fixed five-symbol basket')
    common=sorted(set.intersection(*(set(f.index) for f in frames.values())))
    frames={s:f.loc[common].copy() for s,f in frames.items()}
    dates=sorted(set(t.date() for t in common))
    cuts=(int(len(dates)*.5),int(len(dates)*.75))
    if cuts[0]<10 or len(dates)-cuts[1]<10: raise ValueError('Insufficient sessions')
    partitions={'development':dates[:cuts[0]],'validation':dates[cuts[0]:cuts[1]],'test':dates[cuts[1]:]}
    variants={}; causal={}; hashes={}
    with zipfile.ZipFile(args.zip) as z:
        for name in ('technical-basic','multi-factor'):
            engine,hashes[name]=load_reviewed(z,name)
            raw=engine.generate({s:f.copy() for s,f in frames.items()})
            mismatch=checks=0
            for i in np.linspace(100,len(common)-2,12).astype(int):
                ts=common[i]
                truncated=engine.generate({s:f.loc[:ts].copy() for s,f in frames.items()})
                for s in frames:
                    checks+=1
                    mismatch+=not np.isclose(raw[s].loc[ts],truncated[s].loc[ts],equal_nan=True)
            causal[name]=dict(checks=checks,mismatches=int(mismatch))
            # Negative target -> cash, not naked short. Multiply cross-sectional
            # weights by basket size to map to separate equal cash sleeves.
            variants[name]={s:raw[s].clip(lower=0).mul(len(frames) if name=='multi-factor' else 1).clip(upper=1) for s in frames}
    # Fixed baseline proxies share exactly the same execution/accounting engine.
    for name in ('vrev_core','volume_breakout','cash','session_hold'):
        variants[name]={}
        for s,f in frames.items():
            state=0; stopped=False; day=None; entry=0; values=[]
            for ts,b in f.iterrows():
                if ts.date()!=day: state=0; stopped=False; day=ts.date()
                if name=='cash': state=0
                elif name=='session_hold': state=1
                elif state:
                    stop=1.5 if name=='vrev_core' else .8
                    target=2 if name=='vrev_core' else 1.4
                    if b.close<=entry*(1-stop/100) or b.close>=entry*(1+target/100) or (name=='volume_breakout' and b.close<b.vwap):
                        stopped=b.close<=entry*(1-stop/100)
                        state=0
                elif not stopped:
                    enter=(b.close<=b.anchor and not service.vrev_entry_issues(b.to_dict(),service.DEFAULT_PROFILE)) if name=='vrev_core' else (b.volume_surge_ratio>=1.2 and b.close>=b.breakout_high_20*.998 and b.close>=b.vwap*.995)
                    if enter: state=1; entry=b.close
                values.append(state)
            variants[name][s]=pd.Series(values,index=f.index)
    results={}
    for part,days in partitions.items():
        results[part]={}
        for name,signals in variants.items():
            for scale in (1,2):
                runs=[]
                for s,f in frames.items():
                    mask=[t.date() in days for t in f.index]
                    selected=f.loc[mask]
                    runs.append(replay.replay(selected.to_dict('records'),signals[s].loc[selected.index].fillna(0).tolist(),buy_bps=4*scale,sell_bps=(4 if s=='069500.KS' else 22)*scale))
                results[part][name+('_cost2' if scale==2 else '')]=replay.aggregate(runs)
    # Predeclared screen; do not tune after observing the final partition.
    decisions={}
    for name in ('technical-basic','multi-factor'):
        reasons=[]
        if causal[name]['mismatches']: reasons.append('causality mismatch')
        for part in ('validation','test'):
            r=results[part][name]
            if r['return_pct']<=0: reasons.append(part+': nonpositive net return')
            if r['sell_events']<30: reasons.append(part+': fewer than 30 sell events')
            if r['profit_factor'] is None or r['profit_factor']<1.1: reasons.append(part+': PF unavailable/below 1.1')
            if r['low_mark_mdd_pct']>10: reasons.append(part+': low-mark drawdown >10%')
            if results[part][name+'_cost2']['return_pct']<=0: reasons.append(part+': doubled-cost loss')
        decisions[name]=dict(research_screen_pass=not reasons,reasons=reasons,live_approved=False,
                            note='Known sample and short history: forward PAPER validation still required')
    output=dict(inputs=inputs,source_hashes=hashes,causality=causal,partitions={k:[str(v[0]),str(v[-1]),len(v)] for k,v in partitions.items()},
                assumptions={'interval':'5m','session_flat':True,'long_only':True,'seed_per_symbol':1000000,
                             'sample':'previously inspected; not independent OOS','costs':'research assumptions, not broker tariff',
                             'baselines':'VREV/breakout signal-core adaptations, NOT live-engine replay',
                             'multifactor':'original 20-bar rebalance on 5m bars, NOT original 20-day strategy'},
                results=results,decisions=decisions)
    target=ROOT/args.out
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
