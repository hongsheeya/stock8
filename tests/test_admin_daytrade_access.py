"""Role boundaries run without server, credentials or orders."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class AccessTests(unittest.TestCase):
    def test_both_markets_reject_regular_users_even_with_legacy_allowlist(self):
        for page in ('page.daytrade', 'page.daytrade.us'):
            tree=ast.parse((ROOT/'src/app'/page/'api.py').read_text(encoding='utf-8-sig'))
            fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_daytrade_access_payload')
            for mode in ('PAPER','LIVE'):
                for admin in (False,True):
                    scope=dict(_session_user=lambda:{'id':'test-user'}, _is_admin_user=lambda u:admin,
                               _DAYTRADE_HARD_LOCKED=False, _TRADING_MODE=mode,
                               _PAPER_DAYTRADE_FULL_ACCESS=mode=='PAPER', _truthy=lambda x:True,
                               _get_config=lambda *a:'true', _listed_user=lambda *a:True,
                               _DAYTRADE_LOCK_MESSAGE='locked')
                    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<role-test>','exec'),scope)
                    result=scope['_daytrade_access_payload']()
                    self.assertEqual(result['daytrade_access_enabled'],admin,(page,mode,admin))
                    self.assertEqual(result['daytrade_user_authorized'],admin)

    def test_shared_settings_ignores_daytrade_fields_for_regular_user(self):
        tree=ast.parse((ROOT/'src/app/page.settings/api.py').read_text(encoding='utf-8-sig'))
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_set_config')
        scope=dict(_session_user=lambda:(None,None,{'role':'user'}),_is_admin_user=lambda u:False)
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<settings-role-test>','exec'),scope)
        # No trading/config object: returning here proves no persistence occurred.
        for key in ('daytrade_auto_enabled','us_daytrade_auto_enabled','daytrade_feature_enabled'):
            self.assertIsNone(scope['_set_config'](key,'true'))
