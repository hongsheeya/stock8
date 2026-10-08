import importlib.util
from pathlib import Path
from unittest.mock import patch
import unittest

spec = importlib.util.spec_from_file_location('martin_research', Path(__file__).resolve().parents[1] / 'scripts/compare-martingale.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


class SizingResearchTests(unittest.TestCase):
    def sessions(self, count=8, falling=False):
        return [dict(prev_close=100, bars=[dict(timestamp=f'{d}:00:{i}', open=p,
                    close=p, rsi14=50, bb_upper=1000) for i,p in enumerate(
                    [100,100,98,97,97] if falling else [100]*5)]) for d in range(count)]

    def test_flat_market_loses_only_costs(self):
        with patch.object(bench.research,'vrev_entry_issues',return_value=[]):
            r = bench.run(self.sessions(1), cost_scale=1)
            zero = bench.run(self.sessions(1), cost_scale=0)
        self.assertLess(r['return_pct'],0)
        self.assertEqual(zero['return_pct'],0)

    def test_losing_streak_increases_drawdown_not_signal_win_rate(self):
        with patch.object(bench.research,'vrev_entry_issues',return_value=[]):
            fixed = bench.run(self.sessions(falling=True))
            martin = bench.run(self.sessions(falling=True), multiplier=2, cap=8)
        self.assertEqual(fixed['trades'], martin['trades'])
        self.assertEqual(fixed['win_rate_pct'], martin['win_rate_pct'])
        self.assertGreater(martin['mdd_pct'], fixed['mdd_pct'])
        self.assertLessEqual(martin['max_allocation_pct'], 80.1)

    def test_no_unlimited_cash_for_unbounded_multiplier(self):
        with patch.object(bench.research,'vrev_entry_issues',return_value=[]):
            result = bench.run(self.sessions(count=20,falling=True), multiplier=2,cap=1024)
        self.assertGreater(result['cash_capped_entries'],0)
        self.assertGreater(result['return_pct'],-100)
        self.assertLessEqual(result['max_allocation_pct'],100)
