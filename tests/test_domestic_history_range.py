import unittest
from unittest.mock import Mock
from test_kis_api_buying_power import kis_api, _StructStub


def page(start, count, continuation='', cursor=''):
    return {'rt_cd':'0', 'tr_cont':continuation,
            'ctx_area_fk100':cursor, 'ctx_area_nk100':cursor,
            'output1':[{'odno':str(i), 'pdno':'005930', 'ord_qty':'1',
                        'tot_ccld_qty':'1', 'tot_ccld_amt':'100', 'rmn_qty':'0'}
                       for i in range(start, start + count)]}


class DomesticHistoryRangeTests(unittest.TestCase):
    def setUp(self):
        self.api = kis_api.KisApi(_StructStub())

    def test_two_weeks_use_one_range_request_not_fifteen_day_requests(self):
        self.api._request = Mock(return_value=page(0, 6))
        self.assertEqual(len(self.api.get_domestic_fills_by_date('20260923','20261007')), 6)
        self.assertEqual(self.api._request.call_count, 1)
        params = self.api._request.call_args.kwargs['params']
        self.assertEqual(params['INQR_STRT_DT'], '20260923')
        self.assertEqual(params['INQR_END_DT'], '20261007')

    def test_all_45_records_are_loaded(self):
        self.api._request = Mock(side_effect=[page(0,20,'M','a'), page(20,20,'M','b'), page(40,5,'D')])
        rows = self.api.get_domestic_fills_by_date('20260923','20261007')
        self.assertEqual(len(rows),45)
        self.assertEqual(len({r['order_no'] for r in rows}),45)
        self.assertEqual(self.api._request.call_args_list[1].kwargs['tr_cont'],'N')

    def test_broken_continuation_never_returns_partial_success(self):
        for responses in ([page(0,20,'M','a'),page(20,20,'M','a')], [page(0,20,'M','')],
                          [page(0,20,'M','a'),{'rt_cd':'1','msg1':'timeout'}]):
            self.api._request = Mock(side_effect=responses)
            with self.assertRaises(RuntimeError):
                self.api.get_domestic_fills_by_date('20260923','20261007')

    def test_single_day_contract_is_preserved(self):
        self.api._request = Mock(return_value=page(0,1))
        self.api.get_domestic_fills_for_day('20261007')
        self.assertEqual(self.api._request.call_args.kwargs['params']['INQR_END_DT'],'20261007')
