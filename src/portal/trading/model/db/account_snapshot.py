import peewee as pw
import datetime

orm = wiz.model("portal/season/orm")
base = orm.base("trading")
_TIME = wiz.model("portal/trading/kst")


def _kst_now():
    return _TIME.now()

class Model(base):
    class Meta:
        db_table = "account_snapshot"

    id = pw.CharField(max_length=32, primary_key=True)
    snapshot_date = pw.CharField(max_length=10, unique=True, index=True)
    cash_balance = pw.FloatField(default=0.0)
    eval_amount = pw.FloatField(default=0.0)
    total_asset = pw.FloatField(default=0.0)
    total_profit = pw.FloatField(default=0.0)
    profit_rate = pw.FloatField(default=0.0)
    holdings_count = pw.IntegerField(default=0)
    active_cycles = pw.IntegerField(default=0)
    memo = pw.TextField(default="")
    created = pw.DateTimeField(default=_kst_now)
