import peewee as pw
import datetime

orm = wiz.model("portal/season/orm")
base = orm.base("trading")
_TIME = wiz.model("portal/trading/kst")


def _kst_now():
    return _TIME.now()

class Model(base):
    class Meta:
        db_table = "simulation_run"

    id = pw.CharField(max_length=32, primary_key=True)
    symbol = pw.CharField(max_length=16, index=True)
    start_date = pw.CharField(max_length=10)
    end_date = pw.CharField(max_length=10)
    initial_investment = pw.FloatField(default=0.0)
    division_count = pw.IntegerField(default=40)
    target_profit = pw.FloatField(default=10.0)
    buy_commission_rate = pw.FloatField(default=0.0)
    sell_commission_rate = pw.FloatField(default=0.0)
    tax_rate = pw.FloatField(default=0.0)
    total_cycles = pw.IntegerField(default=0)
    total_profit = pw.FloatField(default=0.0)
    total_profit_rate = pw.FloatField(default=0.0)
    total_commission = pw.FloatField(default=0.0)
    avg_cycle_days = pw.FloatField(default=0.0)
    max_drawdown = pw.FloatField(default=0.0)
    win_rate = pw.FloatField(default=0.0)
    final_asset = pw.FloatField(default=0.0)
    status = pw.CharField(max_length=16, default="RUNNING", index=True)
    created = pw.DateTimeField(default=_kst_now)
    completed_at = pw.DateTimeField(null=True)
