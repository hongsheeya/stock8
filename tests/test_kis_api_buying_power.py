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


class _WizStub:
    @staticmethod
    def model(name):
        if name == "portal/trading/kst":
            return _TimeStub
        raise AssertionError(f"unexpected wiz.model({name})")


class _StructStub:
    def __init__(self):
        self.configs = {
            "kis_is_real": "true",
            "kis_account_no": "12345678-01",
            "kis_app_key": "app",
            "kis_app_secret": "secret",
            "kis_paper_account_no": "12345678-01",
            "kis_paper_app_key": "paper-app",
            "kis_paper_app_secret": "paper-secret",
        }

    def get_config(self, key, default=""):
        return self.configs.get(key, default)

    def set_config(self, key, value, description="", is_secret=False):
        self.configs[key] = str(value)


builtins.wiz = _WizStub()
kis_api_path = SRC / "portal" / "trading" / "model" / "struct" / "kis_api.py"
kis_api_spec = importlib.util.spec_from_file_location("kis_api_under_test", kis_api_path)
kis_api = importlib.util.module_from_spec(kis_api_spec)
kis_api_spec.loader.exec_module(kis_api)


class KisBuyingPowerTests(unittest.TestCase):
    def test_momentum_rank_uses_bounded_official_request(self):
        api = kis_api.KisApi(_StructStub())
        calls = []
        api._request = lambda *args, **kwargs: calls.append((args, kwargs)) or {'rt_cd':'0', 'output2':[{'symb':'TEST'}]}
        self.assertEqual(api.get_us_momentum_rank('NAS'), [{'symb':'TEST'}])
        args, kwargs = calls[0]
        self.assertEqual(args[0], 'GET')
        self.assertEqual(args[2], 'HHDFS76260000')
        self.assertEqual(kwargs['params']['GUBN'], '1')
        self.assertEqual(kwargs['params']['MINX'], '3')
        self.assertEqual(kwargs['retries'], 0)
        with self.assertRaises(ValueError): api.get_us_momentum_rank('INVALID')

    def test_domestic_buying_power_never_uses_margin_inclusive_max_amount(self):
        api = kis_api.KisApi(_StructStub())
        api._request = lambda *args, **kwargs: {
            "rt_cd": "0",
            "output": {
                "nrcvb_buy_amt": "0",
                "nrcvb_buy_qty": "0",
                "max_buy_amt": "250000000",
                "max_buy_qty": "2500",
            },
        }

        info = api.get_domestic_buying_power_info(symbol="005930", order_type="MARKET")

        self.assertEqual(info["amount"], 0)
        self.assertEqual(info["qty"], 0)
        self.assertTrue(info["cash_only"])
        self.assertEqual(info["broker_orderable_amount"], 250000000)

    def test_domestic_rank_queries_use_official_ranking_endpoints(self):
        api = kis_api.KisApi(_StructStub())
        calls = []

        def _request(method, path, tr_id, params=None, **_kwargs):
            calls.append((method, path, tr_id, params or {}))
            return {"rt_cd": "0", "output": [{"mksc_shrn_iscd": "005930"}]}

        api._request = _request
        volume = api.get_domestic_volume_rank()
        movers = api.get_domestic_fluctuation_rank()

        self.assertEqual(volume[0]["mksc_shrn_iscd"], "005930")
        self.assertEqual(movers[0]["mksc_shrn_iscd"], "005930")
        self.assertEqual(calls[0][1:3], ("/uapi/domestic-stock/v1/quotations/volume-rank", "FHPST01710000"))
        self.assertEqual(calls[1][1:3], ("/uapi/domestic-stock/v1/ranking/fluctuation", "FHPST01700000"))

    def test_get_balance_dedupes_same_symbol_returned_from_multiple_exchanges(self):
        api = kis_api.KisApi(_StructStub())

        def _request(_method, _path, _tr_id, params=None, **_kwargs):
            exchange = (params or {}).get("OVRS_EXCG_CD")
            if exchange == "NASD":
                return {
                    "rt_cd": "0",
                    "output1": [{
                        "ovrs_pdno": "SOXL",
                        "ovrs_item_name": "SOXL",
                        "ovrs_cblc_qty": "3",
                        "pchs_avg_pric": "226.19",
                        "now_pric2": "226.19",
                        "ovrs_stck_evlu_amt": "678.57",
                        "frcr_evlu_pfls_amt": "0",
                        "evlu_pfls_rt": "0",
                        "ovrs_excg_cd": "NASD",
                    }],
                    "output2": {"tot_evlu_amt": "678.57", "ord_psbl_frcr_amt": "0"},
                }
            if exchange == "AMEX":
                return {
                    "rt_cd": "0",
                    "output1": [{
                        "ovrs_pdno": "SOXL",
                        "ovrs_item_name": "SOXL",
                        "ovrs_cblc_qty": "3",
                        "pchs_avg_pric": "226.19",
                        "now_pric2": "226.19",
                        "ovrs_stck_evlu_amt": "678.57",
                        "frcr_evlu_pfls_amt": "0",
                        "evlu_pfls_rt": "0",
                        "ovrs_excg_cd": "AMEX",
                    }],
                    "output2": {"tot_evlu_amt": "678.57", "ord_psbl_frcr_amt": "0"},
                }
            return {"rt_cd": "0", "output1": [], "output2": {"tot_evlu_amt": "678.57", "ord_psbl_frcr_amt": "0"}}

        api._request = _request
        balance = api.get_balance()

        self.assertEqual(len(balance["holdings"]), 1)
        self.assertEqual(balance["holdings"][0]["symbol"], "SOXL")
        self.assertEqual(balance["total_eval"], 678.57)

    def test_explicit_zero_orderable_is_not_overridden_by_foreign_currency_maximum(self):
        api = kis_api.KisApi(_StructStub())
        api._request = lambda *args, **kwargs: {
            "rt_cd": "0",
            "msg1": "조회되었습니다",
            "output": {
                "ovrs_ord_psbl_amt": "0.00",
                "ord_psbl_frcr_amt": "0.00",
                "frcr_ord_psbl_amt1": "1560.584194",
                "echm_af_ord_psbl_amt": "0.00",
                "max_ord_psbl_qty": "0",
                "ord_psbl_qty": "0",
                "ovrs_max_ord_psbl_qty": "0",
                "echm_af_ord_psbl_qty": "0",
            },
        }
        api.get_balance = lambda: {"cash_balance": 0}
        api.get_present_balance = lambda: {"usd_krw": 1400, "withdrawable_krw": 0}
        api._us_auto_exchange_ready = lambda now=None: True

        info = api.get_buying_power_info(symbol="IONQ", price=70.10, exchange="NYSE")

        self.assertTrue(info["ok"])
        self.assertEqual(info["source"], "ovrs_ord_psbl_amt")
        self.assertEqual(info["broker_qty"], 0)
        self.assertEqual(info["executable_amount"], 0)
        self.assertEqual(info["executable_qty"], 0)
        self.assertEqual(info["qty"], 0)

    def test_failed_buying_power_never_promotes_cash_balance_to_order_permission(self):
        api = kis_api.KisApi(_StructStub())
        api._request = lambda *a, **kw: {'rt_cd': '1', 'msg1': 'rate limited'}
        api.get_balance = lambda: self.fail('Failed preflight must not substitute cash')
        info = api.get_buying_power_info('SOXL', 158.64, 'AMEX')
        self.assertFalse(info['ok'])
        self.assertIn('rate limited', info['message'])

    def test_soxl_broker_orderable_not_largest_unrelated_field(self):
        api = kis_api.KisApi(_StructStub())
        api._request = lambda *a, **kw: {'rt_cd': '0', 'output': {
            'ovrs_ord_psbl_amt': '2425.49', 'max_ord_psbl_qty': '15',
            'frcr_ord_psbl_amt1': '3099.369307', 'ovrs_max_ord_psbl_qty': '19'}}
        api.get_balance = lambda: {}
        api.get_present_balance = lambda: {}
        api._us_auto_exchange_ready = lambda: False
        info = api.get_buying_power_info('SOXL', 158.64, 'AMEX')
        self.assertEqual(info['executable_amount'], 2425.49)
        self.assertEqual(info['executable_qty'], 15)

    def test_overseas_order_history_parses_kis_field_variants_and_uses_blank_pdno(self):
        api = kis_api.KisApi(_StructStub())
        calls = []

        def _request(_method, _path, _tr_id, params=None, **_kwargs):
            calls.append(params or {})
            self.assertEqual((params or {}).get("PDNO"), "")
            return {
                "rt_cd": "0",
                "output1": [{
                    "ODNO": "A001",
                    "PDNO": "SOXL",
                    "SLL_BUY_DVSN_CD": "02",
                    "ORD_DT": "20260622",
                    "ORD_TMD": "220100",
                    "FT_ORD_QTY": "3",
                    "FT_ORD_UNPR3": "226.76",
                    "FT_CCLD_QTY": "3",
                    "FT_CCLD_UNPR3": "226.76",
                    "FT_CCLD_AMT3": "680.28",
                    "OVRS_EXCG_CD": "NASD",
                }],
                "output2": {},
            }

        api._request = _request
        api.get_overseas_reservation_orders = lambda **_kwargs: []
        orders = api.get_overseas_order_history(start_date="20260622", end_date="20260623", exchanges=["NASD"])

        self.assertEqual(len(calls), 1)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["symbol"], "SOXL")
        self.assertEqual(orders[0]["action"], "BUY")
        self.assertEqual(orders[0]["filled_qty"], 3)
        self.assertEqual(orders[0]["filled_price"], 226.76)
        self.assertEqual(orders[0]["status"], "FILLED")

    def test_overseas_order_history_falls_back_to_filled_reservations(self):
        api = kis_api.KisApi(_StructStub())
        api._request = lambda *args, **kwargs: {"rt_cd": "0", "output1": [], "output2": {}}
        api.get_overseas_reservation_orders = lambda **_kwargs: [{
            "reserve_order_no": "R001",
            "order_no": "R001",
            "symbol": "TQQQ",
            "exchange": "NASD",
            "receipt_date": "20260622",
            "side": "BUY",
            "qty": 5,
            "price": 86.84,
            "filled_qty": 5,
            "filled_price": 86.84,
        }]

        orders = api.get_overseas_order_history(start_date="20260622", end_date="20260623", exchanges=["NASD"])

        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["symbol"], "TQQQ")
        self.assertEqual(orders[0]["action"], "BUY")
        self.assertEqual(orders[0]["filled_qty"], 5)
        self.assertEqual(orders[0]["status"], "FILLED")
        self.assertEqual(orders[0]["source"], "reservation_filled_fallback")

    def test_overseas_order_history_symbol_query_also_checks_blank_pdno(self):
        api = kis_api.KisApi(_StructStub())
        calls = []

        def _request(_method, _path, _tr_id, params=None, **_kwargs):
            pdno = (params or {}).get("PDNO")
            calls.append(pdno)
            if pdno:
                return {"rt_cd": "0", "output1": [], "output2": {}}
            return {
                "rt_cd": "0",
                "output1": [{
                    "odno": "A-TQQQ-LATE",
                    "pdno": "TQQQ",
                    "sll_buy_dvsn_cd": "02",
                    "ord_dt": "20260625",
                    "ord_tmd": "222010",
                    "ft_ord_qty": "3",
                    "ft_ord_unpr3": "80.00",
                    "ft_ccld_qty": "3",
                    "ft_ccld_unpr3": "80.00",
                }],
                "output2": {},
            }

        api._request = _request
        api.get_overseas_reservation_orders = lambda **_kwargs: []

        orders = api.get_overseas_order_history(start_date="20260625", end_date="20260625", symbol="TQQQ", exchanges=["NASD"])

        self.assertEqual(calls, ["TQQQ", ""])
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["order_no"], "A-TQQQ-LATE")
        self.assertEqual(orders[0]["symbol"], "TQQQ")
        self.assertEqual(orders[0]["filled_qty"], 3)

    def test_overseas_reservation_orders_parse_kis_field_variants(self):
        api = kis_api.KisApi(_StructStub())

        def _request(_method, _path, _tr_id, params=None, **_kwargs):
            if (params or {}).get("OVRS_EXCG_CD") != "NASD":
                return {"rt_cd": "0", "output": []}
            return {
                "rt_cd": "0",
                "output": [{
                    "OVRS_RSVN_ODNO": "R-NAS-1",
                    "PDNO": "TQQQ",
                    "SLL_BUY_DVSN_CD_NAME": "매수",
                    "RSVN_ORD_RCIT_DT": "20260623",
                    "ORD_RCIT_TMD": "174000",
                    "OVRS_EXCG_CD": "NAS",
                    "RSVN_ORD_QTY": "4",
                    "RSVN_ORD_UNPR": "85.57",
                    "ORD_DVSN": "00",
                    "FT_CCLD_QTY": "0",
                    "OVRS_RSVN_ORD_STAT_CD_NAME": "접수",
                }],
            }

        api._request = _request

        orders = api.get_overseas_reservation_orders(start_date="20260623", exchanges=["NASD"])

        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["order_no"], "R-NAS-1")
        self.assertEqual(orders[0]["symbol"], "TQQQ")
        self.assertEqual(orders[0]["side"], "BUY")
        self.assertEqual(orders[0]["exchange"], "NAS")
        self.assertEqual(orders[0]["qty"], 4)
        self.assertEqual(orders[0]["price"], 85.57)
        self.assertEqual(orders[0]["ord_dvsn"], "00")
        self.assertEqual(orders[0]["order_type"], "LIMIT")

    def test_overseas_reservation_orders_follows_ctx_pagination(self):
        api = kis_api.KisApi(_StructStub())
        seen_ctx = []
        seen_tr_cont = []

        def _request(_method, _path, _tr_id, params=None, **_kwargs):
            params = params or {}
            if params.get("OVRS_EXCG_CD") != "NASD":
                return {"rt_cd": "0", "output": []}
            seen_ctx.append((params.get("CTX_AREA_FK200"), params.get("CTX_AREA_NK200")))
            seen_tr_cont.append(_kwargs.get("tr_cont", ""))
            if params.get("CTX_AREA_FK200") == "":
                return {
                    "rt_cd": "0",
                    "tr_cont": "M",
                    "CTX_AREA_FK200": "NEXT-FK",
                    "CTX_AREA_NK200": "NEXT-NK",
                    "output": [{
                        "OVRS_RSVN_ODNO": "R-PAGE-1",
                        "PDNO": "TQQQ",
                        "SLL_BUY_DVSN_CD_NAME": "매수",
                        "RSVN_ORD_RCIT_DT": "20260623",
                        "OVRS_EXCG_CD": "NASD",
                        "RSVN_ORD_QTY": "4",
                        "RSVN_ORD_UNPR": "77.01",
                        "ORD_DVSN": "34",
                    }],
                }
            return {
                "rt_cd": "0",
                "tr_cont": "D",
                "output": [{
                    "OVRS_RSVN_ODNO": "R-PAGE-2",
                    "PDNO": "TQQQ",
                    "SLL_BUY_DVSN_CD_NAME": "매수",
                    "RSVN_ORD_RCIT_DT": "20260623",
                    "OVRS_EXCG_CD": "NASD",
                    "RSVN_ORD_QTY": "4",
                    "RSVN_ORD_UNPR": "77.58",
                    "ORD_DVSN": "34",
                }],
            }

        api._request = _request

        orders = api.get_overseas_reservation_orders(start_date="20260623", exchanges=["NASD"])

        self.assertEqual(len(orders), 2)
        self.assertEqual([order["order_no"] for order in orders], ["R-PAGE-1", "R-PAGE-2"])
        self.assertEqual(seen_ctx, [("", ""), ("NEXT-FK", "NEXT-NK")])
        self.assertEqual(seen_tr_cont, ["", "N"])

    def test_overseas_reservation_orders_reads_beyond_ten_pages(self):
        api = kis_api.KisApi(_StructStub())
        seen_tr_cont = []

        def _request(_method, _path, _tr_id, params=None, **_kwargs):
            params = params or {}
            seen_tr_cont.append(_kwargs.get("tr_cont", ""))
            page = int(params.get("CTX_AREA_FK200") or 0)
            next_page = page + 1
            data = {
                "rt_cd": "0",
                "tr_cont": "M" if page < 10 else "D",
                "CTX_AREA_FK200": str(next_page) if page < 10 else "",
                "CTX_AREA_NK200": str(next_page) if page < 10 else "",
                "output": [{
                    "OVRS_RSVN_ODNO": f"R-PAGE-{page + 1}",
                    "PDNO": "TQQQ",
                    "SLL_BUY_DVSN_CD_NAME": "매수",
                    "RSVN_ORD_RCIT_DT": "20260623",
                    "OVRS_EXCG_CD": "NASD",
                    "RSVN_ORD_QTY": "1",
                    "RSVN_ORD_UNPR": "77.01",
                    "ORD_DVSN": "34",
                }],
            }
            return data

        api._request = _request

        orders = api.get_overseas_reservation_orders(start_date="20260623", exchanges=["NASD"])

        self.assertEqual(len(orders), 11)
        self.assertEqual(orders[-1]["order_no"], "R-PAGE-11")
        self.assertEqual(seen_tr_cont[0], "")
        self.assertTrue(all(value == "N" for value in seen_tr_cont[1:]))

    def test_overseas_order_history_merges_missing_filled_reservations_without_duplicates(self):
        api = kis_api.KisApi(_StructStub())
        api._request = lambda *args, **kwargs: {
            "rt_cd": "0",
            "output1": [{
                "odno": "A001",
                "pdno": "TQQQ",
                "sll_buy_dvsn_cd": "02",
                "ord_dt": "20260622",
                "ord_tmd": "220100",
                "ft_ord_qty": "5",
                "ft_ord_unpr3": "86.84",
                "ft_ccld_qty": "5",
                "ft_ccld_unpr3": "86.84",
            }],
            "output2": {},
        }
        api.get_overseas_reservation_orders = lambda **_kwargs: [
            {
                "reserve_order_no": "R001",
                "order_no": "R001",
                "symbol": "TQQQ",
                "exchange": "NASD",
                "receipt_date": "20260622",
                "forward_time": "220100",
                "side": "BUY",
                "qty": 5,
                "price": 86.84,
                "filled_qty": 5,
                "filled_price": 86.84,
            },
            {
                "reserve_order_no": "R002",
                "order_no": "R002",
                "symbol": "SOXL",
                "exchange": "NASD",
                "receipt_date": "20260622",
                "forward_time": "230000",
                "side": "BUY",
                "qty": 1,
                "price": 267.57,
                "filled_qty": 1,
                "filled_price": 267.57,
            },
        ]

        orders = api.get_overseas_order_history(start_date="20260622", end_date="20260623", exchanges=["NASD"])

        self.assertEqual([order["symbol"] for order in orders], ["TQQQ", "SOXL"])
        self.assertEqual(len([order for order in orders if order["symbol"] == "TQQQ"]), 1)
        self.assertEqual(orders[1]["source"], "reservation_filled_fallback")

    def test_sell_reservation_order_uses_kis_overseas_reserve_sell_tr_id(self):
        api = kis_api.KisApi(_StructStub())
        captured = {}

        def _request(method, path, tr_id, params=None, body=None, **_kwargs):
            captured["method"] = method
            captured["path"] = path
            captured["tr_id"] = tr_id
            captured["body"] = body
            return {"rt_cd": "0", "output": {"OVRS_RSVN_ODNO": "SELL-RSV-1", "ORD_TMD": "173000"}}

        api._request = _request

        order = api.sell_reservation_order("SOXL", 3, price=267.58, order_type="LOC", exchange="NASD")

        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["path"], "/uapi/overseas-stock/v1/trading/order-resv")
        self.assertEqual(captured["tr_id"], "VTTT3016U")
        self.assertEqual(captured["body"]["PDNO"], "SOXL")
        self.assertEqual(captured["body"]["FT_ORD_QTY"], "3")
        self.assertEqual(captured["body"]["FT_ORD_UNPR3"], "267.58")
        self.assertEqual(captured["body"]["ORD_DVSN"], "34")
        self.assertEqual(order["order_no"], "SELL-RSV-1")
        self.assertTrue(order["reserved"])

    def test_cancel_overseas_reservation_order_uses_kis_reserve_cancel_api(self):
        api = kis_api.KisApi(_StructStub())
        captured = {}

        def _request(method, path, tr_id, params=None, body=None, **_kwargs):
            captured["method"] = method
            captured["path"] = path
            captured["tr_id"] = tr_id
            captured["body"] = body
            return {"rt_cd": "0", "output": {"ODNO": "CANCEL-1"}}

        api._request = _request

        result = api.cancel_overseas_reservation_order(
            "SELL-RSV-1",
            symbol="TQQQ",
            qty=14,
            exchange="NASD",
            side="SELL",
            receipt_date="20260625",
        )

        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["path"], "/uapi/overseas-stock/v1/trading/order-resv-ccnl")
        self.assertEqual(captured["tr_id"], "VTTT3017U")
        self.assertEqual(captured["body"]["RSVN_ORD_RCIT_DT"], "20260625")
        self.assertEqual(captured["body"]["OVRS_RSVN_ODNO"], "SELL-RSV-1")
        self.assertEqual(result["reserve_order_no"], "SELL-RSV-1")
        self.assertEqual(result["receipt_date"], "20260625")
        self.assertEqual(result["cancel_order_no"], "CANCEL-1")


if __name__ == "__main__":
    unittest.main()
