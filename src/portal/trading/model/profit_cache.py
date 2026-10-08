"""Account-scoped durable P/L materialization; no broker access on reads."""
import copy
import datetime
import decimal
import hashlib
import json
import time


def _json_value(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    raise TypeError('Unsupported profit snapshot value: ' + type(value).__name__)


class Store:
    def __init__(self, db, scope):
        self.db = db
        self.prefix = 'profit_v2:' + hashlib.sha256(scope.encode()).hexdigest() + ':'

    def key(self, name):
        # trading_config.key is VARCHAR(64), including on MySQL deployments.
        return 'profit_v2:' + hashlib.sha256((self.prefix + name).encode()).hexdigest()[:54]

    def read(self, name, max_age=None):
        row = self.db.get(key=self.key(name))
        if not row:
            return None
        entry = json.loads(row['value'])
        if max_age is not None and time.time() - entry['at'] >= max_age:
            return None
        return copy.deepcopy(entry)

    def write(self, name, payload):
        key = self.key(name)
        values = {'value': json.dumps({'at':time.time(), 'payload':payload}, ensure_ascii=False, default=_json_value),
                  'description':'계좌별 수익 집계 스냅샷', 'is_secret':False}
        row = self.db.get(key=key)
        if row:
            self.db.update(values, id=row['id'])
        else:
            self.db.insert(dict(values, key=key))

    def summary(self, start, end, today, loader):
        """Yesterday-and-earlier is reused; today's fills are reconciled separately.

        The loader owns cost-basis matching and complete broker pagination.
        Never build daily P/L by subtracting arbitrary cash snapshots.
        """
        parts = []
        yesterday = (datetime.datetime.strptime(today, '%Y%m%d') - datetime.timedelta(days=1)).strftime('%Y%m%d')
        if start < today:
            past_end = min(end, yesterday)
            key = 'history:' + start + ':' + past_end
            cached = self.read(key, 21600)
            past = cached['payload'] if cached else loader(start, past_end, False)
            if not cached and past.get('broker_sync_ok') is True:
                self.write(key, past)
            parts.append(past)
        if end >= today:
            key = 'today:' + today
            cached = self.read(key, 30)
            current = cached['payload'] if cached else loader(today, today, True)
            if not cached and current.get('broker_sync_ok') is True:
                self.write(key, current)
            parts.append(current)
        if not parts:
            return {}
        result = dict(parts[-1])
        for field in ('pnl_net', 'pnl_gross', 'trade_count', 'total_buy_amount'):
            result[field] = sum(float(p.get(field, 0) or 0) for p in parts)
        result['daily_breakdown'] = [r for p in parts for r in p.get('daily_breakdown', [])]
        result['broker_sync_ok'] = all(p.get('broker_sync_ok') is True for p in parts)
        return result


Model = Store
