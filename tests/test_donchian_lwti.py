import importlib.util
from pathlib import Path
import unittest
import pandas as pd
spec=importlib.util.spec_from_file_location('dc',Path(__file__).resolve().parents[1]/'src/portal/trading/model/donchian_lwti.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class DonchianTests(unittest.TestCase):
    def frame(self):
        return pd.DataFrame([dict(open=100+i,close=100+i,high=101+i,low=99+i,volume=100) for i in range(60)],index=pd.date_range('2026-01-01 09:00',periods=60,freq='5min'))
    def test_channel_excludes_current_bar(self):
        f=self.frame(); f.iloc[30,f.columns.get_loc('high')]=999
        self.assertEqual(m.indicators(f).upper.iloc[30],130)
    def test_flat_lwti_is_neutral(self):
        f=self.frame(); f['close']=100; f['high']=101; f['low']=99
        self.assertAlmostEqual(m.indicators(f).lwti.iloc[-1],50)
    def test_volume_excludes_current_bar(self):
        f=self.frame(); f.iloc[30,f.columns.get_loc('volume')]=200
        self.assertEqual(m.indicators(f).rvol.iloc[30],2)
    def test_future_changes_do_not_repaint(self):
        f=self.frame(); expected=m.targets(f).iloc[40]
        f.iloc[41:,f.columns.get_loc('close')]=500
        self.assertEqual(m.targets(f).iloc[40],expected)
    def test_zero_range_is_not_green(self):
        f=self.frame()
        for k in ('open','high','low','close'): f[k]=100
        self.assertTrue(m.indicators(f).lwti.isna().all())
        self.assertEqual(m.targets(f).sum(),0)
