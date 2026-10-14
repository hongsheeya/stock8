import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock
import datetime

spec=importlib.util.spec_from_file_location('accounting_audit',Path(__file__).resolve().parents[1]/'src/portal/trading/model/struct/daytrade.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class AccountingTests(unittest.TestCase):
    def service(self):
        s=m.Daytrade.__new__(m.Daytrade)
        s.strategy_spec=lambda _: {'name':'test'}
        return s
    def summary(self,row):
        return self.service()._summarize_backtest([row],100,'TEST','KS','1d','5m',{},'vrev')['summary']
    def test_intraday_risk_not_hidden_by_positive_close(self):
        r=self.summary(dict(seed=100,net_profit=10,equity_curve=[100,50,110],trades=[]))
        self.assertEqual(r['max_drawdown'],50)
    def test_average_winner_uses_only_winners(self):
        r=self.summary(dict(net_profit=5,gross_profit=10,gross_loss=-5,trades=[{'side':'SELL','pnl':10},{'side':'SELL','pnl':-5}]))
        self.assertEqual(r['avg_win'],10)
        self.assertEqual(r['trade_win_rate'],50)
        self.assertEqual(r['win_rate_basis'],'profitable_sessions')
    def test_no_loss_pf_not_currency(self):
        r=self.summary(dict(net_profit=10000,gross_profit=10000,gross_loss=0,trades=[]))
        self.assertFalse(r['profit_factor_defined'])
        self.assertEqual(r['profit_factor'],0)
    def test_holding_uses_timestamps_not_bar_count(self):
        trades=[dict(side='BUY',qty=2,timestamp='2026-01-01T09:00:00'),dict(side='SELL',qty=2,timestamp='2026-01-01T09:15:00')]
        r=self.service()._summarize_session({'bars':[]},100,trades,0,[],'vrev',{},holding_minutes=3)
        self.assertEqual(r['avg_holding_minutes'],15)
    def test_final_block_is_evaluated_after_selection(self):
        s=self.service()
        s._prepare_dataset=Mock(return_value=[{'id':i} for i in range(10)])
        s._profile_grid=lambda _: {'choice':[1,2]}
        s._default_profile_for_market=lambda **kw: {'choice':1}
        s._now=lambda: datetime.datetime(2026,1,1)
        calls=[]
        def fake(sessions,*args,**kw):
            ids=[x['id'] for x in sessions]; calls.append(ids)
            # Test would favor choice 2 if it leaked into optimization.
            score=(100 if kw['profile']['choice']==2 else 0) if ids==[8,9] else (10 if kw['profile']['choice']==1 else 0)
            return {'summary':{'score':score},'validation':{}}
        s._backtest_sessions=fake
        r=s._optimize_payload('TEST')
        self.assertEqual(r['best']['profile']['choice'],1)
        self.assertEqual(calls[-1],[8,9])
        self.assertTrue(all(x==list(range(8)) for x in calls[:-1]))
    def test_breakout_fills_following_open(self):
        s=self.service()
        s._event_filter_snapshot=lambda *args: {}
        bars=[]
        for i,(o,c) in enumerate([(100,100),(200,200),(210,210),(220,220)]):
            bars.append(dict(timestamp=f'2026-01-01T09:{i*5:02d}:00',time=f'09:{i*5:02d}',open=o,close=c,high=max(o,c),low=min(o,c),volume=100,volume_surge_ratio=2,vwap=c,breakout_high_20=c,breakout_low_20=0))
        r=s._simulate_volume_breakout_session({'date':'2026-01-01','prev_close':100,'bars':bars},1000,dict(commission_bps=0,slippage_bps=0,sell_tax_bps=0))
        first=r['trades'][0]
        self.assertEqual(first['price'],200)
        self.assertEqual(first['timestamp'],bars[1]['timestamp'])


if __name__=='__main__': unittest.main()
