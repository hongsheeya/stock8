"""Encryption at rest for secret trading_config rows (10-21, pre-launch)."""
import os
import tempfile
import types
import unittest
from pathlib import Path

try:
    import cryptography  # noqa: F401
    import peewee as pw
except ImportError:  # the runtime venv has both; skip elsewhere
    pw = None

NOW = __import__("datetime").datetime(2026, 10, 21)
SRC = Path(__file__).resolve().parents[1] / "src" / "portal" / "trading" / "model"


def _load(path, wiz=None):
    env = {"__name__": str(path), "wiz": wiz}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), env)
    return env


@unittest.skipIf(pw is None, "cryptography/peewee not installed")
class SecretConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = {k: os.environ.get(k) for k in ("STOCK8_CONFIG_KEY", "STOCK8_CONFIG_KEY_FILE")}
        os.environ.pop("STOCK8_CONFIG_KEY", None)
        os.environ["STOCK8_CONFIG_KEY_FILE"] = os.path.join(self.tmp.name, "keys", "config.key")
        self.box_env = _load(SRC / "secret_box.py")
        self.box_env["reset"]()
        self.addCleanup(self._restore)
        self.db = pw.SqliteDatabase(":memory:")

        class Base(pw.Model):
            class Meta:
                database = self.db

        box = self.box_env["Model"]
        kst = types.SimpleNamespace(now=lambda: None)
        models = {"portal/season/orm": types.SimpleNamespace(base=lambda name: Base),
                  "portal/trading/kst": kst, "portal/trading/secret_box": box}
        wiz = types.SimpleNamespace(model=lambda name: models[name])
        self.Model = _load(SRC / "db" / "trading_config.py", wiz)["Model"]
        self.db.create_tables([self.Model])

    def _restore(self):
        self.box_env["reset"]()
        for key, value in self.env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _raw(self, key):
        return self.db.execute_sql("SELECT value FROM trading_config WHERE key=?", (key,)).fetchone()[0]

    def test_secret_rows_are_encrypted_at_rest_and_read_back_plain(self):
        self.Model.create(id="a" * 32, key="user:u1:kis_live_app_secret", value="s3cret", is_secret=True,
                          description="", created=NOW, updated=NOW)
        self.Model.create(id="b" * 32, key="daytrade_regime_trend_start", value="10:00", is_secret=False,
                          description="", created=NOW, updated=NOW)
        self.assertTrue(self._raw("user:u1:kis_live_app_secret").startswith("enc:v1:"))
        self.assertNotIn("s3cret", self._raw("user:u1:kis_live_app_secret"))
        self.assertEqual(self._raw("daytrade_regime_trend_start"), "10:00")
        rows = {r["key"]: r["value"] for r in self.Model.select().dicts()}
        self.assertEqual(rows["user:u1:kis_live_app_secret"], "s3cret")
        self.assertEqual(rows["daytrade_regime_trend_start"], "10:00")
        self.assertTrue(os.path.exists(os.environ["STOCK8_CONFIG_KEY_FILE"]))

    def test_update_encrypts_and_empty_values_stay_empty(self):
        self.Model.create(id="a" * 32, key="kis_live_access_token", value="", is_secret=True,
                          description="", created=NOW, updated=NOW)
        self.assertEqual(self._raw("kis_live_access_token"), "")
        self.Model.update(value="tok", is_secret=True).where(self.Model.id == "a" * 32).execute()
        self.assertTrue(self._raw("kis_live_access_token").startswith("enc:v1:"))
        self.assertEqual(self.Model.get().value, "tok")

    def test_plain_legacy_rows_are_found_for_migration_and_wrong_key_reads_empty(self):
        self.db.execute_sql("INSERT INTO trading_config (id, key, value, description, is_secret, created, updated) "
                            "VALUES (?, ?, ?, '', 1, '2026-10-21', '2026-10-21')", ("c" * 32, "kis_live_app_key", "plainkey"))
        m = self.Model
        legacy = list(m.select().where((m.is_secret == True) & (m.value != "") & ~(m.value.startswith("enc:v1:"))).dicts())
        self.assertEqual([r["value"] for r in legacy], ["plainkey"])
        m.update(value="plainkey", is_secret=True).where(m.id == "c" * 32).execute()
        self.assertEqual(list(m.select().where((m.is_secret == True) & ~(m.value.startswith("enc:v1:"))).dicts()), [])
        # A different key (lost key file): the secret reads as "not configured".
        from cryptography.fernet import Fernet
        os.environ["STOCK8_CONFIG_KEY"] = Fernet.generate_key().decode()
        self.box_env["reset"]()
        self.assertEqual(m.get().value, "")


if __name__ == "__main__":
    unittest.main()
