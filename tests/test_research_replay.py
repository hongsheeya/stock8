import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('replay',Path(__file__).resolve().parents[1]/'src/portal/trading/model/research_replay.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def bars(prices):
    return [dict(timestamp=f'2026-01-01T09:{i*5:02d}:00',open=p,high=p,low=p,close=p) for i,p in enumerate(prices)]


class ReplayTests(unittest.TestCase):
    def test_next_open_and_cash(self):
        r=m.replay(bars([100,200,220]),[1,1,0],seed=1000,buy_bps=0,sell_bps=0)
        self.assertEqual(r['orders'][0]['price'],200)
        self.assertEqual(r['orders'][0]['qty'],5)
        self.assertEqual(r['pnl'],100)
    def test_intraday_drawdown(self):
        r=m.replay(bars([100,100,50,110]),[1]*4,seed=1000,buy_bps=0,sell_bps=0)
        self.assertEqual(r['close_mdd_pct'],50)
        self.assertEqual(r['profit_factor'],None)
    def test_both_costs_charged(self):
        r=m.replay(bars([100]*3),[1]*3,seed=1000,buy_bps=100,sell_bps=100)
        self.assertAlmostEqual(r['pnl'],-18)
        self.assertAlmostEqual(r['costs'],18)
    def test_no_future_signal_execution(self):
        r=m.replay(bars([100]*3),[0,0,1],buy_bps=0,sell_bps=0)
        self.assertEqual(r['orders'],[])
    def test_short_blocked(self):
        with self.assertRaises(ValueError): m.replay(bars([100]*3),[-1]*3)
    def test_misaligned_basket_rejected(self):
        a=m.replay(bars([100]*3),[0]*3)
        b=m.replay(bars([100]*2),[0]*2)
        with self.assertRaises(ValueError): m.aggregate([a,b])
