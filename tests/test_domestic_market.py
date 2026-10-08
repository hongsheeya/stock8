import datetime as dt
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('domestic_market', ROOT / 'src/portal/trading/model/domestic_market.py')
market = importlib.util.module_from_spec(spec)
spec.loader.exec_module(market)


def clock(h, m=0, s=0, day=1):
    return dt.datetime(2026, 10, day, h, m, s, tzinfo=market.KST)


def proof(exchange='KRX'):
    return {'symbol': '005930', 'date': '2026-10-01', 'exchange': exchange,
            'open': True, 'eligible': True, 'halted': False, 'instrument': 'STOCK'}


class MarketTests(unittest.TestCase):
    def test_boundaries(self):
        cases = [('NXT', 7,59,59,'CLOSED'), ('NXT',8,0,0,'PRE'),
                 ('NXT',8,50,0,'CLOSED'), ('NXT',9,0,29,'CLOSED'),
                 ('NXT',9,0,30,'REGULAR'), ('NXT',15,20,0,'CLOSED'),
                 ('NXT',15,39,59,'CLOSED'), ('NXT',15,40,0,'AFTER'),
                 ('KRX',8,59,59,'CLOSED'), ('KRX',9,0,0,'REGULAR'),
                 ('KRX',15,20,0,'CLOSING_AUCTION'), ('KRX',15,30,0,'CLOSED'),
                 ('KRX',15,59,59,'CLOSED'), ('KRX',16,0,0,'AFTER'),
                 ('KRX',19,59,59,'AFTER'), ('KRX',20,0,0,'CLOSED'),
                 ('NXT',20,0,0,'CLOSED')]
        for exchange,h,m,s,expected in cases:
            with self.subTest(exchange=exchange,time=(h,m,s)):
                self.assertEqual(market.session(clock(h,m,s), exchange), expected)

    def test_weekend_timezone_and_naive(self):
        self.assertEqual(market.session(clock(10,day=3)), 'CLOSED')
        self.assertEqual(market.session(clock(16).astimezone(dt.timezone.utc)), 'AFTER')
        with self.assertRaises(ValueError): market.session(dt.datetime(2026,10,1,16))

    def test_codes(self):
        for exchange,h,code in [('KRX',10,'00'), ('KRX',16,'41'), ('NXT',8,'27'), ('NXT',16,'00')]:
            self.assertEqual(market.route(clock(h),exchange,'LIMIT',70000,1,proof(exchange))['ord_dvsn'],code)
        self.assertEqual(market.route(clock(10),'KRX','MARKET',999,1)['price'],0)

    def test_fail_closed(self):
        for change in [{'date':'2026-09-30'}, {'open':False}, {'eligible':False},
                       {'halted':True}, {'halted':None}, {'instrument':'ETF'}, {'exchange':'NXT'}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                market.route(clock(16),'KRX','LIMIT',70000,1,{**proof(),**change})
        for exchange in ('KRX','NXT'):
            with self.assertRaises(ValueError): market.route(clock(16),exchange,'MARKET',0,1,proof(exchange))
        with self.assertRaises(ValueError): market.route(clock(16),'KRX','LIMIT',70000,1)
        with self.assertRaises(ValueError): market.route(clock(16),'SOR','LIMIT',70000,1,proof())

    def test_invalid_orders(self):
        for qty in (0,-1,1.5,float('nan'),float('inf')):
            with self.assertRaises(ValueError): market.route(clock(10),'KRX','LIMIT',70000,qty)
        for price in (0,-1,1.5,float('nan'),float('inf')):
            with self.assertRaises(ValueError): market.route(clock(10),'KRX','LIMIT',price,1)
        with self.assertRaises(ValueError): market.route(clock(10),'KRX','TYPO',70000,1)

    def test_cancel_original_market(self):
        self.assertEqual(market.cancel_route('KRX','41')['ORD_DVSN'],'41')
        self.assertEqual(market.cancel_route('NXT','27')['EXCG_ID_DVSN_CD'],'NXT')
        for exchange,code in [(None,None),('NXT','41'),('KRX','27')]:
            with self.assertRaises(ValueError): market.cancel_route(exchange,code)


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.time = clock(10)
        spec = importlib.util.spec_from_file_location('kis_routing_test', ROOT / 'src/portal/trading/model/struct/kis_api.py')
        self.mod = importlib.util.module_from_spec(spec)
        self.mod.wiz = SimpleNamespace(model=lambda name: SimpleNamespace(now=lambda: self.time.replace(tzinfo=None))
                                      if name.endswith('/kst') else market.Model)
        spec.loader.exec_module(self.mod)
        self.config = {'kis_live_account_no':'12345678-01','kis_is_real':'true',
                       'domestic_extended_orders_enabled':'true'}
        self.api = self.mod.KisApi(SimpleNamespace(get_config=lambda key,default='':self.config.get(key,default)))
        self.mod.PAPER_MODE = False
        self.calls = []
        self.api._request = self.request

    def request(self,*args,**kwargs):
        self.calls.append((args,kwargs))
        return {'rt_cd':'0','output':{'ODNO':'123','KRX_FWDG_ORD_ORGNO':'321'}}

    def test_regular_payload(self):
        result = self.api.buy_domestic_order('005930',1)
        args,kw = self.calls[-1]
        self.assertEqual(args[2],'TTTC0012U')
        self.assertEqual(kw['body']['EXCG_ID_DVSN_CD'],'KRX')
        self.assertEqual(kw['body']['ORD_DVSN'],'01')
        self.assertEqual(kw['retries'],0)
        self.assertEqual(result['org_branch_no'],'321')

    def test_after_payload(self):
        self.time = clock(16)
        result = self.api.sell_domestic_order('005930',1,70000,'LIMIT',evidence=proof())
        self.assertEqual(result['market_session'],'AFTER')
        self.assertEqual(self.calls[-1][1]['body']['ORD_DVSN'],'41')

    def test_paper_and_missing_proof_no_post(self):
        self.time = clock(16)
        with self.assertRaises(ValueError): self.api.buy_domestic_order('005930',1,70000,'LIMIT')
        self.mod.PAPER_MODE = True
        with self.assertRaises(ValueError): self.api.buy_domestic_order('005930',1,70000,'LIMIT',evidence=proof())
        self.assertEqual(self.calls,[])

    def test_cancel_preserves_original_type_and_never_retries(self):
        self.time = clock(10)
        self.api.cancel_domestic_order('123','005930',1,'321','KRX','41')
        args,kw = self.calls[-1]
        self.assertEqual(args[2],'TTTC0013U')
        self.assertEqual(kw['body']['ORD_DVSN'],'41')
        self.assertEqual(kw['retries'],0)


if __name__ == '__main__':
    unittest.main()
