"""Paused strategies open no new positions; held positions keep their exits.

10-16: the user paused the rule strategies that showed no edge (KS
vrev/volume_breakout and the US rule set), keeping the direction-ETF trend.
"""
import unittest

from test_daytrade_engine_regressions import _engine_with_state

PAUSED = "vrev,volume_breakout,us_premarket,us_breakout,us_pullback,us_vwap,us_opening_reclaim"


class PausedEntryTests(unittest.TestCase):
    def test_paused_new_entries_are_dropped_and_held_positions_kept(self):
        engine, _ = _engine_with_state({}, [], configs={"daytrade_paused_entry_strategies": PAUSED})
        rows = [{"symbol": "114800", "strategy_id": "paper_regime_trend", "source": "regime_trend"},
                {"symbol": "042510", "strategy_id": "vrev", "source": "leaderboard"},
                {"symbol": "HUBS", "strategy_id": "us_premarket", "source": "leaderboard"},
                {"symbol": "EPAM", "strategy_id": "us_premarket", "source": "active_position"}]
        kept = engine._without_paused_entries(rows)
        self.assertEqual([r["symbol"] for r in kept], ["114800", "EPAM"])

    def test_us_entries_off_keeps_only_held_us_positions(self):
        engine, _ = _engine_with_state({}, [], configs={"daytrade_us_entries_enabled": "false"})
        rows = [{"symbol": "QLD", "strategy_id": "paper_regime_trend", "source": "regime_trend"},
                {"symbol": "HUBS", "strategy_id": "us_premarket", "source": "leaderboard"},
                {"symbol": "KBH", "strategy_id": "us_premarket", "source": "active_position"}]
        self.assertEqual([r["symbol"] for r in engine._without_paused_entries(rows, market="US")], ["KBH"])
        # the KS lane is untouched by the US switch
        ks = [{"symbol": "114800", "strategy_id": "paper_regime_trend", "source": "regime_trend"}]
        self.assertEqual(engine._without_paused_entries(ks, market="KS"), ks)

    def test_nothing_is_paused_by_default(self):
        engine, _ = _engine_with_state({}, [])
        rows = [{"symbol": "042510", "strategy_id": "vrev", "source": "leaderboard"}]
        self.assertEqual(engine._without_paused_entries(rows), rows)

    def test_all_rules_paused_skips_retraining(self):
        engine, _ = _engine_with_state({}, [], configs={"daytrade_paused_entry_strategies": PAUSED})
        self.assertTrue(engine._rule_strategies_paused("US"))
        self.assertTrue(engine._rule_strategies_paused("KS"))
        engine, _ = _engine_with_state({}, [], configs={"daytrade_paused_entry_strategies": "vrev"})
        self.assertFalse(engine._rule_strategies_paused("KS"))
        self.assertFalse(engine._rule_strategies_paused("US"))


if __name__ == "__main__":
    unittest.main()
