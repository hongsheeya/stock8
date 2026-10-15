"""US movers when KIS's ranking is unavailable, and the venue their orders use.

KIS's overseas ranking API is not served on the paper gateway, so PAPER's US
universe was always the fixed large-cap list: the same three stocks every
pass. Yahoo's screener now fills in during the regular session.
"""
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from test_daytrade_engine_regressions import _StrategyStub, _engine_with_state
from test_vrev_execution_timing import module as daytrade_module


def _quote(symbol, change, price=20.0, volume=2_000_000, exchange="NYQ", state="REGULAR", kind="EQUITY",
           name=None, bid=19.99, ask=20.01):
    return {"symbol": symbol, "shortName": name or f"{symbol} Inc", "exchange": exchange, "quoteType": kind,
            "marketState": state, "regularMarketPrice": price, "regularMarketVolume": volume,
            "regularMarketChangePercent": change, "bid": bid, "ask": ask}


def _yfinance(quotes):
    class Query:
        def __init__(self, *args):
            self.args = args
    return types.SimpleNamespace(EquityQuery=Query, screen=lambda *a, **k: {"quotes": quotes})


class YahooMoversTests(unittest.TestCase):
    def setUp(self):
        self.svc = daytrade_module.Daytrade.__new__(daytrade_module.Daytrade)
        for patcher in (patch.object(daytrade_module.Daytrade, "_US_DYNAMIC_CACHE", {}),
                        patch.object(daytrade_module.Daytrade, "_US_EXCHANGE_BOOK", {})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_only_regular_session_equity_movers_pass_the_kis_filter(self):
        quotes = [_quote("RUNR", 12.0, exchange="NMS", volume=5_000_000),
                  _quote("BIGV", 8.0, price=50.0, volume=9_000_000),
                  _quote("PREM", 9.0, state="PRE"),                 # stale outside the session
                  _quote("SOXL", 9.0, exchange="PCX"),              # excluded ETF
                  _quote("FUND", 9.0, kind="ETF"),
                  _quote("TINY", 9.0, price=1.5),                   # < $2
                  _quote("THIN", 9.0, volume=100_000),
                  _quote("WIDE", 9.0, bid=19.0, ask=21.0),          # spread > 0.8%
                  _quote("HUGE", 60.0),                             # > +45%
                  _quote("BATS", 9.0, exchange="BTS")]              # venue KIS cannot route
        with patch.dict(sys.modules, {"yfinance": _yfinance(quotes)}):
            rows = self.svc._yahoo_us_movers()
        self.assertEqual([r["symbol"] for r in rows], ["BIGV", "RUNR"])  # by dollar volume
        self.assertEqual({r["symbol"]: r["exchange"] for r in rows}, {"BIGV": "NYSE", "RUNR": "NASD"})
        self.assertTrue(all(r["source"] == "yahoo_gainers" for r in rows))

    def test_refresh_falls_back_to_yahoo_and_books_the_venues(self):
        def failing_rank(exchange):
            raise RuntimeError("모의투자 미지원 API")
        self.svc.struct = SimpleNamespace(get_config=lambda key, default=None: default,
                                          kis_api=SimpleNamespace(get_us_momentum_rank=failing_rank,
                                                                  request_options=lambda **k: _NullContext()))
        with patch.dict(sys.modules, {"yfinance": _yfinance([_quote("RUNR", 12.0, exchange="NYQ")])}):
            universe = self.svc.refresh_us_dynamic_candidate_universe(force=True)
        self.assertEqual([r["symbol"] for r in universe], ["RUNR"])
        self.assertEqual(daytrade_module.Daytrade._US_EXCHANGE_BOOK["RUNR"], "NYSE")
        self.assertIn("Yahoo", self.svc.us_candidate_universe_policy()["source_label"])

    def test_outside_the_session_the_fixed_list_stays(self):
        self.svc.struct = SimpleNamespace(get_config=lambda key, default=None: default,
                                          kis_api=SimpleNamespace(get_us_momentum_rank=lambda e: [],
                                                                  request_options=lambda **k: _NullContext()))
        with patch.dict(sys.modules, {"yfinance": _yfinance([_quote("PREM", 9.0, state="PRE")])}):
            universe = self.svc.refresh_us_dynamic_candidate_universe(force=True)
        self.assertTrue(universe and all(r.get("source") == "curated_fallback" for r in universe))


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class MoverVenueTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(_StrategyStub, "us_candidate_universe", create=True, new=lambda self: [])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_exit_uses_the_venue_recorded_at_entry(self):
        engine, _ = _engine_with_state({"RUNR.US": {"symbol": "RUNR", "market": "US", "us_exchange": "NYSE"}}, [])
        self.assertEqual(engine._us_exchange("RUNR"), "NYSE")

    def test_a_scanned_mover_keeps_its_venue_after_leaving_the_scan(self):
        engine, _ = _engine_with_state({}, [])
        with patch.dict(sys.__dict__, {"_stock8_us_exchange_book": {"RUNR": "AMEX"}}):
            self.assertEqual(engine._us_exchange("RUNR"), "AMEX")
        self.assertEqual(engine._us_exchange("ZZZZ"), "NASD")  # unknown: legacy default


if __name__ == "__main__":
    unittest.main()
