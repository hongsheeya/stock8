import importlib.util
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock
import time

spec=importlib.util.spec_from_file_location('ks_discovery',Path(__file__).resolve().parents[1]/'src/portal/trading/model/struct/daytrade.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class DiscoveryTests(TestCase):
    def service(self):
        s=m.Daytrade.__new__(m.Daytrade)
        s._config=lambda key,default=None: default
        s._DYNAMIC_UNIVERSE_CACHE={}
        return s

    def test_no_static_fallback(self):
        s=self.service()
        self.assertEqual(s.candidate_universe(),[])

    def test_stale_candidates_are_not_entries(self):
        s=self.service()
        s._DYNAMIC_UNIVERSE_CACHE=dict(status='ready',ts=time.monotonic()-301,rows=[{'symbol':'005930'}])
        self.assertEqual(s.candidate_universe(),[])

    def test_failure_clears_rows_and_is_throttled(self):
        s=self.service()
        s._DYNAMIC_UNIVERSE_CACHE=dict(rows=[{'symbol':'005930'}])
        s._scan_dynamic_candidate_universe=Mock(side_effect=RuntimeError('offline'))
        self.assertEqual(s.refresh_dynamic_candidate_universe(),[])
        self.assertEqual(s.refresh_dynamic_candidate_universe(),[])
        self.assertEqual(s._DYNAMIC_UNIVERSE_CACHE['status'],'unavailable')
        s._scan_dynamic_candidate_universe.assert_called_once()

    def test_empty_scan_is_distinct_from_failure(self):
        s=self.service(); s._scan_dynamic_candidate_universe=Mock(return_value=[])
        self.assertEqual(s.refresh_dynamic_candidate_universe(),[])
        self.assertEqual(s._DYNAMIC_UNIVERSE_CACHE['status'],'empty')

    def test_missing_liquidity_rejected(self):
        s=self.service(); s.struct=Mock()
        s.struct.kis_api.get_domestic_volume_rank.return_value=[dict(mksc_shrn_iscd='005930',hts_kor_isnm='삼성전자',stck_prpr=70000,acml_vol=0,acml_tr_pbmn=0)]
        s.struct.kis_api.get_domestic_fluctuation_rank.return_value=[]
        self.assertEqual(s.refresh_dynamic_candidate_universe(),[])

    def test_new_discovery_invalidates_fresh_training(self):
        s=self.service()
        s.refresh_dynamic_candidate_universe=Mock()
        s.candidate_universe=Mock(return_value=[{'symbol':'NEW'}])
        s.latest_recommendation=Mock(return_value={'selected':{'strategy_id':'vrev','market':'KS'},'discovery_symbols':['OLD']})
        s.auto_train=Mock(return_value={'leaderboard':[]})
        s._save_recommendation=Mock()
        result=s.recommend(seed=1000000)
        s.auto_train.assert_called_once()
        self.assertEqual(result['discovery_symbols'],['NEW'])
