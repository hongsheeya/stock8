"""Archive only the identified empty auto-restart cycle; no broker calls."""
import sqlite3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
db_path = root / 'data/live/trading.db'
backup_path = root / 'data/reconciliation-audits/before-empty-tqqq-20261003.db'
target = 'ttmmplggdhekfniymsxavcqiuehklooi'
if backup_path.exists():
    raise SystemExit('Backup already exists; refusing repeat execution')
with sqlite3.connect(db_path) as db:
    row = db.execute('SELECT symbol,status,total_qty FROM trading_cycle WHERE id=?', (target,)).fetchone()
    assert row == ('TQQQ', 'COMPLETED', 0), 'Target state changed'
    assert db.execute('SELECT count(*) FROM cycle_trade WHERE cycle_id=?', (target,)).fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM trade_log WHERE cycle_id=? AND (coalesce(order_no,'')<>'' OR coalesce(filled_qty,0)>0)", (target,)).fetchone()[0] == 0
    with sqlite3.connect(backup_path) as backup:
        db.backup(backup)
    db.execute('BEGIN IMMEDIATE')
    assert db.execute('SELECT symbol,status,total_qty FROM trading_cycle WHERE id=?', (target,)).fetchone() == row
    assert db.execute('SELECT count(*) FROM cycle_trade WHERE cycle_id=?', (target,)).fetchone()[0] == 0
    db.execute('DELETE FROM trading_cycle WHERE id=?', (target,))
    db.commit()
print('Archived empty TQQQ #4. Original cycles, fills and audit logs preserved.')
print('Recovery backup:', backup_path)
