"""Reservation reads must be complete before the scheduler can mutate orders."""
import unittest
import json
from unittest.mock import Mock
from test_kis_api_buying_power import kis_api, _StructStub
import test_infinitebuy_loc_schedule_regressions as schedule_fixtures


def page(start, count=20, continuation="M", cursor="next"):
    return {"rt_cd": "0", "tr_cont": continuation,
            "CTX_AREA_FK200": cursor, "CTX_AREA_NK200": cursor,
            "output": [{"OVRS_RSVN_ODNO": str(i), "PDNO": "SOXL",
                        "SLL_BUY_DVSN_CD": "02", "RSVN_ORD_QTY": "1",
                        "RSVN_ORD_UNPR": "158.64", "ORD_DVSN": "34"}
                       for i in range(start, start + count)]}


class ReservationPaginationSafetyTests(unittest.TestCase):
    def test_pending_inspection_queries_both_sources_without_clearing_barrier(self):
        config = _StructStub()
        config.set_config('kis_reservation_pending', json.dumps({'at':'2026-05-29T02:15:18','symbol':'SOXL','qty':'2','price':'159.27'}))
        api = kis_api.KisApi(config)
        api.get_overseas_reservation_orders = Mock(return_value=[])
        api.get_overseas_order_history = Mock(return_value=[])
        self.assertEqual(api.inspect_pending_reservation()['status'], 'not_found')
        self.assertTrue(api.get_overseas_order_history.call_args.kwargs['strict'])
        self.assertTrue(config.get_config('kis_reservation_pending'))
        api.get_overseas_order_history.side_effect = RuntimeError('partial query')
        with self.assertRaises(RuntimeError):
            api.inspect_pending_reservation()
        self.assertTrue(config.get_config('kis_reservation_pending'))

    def test_26_buy_fills_do_not_exhaust_firegate_20_divisions(self):
        engine, _, _ = schedule_fixtures.InfiniteBuyLocScheduleRegressionTests()._engine(
            {}, configs={'firegate_authoritative_reservations_only':'true'})
        trades, cycles = Mock(), Mock()
        trades.rows.return_value = [{'id':str(i),'action':'BUY','status':'FILLED',
            'filled_qty':1,'filled_price':100,'filled_amount':100} for i in range(26)]
        cycles.get.return_value = {'id':'c','status':'PENDING_EXTENSION','division_count':20,
                                   't_value':7.35,'total_investment':15000}
        engine._trade_db = lambda: trades
        engine._cycle_db = lambda: cycles
        engine._is_synthetic_external_trade = lambda row: False
        result = engine._recalculate_cycle_from_trades('c')
        self.assertEqual(result['current_round'], 7)
        self.assertEqual(result['status'], 'ACTIVE')

    def test_firegate_t_restores_strategy_without_overwriting_holdings(self):
        engine, _, _ = schedule_fixtures.InfiniteBuyLocScheduleRegressionTests()._engine(
            {}, configs={'firegate_authoritative_reservations_only':'true'})
        engine._load_firegate_authoritative_states = lambda: {'states':{'SOXL':{
            'current_round':7,'t_value':7.35,'division_count':20,'status':'ACTIVE','total_qty':35}}}
        engine._find_external_cycle = lambda symbol: {'id':'c','status':'PENDING_EXTENSION'}
        db = Mock()
        engine._cycle_db = lambda: db
        engine.sync_firegate_strategy_metadata()
        data = db.update.call_args.args[0]
        self.assertEqual(data['status'], 'ACTIVE')
        self.assertEqual(data['t_value'], 7.35)
        self.assertNotIn('total_qty', data)

    def test_recent_fill_sync_does_not_expand_to_cycle_start(self):
        engine, broker, _ = schedule_fixtures.InfiniteBuyLocScheduleRegressionTests()._engine(
            {}, cycle_rows=[{'id':'c','symbol':'SOXL','status':'ACTIVE','created':'2020-01-01'}])
        engine._external_sync_target_symbols = lambda **kw: (['SOXL'], {'SOXL'})
        engine._verified_external_order_history = Mock(return_value={'verified':False, 'errors':[]})
        engine.sync_external_cycle_trades(lookback_days=2, recent_only=True)
        args = engine._verified_external_order_history.call_args.args
        self.assertEqual((args[3] - args[2]).days, 2)

    def test_unknown_receipt_rebuild_stops_before_cancelling(self):
        engine, broker, _ = schedule_fixtures.InfiniteBuyLocScheduleRegressionTests()._engine(
            {}, configs={'kis_reservation_pending': 'unknown'})
        engine.cancel_active_loc_reservations = Mock()
        result = engine.rebuild_loc_reservations(['SOXL'])
        self.assertEqual(result['status'], 'reconciliation_required')
        engine.cancel_active_loc_reservations.assert_not_called()
        self.assertEqual(broker.buy_calls, [])

    def test_buying_power_error_is_not_reported_as_zero_balance(self):
        engine, broker, _ = schedule_fixtures.InfiniteBuyLocScheduleRegressionTests()._engine(
            {'ok':False, 'message':'KIS preflight unavailable'},
            watchlist_rows=[{'id':'w','symbol':'SOXL','exchange':'NASD','is_active':True}],
            cycle_rows=[{'id':'c','symbol':'SOXL','status':'ACTIVE','total_qty':1,'avg_price':100,
                         'total_investment':15000,'division_count':20,'current_round':1,'total_spent':100}])
        result = engine.schedule_loc_buys('SOXL')
        self.assertEqual(broker.buy_calls, [])
        self.assertIn('KIS preflight unavailable', str(result))

    def test_unknown_response_preserves_only_diagnostics_and_blocks_retry(self):
        config = _StructStub()
        api = kis_api.KisApi(config)
        api._request = Mock(return_value={'msg_cd': 'TEST_ERROR', 'msg1': 'Rejected by gateway', 'secret': 'not-for-storage'})
        with self.assertRaisesRegex(RuntimeError, 'TEST_ERROR'):
            api.buy_reservation_order('SOXL', 2, 159.27)
        record = json.loads(config.get_config('kis_reservation_pending'))
        self.assertEqual(record['response']['msg_cd'], 'TEST_ERROR')
        self.assertNotIn('not-for-storage', json.dumps(record))
        with self.assertRaises(RuntimeError):
            api.buy_reservation_order('SOXL', 2, 159.27)
        self.assertEqual(api._request.call_count, 1)

    def test_full_soxl_plan_submission_then_repeat_without_duplicate(self):
        state = {'id': 'c', 'symbol': 'SOXL', 'status': 'ACTIVE', 'current_round': 9,
                 't_value': 9.8, 'division_count': 20, 'total_investment': 15000,
                 'total_buy': 10543.85, 'total_sell': 3978.56, 'total_spent': 7138.9215,
                 'total_qty': 45, 'avg_price': 158.6427, 'total_commission': 0,
                 'target_profit': 20, 'remaining_investment': 8434.71,
                 '_firegate_authoritative': True}
        engine, broker, _ = schedule_fixtures.InfiniteBuyLocScheduleRegressionTests()._engine(
            {'executable_amount': 100000, 'executable_qty': 10000, 'broker_amount': 100000, 'broker_qty': 10000},
            watchlist_rows=[{'id':'w', 'symbol':'SOXL', 'exchange':'NASD', 'is_active':True}],
            cycle_rows=[state], holdings=[{'symbol':'SOXL', 'qty':45}],
            configs={'firegate_authoritative_reservations_only':'true'})
        engine._load_firegate_authoritative_states = lambda **kw: {'states':{'SOXL':state}, 'error':''}
        engine.calculate_buy_decision = schedule_fixtures.engine_module.Engine.calculate_buy_decision.__get__(engine)
        buy = engine.schedule_loc_buys(symbol_filter='SOXL')
        sell = engine.schedule_loc_sells(symbol_filter='SOXL')
        self.assertEqual(buy['scheduled_count'], 9, buy)
        self.assertEqual(sell['scheduled_count'], 2, sell)
        self.assertEqual(sum(r['qty'] for r in broker.buy_calls), 12)
        self.assertEqual([(r['qty'],r['price'],r['order_type']) for r in broker.sell_reservation_calls],
                         [(11,159.28,'LOC'),(34,190.37,'LIMIT')])
        broker.reservation_orders = [dict(r, side=side, cancel_yn='N')
                                     for side, orders in [('BUY',broker.buy_calls),('SELL',broker.sell_reservation_calls)]
                                     for r in orders]
        for _ in range(3):
            self.assertEqual(engine.schedule_loc_buys(symbol_filter='SOXL')['scheduled_count'], 0)
            self.assertEqual(engine.schedule_loc_sells(symbol_filter='SOXL')['scheduled_count'], 0)
        self.assertEqual(len(broker.buy_calls), 9)
        self.assertEqual(len(broker.sell_reservation_calls), 2)

    def test_accepted_but_invisible_order_is_not_resent_after_restart(self):
        config = _StructStub()
        api = kis_api.KisApi(config)
        api._request = Mock(return_value={'rt_cd': '0', 'output': {'ODNO': '123'}})
        api.buy_reservation_order('SOXL', 3, 158.64)
        restarted = kis_api.KisApi(config)
        restarted._request = Mock(return_value={'rt_cd': '0', 'tr_cont': 'D', 'output': []})
        self.assertEqual(restarted.get_overseas_reservation_orders(start_date='20260529', exchanges=['NASD']), [])
        with self.assertRaises(RuntimeError):
            restarted.buy_reservation_order('SOXL', 3, 158.64)
        self.assertEqual(restarted._request.call_count, 1)  # GET only

    def test_confirmed_receipt_visibility_releases_visibility_barrier(self):
        config = _StructStub()
        api = kis_api.KisApi(config)
        api._request = Mock(return_value={'rt_cd': '0', 'output': {'ODNO': '123'}})
        api.buy_reservation_order('SOXL', 3, 158.64)
        api._request = Mock(return_value=page(123, 1, 'D', ''))
        api.get_overseas_reservation_orders(start_date='20260529', exchanges=['NASD'])
        self.assertEqual(config.get_config('kis_reservation_unseen_receipts'), '{}')

    def test_unknown_submission_blocks_after_api_recreation(self):
        config = _StructStub()
        api = kis_api.KisApi(config)
        api._request = Mock(side_effect=TimeoutError('response lost'))
        with self.assertRaises(TimeoutError):
            api.buy_reservation_order('SOXL', 3, 158.64)
        restarted = kis_api.KisApi(config)
        restarted._request = Mock()
        with self.assertRaises(RuntimeError):
            restarted.buy_reservation_order('SOXL', 3, 158.64)
        with self.assertRaises(RuntimeError):
            restarted.sell_reservation_order('SOXL', 11, 159.28)
        with self.assertRaises(RuntimeError):
            restarted.cancel_overseas_reservation_order('1', receipt_date='20261005')
        restarted._request.assert_not_called()

    def test_missing_receipt_number_keeps_submission_barrier(self):
        config = _StructStub()
        api = kis_api.KisApi(config)
        api._request = Mock(return_value={'rt_cd': '0', 'output': {}})
        with self.assertRaises(RuntimeError):
            api.buy_reservation_order('SOXL', 3, 158.64)
        self.assertTrue(config.get_config('kis_reservation_pending'))

    def read(self, pages):
        api = kis_api.KisApi(_StructStub())
        api._request = Mock(side_effect=pages)
        return api.get_overseas_reservation_orders(start_date="20261005", exchanges=["NASD"])

    def test_reads_all_45_not_only_first_20(self):
        rows = self.read([page(0, cursor="a"), page(20, cursor="b"),
                          page(40, 5, "D", "")])
        self.assertEqual(len(rows), 45)
        self.assertEqual(rows[-1]["order_no"], "44")

    def test_existing_order_on_second_page_suppresses_repeated_engine_submission(self):
        first = page(0)
        for row in first['output']:
            row['PDNO'] = 'OTHER'
        last = page(20, 1, 'D', '')
        last['output'][0]['RSVN_ORD_UNPR'] = '150.0'
        rows = self.read([first, last])
        engine, broker, _ = schedule_fixtures.InfiniteBuyLocScheduleRegressionTests()._engine(
            {'executable_amount': 100000, 'executable_qty': 1000}, reservation_orders=rows,
            watchlist_rows=[{'id': 'w', 'symbol': 'SOXL', 'exchange': 'NASD', 'is_active': True}],
            cycle_rows=[{'id': 'c', 'symbol': 'SOXL', 'status': 'ACTIVE', 'current_round': 1,
                         'division_count': 20, 'total_investment': 15000, 'total_spent': 150,
                         'total_qty': 1, 'avg_price': 150, 'remaining_investment': 14850}])
        for _ in range(3):
            result = engine.schedule_loc_buys(symbol_filter='SOXL')
            self.assertEqual(result['satisfied_count'], 1)
        self.assertEqual(broker.buy_calls, [])

    def test_second_page_broker_error_never_returns_partial_success(self):
        with self.assertRaises(RuntimeError):
            self.read([page(0), {"rt_cd": "1", "msg1": "rate limit"}])

    def test_second_page_timeout_never_returns_partial_success(self):
        with self.assertRaises(TimeoutError):
            self.read([page(0), TimeoutError("timeout")])

    def test_repeating_cursor_blocks(self):
        with self.assertRaises(RuntimeError):
            self.read([page(0), page(20)])

    def test_cursor_loop_blocks(self):
        with self.assertRaises(RuntimeError):
            self.read([page(0, cursor="a"), page(20, cursor="b"), page(40, cursor="a")])

    def test_full_page_without_completion_metadata_blocks(self):
        with self.assertRaises(RuntimeError):
            self.read([page(0, continuation="", cursor="")])

    def test_more_pages_without_cursor_blocks(self):
        with self.assertRaises(RuntimeError):
            self.read([page(0, cursor="")])

    def test_overlapping_pages_deduplicate_order_identity(self):
        rows = self.read([page(0), page(19, 3, "D", "")])
        self.assertEqual(len(rows), 22)

    def test_partial_query_blocks_both_buy_and_sell_submission(self):
        fixture = schedule_fixtures.InfiniteBuyLocScheduleRegressionTests()
        engine, broker, _ = fixture._engine(
            {}, watchlist_rows=[{"id": "w", "symbol": "SOXL", "exchange": "NASD", "is_active": True}],
            cycle_rows=[{"id": "c", "symbol": "SOXL", "status": "ACTIVE"}])
        broker.get_overseas_reservation_orders = lambda **kw: self.read([
            page(0), {"rt_cd": "1"}])
        for schedule in (engine.schedule_loc_buys, engine.schedule_loc_sells):
            result = schedule(symbol_filter="SOXL")
            self.assertTrue(result["reservation_query_failed"])
        self.assertEqual(broker.buy_calls, [])
        self.assertEqual(broker.sell_reservation_calls, [])

    def test_soxl_screenshot_plan_prices_quantities_and_types(self):
        engine, _, _ = schedule_fixtures.InfiniteBuyLocScheduleRegressionTests()._engine({})
        state = {"symbol": "SOXL", "current_round": 9, "t_value": 9.8,
                 "division_count": 20, "total_investment": 15000,
                 "total_buy": 10543.85, "total_sell": 3978.56,
                 "total_qty": 45, "avg_price": 158.6427,
                 "_firegate_authoritative": True}
        buy = engine._firegate_v4_buy_decision(state, state['avg_price'], 0)['buy_orders']
        self.assertEqual([(r['loc_price'], r['order_qty']) for r in buy], [
            (158.64, 3), (159.27, 2), (137.82, 1), (118.13, 1),
            (103.37, 1), (91.88, 1), (82.69, 1), (75.18, 1), (68.91, 1)])
        sell = engine._firegate_v4_sell_orders(state)
        self.assertEqual([(r['price'], r['order_qty'], r['order_type']) for r in sell],
                         [(159.28, 11, 'LOC'), (190.37, 34, 'LIMIT')])


if __name__ == "__main__":
    unittest.main()
