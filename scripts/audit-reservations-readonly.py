"""Read-only reservation audit: no order, cancellation, token/config writes."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
os.environ['TRADING_MODE'] = 'LIVE'
db = sqlite3.connect(f'file:{ROOT / "data/live/trading.db"}?mode=ro', uri=True)
uid = db.execute('select user_id from trading_cycle where id=?',
                 ('tsevwkrrjetkjjunnsamosnumiuskebe',)).fetchone()[0]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    if name != 'clock':
        module.wiz = type('Wiz', (), {'model': lambda self, name: clock.Model})()
    spec.loader.exec_module(module)
    return module

clock = load('clock', 'src/portal/trading/model/kst.py')
kis = load('kis_audit', 'src/portal/trading/model/struct/kis_api.py')

class Config:
    def _current_user_id(self):
        return uid

    def get_config(self, key, default=''):
        row = db.execute('select value from trading_config where key=?',
                         (f'user:{uid}:{key}',)).fetchone()
        return row[0] if row else default

    def set_config(self, *args, **kwargs):
        raise RuntimeError('Read-only audit cannot persist configuration')

class ReadOnlyKis(kis.KisApi):
    def _issue_token(self, *args, **kwargs):
        raise RuntimeError('Cached token unavailable; audit stopped without writes')

    def _request(self, method, path, *args, **kwargs):
        if method != 'GET' or path != '/uapi/overseas-stock/v1/trading/order-resv-list':
            raise RuntimeError('Read-only endpoint allowlist blocked request')
        return super()._request(method, path, *args, **kwargs)

if __name__ == '__main__':
    api = ReadOnlyKis(Config())
    with api.request_options(timeout=8, retries=0):
        rows = api.get_overseas_reservation_orders(start_date='20261002', end_date='20261005')
    fields = ('symbol', 'side', 'order_type', 'qty', 'price', 'filled_qty',
              'receipt_date', 'status_code', 'status_name', 'cancel_yn', 'reject_reason')
    print(json.dumps({'total_rows': len(rows), 'soxl': [
        {k: r.get(k) for k in fields} for r in rows if r.get('symbol') == 'SOXL'
    ]}, ensure_ascii=False))
