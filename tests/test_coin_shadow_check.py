"""Coin shadow-run progress (10-24): decision coverage, signal match against
the offline replay, and the pre-registered gates."""
import importlib.util
import unittest
from pathlib import Path

MODEL = Path(__file__).resolve().parents[1] / "src" / "portal" / "trading" / "model"


def _module(name):
    spec = importlib.util.spec_from_file_location(f"t_{name}", MODEL / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


S = _module("coin_strategy")
C = _module("coin_shadow_check")
H = 3600
T0 = 1785715200  # 2026-08-03 00:00 UTC (4h and day boundary)


def candles(days=80):
    """Flat for 70 days, then a breakout rally and a sharp drop."""
    rows = []
    for i in range(days * 24):
        if i < 70 * 24:
            p = 100.0 + (i % 24) * 0.01
        elif i < 75 * 24:
            p = 101.0 + (i - 70 * 24) * 0.2
        else:
            p = 125.0 - (i - 75 * 24) * 1.0
        rows.append({"t": T0 + i * H, "o": p, "h": p * 1.001, "l": p * 0.999, "c": p})
    return rows


class ShadowCheckTests(unittest.TestCase):
    def setUp(self):
        self.c = {"KRW-BTC": candles()}
        self.now = T0 + 80 * 24 * H - 60
        self.started = T0 + 60 * 86400
        start = self.started
        trades = S.replay(self.c["KRW-BTC"], start, self.now // C.BAR_SEC * C.BAR_SEC)
        self.assertTrue(trades, "fixture must produce a trade")
        self.trades = trades
        bars = list(range(C.first_bar_end(start), self.now // C.BAR_SEC * C.BAR_SEC + 1, C.BAR_SEC))
        self.state = {"created_at": start, "decisions": [{"bar_end": e} for e in bars]}

    def events(self, exit_shift=0, drop_entry=False):
        out = []
        for et, _e, xt, _x, why in self.trades:
            if not drop_entry:
                out.append({"time": et + 5, "market": "KRW-BTC", "side": "BUY", "bar_end": et})
            if why != "end" and not drop_entry:
                out.append({"time": xt + 1800 + exit_shift, "market": "KRW-BTC", "side": "SELL"})
        return out

    def test_identical_run_matches_and_counts_entries(self):
        summary, ledger = C.check(S, self.state, self.events(), self.c, {}, self.now)
        self.assertEqual(summary["match_pct"], 100.0)
        self.assertEqual(summary["entries"], len(self.trades))
        self.assertEqual(summary["missed_count"], 0)
        self.assertFalse(summary["gates"]["weeks"]["ok"])
        self.assertTrue(ledger["compared"])

    def test_missed_signal_and_late_exit_are_flagged(self):
        summary, _ = C.check(S, self.state, self.events(drop_entry=True), self.c, {}, self.now)
        self.assertEqual({r["status"] for r in summary["compared"]}, {"replay_only"})
        self.assertEqual(summary["match_pct"], 0.0)
        summary, _ = C.check(S, self.state, self.events(exit_shift=6 * H), self.c, {}, self.now)
        self.assertIn("exit_differs", {r["status"] for r in summary["compared"]})

    def test_missing_decisions_show_as_missed_bars(self):
        state = dict(self.state, decisions=self.state["decisions"][:-3])
        summary, _ = C.check(S, state, self.events(), self.c, {}, self.now)
        self.assertEqual(summary["missed_count"], 3)
        self.assertLess(summary["coverage_pct"], 100)

    def test_ledger_keeps_results_after_candles_roll_off(self):
        _, ledger = C.check(S, self.state, self.events(), self.c, {}, self.now)
        later = self.now + 30 * 86400
        summary, ledger2 = C.check(S, {"created_at": self.started, "decisions": []}, self.events(), {"KRW-BTC": []}, ledger, later)
        self.assertEqual(summary["match_pct"], 100.0)
        self.assertEqual(ledger2["started_at"], self.started)

    def test_slippage_is_measured_against_the_model_prices(self):
        events = []
        for et, epx, xt, xpx, why in self.trades:
            events.append({"time": et + 5, "market": "KRW-BTC", "side": "BUY", "bar_end": et, "price": epx * 1.001})
            if why != "end":
                events.append({"time": xt + 1800, "market": "KRW-BTC", "side": "SELL", "price": xpx * 0.998})
        summary, _ = C.check(S, self.state, events, self.c, {}, self.now)
        self.assertGreater(summary["slippage_samples"], 0)
        self.assertAlmostEqual(min(summary["compared"][0]["slippage"]), 0.1, places=3)
        self.assertLessEqual(summary["slippage_median_pct"], 0.2)

    def test_a_skip_below_the_stop_counts_as_a_match(self):
        et = self.trades[0][0]
        events = [{"time": et + 5, "market": "KRW-BTC", "side": "SKIP", "bar_end": et}]
        summary, _ = C.check(S, self.state, events, self.c, {}, self.now)
        row = next(r for r in summary["compared"] if r["bar_end"] == et)
        self.assertEqual(row["status"], "match")
        self.assertTrue(row["skipped"])

    def test_kst_epoch(self):
        self.assertEqual(C.kst_epoch("2026-10-24 09:00:00"), 1792800000)


if __name__ == "__main__":
    unittest.main()
