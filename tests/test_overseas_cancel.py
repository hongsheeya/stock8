import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

class OverseasCancelTests(TestCase):
    def method(self):
        path = Path(__file__).resolve().parents[1] / 'src/portal/trading/model/struct/kis_api.py'
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'cancel_overseas_order')
        scope = {}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), scope)
        return scope[fn.name]

    def test_paper_cancel_acceptance_is_not_confirmation(self):
        obj = SimpleNamespace(is_real=False, account_prefix='12345678', account_suffix='01',
                              _request=Mock(return_value={'rt_cd':'0','output':{'ODNO':'2'}}))
        result = self.method()(obj, '1', 'NVDA', 1)
        self.assertFalse(result['confirmed'])
        self.assertEqual(obj._request.call_args.args[2], 'VTTT1004U')
        self.assertEqual(obj._request.call_args.kwargs['retries'], 0)
        self.assertEqual(obj._request.call_args.kwargs['body']['RVSE_CNCL_DVSN_CD'], '02')

    def test_invalid_quantity_never_sends_request(self):
        obj = SimpleNamespace(_request=Mock())
        for qty in (0, -1, 1.5, True):
            with self.assertRaises(ValueError):
                self.method()(obj, '1', 'NVDA', qty)
        obj._request.assert_not_called()
