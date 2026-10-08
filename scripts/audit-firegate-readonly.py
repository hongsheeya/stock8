"""Read portfolio identity and transaction counts; no FireGate record writes."""
import importlib.util
import json
from pathlib import Path
import sqlite3

root = Path(__file__).resolve().parents[1]
db = sqlite3.connect(f'file:{root / "data/live/trading.db"}?mode=ro', uri=True)
uid = db.execute('select user_id from trading_cycle where id=?', ('tsevwkrrjetkjjunnsamosnumiuskebe',)).fetchone()[0]
cfg = json.loads(db.execute('select value from trading_config where key=?', (f'user:{uid}:fire_gate_bridge',)).fetchone()[0])
spec = importlib.util.spec_from_file_location('fg_audit', root / 'src/portal/trading/model/struct/firegate_bridge.py')
fg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fg)
token = fg.refresh_id_token(cfg['refresh_token'])
client = fg.FireGateBridge(cfg['email'], token.get('id_token') or token.get('idToken'))
for portfolio in client.list_portfolios():
    if portfolio.get('ticker') not in ('SOXL', 'TQQQ'): continue
    row = {k: portfolio.get(k) for k in ('id', 'ticker', 'isRunning', 'holdingQty', 'avgPrice', 'source', 'sourceCycleId', 'portfolioGroup', 'startDate', 'endDate')}
    txs = client.list_transactions(portfolio['id'])
    row['transactions'] = len(txs)
    row['sources'] = sorted(set(str(t.get('source', '')) for t in txs))
    row['recent'] = [{k:t.get(k) for k in ('date','type','size','price','source')} for t in txs[-3:]]
    print(json.dumps(row, ensure_ascii=False), flush=True)
