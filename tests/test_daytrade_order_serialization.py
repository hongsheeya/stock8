import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

class OrderSerializationTests(TestCase):
    def test_old_precomputed_buy_cannot_replace_pending_order(self):
        for field in ('pending_buy_order_no', 'pending_sell_order_no'):
            obj = SimpleNamespace(strategy=SimpleNamespace(_normalize_strategy=lambda x:x),
                                  _state_for=lambda *a,**kw:{field:'123'},
                                  _safe_int=lambda v,d:int(v), signal_status=Mock())
            previous = {'state':{}, 'signal':{'action':'BUY1'}}
            result = self.method('_execute_live_locked')(obj,'NVDA','US',5000000,'','vrev',False,True,True,None,'',0,previous)
            self.assertEqual(result['action'], 'PENDING_ORDER')

    def method(self, name):
        path = Path(__file__).resolve().parents[1] / 'src/portal/trading/model/struct/daytrade_engine.py'
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
        scope = {'_PAPER_MODE':False, '_PAPER_CONTINUOUS':False}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), scope)
        return scope[name]

    def test_overlapping_order_never_reaches_signal_or_broker(self):
        lock = Mock()
        lock.acquire.return_value = False
        obj = SimpleNamespace(_hard_locked=lambda:False, _feature_enabled=lambda:True,
                              _global_lock=lambda name:lock, _execute_live_locked=Mock())
        result = self.method('execute_live')(obj,'233740')
        self.assertEqual(result['action'],'ORDER_IN_FLIGHT')
        obj._execute_live_locked.assert_not_called()

    def test_stale_exit_after_full_sale_is_discarded(self):
        obj = SimpleNamespace(strategy=SimpleNamespace(_normalize_strategy=lambda x:x),
                              _state_for=lambda *a,**kw:{'position_qty':0},
                              _safe_int=lambda v,d:int(v), signal_status=Mock())
        previous = {'state':{'position_qty':717},'signal':{'action':'SELL_FULL'}}
        result = self.method('_execute_live_locked')(obj,'233740','KS',5000000,'','vrev',False,False,True,None,'',0,previous)
        self.assertEqual(result['action'],'STALE_SIGNAL')
        obj.signal_status.assert_not_called()
