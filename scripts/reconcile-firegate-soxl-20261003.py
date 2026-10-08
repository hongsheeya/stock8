"""Restore the original SOXL record; archive its duplicate, never broker orders.

Default is a read-only plan. --apply requires all current LIVE strategy flags OFF,
the exact verified broker fill and holding, and writes recoverable backups first.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--apply', action='store_true')
args = p.parse_args()
os.environ['TRADING_MODE'] = 'LIVE'
cid = 'tsevwkrrjetkjjunnsamosnumiuskebe'
original_id, duplicate_id = 1780022179464, 1790947379164
event = 'soxl-identity-repair-20261003'
db = sqlite3.connect(root / 'data/live/trading.db')
db.row_factory = sqlite3.Row
cycle = dict(db.execute('select * from trading_cycle where id=?', (cid,)).fetchone())
uid = cycle['user_id']

class Config:
    def _current_user_id(self): return uid
    def get_config(self, key, default=''):
        row = db.execute('select value from trading_config where key=?', (f'user:{uid}:{key}',)).fetchone()
        return row[0] if row else default
    def set_config(self, *args, **kwargs): raise RuntimeError('Configuration writes forbidden')

def assert_off():
    account = Config().get_config('kis_live_account_no').strip()
    key = 'order_policy_v1:' + hashlib.sha256(('kis:' + account).encode()).hexdigest()[:40]
    policy = json.loads(db.execute('select value from trading_config where key=?', (key,)).fetchone()[0])
    assert all(policy.get(lane) is False for lane in ('infinite_buy', 'daytrade_ks', 'daytrade_us')), 'Strategies must remain OFF'

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, root / path)
    module = importlib.util.module_from_spec(spec)
    module.wiz = type('Wiz', (), {'model': lambda self, name: clock.Model})()
    spec.loader.exec_module(module)
    return module

assert_off()
clock = load('reconcile_clock', 'src/portal/trading/model/kst.py')
kis = load('reconcile_kis', 'src/portal/trading/model/struct/kis_api.py')
fg = load('reconcile_fg', 'src/portal/trading/model/struct/firegate_bridge.py')

class ReadOnlyKis(kis.KisApi):
    def _issue_token(self, *args, **kwargs): raise RuntimeError('Cached token required')
    def _log(self, *args, **kwargs): pass
    def _request(self, method, path, *args, **kwargs):
        assert method == 'GET' and path in (
            '/uapi/overseas-stock/v1/trading/inquire-balance',
            '/uapi/overseas-stock/v1/trading/inquire-ccnl'), 'Broker writes forbidden'
        time.sleep(1.2)
        return super()._request(method, path, *args, **kwargs)

api = ReadOnlyKis(Config())
with api.request_options(timeout=8, retries=0):
    holding = next(h for h in api.get_balance()['holdings'] if h['symbol'] == 'SOXL')
    fills = api.get_overseas_order_history(start_date='20261001', end_date='20261003', symbol='SOXL')
confirmed = [f for f in fills if f.get('filled_qty', 0) > 0]
assert len(confirmed) == 1, 'Reconciliation range changed'
fill = confirmed[0]
assert fill['action'] == 'SELL' and fill['order_no'] == '0030955142' and fill['filled_qty'] == 15 and fill['filled_price'] == 163
assert holding['qty'] == 45 and abs(holding['avg_price'] - 158.6427) < .00001, 'Broker holding changed'
cfg = json.loads(Config().get_config('fire_gate_bridge'))
token = fg.refresh_id_token(cfg['refresh_token'])
client = fg.FireGateBridge(cfg['email'], token.get('id_token') or token.get('idToken'))
original, duplicate = client.get_portfolio(original_id), client.get_portfolio(duplicate_id)
original_txs, duplicate_txs = client.list_transactions(original_id), client.list_transactions(duplicate_id)
local_txs = [dict(t) for t in db.execute('select * from cycle_trade where cycle_id=?', (cid,))]
trade = next(t for t in local_txs if str(t.get('broker_order_no', '')).lstrip('0') == '30955142')
assert trade['filled_qty'] == 15 and trade['filled_price'] == 163 and trade['action'] == 'SELL'
already = original.get('identityRepairId') == event
if not already:
    assert original['holdingQty'] == 60 and abs(original['avgPrice'] - 158.6427) < .00001
assert duplicate['ticker'] == original['ticker'] == 'SOXL'
tx = fg.transaction_from_cycle_trade(trade, original_id, portfolio=original)
assert tx and tx['size'] == 15 and tx['type'] == 'sell'
tx['brokerOrderNo'] = fill['order_no']
tx['memo'] = 'KIS confirmed 2026-10-02 SELL 15 @ 163. Identity repair, no broker order.'
changes = dict(original) if already else fg.apply_v4_transaction(original, tx)
changes.update(holdingQty=45, avgPrice=holding['avg_price'], sourceCycleId=cid,
               identityRepairId=event, reconciledSourceTradeIds=[str(t['id']) for t in local_txs],
               isRunning=True, archivedDuplicateId=duplicate_id)
for key in ('_doc_id', 'id'):
    changes.pop(key, None)
print(json.dumps({'plan': 'original SOXL becomes canonical; duplicate retained but archived',
                  'broker_qty': holding['qty'], 'broker_avg': holding['avg_price'],
                  'confirmed_sell_qty': fill['filled_qty'], 'original_transactions': len(original_txs),
                  'duplicate_transactions_preserved': len(duplicate_txs), 'already_repaired': already}, ensure_ascii=False), flush=True)
if not args.apply: raise SystemExit(0)
assert_off()
backup_dir = root / 'data/reconciliation-audits'
backup_dir.mkdir(exist_ok=True)
backup = backup_dir / (event + '.json')
if not backup.exists():
    backup.write_text(json.dumps({'original': original, 'duplicate': duplicate,
        'original_transactions': original_txs, 'duplicate_transactions': duplicate_txs,
        'cycle_before': cycle, 'local_transactions': local_txs,
        'broker_holding': holding, 'broker_fill': fill}, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
sqlite_backup = backup_dir / (event + '.db')
if not sqlite_backup.exists():
    with sqlite3.connect(sqlite_backup) as out: db.backup(out)
doc_id = f"identity-repair-{original_id}-{trade['id']}"
if not any(str(t.get('sourceTradeId', '')) == str(trade['id']) for t in original_txs):
    client.create_transaction(tx, doc_id=doc_id)
client.update_portfolio(original_id, changes)
client.update_portfolio(duplicate_id, {'isRunning': False, 'stock8Archived': True,
    'archivedIntoPortfolioId': original_id, 'identityRepairId': event,
    'nickname': '보관 · SOXL 중복 기록 (원본으로 통합)',
    'archiveReason': 'Local cycle ID migration created duplicate. All transactions preserved.'})
assert_off()
cost = round(holding['qty'] * holding['avg_price'], 2)
now = datetime.datetime.now().isoformat(sep=' ', timespec='seconds')
db.execute('update trading_cycle set total_qty=?,avg_price=?,total_spent=?,current_price=?,current_eval=?,remaining_investment=?,current_round=?,t_value=?,status=?,updated=? where id=?',
    (45, holding['avg_price'], cost, holding['current_price'], holding['eval_amount'],
     max(0, original['seed'] - (changes['totalBuy'] - changes['totalSell'])),
     int(changes['tValue']), changes['tValue'], 'ACTIVE', now, cid))
anchor_key = f'user:{uid}:cycle_bookkeeping_anchor:{cid}'
anchor = json.dumps({'verified': True, 'trade_id': trade['id'], 'qty_before': 60,
    'avg_before': holding['avg_price'], 'source': 'KIS holding + confirmed 20261002 sell; no intervening buys',
    'order_no': fill['order_no']}, ensure_ascii=False)
if db.execute('select 1 from trading_config where key=?', (anchor_key,)).fetchone():
    db.execute('update trading_config set value=?,updated=? where key=?', (anchor, now, anchor_key))
else:
    db.execute('insert into trading_config(id,key,value,description,is_secret,created,updated) values(?,?,?,?,?,?,?)',
        (uuid.uuid4().hex, anchor_key, anchor, 'Verified cost-basis anchor, not a synthetic fill', 0, now, now))
sold_cost = holding['avg_price'] * 15
realized = 2445 - float(trade.get('commission') or 0) - sold_cost
db.execute('update cycle_trade set avg_buy_price=?,total_qty_after=?,total_spent_after=?,profit_rate=? where id=?',
    (holding['avg_price'], 45, cost, round(realized / sold_cost * 100, 2), trade['id']))
db.commit()
after = client.get_portfolio(original_id)
archived = client.get_portfolio(duplicate_id)
assert after['holdingQty'] == 45 and after['sourceCycleId'] == cid
assert archived['stock8Archived'] and not archived['isRunning']
assert len(client.list_transactions(duplicate_id)) == len(duplicate_txs)
assert db.execute('select count(*) from cycle_trade where cycle_id=?', (cid,)).fetchone()[0] == len(local_txs)
print('Verified: canonical SOXL 45 shares; duplicate archived; all old transactions preserved; strategies OFF.', flush=True)
