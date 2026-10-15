"""US quotes use the price API's exchange codes even when given order codes.

The day-trade engine passes its order codes (NASD/NYSE/AMEX) to
get_current_price. The price API only knows NAS/NYS/AMS, so every US quote
first failed and was retried before falling back; on 10-16 one USD quote
held the worker loop for about 3 minutes.
"""
import unittest

from test_kis_api_buying_power import _StructStub, kis_api


class UsQuoteExchangeCodeTests(unittest.TestCase):
    def _api(self, listed_on):
        api = kis_api.KisApi(_StructStub())
        self.calls = []

        def request(method, path, tr_id, params=None, **_kwargs):
            self.calls.append(params["EXCD"])
            if params["EXCD"] != listed_on:
                return {"rt_cd": "1", "msg1": "invalid exchange"}
            return {"rt_cd": "0", "output": {"last": "80.6", "base": "79.0"}}

        api._request = request
        return api

    def test_order_codes_are_translated_before_the_first_call(self):
        for order_code, price_code in (("AMEX", "AMS"), ("NASD", "NAS"), ("NYSE", "NYS")):
            with self.subTest(order_code=order_code):
                api = self._api(price_code)
                quote = api.get_current_price("USD", exchange=order_code)
                self.assertEqual(self.calls, [price_code])
                self.assertEqual(quote["price"], 80.6)

    def test_price_codes_and_fallback_are_unchanged(self):
        api = self._api("AMS")
        api.get_current_price("SOXL", exchange="NAS")
        self.assertEqual(self.calls, ["NAS", "NYS", "AMS"])


if __name__ == "__main__":
    unittest.main()
