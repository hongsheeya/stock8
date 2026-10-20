"""FireGate's sellPrice is not a market quote (10-20: SOXL showed $164.27, close $98.65)."""
import importlib.util
import pathlib
import unittest
from unittest.mock import MagicMock

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("firegate_bridge_price_test", ROOT / "src/portal/trading/model/struct/firegate_bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

PORTFOLIO = {"ticker": "SOXL", "seed": 15000, "divisionDate": 20, "targetProfit": 20, "holdingQty": 90,
             "avgPrice": 134.11, "totalBuy": 12069.9, "totalSell": 0, "tValue": 17, "sellPrice": 164.27,
             "isRunning": True, "startDate": "2026-06-26"}


def _run(existing_price):
    cycle_db = MagicMock()
    existing = {"id": "cy-1", "symbol": "SOXL", "status": "ACTIVE", "current_price": existing_price}
    bridge._active_cycle = lambda db, symbol: existing
    trading = MagicMock()
    trading.db.return_value = cycle_db
    assert bridge._cycle_from_portfolio(trading, dict(PORTFOLIO)) == "updated"
    return cycle_db.update.call_args.args[0]


class FireGateMarketPriceTests(unittest.TestCase):
    def test_keeps_the_broker_price(self):
        data = _run(98.65)
        self.assertEqual(data["current_price"], 98.65)
        self.assertLess(data["profit_rate"], 0)

    def test_sell_price_only_fills_a_missing_price(self):
        self.assertEqual(_run(0)["current_price"], 164.27)


if __name__ == "__main__":
    unittest.main()
