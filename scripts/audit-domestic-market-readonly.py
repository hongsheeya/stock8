"""Inspect KIS market metadata with cached credentials, never submit orders."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import time

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--cycle-id', required=True)
p.add_argument('--symbol', default='005930')
a = p.parse_args()
os.environ['TRADING_MODE'] = 'LIVE'
db = sqlite3.connect(f'file:{ROOT / "data/live/trading.db"}?mode=ro', uri=True)
row = db.execute('select user_id from trading_cycle where id=?', (a.cycle_id,)).fetchone()
if not row: raise SystemExit('Account scope not found')
uid = row[0]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    module.wiz = type('Wiz', (), {'model': lambda self,name: clock.Model})()
    spec.loader.exec_module(module)
    return module

clock = load('market_audit_clock','src/portal/trading/model/kst.py')
kis = load('market_audit_kis','src/portal/trading/model/struct/kis_api.py')

class Config:
    def _current_user_id(self): return uid
    def get_config(self, key, default=''):
        value = db.execute('select value from trading_config where key=?',(f'user:{uid}:{key}',)).fetchone()
        return value[0] if value else default
    def set_config(self,*args,**kwargs): raise RuntimeError('Read-only audit')

class ReadOnly(kis.KisApi):
    def _issue_token(self): raise RuntimeError('No valid cached token; reconnect in settings')
    def _request(self,method,path,*args,**kwargs):
        if method != 'GET' or path not in (
            '/uapi/domestic-stock/v1/quotations/search-stock-info',
            '/uapi/domestic-stock/v1/quotations/inquire-price'):
            raise RuntimeError('Endpoint denied')
        time.sleep(1.2)
        return super()._request(method,path,*args,**kwargs)

api = ReadOnly(Config())
with api.request_options(timeout=8,retries=0):
    data = api._request('GET','/uapi/domestic-stock/v1/quotations/search-stock-info','CTPF1002R',
                        params={'PRDT_TYPE_CD':'300','PDNO':a.symbol})
    output = data.get('output', {})
    # Only public instrument facts; never print headers, tokens or account data.
    print(json.dumps({'rt_cd':data.get('rt_cd'),'msg':data.get('msg1'), 'metadata':output},ensure_ascii=False),flush=True)
    for exchange in ('KRX','NXT'):
        quote = api.get_domestic_current_price(a.symbol, exchange)
        print(json.dumps({'exchange':exchange,'quote':quote['raw']},ensure_ascii=False),flush=True)
