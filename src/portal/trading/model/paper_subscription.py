"""Shared opt-in entitlement; no orders or broker credentials are copied."""
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager

class Subscription:
    def __init__(self, root):
        self.root = Path(root)

    @contextmanager
    def _db(self):
        path = self.root / 'project/main/data/paper-subscriptions.db'
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(path), timeout=3)
        db.execute('CREATE TABLE IF NOT EXISTS subscriptions (user_id TEXT PRIMARY KEY, created TEXT DEFAULT CURRENT_TIMESTAMP)')
        try:
            with db:
                yield db
        finally:
            db.close()

    def enabled(self, uid):
        if not uid:
            return False
        with self._db() as db:
            if db.execute('SELECT 1 FROM subscriptions WHERE user_id=?', (str(uid),)).fetchone():
                return True
        # Existing users keep their PAPER account, without granting new users one.
        paper = self.root / os.environ.get('STOCK8_PAPER_DB_PATH', 'project/main/data/paper/trading.db')
        if paper.exists():
            db = sqlite3.connect(paper.resolve().as_uri() + '?mode=ro', uri=True, timeout=3)
            try:
                return bool(db.execute("SELECT 1 FROM trading_config WHERE key=? AND value<>''", ('user:' + str(uid) + ':kis_paper_account_no',)).fetchone())
            except sqlite3.OperationalError:
                return False
            finally:
                db.close()
        return False

    def subscribe(self, uid):
        if not uid:
            raise ValueError('로그인이 필요합니다.')
        with self._db() as db:
            db.execute('INSERT OR IGNORE INTO subscriptions(user_id) VALUES(?)', (str(uid),))
        return True

Model = Subscription
