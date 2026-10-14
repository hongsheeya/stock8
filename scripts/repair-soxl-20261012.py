"""Exact, backed-up FireGate correction. No broker orders or config writes."""
import contextlib,io,runpy,json,hashlib,sqlite3,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
with contextlib.redirect_stdout(io.StringIO()):
    a=runpy.run_path(str(ROOT/'scripts/audit-firegate-readonly.py'))
c=a['db']; fg=a['fg']; client=a['client']; pid=1780022179464
def off():
    account=c.execute('select value from trading_config where key=?',(f"user:{a['uid']}:kis_live_account_no",)).fetchone()[0]
    key='order_policy_v1:'+hashlib.sha256(('kis:'+account).encode()).hexdigest()[:40]
    p=json.loads(c.execute('select value from trading_config where key=?',(key,)).fetchone()[0])
    assert all(p.get(x) is False for x in ('infinite_buy','daytrade_ks','daytrade_us'))
off()
p=client.get_portfolio(pid); txs=client.list_transactions(pid)
assert p['holdingQty']==58 and p['avgPrice']==161.46, 'State changed; stop'
manual=next(t for t in txs if str(t.get('_doc_id'))=='1791794330415')
assert manual['size']==5 and manual['price']==136.5 and not manual.get('source')
base=json.loads((ROOT/'data/reconciliation-audits/soxl-identity-repair-20261003.json').read_text(encoding='utf-8'))['original']
assert base['holdingQty']==60
expected={'wwlfneqtzxqlunwprvakbxwvkytnxahy':('sell',15,163),
 'purglppkdjhxmmltkjddapkdtestaled':('sell',10,164.27),
 'czucvvnqdxzktslmxogehaufptpatxoc':('buy',2,164.26),
 'cxvavuryjvewtinkchqzgdlbqxfylybm':('buy',5,142.45),
 'kipaybcqalsourzgjlgsuniannjxbjnp':('buy',5,136.5)}
state=base
for sid,values in expected.items():
    matches=[t for t in txs if t.get('sourceTradeId')==sid]
    assert len(matches)==1
    t=matches[0]; assert (t['type'],t['size'],t['price'])==values
    state=fg.apply_v4_transaction(state,t)
assert state['holdingQty']==47
changes={k:state[k] for k in ('holdingQty','totalBuy','totalSell','tValue','reverseMode','reverseModeStarPrice')}
changes.update(avgPrice=154.8035,stock8Reconciliation='KIS holding 47 @ 154.8035; verified Oct-03 anchor plus subsequent fills; 2026-10-12')
backup=ROOT/'data/reconciliation-audits'/('soxl-repair-20261012-'+datetime.datetime.now().strftime('%H%M%S%f')+'.json')
backup.write_text(json.dumps(dict(portfolio=p,transactions=txs,changes=changes),ensure_ascii=False,indent=2),encoding='utf-8')
off()
# Preserve the auto-imported broker record; remove only the identified manual duplicate.
client._request('DELETE',client._path('transactions',manual['_doc_id']))
client.update_portfolio(pid,changes)
after=client.get_portfolio(pid); after_txs=client.list_transactions(pid)
assert after['holdingQty']==47 and abs(after['avgPrice']-154.8035)<1e-8
assert not any(t.get('_doc_id')==manual['_doc_id'] for t in after_txs)
assert len(after_txs)==len(txs)-1
print(json.dumps({'verified':True,'qty':after['holdingQty'],'avg':after['avgPrice'],'tValue':after['tValue'],'backup':backup.name}))
