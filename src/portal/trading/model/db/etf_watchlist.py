import peewee as pw
import datetime

orm = wiz.model("portal/season/orm")
base = orm.base("trading")
_TIME = wiz.model("portal/trading/kst")


def _kst_now():
    return _TIME.now()

class Model(base):
    class Meta:
        db_table = "etf_watchlist"

    id = pw.CharField(max_length=32, primary_key=True)
    symbol = pw.CharField(max_length=16, unique=True, index=True)
    name = pw.CharField(max_length=128, default="")
    exchange = pw.CharField(max_length=16, default="NASD")
    total_investment = pw.FloatField(default=0.0)
    division_count = pw.IntegerField(default=40)
    target_profit = pw.FloatField(default=10.0)
    cycle_mode = pw.CharField(max_length=16, default="auto")
    is_active = pw.BooleanField(default=True, index=True)
    memo = pw.TextField(default="")
    created = pw.DateTimeField(default=_kst_now)
    updated = pw.DateTimeField(default=_kst_now)
