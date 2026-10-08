import copy
import unittest
from test_dashboard_accounting_regressions import dashboard_api


class BrokerAssetReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.d = {'raw': {'output2': [dict(nass_amt='8893271', dnca_tot_amt='2547752',
            prvs_rcdl_excc_amt='980511', evlu_amt_smtl_amt='7912760', tot_loan_amt='0')]}}
        self.p = {'raw': {'output3': dict(tot_asst_amt='15879690', tot_dncl_amt='2547752',
            evlu_amt_smtl_amt='10016105', ustl_sll_amt_smtl='3315833', ustl_buy_amt_smtl='0', tot_loan_amt='0')}}

    def test_actual_broker_snapshot_cash_counted_once(self):
        result = dashboard_api._reconcile_broker_assets(self.d, self.p)
        self.assertTrue(result['verified'])
        self.assertEqual(result['total'], 22225209)
        self.assertEqual(result['total'], 7912760 + 980511 + 10016105 + 3315833)

    def test_unsettled_buy_is_subtracted_once(self):
        self.p['raw']['output3'].update(ustl_buy_amt_smtl='1000000', tot_asst_amt='14879690')
        self.assertEqual(dashboard_api._reconcile_broker_assets(self.d, self.p)['total'], 21225209)

    def test_unsupported_missing_inconsistent_or_nonfinite_is_not_attested(self):
        for key, value in [('tot_dncl_amt', '1'), ('tot_asst_amt', '99999999'),
                           ('tot_loan_amt', '500000'), ('tot_asst_amt', 'NaN')]:
            p = copy.deepcopy(self.p)
            p['raw']['output3'][key] = value
            self.assertFalse(dashboard_api._reconcile_broker_assets(self.d, p)['verified'])
        self.assertFalse(dashboard_api._reconcile_broker_assets({}, self.p)['verified'])

    def test_zero_cash_and_assets_are_valid_not_missing(self):
        for row in (self.d['raw']['output2'][0], self.p['raw']['output3']):
            for key in row: row[key] = '0'
        result = dashboard_api._reconcile_broker_assets(self.d, self.p)
        self.assertTrue(result['verified'])
        self.assertEqual(result['total'], 0)
