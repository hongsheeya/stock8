"""The deleverage check compares exposure with the account's equity.

10-16 09:30: a regime ETF (233740) was bought for 31.2M. With a cold balance
cache the cache-only budget's total_seed_krw collapsed to that cost, so when
the price rose 3% the exit watch read "exposure 32.2M > net assets 31.2M"
and force-sold part of the winner.
"""
import unittest

from test_daytrade_engine_regressions import _engine_with_state


def _run(budget):
    engine, _ = _engine_with_state({
        "233740.KS": {"symbol": "233740", "market": "KS", "position_qty": 5345, "avg_price": 5842.6,
                      "strategy_id": "paper_regime_trend"},
    }, [], configs={"daytrade_auto_enabled": "true"})
    engine.active_positions = lambda **_k: [{
        "symbol": "233740", "market": "KS", "position_qty": 5345, "avg_price": 5842.6, "current_price": 6025,
        "pnl_pct": 3.1, "strategy_id": "paper_regime_trend"}]
    engine.shared_budget_status = lambda **_k: dict(budget)
    engine._append_runtime_log = lambda *a, **k: None
    calls = []

    def execute(*args, **kwargs):
        calls.append(kwargs)
        return {"executed": False, "message": "hold", "status": {"signal": {"action": "HOLD"}}}

    engine.execute_live = execute
    engine.kr_execute_exit_watch(requested_seed=100_000_000)
    return [c for c in calls if c.get("force")]


class DeleverageNetAssetTests(unittest.TestCase):
    def test_cold_cache_never_forces_a_sale(self):
        # The 10-16 read: no balance, seed equal to the position's cost.
        self.assertEqual(_run({"source": "cache_miss", "total_seed_krw": 31_228_710, "total_asset_krw": 0}), [])

    def test_equity_above_exposure_holds(self):
        self.assertEqual(_run({"source": "cache_only:domestic_balance", "total_seed_krw": 31_228_710,
                               "total_asset_krw": 97_700_000}), [])

    def test_exposure_above_equity_still_deleverages(self):
        forced = _run({"source": "cache_only:domestic_balance", "total_asset_krw": 30_000_000})
        self.assertEqual(len(forced), 1)


if __name__ == "__main__":
    unittest.main()
