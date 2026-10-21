import peewee as pw
import datetime

orm = wiz.model("portal/season/orm")
base = orm.base("trading")
_TIME = wiz.model("portal/trading/kst")
_SECRET = wiz.model("portal/trading/secret_box")


def _kst_now():
    return _TIME.now()


class SecretAwareTextField(pw.TextField):
    """Decrypts "enc:v1:" values on read; plain values pass through."""

    def python_value(self, value):
        return _SECRET.decrypt(super().python_value(value))


def _seal(values):
    # Rows written as secret store the value encrypted (see secret_box).
    if values.get("is_secret") and "value" in values:
        values["value"] = _SECRET.encrypt(values["value"])
    return values


class Model(base):
    class Meta:
        db_table = "trading_config"

    id = pw.CharField(max_length=32, primary_key=True)
    key = pw.CharField(max_length=64, unique=True, index=True)
    value = SecretAwareTextField(default="")
    description = pw.CharField(max_length=256, default="")
    is_secret = pw.BooleanField(default=False)
    created = pw.DateTimeField(default=_kst_now)
    updated = pw.DateTimeField(default=_kst_now)

    @classmethod
    def create(cls, **query):
        return super().create(**_seal(query))

    @classmethod
    def update(cls, *args, **update):
        return super().update(*args, **_seal(update))
