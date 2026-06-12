import builtins
import datetime
import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class _TimeStub:
    @staticmethod
    def now():
        return datetime.datetime(2026, 5, 26, 17, 30, 0)


class _WizStub:
    @staticmethod
    def model(name):
        if name == "portal/trading/kst":
            return _TimeStub
        raise AssertionError(f"unexpected wiz.model({name})")


class _StructStub:
    def __init__(self, configs=None):
        self.configs = dict(configs or {})

    def get_config(self, key, default=""):
        return self.configs.get(key, default)


builtins.wiz = _WizStub()
engine_path = SRC / "portal" / "trading" / "model" / "struct" / "engine.py"
engine_spec = importlib.util.spec_from_file_location("infinite_buy_engine_under_test", engine_path)
engine_mod = importlib.util.module_from_spec(engine_spec)
engine_spec.loader.exec_module(engine_mod)


def _engine(configs=None):
    return engine_mod.Engine(_StructStub(configs=configs))


def _cycle(**overrides):
    data = {
        "id": "cycle-1",
        "symbol": "SOXL",
        "current_round": 0,
        "division_count": 20,
        "target_profit": 10.0,
        "total_investment": 5000.0,
        "total_spent": 0.0,
        "total_qty": 0,
        "avg_price": 0.0,
        "remaining_investment": 5000.0,
        "total_commission": 0.0,
    }
    data.update(overrides)
    return data


class InfiniteBuyFireGateV4Tests(unittest.TestCase):
    def test_initial_buy_uses_firegate_v4_previous_close_plus_12_percent(self):
        decision = _engine().calculate_buy_decision(_cycle(), prev_close=100)

        self.assertTrue(decision["should_buy"])
        self.assertEqual(decision["algorithm"], "firegate_v4")
        self.assertEqual(decision["loc_price"], 112.0)
        self.assertEqual(decision["order_qty"], 2)
        self.assertEqual(decision["buy_orders"][0]["loc_price"], 112.0)
        self.assertEqual(decision["buy_orders"][0]["order_qty"], 2)

    def test_initial_buy_allows_one_share_even_when_turn_budget_is_smaller(self):
        decision = _engine().calculate_buy_decision(
            _cycle(total_investment=1000, remaining_investment=1000),
            prev_close=100,
        )

        self.assertTrue(decision["should_buy"])
        self.assertEqual(decision["loc_price"], 112.0)
        self.assertEqual(decision["order_qty"], 1)

    def test_first_half_uses_firegate_v4_star_point_loc_price(self):
        decision = _engine().calculate_buy_decision(
            _cycle(
                current_round=4,
                total_investment=2000,
                total_spent=400,
                remaining_investment=1600,
                total_qty=40,
                avg_price=10,
            ),
            prev_close=9.5,
        )

        self.assertTrue(decision["should_buy"])
        self.assertEqual(decision["loc_price"], 11.19)
        self.assertEqual(decision["star_price"], 11.2)
        self.assertEqual(decision["order_qty"], 4)

    def test_firegate_v4_initial_plan_matches_firegate_extra_buy_ladder(self):
        decision = _engine().calculate_buy_decision(
            _cycle(total_investment=15000, remaining_investment=15000),
            prev_close=225.78571428571428,
        )

        orders = decision["buy_orders"]
        self.assertEqual([(o["loc_price"], o["order_qty"]) for o in orders], [
            (252.88, 2),
            (250.0, 1),
            (187.5, 1),
            (150.0, 1),
            (125.0, 1),
            (107.14, 1),
            (93.75, 1),
            (83.33, 1),
        ])

    def test_firegate_v4_first_half_plan_matches_tqqq_screenshot_ladder(self):
        decision = _engine().calculate_buy_decision(
            _cycle(
                symbol="TQQQ",
                current_round=5,
                t_value=5.5,
                total_investment=10000,
                total_spent=2199,
                remaining_investment=7801,
                total_qty=29,
                avg_price=75.83,
            ),
            prev_close=70,
        )

        orders = decision["buy_orders"]
        self.assertEqual(decision["star_percent"], 6.75)
        self.assertEqual(decision["star_price"], 80.95)
        self.assertEqual([(o["label"], o["loc_price"], o["order_qty"]) for o in orders], [
            ("LOC 평단", 75.83, 4),
            ("LOC ★6.75%", 80.94, 3),
            ("LOC", 67.25, 1),
            ("LOC", 59.78, 1),
            ("LOC", 53.8, 1),
            ("LOC", 48.91, 1),
            ("LOC", 44.83, 1),
            ("LOC", 41.38, 1),
            ("LOC", 38.43, 1),
        ])

    def test_target_sell_price_does_not_double_count_buy_commission(self):
        cycle = _cycle(
            total_spent=1002.5,
            total_qty=10,
            target_profit=10,
            total_commission=2.5,
        )
        price = _engine({
            "buy_commission_rate": "0.25",
            "sell_commission_rate": "0.25",
            "tax_rate": "0",
        }).calculate_target_sell_price(cycle)

        self.assertEqual(price, 110.55)


if __name__ == "__main__":
    unittest.main()
