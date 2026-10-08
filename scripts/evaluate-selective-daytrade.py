"""Research-only fixed candidates; no optimization or broker access.

Previously inspected historical data is NOT a fresh validation set. Results
cannot enable any strategy or modify account settings. All failed variants kept.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('basket_benchmark', ROOT / 'scripts/compare-basket-strategies.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)

CONFIG = dict(stop_pct=1.0, target_pct=2.5, max_bars=18, max_daily_entries=1)


def signals(sessions, kind):
    result = copy.deepcopy(sessions)
    for s in result:
        history = []
        for b in s['bars']:
            prior = history[-1] if history else None
            clock = b['timestamp'][11:16]
            previous_volume = mean(x['volume'] for x in history[-5:]) if history else 0
            common = (b['warm'] and len(history) >= 20 and '09:30' <= clock <= '13:30'
                      and b['close'] > b['ema20'] > b['ema50']
                      and b['ema20'] > prior['ema20']
                      and 55 <= b['trend_rsi'] <= 70
                      and b['trend_rsi'] > b['trend_rsi_prev']
                      and b['close'] >= b['vwap']
                      and previous_volume > 0 and b['volume'] >= previous_volume*1.5)
            if kind == 'breakout':
                trigger = bool(history and b['close'] > max(x['high'] for x in history[-20:]))
            elif kind == 'pullback':
                trigger = bool(prior and prior['close'] <= prior['ema20'] and b['close'] > b['ema20'])
            else:
                raise ValueError(kind)
            b['candidate_entry'] = bool(common and trigger)
            history.append(b)
    return result


def main():
    out = dict(scope='offline stock long-only candidates, NOT live deployment',
               config=CONFIG, cap_fraction=.3, seed=bench.INITIAL*len(bench.SYMBOLS),
               warning='Known sample; no claim of independent out-of-sample success',
               inputs={}, results={}, aggregates={})
    scenarios = ['full', 'first41', 'last18', 'last18_cost_x2']
    for symbol in bench.SYMBOLS:
        path = ROOT / f'data/reconciliation-audits/martin-bars-20261004-{symbol}.json'
        raw = json.loads(path.read_text(encoding='utf-8'))
        sessions = bench.prepare(raw)
        split = int(len(sessions)*.7)
        out['inputs'][symbol] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                    days=len(sessions), split=split)
        out['results'][symbol] = {}
        for scenario in scenarios:
            data = sessions if scenario == 'full' else sessions[:split] if scenario == 'first41' else sessions[split:]
            scale = 2 if scenario.endswith('x2') else 1
            options = dict(cost_scale=scale, etf=symbol=='069500.KS', cap_fraction=.3)
            result = dict(stock8=bench.run_source(data, **options))
            for candidate in ('breakout', 'pullback'):
                result[candidate] = bench.run(signals(data, candidate), mode='selective', candidate=CONFIG, **options)
            out['results'][symbol][scenario] = result
    for scenario in scenarios:
        out['aggregates'][scenario] = {name:bench.aggregate([out['results'][s][scenario][name] for s in bench.SYMBOLS])
                                      for name in ('stock8','breakout','pullback')}
    out['decisions'] = {}
    for name in ('breakout','pullback'):
        reasons = []
        for period in ('first41','last18'):
            result = out['aggregates'][period][name]
            if result['cycles'] < 30:
                reasons.append(f'{period}: fewer than 30 cycles')
            if result['return_pct'] <= 0:
                reasons.append(f'{period}: nonpositive net return')
            if result['profit_factor'] is None or result['profit_factor'] < 1.1:
                reasons.append(f'{period}: profit factor below 1.1 or unavailable')
        if out['aggregates']['last18_cost_x2'][name]['return_pct'] <= 0:
            reasons.append('double-cost test: nonpositive return')
        out['decisions'][name] = dict(research_gate_pass=not reasons, reasons=reasons,
                                     live_deployable=False,
                                     note='Even passing this screen is not live certification or untouched validation')
    target = ROOT / 'data/reconciliation-audits/selective-daytrade-20261004.json'
    target.write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({s:{k:{a:b for a,b in v.items() if a!='daily'} for k,v in modes.items()}
                      for s,modes in out['aggregates'].items()}, indent=2))


if __name__ == '__main__':
    main()
