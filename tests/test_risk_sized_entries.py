"""Day-trade entries risk the same share of the seed at their stop."""
import unittest

from test_daytrade_engine_regressions import _engine_with_state

SEED = 95_000_000


def _engine(stop_pct=1.5, configs=None):
    engine, _ = _engine_with_state({}, [], configs=configs or {})
    engine._profile_for = lambda *_a, **_k: {"stop_loss_pct": stop_pct, "breakout_stop_loss_pct": 2.5}
    return engine


class RiskSizedEntryTests(unittest.TestCase):
    def test_ks_vrev_with_a_1_5_percent_stop_takes_a_third(self):
        size = _engine(1.5)._risk_sized_entry_seed_krw("005930", "vrev", "KS", SEED, SEED)
        self.assertAlmostEqual(size, SEED * 0.5 / 1.5, delta=1)

    def test_tight_stop_is_capped_and_wide_stop_floored(self):
        self.assertAlmostEqual(_engine(0.5)._risk_sized_entry_seed_krw("005930", "vrev", "KS", SEED, SEED), SEED * 0.40, delta=1)
        # us_premarket stops at 8%: 0.5/8 = 6.25% -> the 10% floor.
        self.assertAlmostEqual(_engine(8.0)._risk_sized_entry_seed_krw("TEST", "us_premarket", "US", SEED, SEED), SEED * 0.10, delta=1)

    def test_us_rule_strategy_uses_its_backtest_stop(self):
        # us_breakout stop 2.5% -> 20% of the seed.
        size = _engine(8.0)._risk_sized_entry_seed_krw("TEST", "us_breakout", "US", SEED, SEED)
        self.assertAlmostEqual(size, SEED * 0.20, delta=1)

    def test_never_more_than_what_remains_or_anything_without_seed(self):
        engine = _engine(1.5)
        self.assertEqual(engine._risk_sized_entry_seed_krw("005930", "vrev", "KS", SEED, 10_000_000), 10_000_000)
        self.assertEqual(engine._risk_sized_entry_seed_krw("005930", "vrev", "KS", SEED, 0), 0.0)

    def test_settings_move_the_risk_and_the_bounds(self):
        engine = _engine(1.5, configs={"daytrade_risk_per_trade_pct": "0.25", "daytrade_max_position_pct": "30"})
        self.assertAlmostEqual(engine._risk_sized_entry_seed_krw("005930", "vrev", "KS", SEED, SEED), SEED * 0.25 / 1.5, delta=1)
        engine = _engine(0.5, configs={"daytrade_max_position_pct": "30"})
        self.assertAlmostEqual(engine._risk_sized_entry_seed_krw("005930", "vrev", "KS", SEED, SEED), SEED * 0.30, delta=1)


if __name__ == "__main__":
    unittest.main()
