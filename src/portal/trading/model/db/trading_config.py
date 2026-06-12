import peewee as pw
import datetime

orm = wiz.model("portal/season/orm")
base = orm.base("trading")
_TIME = wiz.model("portal/trading/kst")


def _kst_now():
    return _TIME.now()

class Model(base):
    class Meta:
        db_table = "trading_config"

    id = pw.CharField(max_length=32, primary_key=True)
    key = pw.CharField(max_length=64, unique=True, index=True)
    value = pw.TextField(default="")
    description = pw.CharField(max_length=256, default="")
    is_secret = pw.BooleanField(default=False)
    created = pw.DateTimeField(default=_kst_now)
    updated = pw.DateTimeField(default=_kst_now)
