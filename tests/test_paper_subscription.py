import importlib.util
import pathlib
import tempfile
import unittest
import sqlite3

path = pathlib.Path(__file__).resolve().parents[1] / 'src/portal/trading/model/paper_subscription.py'
spec = importlib.util.spec_from_file_location('subscriptions', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class SubscriptionTests(unittest.TestCase):
    def test_new_user_requires_explicit_opt_in_and_isolation(self):
        with tempfile.TemporaryDirectory() as root:
            model = module.Subscription(root)
            self.assertFalse(model.enabled('new'))
            model.subscribe('new')
            self.assertTrue(module.Subscription(root).enabled('new'))
            self.assertFalse(model.enabled('other'))

    def test_existing_paper_account_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            path = pathlib.Path(root) / 'project/main/data/paper/trading.db'
            path.parent.mkdir(parents=True)
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE trading_config(key TEXT, value TEXT)')
                db.execute('INSERT INTO trading_config VALUES(?,?)', ('user:old:kis_paper_account_no','test-account'))
            db.close()
            self.assertTrue(module.Subscription(root).enabled('old'))
            self.assertFalse(module.Subscription(root).enabled('new'))
