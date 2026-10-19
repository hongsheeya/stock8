"""Optional floor for FireGate's 1-share dip legs (10-20, user request).

LIVE cash covered 8 of 13 main SOXL shares and none of the seven dip legs,
while the reserve still counted them all. Legs needing a close more than
infinite_buy_dip_floor_pct below the reference are neither placed nor reserved.
"""
import unittest

from test_infinitebuy_loc_schedule_regressions import engine_module

CYCLE = dict(symbol="SOXL", status="ACTIVE", current_round=17, t_value=17, division_count=20,
             total_investment=15000, total_spent=11279.1, remaining_investment=4342.1,
             total_qty=82, avg_price=137.55, target_profit=20)


def _engine(pct):
    engine = engine_module.Engine.__new__(engine_module.Engine)
    engine._get_config_value = lambda key, default=None: pct if key == "infinite_buy_dip_floor_pct" else default
    return engine


def _legs(engine, prev_close, **kw):
    return [leg["loc_price"] for leg in engine.calculate_buy_decision(dict(CYCLE), prev_close, **kw)["buy_orders"]]


class DipFloorTests(unittest.TestCase):
    def test_off_by_default_keeps_the_firegate_plan(self):
        full = _legs(_engine("0"), 93.67)
        self.assertEqual(len(full), 8)
        self.assertLess(min(full), 80)

    def test_legs_below_the_floor_are_dropped(self):
        full = _legs(_engine("0"), 93.67)
        floored = _legs(_engine("15"), 93.67)
        floor = 93.67 * 0.85
        self.assertEqual(floored, [price for price in full if price >= floor])
        self.assertEqual(floored[0], full[0])  # the main LOC leg is never touched
        self.assertGreater(len(floored), 1)

    def test_dip_reference_overrides_the_planning_price(self):
        engine = _engine("15")
        # The reserve prices the plan off the average (137.55); the floor must
        # follow today's price instead, and 0 means "unknown: keep every leg".
        self.assertEqual(_legs(engine, 137.55, dip_reference=93.67), _legs(engine, 93.67))
        self.assertEqual(_legs(engine, 137.55, dip_reference=0), _legs(_engine("0"), 137.55))

    def test_a_broken_config_keeps_every_leg(self):
        engine = engine_module.Engine.__new__(engine_module.Engine)
        self.assertEqual(_legs(engine, 93.67), _legs(_engine("0"), 93.67))


if __name__ == "__main__":
    unittest.main()
