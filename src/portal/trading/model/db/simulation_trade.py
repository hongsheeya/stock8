import peewee as pw
import datetime

orm = wiz.model("portal/season/orm")
base = orm.base("trading")
_TIME = wiz.model("portal/trading/kst")


def _kst_now():
    return _TIME.now()

class Model(base):
    class Meta:
        db_table = "simulation_trade"

    id = pw.CharField(max_length=32, primary_key=True)
    run_id = pw.CharField(max_length=32, index=True)
    cycle_num = pw.IntegerField(default=1, index=True)
    symbol = pw.CharField(max_length=16, index=True)
    round = pw.IntegerField(default=0)
    trade_date = pw.CharField(max_length=10, index=True)
    action = pw.CharField(max_length=8, default="BUY")
    order_type = pw.CharField(max_length=8, default="LOC")
    order_price = pw.FloatField(default=0.0)
    order_qty = pw.IntegerField(default=0)
    filled_price = pw.FloatField(null=True)
    filled_qty = pw.IntegerField(default=0)
    filled_amount = pw.FloatField(default=0.0)
    commission = pw.FloatField(default=0.0)
    avg_buy_price = pw.FloatField(default=0.0)
    total_qty_after = pw.IntegerField(default=0)
    total_spent_after = pw.FloatField(default=0.0)
    current_eval = pw.FloatField(default=0.0)
    profit_rate = pw.FloatField(default=0.0)
    remaining_investment = pw.FloatField(default=0.0)
    remaining_rounds = pw.IntegerField(default=0)
    total_asset = pw.FloatField(default=0.0)
    status = pw.CharField(max_length=16, default="FILLED")
    created = pw.DateTimeField(default=_kst_now)
