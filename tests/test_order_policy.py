import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('order_policy_test', ROOT / 'src/portal/trading/model/order_policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

class DB:
    def __init__(self): self.rows = {}
    def get(self, key): return self.rows.get(key)
    def insert(self, row): self.rows[row['key']] = dict(row, id=row['key'])
    def update(self, values, id): self.rows[id].update(values)

class PolicyTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'TRADING_MODE': 'LIVE'})
        env.start(); self.addCleanup(env.stop)
        self.db = DB()
        self.cycle = {'symbol': 'SOXL', 'status': 'ACTIVE', 'user_id': 'owner-a'}
        self.cycles = SimpleNamespace(get=lambda **kw: self.cycle if self.cycle and all(self.cycle.get(k) == v for k, v in kw.items()) else None)
        self.struct = SimpleNamespace(db=lambda name: self.cycles if name == 'trading_cycle' else self.db, broker_provider='kis',
            broker_api=SimpleNamespace(account_no='12345678-01'), _current_user_id=lambda: 'owner-a',
            _current_user_is_admin=lambda uid: True)
        self.policy = policy.Policy(self.struct)

    def on(self, lane='infinite_buy'):
        self.policy.update(lane=lane, enabled=True, confirmation=policy.WARNING_VERSION)

    def unlock(self, symbol='TQQQ'):
        self.policy.update(symbol=symbol, locked=False, confirmation=policy.WARNING_VERSION)

    def request(self, lane='infinite_buy', symbol='TQQQ'):
        token = policy.CONTEXT.set((lane, symbol))
        try: self.policy.assert_order(symbol)
        finally: policy.CONTEXT.reset(token)

    def test_default_both_off_and_all_symbols_locked(self):
        self.assertFalse(self.policy.status()['infinite_buy'])
        self.assertFalse(self.policy.status()['daytrade'])
        self.assertTrue(self.policy.status()['default_locked'])
        with self.assertRaises(RuntimeError): self.request()

    def test_soxl_is_infinite_buy_only_even_when_daytrade_on_and_unlocked(self):
        self.on(); self.on('daytrade_us'); self.unlock('SOXL')
        self.request('infinite_buy', 'SOXL')
        for live in (True, False):
            self.policy.live = live
            with self.assertRaisesRegex(RuntimeError, '무한매수 전용'):
                self.request('daytrade_us', 'SOXL')

    def test_bound_daytrade_soxl_mutations_never_reach_broker(self):
        from unittest.mock import Mock
        class Broker:
            def buy_order(self, symbol): raise AssertionError('broker reached')
            def sell_order(self, symbol): raise AssertionError('broker reached')
            def cancel_overseas_reservation_order(self, symbol): raise AssertionError('broker reached')
        broker = self.policy.bind(Broker(), 'daytrade')
        for name in ('buy_order', 'sell_order', 'cancel_overseas_reservation_order'):
            with self.assertRaisesRegex(RuntimeError, '무한매수 전용'):
                getattr(broker, name)('SOXL')

    def test_soxl_cycle_uses_strategy_not_daytrade_lock(self):
        self.on()
        self.policy.update(symbol='SOXL', locked=True)
        self.request(symbol='SOXL')
        self.policy.update(lane='infinite_buy', enabled=False)
        with self.assertRaises(RuntimeError): self.request(symbol='SOXL')

    def test_soxl_requires_owned_operating_cycle_even_when_unlocked(self):
        self.on(); self.unlock('SOXL')
        for cycle in (None, {'symbol':'SOXL', 'status':'PAUSED', 'user_id':'owner-a'},
                      {'symbol':'SOXL', 'status':'ACTIVE', 'user_id':'other'}):
            self.cycle = cycle
            with self.assertRaises(RuntimeError): self.request(symbol='SOXL')

    def test_soxl_holding_cycle_can_exit_and_lookup_failure_blocks(self):
        self.on()
        self.cycle['status'] = 'HOLDING'
        self.request(symbol='SOXL')
        def broken(**kwargs): raise RuntimeError('database unavailable')
        self.cycles.get = broken
        with self.assertRaises(RuntimeError): self.request(symbol='SOXL')

    def test_regular_user_can_only_enable_infinite_buy(self):
        self.struct._current_user_is_admin=lambda uid:False
        self.on(); self.unlock(); self.request()
        for lane in ('daytrade_ks','daytrade_us'):
            with self.assertRaises(ValueError): self.on(lane)
            with self.assertRaises(RuntimeError): self.request(lane)
        self.assertFalse(self.policy.status()['daytrade_allowed'])

    def test_demotion_blocks_stale_on_permission_without_deleting_history(self):
        self.on('daytrade_ks'); self.unlock('005930')
        self.struct._current_user_is_admin=lambda uid:False
        self.assertTrue(self.policy.read()['daytrade_ks'])
        self.assertFalse(self.policy.status()['daytrade_ks'])
        with self.assertRaises(RuntimeError): self.request('daytrade_ks','005930')

    def test_paper_also_requires_admin_for_daytrade(self):
        self.policy.live=False
        self.struct._current_user_is_admin=lambda uid:False
        for lane in ('daytrade_ks','daytrade_us'):
            with self.assertRaises(ValueError): self.on(lane)
            with self.assertRaises(RuntimeError): self.request(lane)
    def test_enable_requires_warning_confirmation(self):
        with self.assertRaises(ValueError): self.policy.update(lane='daytrade', enabled=True)
        self.assertFalse(self.policy.status()['daytrade'])

    def test_unlock_requires_warning_confirmation(self):
        with self.assertRaises(ValueError): self.policy.update(symbol='TQQQ', locked=False)

    def test_infinite_only_does_not_authorize_daytrade(self):
        self.on(); self.unlock(); self.request()
        with self.assertRaises(RuntimeError): self.request('daytrade')

    def test_daytrade_only_does_not_authorize_infinite_buy(self):
        self.on('daytrade_us'); self.unlock(); self.request('daytrade_us')
        with self.assertRaises(RuntimeError): self.request()

    def test_lock_rechecked_for_each_submission(self):
        self.on(); self.unlock(); self.request()
        self.policy.update(symbol='TQQQ', locked=True)
        with self.assertRaises(RuntimeError): self.request()

    def test_off_rechecked_for_each_submission(self):
        self.on(); self.unlock(); self.request()
        self.policy.update(lane='infinite_buy', enabled=False)
        with self.assertRaises(RuntimeError): self.request()

    def test_unlock_does_not_enable_either_lane(self):
        self.unlock()
        with self.assertRaises(RuntimeError): self.request()

    def test_new_account_cannot_inherit_approval(self):
        self.on(); self.unlock()
        self.struct.broker_api.account_no = '98765432-01'
        with self.assertRaises(RuntimeError): self.request()
        self.assertFalse(self.policy.status()['infinite_buy'])

    def test_bad_state_fails_closed(self):
        self.on(); self.unlock()
        self.db.rows[self.policy._key()]['value'] = '{broken'
        with self.assertRaises(ValueError): self.request()

    def test_unknown_strategy_is_blocked(self):
        self.on(); self.unlock()
        with self.assertRaises(RuntimeError): self.request('')

    def test_bound_broker_carries_cancel_symbol_and_restores_context(self):
        self.on(); self.unlock()
        broker = SimpleNamespace(cancel_domestic_order=lambda order_no, symbol, qty: self.policy.assert_order())
        bound = self.policy.bind(broker, 'infinite_buy')
        bound.cancel_domestic_order('123', 'TQQQ', 1)
        self.assertEqual(policy.CONTEXT.get(), ('', ''))
        self.policy.update(symbol='TQQQ', locked=True)
        with self.assertRaises(RuntimeError): bound.cancel_domestic_order('123', 'TQQQ', 1)
        self.assertEqual(policy.CONTEXT.get(), ('', ''))

    def test_locking_one_symbol_does_not_change_another(self):
        self.on(); self.unlock('TQQQ'); self.unlock('SOXL')
        self.policy.update(symbol='TQQQ', locked=True)
        self.request(symbol='SOXL')
        with self.assertRaises(RuntimeError): self.request(symbol='TQQQ')

    def test_off_preserves_other_strategy(self):
        self.on(); self.on('daytrade_us'); self.unlock()
        self.policy.update(lane='infinite_buy', enabled=False)
        self.request('daytrade_us')
        with self.assertRaises(RuntimeError): self.request()

    def test_missing_account_cannot_be_enabled(self):
        self.struct.broker_api.account_no = ''
        self.assertFalse(self.policy.status()['configured'])
        with self.assertRaises(ValueError): self.on()

    def test_policy_is_persistent_and_not_a_cached_consent(self):
        self.on(); self.unlock()
        other = policy.Policy(self.struct)
        other.update(lane='infinite_buy', enabled=False)
        with self.assertRaises(RuntimeError): self.request()

    def test_markets_have_independent_permissions(self):
        self.on('daytrade_ks'); self.unlock('005930'); self.unlock('AAPL')
        self.request('daytrade_ks', '005930')
        with self.assertRaises(RuntimeError): self.request('daytrade_us', 'AAPL')
        self.on('daytrade_us')
        self.policy.update(lane='daytrade_ks', enabled=False)
        self.request('daytrade_us', 'AAPL')
        with self.assertRaises(RuntimeError): self.request('daytrade_ks', '005930')

    def test_legacy_combined_on_does_not_enable_new_market_switches(self):
        self.on('infinite_buy')
        row = self.db.rows[self.policy._key()]
        state = json.loads(row['value'])
        state['daytrade'] = True
        state.pop('daytrade_ks', None); state.pop('daytrade_us', None)
        row['value'] = json.dumps(state)
        self.assertFalse(self.policy.read()['daytrade_ks'])
        self.assertFalse(self.policy.read()['daytrade_us'])

    def test_shared_broker_routes_market_at_submission(self):
        self.on('daytrade_ks'); self.unlock('005930'); self.unlock('AAPL')
        broker = SimpleNamespace(
            buy_domestic_order=lambda symbol: self.policy.assert_order(symbol),
            buy_order=lambda symbol: self.policy.assert_order(symbol))
        bound = self.policy.bind(broker, 'daytrade')
        bound.buy_domestic_order('005930')
        with self.assertRaises(RuntimeError): bound.buy_order('AAPL')
        self.assertEqual(policy.CONTEXT.get(), ('', ''))
