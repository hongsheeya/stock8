import peewee as pw
import datetime

orm = wiz.model("portal/season/orm")
base = orm.base("trading")
_TIME = wiz.model("portal/trading/kst")


def _kst_now():
    return _TIME.now()

class Model(base):
    class Meta:
        db_table = "trading_cycle"

    id = pw.CharField(max_length=32, primary_key=True)
    symbol = pw.CharField(max_length=16, index=True)
    cycle_number = pw.IntegerField(default=1)
    status = pw.CharField(max_length=16, default="IDLE", index=True)
    current_round = pw.IntegerField(default=0)
    t_value = pw.FloatField(default=0.0)
    division_count = pw.IntegerField(default=40)
    target_profit = pw.FloatField(default=10.0)
    total_investment = pw.FloatField(default=0.0)
    total_spent = pw.FloatField(default=0.0)
    total_qty = pw.IntegerField(default=0)
    avg_price = pw.FloatField(default=0.0)
    current_price = pw.FloatField(default=0.0)
    current_eval = pw.FloatField(default=0.0)
    profit_rate = pw.FloatField(default=0.0)
    total_commission = pw.FloatField(default=0.0)
    remaining_investment = pw.FloatField(default=0.0)
    partial_sold_count = pw.IntegerField(default=0)
    crash_buy_count = pw.IntegerField(default=0)
    started_at = pw.DateTimeField(null=True)
    completed_at = pw.DateTimeField(null=True)
    created = pw.DateTimeField(default=_kst_now)
    updated = pw.DateTimeField(default=_kst_now)
