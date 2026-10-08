import builtins
import datetime
import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class _TimeStub:
    @staticmethod
    def now():
        return datetime.datetime(2026, 5, 29, 10, 0, 0)


class _FsStub:
    def exists(self, _path):
        return False

    def read(self, _path):
        return ""

    def read_json(self, _path, default=None):
        return default

    def write(self, _path, _content):
        return None

    def write_json(self, _path, _content):
        return None

    def makedirs(self, _path):
        return None


class _ProjectStub:
    def fs(self):
        return _FsStub()


class _WizStub:
    project = _ProjectStub()

    @staticmethod
    def model(name):
        if name == "portal/trading/kst":
            return _TimeStub
        raise AssertionError(f"unexpected wiz.model({name})")


class _StructStub:
    def get_config(self, _key, default=None):
        return default


builtins.wiz = _WizStub()
daytrade_path = SRC / "portal" / "trading" / "model" / "struct" / "daytrade.py"
daytrade_spec = importlib.util.spec_from_file_location("daytrade_under_test", daytrade_path)
daytrade = importlib.util.module_from_spec(daytrade_spec)
daytrade_spec.loader.exec_module(daytrade)


class DaytradeVrevFilterTests(unittest.TestCase):
    def momentum_row(self, **changes):
        return dict(dict(symb='TEST', knam='Example common stock', last='12', tvol='900000',
                         tamt='10800000', rate='12', n_rate='2', pbid='11.99', pask='12.01', e_ordyn='Y'), **changes)

    def test_us_momentum_requires_liquidity_spread_and_evidence(self):
        service = daytrade.Daytrade(_StructStub())
        candidate = service._us_momentum_candidate(self.momentum_row(), 'NAS')
        self.assertEqual(candidate['source'], 'kis_momentum_rank')
        self.assertFalse(candidate['trade_ready'])
        for changes in ({'tvol':'100'}, {'tamt':'0'}, {'pask':'14'}, {'pbid':'0'},
                        {'rate':'1'}, {'n_rate':'-2'}, {'e_ordyn':'N'}, {'symb':'SOXL'},
                        {'knam':'Example ETF'}, {'last':'0.5'}):
            self.assertIsNone(service._us_momentum_candidate(self.momentum_row(**changes), 'NAS'), changes)

    def test_major_stocks_require_stronger_momentum(self):
        service = daytrade.Daytrade(_StructStub())
        self.assertIsNone(service._us_momentum_candidate(self.momentum_row(symb='NVDA', rate='6'), 'NAS'))
        self.assertIsNone(service._us_momentum_candidate(self.momentum_row(symb='NVDA', n_rate='0.5'), 'NAS'))
        self.assertIsNotNone(service._us_momentum_candidate(self.momentum_row(symb='NVDA'), 'NAS'))

    def test_entry_ownership_guard_fails_closed(self):
        service = daytrade.Daytrade(_StructStub())
        self.assertTrue(service.daytrade_entry_issue('SOXL'))
        self.assertTrue(service.daytrade_entry_issue('TEST'))
        class DB:
            def get(self, symbol, status):
                return {'symbol':symbol} if symbol == 'OWNED' and status == 'PAUSED' else None
        service.struct.db = lambda name: DB()
        self.assertTrue(service.daytrade_entry_issue('OWNED'))
        self.assertEqual(service.daytrade_entry_issue('NEW'), '')

    def test_us_default_candidates_exclude_infinite_buy_and_index_etfs(self):
        service = daytrade.Daytrade(_StructStub())
        symbols = {row['symbol'] for row in service.us_candidate_universe()}
        self.assertTrue(symbols)
        self.assertFalse(symbols & {'TQQQ', 'SOXL', 'SPXL', 'UPRO', 'SPY', 'QQQ', 'IWM'})
        self.assertEqual(service.us_candidate_universe_policy()['candidate_count'], len(symbols))

    def test_vrev_entry_issues_blocks_countertrend_knife_catch(self):
        service = daytrade.Daytrade(_StructStub())
        bar = {
            "close": 99.2,
            "vwap": 100.0,
            "rsi14": 29.0,
            "trend_strength_pct": -0.42,
            "ma_fast": 99.1,
            "ma_slow": 99.8,
        }

        issues = service.vrev_entry_issues(bar, profile=service.DEFAULT_PROFILE)

        self.assertTrue(any("VWAP 대비 하락 과다" in issue for issue in issues))
        self.assertTrue(any("RSI" in issue for issue in issues))
        self.assertTrue(any("추세 약세" in issue for issue in issues))
        self.assertTrue(any("단기 이평 약세" in issue for issue in issues))

    def test_simulate_vrev_session_skips_entry_when_preflight_fails(self):
        service = daytrade.Daytrade(_StructStub())
        session = {
            "date": "2026-05-29",
            "prev_close": 100.0,
            "bars": [
                {
                    "timestamp": "2026-05-29 09:00",
                    "close": 99.4,
                    "vwap": 100.2,
                    "rsi14": 28.0,
                    "trend_strength_pct": -0.55,
                    "ma_fast": 99.3,
                    "ma_slow": 100.1,
                    "high": 100.0,
                    "low": 99.0,
                    "open": 100.0,
                    "volume": 1000,
                    "bb_upper": 101.0,
                },
                {
                    "timestamp": "2026-05-29 09:05",
                    "close": 97.8,
                    "vwap": 99.8,
                    "rsi14": 26.0,
                    "trend_strength_pct": -0.9,
                    "ma_fast": 98.0,
                    "ma_slow": 99.6,
                    "high": 99.5,
                    "low": 97.5,
                    "open": 99.4,
                    "volume": 1200,
                    "bb_upper": 100.5,
                },
            ],
        }

        result = service._simulate_vrev_session(session, seed=3000000, profile=service.DEFAULT_PROFILE)

        self.assertEqual(result["trade_count"], 0)
        self.assertEqual(result["profit"], 0.0)


if __name__ == "__main__":
    unittest.main()
