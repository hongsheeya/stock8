import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('selective_research', Path(__file__).resolve().parents[1] / 'scripts/evaluate-selective-daytrade.py')
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)


class SelectiveResearchTests(unittest.TestCase):
    def session(self, prices):
        return [dict(date='2026-09-01', prev_close=100, bars=[dict(
            timestamp=f'2026-09-01T10:{i:02}:00+09:00', open=p,close=p,high=p,low=p,volume=100,
            warm=True,ema20=99,ema50=98,trend_rsi=60,trend_rsi_prev=59,rsi14=60,vwap=99,
            candidate_entry=True,protect_add=False) for i,p in enumerate(prices)])]

    def run_candidate(self, session, **overrides):
        return research.bench.run(session,mode='selective',candidate={**research.CONFIG,**overrides},cost_scale=0)

    def test_one_cycle_per_day_even_after_take_profit(self):
        r=self.run_candidate(self.session([100,100,104,104,100,100,100,100,100,100]))
        self.assertEqual(r['cycles'],1)
        self.assertEqual(r['trades'][0]['reason'],'target')

    def test_candidate_stop_not_basket_five_percent(self):
        r=self.run_candidate(self.session([100,100,98,98,100,100]))
        self.assertEqual(r['trades'][0]['reason'],'stop')
        self.assertEqual(r['trades'][0]['exit_price'],98)

    def test_max_holding_queues_exit_next_bar(self):
        r=self.run_candidate(self.session([100]*10),max_bars=3)
        self.assertEqual(r['trades'][0]['reason'],'time_exit')
        self.assertEqual(r['orders'][1]['time'][14:16],'05')

    def test_false_signal_never_enters(self):
        s=self.session([100]*10)
        for b in s[0]['bars']: b['candidate_entry']=False
        self.assertEqual(self.run_candidate(s)['cycles'],0)

    def test_insufficient_cash_has_no_fill_or_unbound_variable(self):
        r=research.bench.run(self.session([100]*10),mode='selective',candidate=research.CONFIG,cap_fraction=.0000001)
        self.assertEqual(r['cycles'],0)
        self.assertGreater(r['rejected_size'],0)

    def test_signal_rejects_late_or_low_volume_and_is_causal(self):
        s=self.session([100]*21)
        b=s[0]['bars'][-1]
        b.update(close=102,open=102,high=102,low=102,volume=200,ema20=100)
        prepared=research.signals(s,'breakout')
        self.assertTrue(prepared[0]['bars'][-1]['candidate_entry'])
        b['volume']=100
        self.assertFalse(research.signals(s,'breakout')[0]['bars'][-1]['candidate_entry'])
        b['volume']=200
        b['timestamp']='2026-09-01T14:00:00+09:00'
        self.assertFalse(research.signals(s,'breakout')[0]['bars'][-1]['candidate_entry'])
