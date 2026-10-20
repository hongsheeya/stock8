"""Per-user split of FireGate's sell table (10-20, user request)."""
import unittest

from test_infinitebuy_loc_schedule_regressions import engine_module

CYCLE = dict(symbol="SOXL", status="ACTIVE", current_round=8, t_value=8, division_count=20,
             total_investment=15000, total_spent=6000, remaining_investment=9000, total_qty=100, avg_price=60.0)


def _orders(configs):
    engine = engine_module.Engine.__new__(engine_module.Engine)
    engine._get_config_value = lambda key, default="": configs.get(key, default)
    return engine._firegate_v4_sell_orders(dict(CYCLE))


class SellSplitTests(unittest.TestCase):
    def test_default_keeps_firegate_quarter_and_twenty_percent(self):
        star, target = _orders({})
        self.assertEqual((star["order_qty"], target["order_qty"]), (25, 75))
        self.assertEqual(target["price"], 72.0)
        self.assertEqual(target["order_type"], "LIMIT")

    def test_three_quarters_at_star_and_rest_at_plus_25(self):
        star, target = _orders({"infinite_buy_star_sell_ratio": "0.75", "infinite_buy_target_sell_pct": "25"})
        self.assertEqual((star["order_qty"], target["order_qty"]), (75, 25))
        self.assertEqual(target["price"], 75.0)
        self.assertEqual(star["price"], _orders({})[0]["price"])  # ★ price unchanged

    def test_bad_values_fall_back_to_firegate(self):
        star, target = _orders({"infinite_buy_star_sell_ratio": "abc", "infinite_buy_target_sell_pct": "-5"})
        self.assertEqual((star["order_qty"], target["price"]), (25, 72.0))


if __name__ == "__main__":
    unittest.main()
