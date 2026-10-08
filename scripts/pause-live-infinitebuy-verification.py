"""User-authorized pause; scoped to the owner of the audited SOXL cycle."""
import sqlite3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
db = sqlite3.connect(root / 'data/live/trading.db', timeout=15)
uid = db.execute('select user_id from trading_cycle where id=?',
                 ('tsevwkrrjetkjjunnsamosnumiuskebe',)).fetchone()[0]
with db:
    for key in ('auto_trade_enabled', 'loc_auto_schedule_enabled'):
        storage = f'user:{uid}:{key}'
        row = db.execute('select id from trading_config where key=?', (storage,)).fetchone()
        if not row:
            raise RuntimeError('Expected scoped setting missing; no change committed')
        db.execute("update trading_config set value='false' where key=?", (storage,))
        assert db.execute('select value from trading_config where key=?', (storage,)).fetchone()[0] == 'false'
print('Audited LIVE account infinite-buy scheduling OFF; no broker orders/cancellations sent.')
