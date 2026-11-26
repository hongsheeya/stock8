"""A failed domestic balance call must not read as "the account holds nothing".

_fetch_kis_balance_raw swallowed a failed get_domestic_balance and returned
holdings=[] (cached for 120 s); _sync_broker_positions then counted KS as
fetched and zeroed every local KS position: it left the exit watch and BUY1
opened again for the same symbol. Now the raw result says holdings_ok, a
failed read is retried after 15 s, and only a real answer cleans up.
"""
import sys
import unittest
from unittest.mock import patch

from test_daytrade_engine_regressions import _engine_with_state

_CACHE = ("_trading_kis_balance_cache_v2", "_trading_kis_balance_cache_ts")
HELD = {
    "005930.KS": {"symbol": "005930", "market": "KS", "position_qty": 13, "avg_price": 276576.0,
                  "strategy_id": "vrev", "buy1_used": True},
}


def _clear_cache():
    for key in _CACHE:
        if hasattr(sys, key):
            delattr(sys, key)


class _BrokerCalls:
    def __init__(self, engine, fail=True, holdings=None):
        self.balance_calls = 0
        self.fail = fail
        self.holdings = list(holdings or [])
        api = engine.struct.kis_api
        api.get_domestic_balance = self.domestic
        api.get_balance = lambda: {"holdings": [], "cash_balance": 0, "total_eval": 0}
        api.get_present_balance = lambda: {}
        api.get_domestic_buying_power_info = lambda **_kwargs: {"ok": True, "amount": 1000000}

    def domestic(self):
        self.balance_calls += 1
        if self.fail:
            raise RuntimeError("EGW00201 초당 거래건수를 초과하였습니다.")
        return {"holdings": list(self.holdings), "krw_balance": 1000000}


class FetchBalanceTests(unittest.TestCase):
    def setUp(self):
        _clear_cache()
        self.addCleanup(_clear_cache)

    def _engine(self, **kwargs):
        engine, _ = _engine_with_state({}, [])
        del engine._fetch_kis_balance_raw
        return engine, _BrokerCalls(engine, **kwargs)

    def test_failed_call_is_marked_not_ok(self):
        engine, _calls = self._engine(fail=True)
        raw = engine._fetch_kis_balance_raw()
        self.assertEqual(raw["holdings"], [])
        self.assertIs(raw["holdings_ok"], False)

    def test_answered_empty_account_is_ok(self):
        engine, _calls = self._engine(fail=False, holdings=[])
        raw = engine._fetch_kis_balance_raw()
        self.assertEqual(raw["holdings"], [])
        self.assertIs(raw["holdings_ok"], True)

    def test_failed_read_is_retried_after_15s_not_120s(self):
        engine, calls = self._engine(fail=True)
        with patch("time.time", return_value=1000.0):
            engine._fetch_kis_balance_raw()
        with patch("time.time", return_value=1010.0):
            engine._fetch_kis_balance_raw()
        self.assertEqual(calls.balance_calls, 1)
        with patch("time.time", return_value=1016.0):
            engine._fetch_kis_balance_raw()
        self.assertEqual(calls.balance_calls, 2)

    def test_good_read_keeps_the_two_minute_cache(self):
        engine, calls = self._engine(fail=False, holdings=[])
        with patch("time.time", return_value=1000.0):
            engine._fetch_kis_balance_raw()
        with patch("time.time", return_value=1100.0):
            engine._fetch_kis_balance_raw()
        self.assertEqual(calls.balance_calls, 1)

    def test_cache_entry_without_the_flag_is_refetched(self):
        engine, calls = self._engine(fail=False, holdings=[])
        setattr(sys, _CACHE[0], {"holdings": [], "withdrawable_krw": 0})
        setattr(sys, _CACHE[1], 1000.0)
        with patch("time.time", return_value=1001.0):
            raw = engine._fetch_kis_balance_raw()
        self.assertEqual(calls.balance_calls, 1)
        self.assertIs(raw["holdings_ok"], True)


class SyncKeepsPositionsTests(unittest.TestCase):
    def _sync(self, raw):
        engine, state = _engine_with_state(HELD, [])
        engine._fetch_kis_balance_raw = lambda use_cache_only=False: dict(raw)
        engine._sync_broker_positions(market_filter="KS")
        return state()["005930.KS"]

    def test_failed_read_keeps_the_position(self):
        position = self._sync({"holdings": [], "holdings_ok": False})
        self.assertEqual(position["position_qty"], 13)
        self.assertEqual(position["avg_price"], 276576.0)
        self.assertTrue(position["buy1_used"])

    def test_answered_empty_account_still_cleans_up(self):
        position = self._sync({"holdings": [], "holdings_ok": True})
        self.assertEqual(position["position_qty"], 0)


if __name__ == "__main__":
    unittest.main()
