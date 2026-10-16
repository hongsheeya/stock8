"""Domestic ETFs and ETNs pay no transaction tax on the sale (10-16).

Every KS sale was charged 0.015% + 0.18%: 122630 KODEX 레버리지 logged a
₩64,564 fee of which ₩55,282 was a tax ETFs do not pay. The inflated fee also
raised the break-even price and the take-profit floor for ETF positions.
"""
import unittest
from unittest import mock

from test_daytrade_engine_regressions import _engine_with_state


class KrEtfSellTaxTests(unittest.TestCase):
    def setUp(self):
        self.engine, _ = _engine_with_state({}, [])

    def test_funds_are_exempt_and_stocks_are_not(self):
        exempt = self.engine._kr_sell_tax_exempt
        self.assertTrue(exempt("122630", "KODEX 레버리지"))
        self.assertTrue(exempt("102110", "TIGER 200"))
        self.assertTrue(exempt("580020", "신한 인버스 2X WTI원유 선물 ETN"))
        self.assertFalse(exempt("005930", "삼성전자"))
        self.assertFalse(exempt("195940", "HK이노엔"))
        self.assertFalse(exempt("000000", ""))

    def test_static_lists_name_a_symbol_without_a_name(self):
        etfs = [{"symbol": "233740", "name": "KODEX 코스닥150레버리지"}]
        with mock.patch.object(type(self.engine.strategy), "KR_REGIME_ETFS", etfs, create=True):
            self.assertTrue(self.engine._kr_sell_tax_exempt("233740"))

    def test_sell_rate_and_break_even(self):
        self.assertAlmostEqual(self.engine._kr_sell_fee_rate("122630", "KODEX 레버리지"), 0.00015)
        self.assertAlmostEqual(self.engine._kr_sell_fee_rate("005930", "삼성전자"), 0.00195)
        etf = self.engine._break_even_price(10000, "122630", "KODEX 레버리지")
        stock = self.engine._break_even_price(10000, "005930", "삼성전자")
        self.assertAlmostEqual(etf, 10000 * 1.00015 / (1 - 0.00015))
        self.assertAlmostEqual(stock, 10000 * 1.00015 / (1 - 0.00195))

    def test_exit_fee_for_the_10_16_trade(self):
        fee = self.engine._estimate_exit_total_fee(71834.34, 70765.0, 434, "122630", "KODEX 레버리지")
        self.assertAlmostEqual(fee, 71834.34 * 434 * 0.00015 + 70765.0 * 434 * 0.00015)
        self.assertLess(fee, 10_000)


if __name__ == "__main__":
    unittest.main()
