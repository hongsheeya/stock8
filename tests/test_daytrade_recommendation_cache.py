import builtins
import datetime
import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class _TimeStub:
    @staticmethod
    def now():
        return datetime.datetime(2026, 5, 26, 10, 30, 0)


class _WizStub:
    @staticmethod
    def model(name):
        if name == "portal/trading/kst":
            return _TimeStub
        raise AssertionError(f"unexpected wiz.model({name})")


class _ReadStub:
    def __init__(self, payload):
        self.payload = payload

    def json(self, _path, default=None):
        return self.payload if self.payload is not None else default


class _FsStub:
    def __init__(self, payload):
        self.read = _ReadStub(payload)

    def exists(self, path):
        return str(path).endswith("data/daytrade/ks/recommendation.json")


class _StructStub:
    def get_config(self, _key, default=None):
        return default


builtins.wiz = _WizStub()
daytrade_path = SRC / "portal" / "trading" / "model" / "struct" / "daytrade.py"
daytrade_spec = importlib.util.spec_from_file_location("daytrade_under_test", daytrade_path)
daytrade = importlib.util.module_from_spec(daytrade_spec)
daytrade_spec.loader.exec_module(daytrade)


class DaytradeRecommendationCacheTests(unittest.TestCase):
    def _service(self, payload):
        service = daytrade.Daytrade(_StructStub())
        service._fs = lambda: _FsStub(payload)
        return service

    def test_graph_validation_metrics_prefers_smoother_holdout_curve(self):
        service = self._service(None)

        stable = service._graph_validation_metrics([
            {"fold": 1, "validation_return": 1.8},
            {"fold": 2, "validation_return": 2.1},
            {"fold": 3, "validation_return": 1.6},
            {"fold": 4, "validation_return": 1.9},
            {"fold": 5, "validation_return": 1.7},
        ], {"profit_factor": 1.8, "max_drawdown": 1.2})
        unstable = service._graph_validation_metrics([
            {"fold": 1, "validation_return": 6.5},
            {"fold": 2, "validation_return": -3.2},
            {"fold": 3, "validation_return": 8.1},
            {"fold": 4, "validation_return": -2.4},
            {"fold": 5, "validation_return": 0.4},
        ], {"profit_factor": 1.8, "max_drawdown": 1.2})

        self.assertEqual(stable["holdout_folds"], 2)
        self.assertGreater(stable["stability_score"], unstable["stability_score"])
        self.assertLess(stable["negative_fold_ratio"], unstable["negative_fold_ratio"])
        self.assertLess(stable["return_swing_pct"], unstable["return_swing_pct"])

    def test_latest_recommendation_without_selection_key_accepts_latest_cache(self):
        payload = {
            "generated_date": "2026-05-26",
            "generated_at": "2026-05-26 10:11:19",
            "selected": {"symbol": "028260", "strategy_id": "vrev", "market": "KS"},
            "leaderboard": [{"symbol": "028260", "strategy_id": "vrev"}],
            "recommendations": [{"symbol": "028260"}],
            "cache_key": {"selection_version": "old-key"},
        }

        result = self._service(payload).latest_recommendation(max_age_sec=3600, market="KS")

        self.assertIsNotNone(result)
        self.assertEqual(result["selected"]["symbol"], "028260")

    def test_candidate_universe_includes_learned_profile_book_winner(self):
        service = self._service(None)
        service._load_profile_book = lambda market="KS": {
            "018260:volume_breakout": {
                "symbol": "018260",
                "market": "KS",
                "strategy_id": "volume_breakout",
                "validation": {
                    "validation": {
                        "total_return": 9.4,
                        "avg_profit": 56598.27,
                        "win_rate": 80.0,
                        "profit_factor": 2.4,
                    },
                    "graph_validation": {
                        "negative_fold_ratio": 0.2,
                        "return_swing_pct": 3.1,
                        "stability_score": 4.2,
                    },
                },
            }
        }
        service._resolve_symbol_name = lambda symbol: "삼성SDS" if symbol == "018260" else symbol

        universe = service.candidate_universe(market="KS")

        learned = [row for row in universe if row.get("symbol") == "018260"]
        self.assertEqual(len(learned), 1)
        self.assertEqual(learned[0]["name"], "삼성SDS")
        self.assertEqual(learned[0]["source"], "profile_book")

    def test_latest_recommendation_with_selection_key_still_rejects_mismatch(self):
        payload = {
            "generated_date": "2026-05-26",
            "generated_at": "2026-05-26 10:11:19",
            "selected": {"symbol": "028260", "strategy_id": "vrev", "market": "KS"},
            "leaderboard": [{"symbol": "028260", "strategy_id": "vrev"}],
            "recommendations": [{"symbol": "028260"}],
            "cache_key": {"selection_version": "old-key"},
        }

        result = self._service(payload).latest_recommendation(seed=3_000_000, price_cap=500_000, max_age_sec=3600, market="KS")

        self.assertIsNone(result)

    def test_price_filter_keeps_expanded_ks_leaderboard(self):
        leaderboard = [
            {
                "symbol": f"{idx:06d}",
                "market": "KS",
                "strategy_id": "vrev",
                "last_price": 10_000,
                "trade_ready": idx % 2 == 0,
                "validation": {"validation": {"total_return": idx}},
            }
            for idx in range(60)
        ]
        payload = {
            "generated_date": "2026-05-26",
            "generated_at": "2026-05-26 10:11:19",
            "selected": {"symbol": "000000", "strategy_id": "vrev", "market": "KS"},
            "leaderboard": leaderboard,
            "recommendations": [{"symbol": "000000"}],
        }

        result = self._service(payload)._recommendation_price_filter(payload, market="KS", price_cap=50_000, seed=3_000_000)

        self.assertEqual(len(result["leaderboard"]), 48)
        self.assertEqual(result["leaderboard_limit"], 48)
        self.assertEqual(result["leaderboard_total_count"], 60)

    def test_us_quality_gate_flags_low_profit_factor_and_liquidity(self):
        service = self._service(None)
        service.candidate_universe = lambda market="US": [{"symbol": "TQQQ", "market": "US", "name": "TQQQ", "exchange": "NASD"}]
        service.recommendation_training_defaults = lambda: {
            "period": "10d",
            "interval": "5m",
            "min_session_count": 3,
            "min_validation_sessions": 2,
            "min_success_rate": 35,
            "min_avg_total_return": 0,
        }
        sessions = [{"bars": [{"close": 100}], "prev_close": 100} for _ in range(6)]
        service._prepare_dataset = lambda *args, **kwargs: sessions
        service._volatility_from_sessions = lambda _sessions: {
            "avg_day_range_pct": 1.5,
            "avg_intraday_move_pct": 2.5,
            "avg_turnover_krw": 100000000,
            "liquidity_score": 0.4,
            "tradability_score": 4.2,
            "fee_buffer_ok": True,
            "last_price": 100,
        }
        service._optimize_payload = lambda *args, **kwargs: {
            "best": {
                "summary": {
                    "total_return": 8.0,
                    "win_rate": 42.0,
                    "max_drawdown": 9.0,
                    "avg_trades": 1.2,
                    "profit_factor": 1.02,
                    "score": 7.0,
                },
                "validation": {
                    "robustness_score": 1.1,
                    "overfit_gap": 4.0,
                    "validation": {
                        "total_return": 2.2,
                        "win_rate": 45.0,
                        "avg_trades": 1.1,
                        "profit_factor": 1.05,
                    },
                },
                "selection_score": 7.0,
                "profile": {},
            }
        }
        service._trend_alignment_snapshot = lambda *args, **kwargs: {"trend_alignment_score": 0.8}
        service._min_trend_alignment_score = lambda *args, **kwargs: 1.0
        service._save_profile_book_entries = lambda *args, **kwargs: None
        service._save_recommendation = lambda *args, **kwargs: None
        service._write_training_artifacts = lambda *args, **kwargs: None

        result = service.auto_train(seed=5_000_000, requested_seed=5_000_000, market="US")

        self.assertFalse(result["leaderboard"][0]["trade_ready"])
        self.assertTrue(any("손익비" in issue for issue in result["leaderboard"][0]["quality_issues"]))
        self.assertTrue(any("유동성" in issue for issue in result["leaderboard"][0]["quality_issues"]))

    def test_ks_quality_gate_flags_graph_holdout_instability(self):
        service = self._service(None)
        service.candidate_universe = lambda market="KS": [{"symbol": "035420", "market": "KS", "name": "NAVER"}]
        service.recommendation_training_defaults = lambda: {
            "period": "10d",
            "interval": "5m",
            "min_session_count": 3,
            "min_validation_sessions": 2,
            "min_success_rate": 35,
            "min_avg_total_return": 0,
        }
        sessions = [{"bars": [{"close": 100}], "prev_close": 100, "date": f"2026-05-{20 + idx:02d}"} for idx in range(6)]
        service._prepare_dataset = lambda *args, **kwargs: sessions
        service._volatility_from_sessions = lambda _sessions: {
            "avg_day_range_pct": 2.0,
            "avg_intraday_move_pct": 3.1,
            "avg_turnover_krw": 180000000,
            "liquidity_score": 1.1,
            "tradability_score": 7.4,
            "fee_buffer_ok": True,
            "last_price": 100000,
        }
        service._optimize_payload = lambda *args, **kwargs: {
            "best": {
                "summary": {
                    "total_return": 10.0,
                    "win_rate": 61.0,
                    "max_drawdown": 2.5,
                    "avg_trades": 5.2,
                    "profit_factor": 1.7,
                    "score": 8.5,
                },
                "validation": {
                    "robustness_score": 5.1,
                    "overfit_gap": 3.5,
                    "validation": {
                        "total_return": 3.2,
                        "win_rate": 58.0,
                        "avg_trades": 4.1,
                        "profit_factor": 1.8,
                    },
                    "graph_validation": {
                        "stability_score": -2.4,
                        "holdout_avg_return": -0.8,
                        "negative_fold_ratio": 0.6,
                        "return_swing_pct": 9.4,
                    },
                },
                "selection_score": 6.2,
                "profile": {},
            }
        }
        service._trend_alignment_snapshot = lambda *args, **kwargs: {"trend_alignment_score": 0.6}
        service._min_trend_alignment_score = lambda *args, **kwargs: 0.0
        service._save_profile_book_entries = lambda *args, **kwargs: None
        service._save_recommendation = lambda *args, **kwargs: None
        service._write_training_artifacts = lambda *args, **kwargs: None

        result = service.auto_train(seed=3_000_000, requested_seed=3_000_000, market="KS")

        self.assertFalse(result["leaderboard"][0]["trade_ready"])
        self.assertTrue(any("그래프 검증 수익률" in issue for issue in result["leaderboard"][0]["quality_issues"]))
        self.assertTrue(any("그래프 음수 비중" in issue for issue in result["leaderboard"][0]["quality_issues"]))
        self.assertTrue(any("그래프 변동폭" in issue for issue in result["leaderboard"][0]["quality_issues"]))

    def test_ks_quality_gate_flags_low_validation_avg_profit(self):
        service = self._service(None)
        service.candidate_universe = lambda market="KS": [{"symbol": "004170", "market": "KS", "name": "Shinsegae"}]
        service.recommendation_training_defaults = lambda: {
            "period": "10d",
            "interval": "5m",
            "min_session_count": 3,
            "min_validation_sessions": 2,
            "min_success_rate": 35,
            "min_avg_total_return": 0,
        }
        sessions = [{"bars": [{"close": 100}], "prev_close": 100, "date": f"2026-05-{20 + idx:02d}"} for idx in range(6)]
        service._prepare_dataset = lambda *args, **kwargs: sessions
        service._volatility_from_sessions = lambda _sessions: {
            "avg_day_range_pct": 2.0,
            "avg_intraday_move_pct": 3.1,
            "avg_turnover_krw": 180000000,
            "liquidity_score": 1.1,
            "tradability_score": 7.4,
            "fee_buffer_ok": True,
            "last_price": 100000,
        }
        service._optimize_payload = lambda *args, **kwargs: {
            "best": {
                "summary": {
                    "total_return": 12.0,
                    "avg_profit": 32000.0,
                    "win_rate": 61.0,
                    "max_drawdown": 2.5,
                    "avg_trades": 5.2,
                    "profit_factor": 1.7,
                    "score": 8.5,
                },
                "validation": {
                    "robustness_score": 5.1,
                    "overfit_gap": 3.5,
                    "validation": {
                        "total_return": 3.2,
                        "avg_profit": 12000.0,
                        "win_rate": 58.0,
                        "avg_trades": 4.1,
                        "profit_factor": 1.8,
                    },
                    "graph_validation": {
                        "stability_score": 3.1,
                        "holdout_avg_return": 1.2,
                        "negative_fold_ratio": 0.2,
                        "return_swing_pct": 4.4,
                    },
                },
                "selection_score": 6.2,
                "profile": {},
            }
        }
        service._trend_alignment_snapshot = lambda *args, **kwargs: {"trend_alignment_score": 0.6}
        service._min_trend_alignment_score = lambda *args, **kwargs: 0.0
        service._save_profile_book_entries = lambda *args, **kwargs: None
        service._save_recommendation = lambda *args, **kwargs: None
        service._write_training_artifacts = lambda *args, **kwargs: None

        result = service.auto_train(seed=3_000_000, requested_seed=3_000_000, market="KS")

        self.assertFalse(result["leaderboard"][0]["trade_ready"])
        self.assertTrue(any("검증 일평균 수익" in issue for issue in result["leaderboard"][0]["quality_issues"]))


if __name__ == "__main__":
    unittest.main()
