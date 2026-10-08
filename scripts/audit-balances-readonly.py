"""Bounded GET-only balance audit. Never refresh tokens, store data or order."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import time

ROOT = Path(__file__).resolve().parents[1]
os.environ['TRADING_MODE'] = 'LIVE'
db = sqlite3.connect(f'file:{ROOT / "data/live/trading.db"}?mode=ro', uri=True)
uid = db.execute('select user_id from trading_cycle where id=?', ('tsevwkrrjetkjjunnsamosnumiuskebe',)).fetchone()[0]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    module.wiz = type('Wiz', (), {'model': lambda self, name: clock.Model})()
    spec.loader.exec_module(module)
    return module

clock = load('balance_audit_clock', 'src/portal/trading/model/kst.py')
kis = load('balance_audit_kis', 'src/portal/trading/model/struct/kis_api.py')

class Config:
    def _current_user_id(self): return uid
    def get_config(self, key, default=''):
        row = db.execute('select value from trading_config where key=?', (f'user:{uid}:{key}',)).fetchone()
        return row[0] if row else default
    def set_config(self, *args, **kwargs): raise RuntimeError('Read-only audit')

class ReadOnly(kis.KisApi):
    def _issue_token(self, *args, **kwargs): raise RuntimeError('Cached token unavailable; audit cannot refresh it')
    def _log(self, *args, **kwargs): pass
    def _request(self, method, path, *args, **kwargs):
        if method != 'GET' or path not in (
            '/uapi/domestic-stock/v1/trading/inquire-balance',
            '/uapi/overseas-stock/v1/trading/inquire-balance',
            '/uapi/overseas-stock/v1/trading/inquire-present-balance',
        ): raise RuntimeError('Endpoint denied')
        time.sleep(1.2)
        return super()._request(method, path, *args, **kwargs)

def main():
  api = ReadOnly(Config())
  with api.request_options(timeout=8, retries=0):
    for name in ('get_domestic_balance', 'get_balance', 'get_present_balance'):
        started = time.monotonic()
        try:
            data = getattr(api, name)()
            fields = {k: v for k, v in data.items() if k in (
                'cash_balance', 'total_eval', 'portfolio_eval_krw', 'total_asset_krw',
                'total_asset_source', 'krw_balance', 'krw_withdrawable', 'usd_krw',
                'usd_krw_source', 'unsettled_buy_krw', 'unsettled_sell_krw')}
            fields['holdings_count'] = len(data.get('holdings', []))
            print(json.dumps({'endpoint': name, 'seconds': round(time.monotonic()-started, 3), 'values': fields}, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(json.dumps({'endpoint': name, 'error_type': type(exc).__name__, 'message': str(exc)[:220]}, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    main()
