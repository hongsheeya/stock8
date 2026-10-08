"""KIS PAPER account read probe. Optional OAuth refresh; all trading POSTs denied."""
import datetime
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account-last4', help='Confirmed PAPER account last four digits, excluding product code')
    parser.add_argument('--refresh-auth', action='store_true', help='Allow PAPER OAuth only; keep refreshed token in memory, never change trading settings')
    args = parser.parse_args()
    if args.account_last4 and (len(args.account_last4) != 4 or not args.account_last4.isdigit()):
        parser.error('account-last4 must contain exactly four digits')
    os.environ['TRADING_MODE'] = 'PAPER'
    db = sqlite3.connect(f'file:{ROOT / "data/paper/trading.db"}?mode=ro', uri=True)
    rows = db.execute("select key, value from trading_config where key like 'user:%:kis_paper_account_no' and value != ''").fetchall()
    report = dict(mode='PAPER', configured_scoped_accounts=len(rows), orders_submitted=0, checks=[])
    if args.account_last4:
        rows = [row for row in rows if str(row[1]).replace('-', '').replace(' ', '')[:8][-4:] == args.account_last4]
    report['matching_scoped_accounts'] = len(rows)
    if len(rows) != 1:
        report['blocked'] = 'Exactly one scoped paper account is required; do not guess account ownership.'
    else:
        uid = rows[0][0].split(':')[1]
        class Config:
            temporary = {}
            def _current_user_id(self): return uid
            def get_config(self, key, default=''):
                if 'live' in key: raise RuntimeError('LIVE configuration denied')
                if key in self.temporary: return self.temporary[key]
                row = db.execute('select value from trading_config where key=?', (f'user:{uid}:{key}',)).fetchone()
                return row[0] if row else default
            def set_config(self, key, value, **kwargs):
                if not args.refresh_auth or key not in api.token_config_keys:
                    raise RuntimeError('read-only probe')
                self.temporary[key] = str(value)
        class Clock:
            @staticmethod
            def now(): return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).replace(tzinfo=None)
            @staticmethod
            def today(fmt='%Y-%m-%d'): return Clock.now().strftime(fmt)
        spec = importlib.util.spec_from_file_location('paper_probe_kis', ROOT/'src/portal/trading/model/struct/kis_api.py')
        module = importlib.util.module_from_spec(spec)
        module.wiz = type('Wiz', (), {'model':lambda self,name:Clock})()
        spec.loader.exec_module(module)
        class PaperReadOnly(module.KisApi):
            def _issue_token(self,*pos,**kwargs):
                if not args.refresh_auth:
                    raise RuntimeError('PAPER cached token missing/expired; no refresh in read-only probe')
                if self.is_real is not False or self.base_url != module.MOCK_BASE_URL:
                    raise RuntimeError('PAPER host binding failed')
                report['oauth_refresh_attempts'] = report.get('oauth_refresh_attempts', 0) + 1
                if report['oauth_refresh_attempts'] > 1:
                    raise RuntimeError('OAuth retry denied')
                return super()._issue_token(*pos,**kwargs)
            def _log(self,*args,**kwargs): pass
            def _request(self,method,path,*args,**kwargs):
                if self.is_real is not False or self.base_url != 'https://openapivts.koreainvestment.com:29443':
                    raise RuntimeError('PAPER host binding failed')
                if method!='GET' or path not in ('/uapi/domestic-stock/v1/trading/inquire-balance','/uapi/domestic-stock/v1/trading/inquire-daily-ccld'):
                    raise RuntimeError('Request denied')
                return super()._request(method,path,*args,**kwargs)
        api=PaperReadOnly(Config())
        report['paper_host_verified']=api.is_real is False and api.base_url==module.MOCK_BASE_URL
        report['credentials_present']=bool(api.app_key and api.app_secret and api.account_no)
        report['cached_auth_valid']=api.has_valid_cached_token()
        with api.request_options(timeout=8,retries=0):
            for method in ('get_domestic_balance','get_domestic_fills_today'):
                try:
                    result=getattr(api,method)()
                    count=len(result) if isinstance(result,list) else len(result.get('holdings',[]))
                    report['checks'].append(dict(method=method,ok=True,rows=count))
                except Exception as exc:
                    message = str(exc)
                    reason = ('cached_auth_unavailable' if 'cached token missing/expired' in message else
                              'oauth_rejected' if 'OAuth' in message else
                              'timeout' if 'timeout' in message.lower() else 'request_failed')
                    report['checks'].append(dict(method=method,ok=False,error_type=type(exc).__name__,reason=reason))
    target=ROOT/'data/reconciliation-audits/selective-paper-readonly-latest.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
