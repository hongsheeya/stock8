"""Repair only SOXL strategy metadata from a unique live FireGate portfolio.
No broker orders, cancellations, permissions, holdings or trade edits.
"""
import contextlib
import io
import runpy
import sqlite3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
with contextlib.redirect_stdout(io.StringIO()):
    audit = runpy.run_path(str(root / 'scripts/audit-firegate-readonly.py'))
portfolios = [p for p in audit['client'].list_portfolios()
              if p.get('ticker') == 'SOXL' and p.get('isRunning') is True]
assert len(portfolios) == 1, 'Ambiguous FireGate portfolio'
p = portfolios[0]
state = audit['fg']._authoritative_cycle_state_from_portfolio(p)
assert state['status'] == 'ACTIVE'
db = sqlite3.connect(root / 'data/live/trading.db')
cycle_id = p['sourceCycleId']
row = db.execute('select total_qty,status from trading_cycle where id=? and user_id=?',
                 (cycle_id, audit['uid'])).fetchone()
assert row and row[0] == state['total_qty'] and row[1] == 'PENDING_EXTENSION'
backup_path = root / 'data/live/strategy-metadata-before-repair-20261006.db'
assert not backup_path.exists(), 'Backup already exists; inspect before repeating'
with sqlite3.connect(backup_path) as backup:
    db.backup(backup)
with db:
    db.execute('update trading_cycle set current_round=?,t_value=?,division_count=?,status=? where id=? and user_id=? and status=?',
               (state['current_round'], state['t_value'], state['division_count'], state['status'],
                cycle_id, audit['uid'], 'PENDING_EXTENSION'))
print(db.execute('select symbol,total_qty,current_round,t_value,division_count,status from trading_cycle where id=?', (cycle_id,)).fetchone())
