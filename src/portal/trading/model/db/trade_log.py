import peewee as pw
import datetime

orm = wiz.model("portal/season/orm")
base = orm.base("trading")
_TIME = wiz.model("portal/trading/kst")


def _kst_now():
    return _TIME.now()

class Model(base):
    class Meta:
        db_table = "trade_log"

    id = pw.CharField(max_length=32, primary_key=True)
    cycle_id = pw.CharField(max_length=32, default="", index=True)
    symbol = pw.CharField(max_length=16, index=True)
    event_type = pw.CharField(max_length=32, index=True)
    action = pw.CharField(max_length=8, default="")
    order_no = pw.CharField(max_length=64, default="")
    order_price = pw.FloatField(default=0.0)
    order_qty = pw.IntegerField(default=0)
    filled_price = pw.FloatField(null=True)
    filled_qty = pw.IntegerField(default=0)
    message = pw.TextField(default="")
    raw_response = pw.TextField(default="")
    created = pw.DateTimeField(default=_kst_now)
