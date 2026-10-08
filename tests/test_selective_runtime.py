"""Offline checks: no broker connection and no real/paper orders."""
import datetime as dt
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

spec = importlib.util.spec_from_file_location('selective_runtime', Path(__file__).resolve().parents[1] / 'src/portal/trading/model/selective_strategy.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Rules = module.SelectiveStrategy
SID = module.IDS[0]
NOW = '2026-10-06T11:00:00+09:00'


class RulesTests(unittest.TestCase):
    def bar(self, **changes):
        return dict(timestamp='2026-10-06T10:55:00+09:00', close=100,
                    common=True, breakout=True, pullback=True, **changes)

    def position(self):
        return dict(position_qty=10, avg_price=100, orders=[dict(
            action='BUY1', strategy_id=SID, filled_qty=10, timestamp='2026-10-06T10:30:00+09:00')])

    def decide(self, state=None, bar=None, now=NOW, **kwargs):
        return Rules.decide(SID, bar or self.bar(), state or {}, now, 1000, **kwargs)

    def test_size_reserves_costs(self):
        self.assertEqual(self.decide()['order_qty'], 9)

    def test_pending_buy_and_sell_block_duplicate_orders(self):
        for key in ('pending_buy_order_no', 'pending_sell_order_no'):
            self.assertEqual(self.decide({key:'pending'})['action'], 'HOLD')

    def test_private_holdings_never_adopted(self):
        for state in ({'broker_unmanaged_position':True}, {'position_qty':10,'avg_price':100},
                      dict(self.position(), position_qty=11)):
            self.assertEqual(self.decide(state)['action'], 'HOLD')

    def test_stop_target_and_time_exit(self):
        for price, now, action in ((98,NOW,'SELL_STOP_LOSS'), (104,NOW,'SELL_FULL'),
                                   (100,'2026-10-06T12:00:00+09:00','SELL_FULL')):
            bar=self.bar(); bar['close']=price
            result=self.decide(self.position(), bar, now)
            self.assertEqual(result['action'], action)
            self.assertEqual(result['order_qty'],10)

    def test_completed_cycle_cannot_reenter_today(self):
        state=self.position(); state['position_qty']=0
        self.assertEqual(self.decide(state)['action'],'HOLD')

    def test_entry_disabled_and_false_trigger(self):
        self.assertEqual(self.decide(allow_buy=False)['action'],'HOLD')
        for key in ('common','breakout'):
            bar=self.bar(); bar[key]=False
            self.assertEqual(self.decide(bar=bar)['action'],'HOLD')

    def test_other_strategy_fill_does_not_authorize_sell(self):
        state=self.position(); state['orders'][0]['strategy_id']='vrev'
        self.assertEqual(self.decide(state)['action'],'HOLD')

    def rows(self):
        start=dt.datetime.fromisoformat('2026-10-06T09:00:00+09:00')
        return [dict(timestamp=(start+dt.timedelta(minutes=5*i)).isoformat(),
                     open=100,high=101,low=99,close=100,volume=100) for i in range(25)]

    def test_unclosed_bar_not_used(self):
        rows=self.rows(); rows[-1]['close']=1000
        bar=Rules.snapshot([{'bars':rows}],NOW)
        self.assertEqual(bar['timestamp'],'2026-10-06T10:55:00+09:00')

    def test_stale_snapshot_rejected(self):
        with self.assertRaises(ValueError):
            Rules.snapshot([{'bars':self.rows()}], '2026-10-06T12:00:00+09:00')

    def test_duplicate_and_invalid_price_rejected(self):
        rows=self.rows()
        for broken in (rows[:2]+rows[1:3], [dict(rows[0],close=float('nan'))], [dict(rows[0],low=200)]):
            with self.assertRaises(ValueError):
                Rules.snapshot([{'bars':broken}],NOW)


class ExecutionBoundaryTests(unittest.TestCase):
    def test_engine_reads_confirmed_bars_through_runtime_model(self):
        from test_daytrade_engine_regressions import daytrade_engine as em, _engine_with_state, _StrategyStub, _WizStub
        engine, _ = _engine_with_state({}, [])
        engine.struct.kis_api.is_real=False
        engine._now=lambda:dt.datetime.fromisoformat(NOW)
        sessions=[{'date':'2026-10-06','bars':RulesTests().rows()}]
        def lookup(name):
            return Rules if name=='portal/trading/selective_strategy' else _WizStub.model(name)
        with patch.object(em,'_PAPER_MODE',True), patch.object(em,'wiz',SimpleNamespace(model=lookup),create=True), \
             patch.object(_StrategyStub,'_prepare_dataset',lambda *a,**k:sessions,create=True), \
             patch.object(_StrategyStub,'_default_profile_for_market',lambda *a,**k:{},create=True):
            result=engine._selective_paper_signal('005930','KS',1000000,'삼성전자',SID,False,True)
        self.assertEqual(result['signal']['action'],'HOLD')
        self.assertEqual(result['signal']['budget_total'],300000)
        self.assertEqual(result['bar']['timestamp'],'2026-10-06T10:55:00+09:00')

    def test_partial_submission_stays_pending_in_actual_engine(self):
        from test_daytrade_engine_regressions import daytrade_engine as engine_module, _engine_with_state, _StrategyStub
        for action in ('BUY1','SELL_FULL'):
            engine, stored = _engine_with_state({}, [], configs={'daytrade_auto_enabled':'true'})
            engine.struct.kis_api.is_real=False
            engine._hard_locked=lambda:False
            engine._feature_enabled=lambda:True
            engine._daytrade_market_open=lambda market:True
            engine.strategy.daytrade_entry_issue=lambda symbol:''
            engine._timestamp=lambda:'2026-10-06 11:00:00'
            state=dict(symbol='005930', market='KS', strategy_id=SID, position_qty=0 if action=='BUY1' else 10,
                       avg_price=0 if action=='BUY1' else 100, orders=[])
            status=dict(state=state, signal=dict(action=action, order_qty=10, current_price=100,
                reason='테스트용 거래량과 추세 조건 확인', price_source='confirmed_5m_paper'), runtime={'risk_status':'SAFE'})
            engine.signal_status=Mock(return_value=status)
            engine._compact_runtime_meta=lambda *args:{}
            engine._invalidate_kis_cache=lambda:None
            engine._log_order_pending=Mock()
            engine._log_order_failure=Mock()
            engine._log_execution=Mock()
            engine._append_runtime_log=Mock()
            broker=Mock()
            broker.buy_domestic_order.return_value={'order_no':'12345'}
            broker.sell_domestic_order.return_value={'order_no':'12345'}
            engine._broker=lambda:broker
            engine._resolve_domestic_fill=lambda *a,**kw:dict(status='PARTIAL',filled_qty=4,filled_price=100)
            with patch.object(engine_module,'_PAPER_MODE',True), patch.object(_StrategyStub,'daytrade_entry_issue',lambda self,symbol:'',create=True):
                result=engine.execute_live('005930',strategy_id=SID,sync_broker=False)
            self.assertTrue(result.get('submitted'),result)
            self.assertFalse(result['executed'])
            key='pending_buy_order_no' if action=='BUY1' else 'pending_sell_order_no'
            self.assertEqual(state[key],'12345')
            self.assertEqual(state['orders'][0]['filled_qty'],0)
            engine._log_execution.assert_not_called()
            engine._log_order_failure.assert_not_called()

    def test_boundary_returns_before_quotes_or_order_side_effects(self):
        from test_daytrade_engine_regressions import daytrade_engine as engine_module
        method=engine_module.DomesticDaytradeEngine.execute_live
        for paper, real, enabled, opened, force, expected in (
            (False,False,True,True,False,'PAPER_ONLY'),
            (True,True,True,True,False,'PAPER_ONLY'),
            (True,None,True,True,False,'PAPER_ONLY'),
            (True,False,False,True,False,'AUTO_OFF'),
            (True,False,True,False,False,'WAIT_MARKET'),
            (True,False,True,True,True,'FORCE_DISABLED')):
            broker=SimpleNamespace(is_real=real)
            engine=SimpleNamespace(struct=SimpleNamespace(kis_api=broker),
                                   auto_enabled=Mock(return_value=enabled),
                                   _daytrade_market_open=Mock(return_value=opened))
            with patch.object(engine_module,'_PAPER_MODE',paper):
                result=method(engine,'005930',strategy_id=SID,force=force)
            self.assertEqual(result['action'],expected)
            self.assertFalse(result['submitted'])


if __name__ == '__main__':
    unittest.main()
