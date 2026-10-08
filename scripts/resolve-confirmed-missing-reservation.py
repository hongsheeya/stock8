"""One-time recovery authorized by owner confirmation on 2026-10-06.
Clear only the exact missing SOXL request; archive it before changing state.
No broker order/cancel calls and no changes to ON/OFF or symbol locks.
"""
import json
import sqlite3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
db = sqlite3.connect(root / 'data/live/trading.db')
uid = db.execute('select user_id from trading_cycle where id=?',
                 ('tsevwkrrjetkjjunnsamosnumiuskebe',)).fetchone()[0]
key = f'user:{uid}:kis_reservation_pending'
raw = db.execute('select value from trading_config where key=?', (key,)).fetchone()[0]
pending = json.loads(raw)
assert pending == {'at':'2026-10-06T02:15:18.438280','tr_id':'TTTT3014U',
                   'symbol':'SOXL','qty':'2','price':'159.27'}, 'Unexpected request; refusing recovery'
backup = root / 'data/live/before-confirmed-reservation-recovery-20261006.db'
assert not backup.exists(), 'Recovery already attempted; inspect before repeating'
with sqlite3.connect(backup) as saved:
    db.backup(saved)
with db:
    changed = db.execute("update trading_config set value='' where key=? and value=?", (key, raw)).rowcount
    assert changed == 1
    # Legacy mirror only when its exact value matches this request.
    db.execute("update trading_config set value='' where key='kis_reservation_pending' and value=?", (raw,))
print('Exact owner-confirmed missing request archived and resolved; policy and locks unchanged.')
