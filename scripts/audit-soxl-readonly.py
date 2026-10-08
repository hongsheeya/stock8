"""Read-only KIS reconciliation evidence. Never issues tokens or submits orders."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import datetime
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--cycle-id', required=True)
parser.add_argument('--start', required=True)
parser.add_argument('--end', required=True)
parser.add_argument('--firegate', action='store_true')
args = parser.parse_args()
os.environ['TRADING_MODE'] = 'LIVE'
db = sqlite3.connect(f'file:{ROOT / "data/live/trading.db"}?mode=ro', uri=True)
row = db.execute('SELECT user_id,symbol FROM trading_cycle WHERE id=?', (args.cycle_id,)).fetchone()
if not row or row[1] != 'SOXL':
    raise SystemExit('Expected one SOXL cycle')
uid = row[0]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    module.wiz = type('Wiz', (), {'model': lambda self, name: clock.Model})()
    spec.loader.exec_module(module)
    return module

spec = importlib.util.spec_from_file_location('audit_clock', ROOT / 'src/portal/trading/model/kst.py')
clock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clock)
kis = load('audit_kis', ROOT / 'src/portal/trading/model/struct/kis_api.py')

class Config:
    def _current_user_id(self):
        return uid

    def get_config(self, key, default=''):
        value = db.execute('SELECT value FROM trading_config WHERE key=?', (f'user:{uid}:{key}',)).fetchone()
        return value[0] if value else default

    def set_config(self, *args, **kwargs):
        raise RuntimeError('Audit cannot write configuration')

class ReadOnlyKis(kis.KisApi):
    def _issue_token(self):
        raise RuntimeError('No valid cached token. Reconnect through Stock8 first.')

    def _request(self, method, path, *args, **kwargs):
        if method.upper() != 'GET' or path not in (
            '/uapi/overseas-stock/v1/trading/inquire-balance',
            '/uapi/overseas-stock/v1/trading/inquire-ccnl',
        ):
            raise RuntimeError('Read-only audit endpoint allowlist blocked request')
        time.sleep(1.2)
        return super()._request(method, path, *args, **kwargs)

api = ReadOnlyKis(Config())
if args.firegate:
    fg = load('audit_firegate', ROOT / 'src/portal/trading/model/struct/firegate_bridge.py')
    cfg = json.loads(Config().get_config('fire_gate_bridge', '{}'))
    client = fg.FireGateBridge(cfg.get('email'), cfg.get('id_token'))
    try:
        portfolios = client.list_portfolios()
    except fg.FireGateAuthError:
        token = fg.refresh_id_token(cfg.get('refresh_token'))
        client = fg.FireGateBridge(cfg.get('email'), token.get('id_token') or token.get('idToken'))
        portfolios = client.list_portfolios()
    for p in portfolios:
        if p.get('ticker') != 'SOXL':
            continue
        keys = ('id','nickname','holdingQty','avgPrice','startDate','totalBuy','totalSell','tValue','sourceCycleId','isRunning')
        print(json.dumps({'portfolio':{k:p.get(k) for k in keys}, 'transactions':client.list_transactions(p['id'])}, ensure_ascii=False), flush=True)
    raise SystemExit(0)
with api.request_options(timeout=8, retries=0):
    balance = api.get_balance()
    print(json.dumps({'holdings': [h for h in balance.get('holdings', []) if h.get('symbol') == 'SOXL']}, ensure_ascii=False), flush=True)
    start = datetime.datetime.strptime(args.start, '%Y%m%d').date()
    end = datetime.datetime.strptime(args.end, '%Y%m%d').date()
    total = 0
    while start <= end:
        next_month = (start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        stop = min(end, next_month - datetime.timedelta(days=1))
        fills = api.get_overseas_order_history(start_date=start.strftime('%Y%m%d'), end_date=stop.strftime('%Y%m%d'), symbol='SOXL')
        confirmed = [{k: r[k] for k in ('order_no','order_date','action','filled_qty','filled_price','filled_amount')} for r in fills if r.get('filled_qty', 0) > 0]
        total += sum(r['filled_qty'] * (1 if r['action'] == 'BUY' else -1) for r in confirmed)
        print(json.dumps({'from': str(start), 'to': str(stop), 'orders_returned':len(fills), 'fills':confirmed, 'cumulative_net_qty':total}, ensure_ascii=False), flush=True)
        start = next_month
