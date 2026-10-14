"""Apply the already verified FireGate repair's round metadata, no orders."""
import datetime
import json
from pathlib import Path
import sqlite3

root = Path(__file__).resolve().parents[1]
cycle_id = 'tsevwkrrjetkjjunnsamosnumiuskebe'
evidence = json.loads((root / 'data/reconciliation-audits/soxl-repair-20261012-180106129556.json').read_text(encoding='utf-8'))
changes = evidence['changes']
assert changes['holdingQty'] == 47 and changes['tValue'] == 9.35
with sqlite3.connect(root / 'data/live/trading.db') as db:
    db.row_factory = sqlite3.Row
    db.execute('BEGIN IMMEDIATE')
    row = dict(db.execute('select * from trading_cycle where id=?', (cycle_id,)).fetchone())
    assert row['symbol'] == 'SOXL' and row['total_qty'] == 47
    assert abs(row['avg_price'] - 154.8035) < 0.0001
    backup = root / 'data/reconciliation-audits/soxl-local-round-before-20261012.json'
    with backup.open('x', encoding='utf-8') as f:
        json.dump(row, f, ensure_ascii=False, indent=2)
    db.execute('update trading_cycle set current_round=?,t_value=?,updated=? where id=?',
               (9, 9.35, datetime.datetime.now().isoformat(), cycle_id))
print('Local round metadata reconciled to verified FireGate: 9 / T 9.35; no orders.')
