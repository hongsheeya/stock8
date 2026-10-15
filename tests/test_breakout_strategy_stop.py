"""volume_breakout exits at its own stop, on a fresh quote.

The backtest stops a breakout at breakout_stop_loss_pct (default 0.8, trained
0.6-1.0). The live exits used the generic stop_loss_pct (1.5), and the fast
watch judged the balance price, which can be two minutes old.
"""
import unittest

from test_daytrade_p0_exit_fixes import LIVE_PROFILE, _state, _watch_engine

PROFILE = {**LIVE_PROFILE, "breakout_stop_loss_pct": 0.8, "breakout_take_profit_pct": 1.4}
BELOW = {"vwap": 9800, "breakout_low_20": 9800}  # VWAP/20-bar-low exits stay quiet


def _run(states, prices, bars):
    engine, _saved, _broker, decisions = _watch_engine(states, prices, bars=bars)
    engine._profile_for = lambda *_a, **_k: dict(PROFILE)
    engine.kr_execute_exit_watch(requested_seed=1000000)
    return decisions


class BreakoutStopTests(unittest.TestCase):
    def test_breakout_stops_at_its_backtest_level(self):
        decisions = _run([_state("BRK", 10000, strategy_id="volume_breakout")], {"BRK": 9915}, {"BRK": BELOW})
        self.assertEqual(decisions["BRK"]["action"], "SELL_STOP_LOSS")
        self.assertIn("0.8", decisions["BRK"]["reason"])

    def test_vrev_keeps_its_wider_stop(self):
        decisions = _run([_state("VRV", 10000)], {"VRV": 9915}, {})
        self.assertEqual(decisions["VRV"]["action"], "HOLD")

    def test_breakout_judges_the_fresh_quote_not_the_balance_price(self):
        quote = {**BELOW, "close": 9915, "price_source": "kis_domestic_quote"}
        decisions = _run([_state("BRK", 10000, strategy_id="volume_breakout")], {"BRK": 9990}, {"BRK": quote})
        self.assertEqual(decisions["BRK"]["action"], "SELL_STOP_LOSS")

    def test_a_bar_without_a_quote_keeps_the_balance_price(self):
        stale = {**BELOW, "close": 9000}  # Yahoo bar, no live quote
        decisions = _run([_state("BRK", 10000, strategy_id="volume_breakout")], {"BRK": 9990}, {"BRK": stale})
        self.assertEqual(decisions["BRK"]["action"], "HOLD")

    def test_risk_sizing_uses_the_same_stop(self):
        engine, _saved, _broker, _decisions = _watch_engine([], {})
        engine._profile_for = lambda *_a, **_k: {**PROFILE, "breakout_stop_loss_pct": 0.6}
        self.assertEqual(engine._entry_stop_pct("114800", "volume_breakout", "KS"), 0.6)
        self.assertEqual(engine._entry_stop_pct("042510", "vrev", "KS"), 1.5)


if __name__ == "__main__":
    unittest.main()
