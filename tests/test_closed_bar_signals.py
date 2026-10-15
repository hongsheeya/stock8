"""Live entries judge closed bars, as the backtests do.

10-15 PAPER: with real-time KIS bars the last bar was the forming minute,
whose partial volume failed the volume-surge test; 114800 met the
volume_breakout rule on 7 closed bars (10:59-12:30) and was never entered.
"""
import datetime
import sys
import unittest
from unittest.mock import Mock, patch

from test_daytrade_engine_regressions import _engine_with_state, _StrategyStub

NOW = datetime.datetime(2026, 10, 15, 12, 30, 20)
PROFILE = {"breakout_volume_ratio": 2.0}


def _bar(minutes_ago, close=1000.0, surge=1.0, high20=1000.0, vwap=990.0):
    ts = (NOW - datetime.timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M")
    return {"timestamp": ts, "date": ts[:10], "time": ts[11:], "open": close, "high": close, "low": close,
            "close": close, "volume": 100, "volume_surge_ratio": surge, "breakout_high_20": high20, "vwap": vwap}


def _engine():
    engine, _ = _engine_with_state({}, [])
    engine._now = lambda: NOW
    return engine


class RecentBreakoutTests(unittest.TestCase):
    def test_breakout_on_a_recent_closed_bar_counts_within_the_chase_limit(self):
        bars = [_bar(m) for m in range(20, 3, -1)] + [_bar(3, surge=2.5), _bar(2), _bar(1), _bar(0)]
        row = _engine()._volume_breakout_signal_bar({"bars": bars}, bars[-1], PROFILE, 1002.0)
        self.assertEqual(row["timestamp"], bars[-4]["timestamp"])

    def test_price_that_ran_past_the_chase_limit_is_not_bought(self):
        bars = [_bar(m) for m in range(20, 3, -1)] + [_bar(3, surge=2.5), _bar(2), _bar(1)]
        self.assertIsNone(_engine()._volume_breakout_signal_bar({"bars": bars}, bars[-1], PROFILE, 1004.0))

    def test_old_breakouts_and_the_forming_minute_never_count(self):
        old = [_bar(m) for m in range(20, 9, -1)] + [_bar(9, surge=3.0)] + [_bar(m) for m in range(8, 0, -1)]
        self.assertIsNone(_engine()._volume_breakout_signal_bar({"bars": old}, old[-1], PROFILE, 1000.0))
        forming = [_bar(m) for m in range(20, 0, -1)] + [_bar(0, surge=3.0)]
        self.assertIsNone(_engine()._volume_breakout_signal_bar({"bars": forming}, forming[-1], PROFILE, 1000.0))

    def test_without_session_bars_the_snapshot_bar_is_judged_at_the_price(self):
        bar = _bar(0, surge=2.5, high20=1000.0, vwap=990.0)
        self.assertIsNotNone(_engine()._volume_breakout_signal_bar({"bars": []}, bar, PROFILE, 1000.0))
        self.assertIsNone(_engine()._volume_breakout_signal_bar({"bars": []}, bar, PROFILE, 980.0))


class ClosedBarSnapshotTests(unittest.TestCase):
    def test_snapshot_indicators_come_from_the_last_closed_bar(self):
        engine = _engine()
        del engine._latest_snapshot
        broker = Mock()
        broker.get_domestic_current_price.return_value = {"price": 1003.0}
        engine._broker = lambda: broker
        bars = [_bar(2, surge=1.1), _bar(1, surge=2.6), _bar(0, surge=0.1)]
        session = {"date": "2026-10-15", "prev_close": 990.0, "bars": bars}
        with patch.object(_StrategyStub, "_prepare_dataset", create=True, return_value=[session]), \
                patch.object(sys, "_trading_snapshot_cache_v3", {}, create=True):
            _session, bar = engine._latest_snapshot("TEST")
        self.assertEqual(bar["timestamp"], bars[1]["timestamp"])
        self.assertEqual(bar["volume_surge_ratio"], 2.6)
        self.assertEqual(bar["close"], 1003.0)


if __name__ == "__main__":
    unittest.main()
