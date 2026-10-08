import importlib.util
import json
import datetime
import decimal
from pathlib import Path
import time
import unittest

spec = importlib.util.spec_from_file_location('profit_cache', Path(__file__).resolve().parents[1] / 'src/portal/trading/model/profit_cache.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DB:
    def __init__(self): self.rows = {}
    def get(self, key): return self.rows.get(key)
    def insert(self, row): self.rows[row['key']] = dict(row, id=row['key'])
    def update(self, values, id): self.rows[id].update(values)


class ProfitMaterializationTests(unittest.TestCase):
    def setUp(self):
        self.db = DB()
        self.store = module.Store(self.db, 'LIVE:user-a:account-a')
        self.calls = []

    def load(self, start, end, current):
        self.calls.append((start, end, current))
        return {'pnl_net': 10 if current else 100, 'trade_count':1,
                'broker_sync_ok':True, 'daily_breakdown':[{'date':end,'pnl_net':10 if current else 100}]}

    def test_past_and_today_are_disjoint_and_additive(self):
        result = self.store.summary('20261001','20261007','20261007',self.load)
        self.assertEqual(self.calls, [('20261001','20261006',False),('20261007','20261007',True)])
        self.assertEqual(result['pnl_net'],110)
        self.assertEqual(result['trade_count'],2)

    def test_refresh_reuses_past_and_only_reloads_today(self):
        self.store.summary('20261001','20261007','20261007',self.load)
        key = self.store.key('today:20261007')
        entry = json.loads(self.db.rows[key]['value']); entry['at'] -= 31
        self.db.rows[key]['value'] = json.dumps(entry)
        self.calls.clear()
        self.store.summary('20261001','20261007','20261007',self.load)
        self.assertEqual(self.calls,[('20261007','20261007',True)])

    def test_restart_preserves_snapshot_and_other_scope_never_reads_it(self):
        self.store.write('view:week',{'realized_profit':123})
        self.assertEqual(module.Store(self.db,'LIVE:user-a:account-a').read('view:week')['payload']['realized_profit'],123)
        for scope in ('PAPER:user-a:account-a','LIVE:user-b:account-a','LIVE:user-a:account-b'):
            self.assertIsNone(module.Store(self.db,scope).read('view:week'))

    def test_failed_broker_partition_is_not_cached(self):
        def failed(*args): return {'broker_sync_ok':False,'pnl_net':0}
        result = self.store.summary('20261001','20261007','20261007',failed)
        self.assertFalse(result['broker_sync_ok'])
        self.assertEqual(len(self.db.rows),0)

    def test_day_rollover_does_not_reuse_yesterdays_today(self):
        self.store.summary('20261001','20261007','20261007',self.load)
        self.calls.clear()
        self.store.summary('20261002','20261008','20261008',self.load)
        self.assertEqual(self.calls,[('20261002','20261007',False),('20261008','20261008',True)])

    def test_warm_read_has_no_loader_calls_and_is_under_one_second(self):
        self.store.summary('20261001','20261007','20261007',self.load)
        def forbidden(*args): raise AssertionError('warm calculation must not query broker')
        start = time.perf_counter()
        for _ in range(100):
            self.assertEqual(self.store.summary('20261001','20261007','20261007',forbidden)['pnl_net'],110)
        self.assertLess(time.perf_counter()-start,1)

    def test_snapshot_serializes_database_dates_and_decimals(self):
        self.store.write('view:week', {'date':datetime.datetime(2026,10,7,12,0), 'amount':decimal.Decimal('123.45')})
        result = self.store.read('view:week')['payload']
        self.assertEqual(result, {'date':'2026-10-07T12:00:00','amount':123.45})
        self.assertLessEqual(len(self.store.key('view:week')),64)
