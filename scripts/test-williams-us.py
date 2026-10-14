"""Fixed, offline follow-up on already-seen US data; no optimization or orders."""
import importlib.util
import json
import hashlib
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/reconciliation-audits'

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def main():
    old=json.loads((OUT/'donchian-us-20261010.json').read_text())
    model=load('w',ROOT/'src/portal/trading/model/williams_research.py')
    dc=load('dc',ROOT/'src/portal/trading/model/donchian_lwti.py')
    replay=load('r',ROOT/'src/portal/trading/model/research_replay.py')
    frames={}
    for symbol in old['universe']:
        path=OUT/f'us-donchian-20261010-{symbol}.json'
        assert hashlib.sha256(path.read_bytes()).hexdigest()==old['inputs'][symbol]['sha256']
        f=pd.read_json(path)
        f.index=pd.to_datetime(f.pop('timestamp'),utc=True).dt.tz_convert('America/New_York')
        frames[symbol]=f
    common=sorted(set.intersection(*(set(f.index) for f in frames.values())))
    counts=pd.Series([t.date() for t in common]).value_counts()
    days=sorted(d for d,n in counts.items() if n==78)
    frames={s:f.loc[[t for t in common if t.date() in days]] for s,f in frames.items()}
    # Equal ten-session indicator warmup for every comparator, no tuned selection.
    parts={'evaluation':days[10:],'recent18':days[-18:]}
    variants={'donchian_combined':dc.targets,'range_once':model.targets,
              'range_guarded':lambda f:model.targets(f,guarded=True)}
    result={}; causality=0
    for name,fn in variants.items():
        signals={s:fn(f) for s,f in frames.items()}
        for s,f in frames.items():
            for cut in (850,1700,3400):
                pd.testing.assert_series_equal(fn(f.iloc[:cut]),signals[s].iloc[:cut])
                causality+=1
        result[name]={}
        for part,dates in parts.items():
            result[name][part]={}
            for bp in (4,8,15):
                runs=[]
                for s,f in frames.items():
                    segment=f.loc[[t.date() in dates for t in f.index]]
                    bars=segment.assign(timestamp=[t.isoformat() for t in segment.index]).to_dict('records')
                    runs.append(replay.replay(bars,signals[s].loc[segment.index].tolist(),seed=10000,buy_bps=bp,sell_bps=bp))
                result[name][part][str(bp)]=replay.aggregate(runs,seed=10000)
    output=dict(results=result,causality_checks=causality,partitions={k:[str(v[0]),str(v[-1]),len(v)] for k,v in parts.items()},
                source_inputs=old['inputs'],warning='Already-seen data, research only, not independent OOS; next-open fills, no intrabar stop guarantee')
    (OUT/'williams-us-20261010.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps(output,indent=2))

if __name__=='__main__': main()
