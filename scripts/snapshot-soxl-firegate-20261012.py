"""Read-only remote snapshot before repair. Never sends broker orders."""
import contextlib
import datetime
import io
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
with contextlib.redirect_stdout(io.StringIO()):
    audit = runpy.run_path(str(ROOT/'scripts/audit-firegate-readonly.py'))
client = audit['client']
portfolio = client.get_portfolio(1780022179464)
transactions = client.list_transactions(portfolio['id'])
stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
path = ROOT/'data/reconciliation-audits'/f'soxl-firegate-before-repair-{stamp}.json'
path.write_text(json.dumps({'portfolio':portfolio,'transactions':transactions},ensure_ascii=False,indent=2),encoding='utf-8')
print('Saved recoverable remote record snapshot:',path.name)
print('Portfolio quantity:',portfolio['holdingQty'])
print('Transaction net quantity:',sum((1 if t.get('type')=='buy' else -1)*int(t.get('size',0)) for t in transactions))
