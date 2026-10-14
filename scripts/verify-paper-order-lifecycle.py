"""Bounded PAPER adapter test: one non-marketable NVDA share, then cancel.

Does not change settings or test strategy profitability. No blind resubmission.
"""
import os
os.environ['TRADING_MODE'] = 'PAPER'
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import argparse
import msvcrt
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--market', choices=['KS', 'US'], default='US')
parser.add_argument('--cancel-order', default='')
args = parser.parse_args()
audit_dir = ROOT / 'data/reconciliation-audits'
audit_dir.mkdir(parents=True, exist_ok=True)
# Hold an OS lock across all reads/writes; process death releases the lock.
run_lock = (audit_dir / ('paper-lifecycle-' + args.market.lower() + '.lock')).open('a+b')
run_lock.seek(0, 2)
if run_lock.tell() == 0:
    run_lock.write(b'0')
    run_lock.flush()
run_lock.seek(0)
msvcrt.locking(run_lock.fileno(), msvcrt.LK_NBLCK, 1)
domestic = args.market == 'KS'
symbol = '233740' if domestic else 'NVDA'
db = sqlite3.connect(f'file:{ROOT / "data/paper/trading.db"}?mode=ro', uri=True)
rows = db.execute("select key,value from trading_config where key like 'user:%:kis_paper_account_no'").fetchall()
rows = [r for r in rows if str(r[1]).replace('-', '').replace(' ', '')[:8].endswith('1791')]
if len(rows) != 1:
    raise RuntimeError('Unique authorized PAPER owner required')
uid = rows[0][0].split(':')[1]
class Clock:
    @staticmethod
    def now(): return datetime.datetime.now(ZoneInfo('Asia/Seoul')).replace(tzinfo=None)
    @staticmethod
    def today(fmt='%Y-%m-%d'): return Clock.now().strftime(fmt)
class Config:
    def _current_user_id(self): return uid
    def get_config(self, key, default=''):
        if 'live' in key: raise RuntimeError('LIVE configuration forbidden')
        row = db.execute('select value from trading_config where key=?',(f'user:{uid}:{key}',)).fetchone()
        return row[0] if row else default
    def set_config(self, *args, **kwargs): raise RuntimeError('Configuration writes forbidden')
spec = importlib.util.spec_from_file_location('paper_lifecycle_kis', ROOT/'src/portal/trading/model/struct/kis_api.py')
module = importlib.util.module_from_spec(spec)
module.wiz = type('Wiz', (), {'model': lambda self,name: Clock})()
spec.loader.exec_module(module)
def local_model(name):
    path = ROOT / ('src/portal/trading/model/' + name.rsplit('/', 1)[-1] + '.py')
    ms = importlib.util.spec_from_file_location('paper_test_' + path.stem, path)
    model = importlib.util.module_from_spec(ms)
    ms.loader.exec_module(model)
    return getattr(model, 'Model', model)
module.wiz = type('Wiz', (), {'model':lambda self,name:local_model(name)})()
module._TIME = local_model('portal/trading/kst')
class PaperOnly(module.KisApi):
    writes = 0
    def _issue_token(self): raise RuntimeError('Cached auth required')
    def _log(self, *args, **kwargs): pass
    def _request(self, method, path, *args, **kwargs):
        if self.is_real or self.base_url != module.MOCK_BASE_URL:
            raise RuntimeError('PAPER host mismatch')
        if method == 'POST':
            body = kwargs.get('body', {})
            cancel_original = (report.get('accepted_order') or {}).get('order_no')
            symbol_ok = body.get('PDNO') == symbol or (domestic and path.endswith('/order-rvsecncl') and cancel_original and body.get('ORGN_ODNO') == cancel_original)
            if not symbol_ok or body.get('ORD_QTY') != '1':
                raise RuntimeError('Only one configured test share allowed')
            allowed = (['/uapi/domestic-stock/v1/trading/order-cash', '/uapi/domestic-stock/v1/trading/order-rvsecncl'] if domestic else
                       ['/uapi/overseas-stock/v1/trading/order', '/uapi/overseas-stock/v1/trading/order-rvsecncl'])
            if self.writes >= 2 or path != allowed[self.writes]:
                raise RuntimeError('Duplicate or unplanned write blocked')
            self.writes += 1
            # Persist before the network request: a crash/timeout may still
            # leave an accepted broker order. Never automatically replay it.
            report.setdefault('write_intents', []).append({'path':path, 'at':Clock.now().isoformat()})
            report['post_attempts'] = self.writes
            save()
            kwargs['retries'] = 0
        return super()._request(method, path, *args, **kwargs)

api = PaperOnly(Config())
report = {'mode':'PAPER','market':args.market,'symbol':symbol,'qty':1,'purpose':'non-marketable limit acceptance/cancel adapter test','checks':[]}
target = ROOT/f'data/reconciliation-audits/paper-order-lifecycle-{args.market.lower()}-latest.json'
def save():
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

if target.exists() and not args.cancel_order:
    prior = json.loads(target.read_text(encoding='utf-8'))
    if prior.get('write_intents') or prior.get('post_attempts', 0) or prior.get('accepted_order'):
        print(json.dumps({'blocked':'Prior test may have reached broker; reconcile without a new order',
                          'evidence':str(target)}, ensure_ascii=False))
        raise SystemExit(2)
if args.cancel_order:
    prior = json.loads(target.read_text(encoding='utf-8'))
    order = prior.get('accepted_order', {})
    if prior.get('mode') != 'PAPER' or order.get('order_no') != args.cancel_order or order.get('symbol') != symbol:
        raise RuntimeError('Only the recorded PAPER test order may be cleaned up')
    report = prior
    if report.get('cancel_acceptance') or len(report.get('write_intents', [])) > 1:
        raise RuntimeError('Cancellation already attempted; verify broker history, do not replay')
    api.writes = 1
    with api.request_options(timeout=30,retries=0):
        report['cancel_acceptance'] = api.cancel_domestic_order(args.cancel_order,symbol,1,org_branch_no=order['org_branch_no'],exchange='KRX',ord_dvsn=order['ord_dvsn']) if domestic else api.cancel_overseas_order(args.cancel_order,symbol,1,'NASD')
    report.pop('error',None)
    save()
    with api.request_options(timeout=45,retries=0):
        report['history'] = api.get_domestic_fills_today(symbol) if domestic else api.get_overseas_order_history(symbol=symbol,exchanges=['NASD'],strict=True)
    report['post_attempts'] = api.writes
    save()
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0)
try:
    now = datetime.datetime.now(ZoneInfo('Asia/Seoul' if domestic else 'America/New_York'))
    start,end = (540,900) if domestic else (570,950)
    if now.weekday() >= 5 or not (start <= now.hour*60+now.minute < end):
        raise RuntimeError('Regular session with cancellation time required')
    modern = str(Config().get_config('daytrade_us_auto_enabled','')).lower()
    enabled = modern if modern in ('true', 'false') else str(Config().get_config('us_daytrade_auto_enabled','false')).lower()
    if domestic: enabled = str(Config().get_config('daytrade_auto_enabled','false')).lower()
    if enabled != 'true':
        raise RuntimeError('PAPER US lane is OFF')
    key = 'order_policy_v1:' + hashlib.sha256(('kis:'+api.account_no).encode()).hexdigest()[:40]
    row = db.execute('select value from trading_config where key=?',(key,)).fetchone()
    if row and json.loads(row[0]).get('symbols',{}).get(symbol,False):
        raise RuntimeError('Test symbol is locked')
    if not api.has_valid_cached_token(): raise RuntimeError('Cached PAPER auth unavailable')
    with api.request_options(timeout=45,retries=0):
        existing = api.get_domestic_fills_today(symbol) if domestic else api.get_overseas_order_history(symbol=symbol, exchanges=['NASD'], strict=True)
    if existing:
        report['existing_orders']=existing
        flat = domestic and all(r.get('status') == 'FILLED' and int(r.get('rmn_qty',0)) == 0 for r in existing)
        net = sum(int(r.get('filled_qty',0)) * (1 if r.get('side') == 'BUY' else -1) for r in existing)
        if not flat or net != 0:
            raise RuntimeError('Existing open orders or position: avoid interference')
    with api.request_options(timeout=20,retries=0):
        quote = api.get_domestic_current_price(symbol) if domestic else api.get_current_price(symbol, exchange='NAS')
    price = round(float(quote.get('price', quote.get('current_price',0))) * (0.9 if domestic else 0.5),2)
    if domestic: price = int(price // 5 * 5)
    if not 1 <= price <= (100000 if domestic else 500): raise RuntimeError('Invalid or oversized test limit')
    if domestic:
        with api.request_options(timeout=20,retries=0):
            power=api.get_domestic_buying_power_info(symbol,price=price,order_type='LIMIT')
        if not power.get('ok') or float(power.get('amount',0)) < price:
            raise RuntimeError('Insufficient confirmed PAPER buying power')
    report['limit_price']=price
    save()
    with api.request_options(timeout=30,retries=0):
        order = (api.buy_domestic_order(symbol,1,price=price,order_type='LIMIT') if domestic else
                 api.buy_order(symbol,1,price=price,order_type='LIMIT',exchange='NASD',allow_auto_exchange_attempt=False))
    report['accepted_order']=order
    save()
    order_no=order.get('order_no','')
    if not order_no: raise RuntimeError('No broker order number; do not retry')
    with api.request_options(timeout=30,retries=0):
        report['cancel_acceptance']=(api.cancel_domestic_order(order_no,symbol,1,org_branch_no=order.get('org_branch_no',''),exchange='KRX',ord_dvsn=order.get('ord_dvsn')) if domestic else api.cancel_overseas_order(order_no,symbol,1,'NASD'))
    save()
    with api.request_options(timeout=45,retries=0):
        history=api.get_domestic_fills_today(symbol) if domestic else api.get_overseas_order_history(symbol=symbol,exchanges=['NASD'],strict=True)
    report['history']=history
except Exception as exc:
    report['error']=str(exc)
finally:
    report['post_attempts']=api.writes
    save()
    print(json.dumps(report,ensure_ascii=False,indent=2))
