"""User-authorized FireGate record reconciliation; no broker order endpoints."""
import argparse
import datetime
import importlib.util
import json
from pathlib import Path
import sqlite3
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--apply', action='store_true')
args = p.parse_args()
db = sqlite3.connect(f'file:{ROOT / "data/live/trading.db"}?mode=ro', uri=True)
uid, = db.execute('SELECT user_id FROM trading_cycle WHERE id=? AND symbol=?', ('tsevwkrrjetkjjunnsamosnumiuskebe','SOXL')).fetchone()
raw, = db.execute('SELECT value FROM trading_config WHERE key=?', (f'user:{uid}:fire_gate_bridge',)).fetchone()
cfg = json.loads(raw)
spec = importlib.util.spec_from_file_location('fg', ROOT / 'src/portal/trading/model/struct/firegate_bridge.py')
fg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fg)
token = fg.refresh_id_token(cfg['refresh_token'])
client = fg.FireGateBridge(cfg['email'], token.get('id_token') or token.get('idToken'))
pid = 1780022179464
portfolio = client.get_portfolio(pid)
transactions = client.list_transactions(pid)
assert portfolio['ticker'] == 'SOXL'
event_id = 'kis-reconciliation-20261001-soxl'
if portfolio.get('reconciliationId') == event_id:
    print('Already reconciled; no writes.'); raise SystemExit(0)
assert portfolio['holdingQty'] == 43 and Decimal(str(portfolio['avgPrice'])) == Decimal('181.97'), 'Source changed; abort'
# Confirmed from KIS inquire-ccnl, not inferred execution prices.
fills = [
    ('0030189464','2026. 08. 31',3,'112.79'),
    ('0030624911','2026. 09. 10',4,'115.76'),
    ('0030007598','2026. 09. 14',5,'107.01'),
    ('0000014993','2026. 09. 29',5,'140.42'),
]
new_txs = []
for order, date, qty, price in fills:
    doc = f'kis-soxl-{date.replace(". ", "")}-{order}'
    matches = [tx for tx in transactions if tx.get('brokerOrderNo') == order or tx.get('_doc_id') == doc or
               (tx.get('date') == date and tx.get('size') == qty and Decimal(str(tx.get('price',0))) == Decimal(price))]
    if matches:
        continue
    new_txs.append((doc, {'portfolioId':pid,'ticker':'SOXL','type':'buy','date':date,
        'size':qty,'price':float(price),'source':'kis_verified_reconciliation','brokerOrderNo':order,
        'sourceTradeId':order,'orderType':'EXTERNAL','commission':0,'commissionUnverified':True,
        'tDelta':0,'tOperator':'+','roundUnverified':True,
        'memo':'KIS 실제 체결 확인. 수수료·전략 회차 미확인으로 0은 미확인 표기이며 무수수료를 뜻하지 않음.'}))
actual_amount = sum(Decimal(price)*qty for _,_,qty,price in fills)
target_cost = Decimal('158.6427')*60
old_cost = Decimal(str(portfolio['avgPrice']))*43
reconciliation = {
    'id':event_id,'source':'KIS balance + confirmed fills','qtyBefore':43,'qtyAfter':60,
    'avgBefore':portfolio['avgPrice'],'avgAfter':158.6427,'verifiedBuyQty':17,
    'verifiedBuyAmount':float(actual_amount),'costBasisAdjustment':float(target_cost-old_cost-actual_amount),
    'note':'보정은 매수 체결이나 실현손익이 아님. 기존 장부 원가 차이. 수수료/회차는 미확인, tValue 유지.',
}
changes = {'holdingQty':60,'avgPrice':158.6427,
           'totalBuy':float(Decimal(str(portfolio.get('totalBuy',0)))+actual_amount),
           'reconciliationId':event_id,'brokerReconciliation':reconciliation}
print(json.dumps({'planned_new_transactions':len(new_txs),'reconciliation':reconciliation},ensure_ascii=False))
if not args.apply:
    raise SystemExit(0)
backup_dir = ROOT / 'data/reconciliation-audits'
backup_dir.mkdir(parents=True, exist_ok=True)
backup = backup_dir / (event_id + '.json')
if not backup.exists():
    backup.write_text(json.dumps({'portfolio_before':portfolio,'transactions_before':transactions,
        'changes':changes,'new_transactions':new_txs},ensure_ascii=False,indent=2),encoding='utf-8')
for doc, tx in new_txs:
    client.create_transaction(tx, doc_id=doc)
client.update_portfolio(pid, changes)
after = client.get_portfolio(pid)
assert after['holdingQty'] == 60 and abs(after['avgPrice']-158.6427)<0.000001
print(json.dumps({'verified_qty':after['holdingQty'],'verified_avg':after['avgPrice'],'backup':str(backup)},ensure_ascii=False))
