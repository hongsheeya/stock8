import importlib.util
from pathlib import Path
import unittest
import pandas as pd

spec=importlib.util.spec_from_file_location('wr',Path(__file__).resolve().parents[1]/'src/portal/trading/model/williams_research.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class WilliamsTests(unittest.TestCase):
    def frame(self):
        idx=pd.DatetimeIndex([pd.Timestamp('2026-07-01 09:30')+pd.Timedelta(days=d,minutes=5*i) for d in range(12) for i in range(4)])
        return pd.DataFrame([dict(open=100+d,high=102+d,low=99+d,close=100+d,volume=100) for d in range(12) for i in range(4)],index=idx)

    def test_first_day_has_no_prior_range(self):
        self.assertEqual(m.targets(self.frame()).iloc[:4].sum(),0)

    def test_current_day_high_does_not_change_earlier_signal(self):
        f=self.frame(); f.iloc[-3,f.columns.get_loc('close')]=120
        before=m.targets(f)
        f.iloc[-1,f.columns.get_loc('high')]=500
        pd.testing.assert_series_equal(before,m.targets(f))

    def test_guarded_exit_prevents_reentry(self):
        f=self.frame()
        f.iloc[-4:,f.columns.get_loc('close')]=[111,113,110,114]
        self.assertEqual(m.targets(f,True).iloc[-4:].tolist(),[0,1,0,0])

    def test_guard_needs_prior_trend_history(self):
        self.assertEqual(m.targets(self.frame(),True).iloc[:40].sum(),0)
