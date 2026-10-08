"""Ten-minute paced broker READ-only check, no token issuance/order/config writes."""
import importlib.util
import json
from pathlib import Path
import time
import hashlib

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('readonly_soak_api', root / 'scripts/audit-balances-readonly.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
api = audit.ReadOnly(audit.Config())
account = audit.Config().get_config('kis_live_account_no').strip()
policy_key = 'order_policy_v1:' + hashlib.sha256(('kis:' + account).encode()).hexdigest()[:40]
results = []
started = time.monotonic()
for index in range(40):
    policy = json.loads(audit.db.execute('select value from trading_config where key=?', (policy_key,)).fetchone()[0])
    if not all(policy.get(lane) is False for lane in ('infinite_buy', 'daytrade_ks', 'daytrade_us')):
        raise SystemExit('Strategy changed from OFF; stopping audit')
    call_started = time.monotonic()
    method = 'get_domestic_balance' if index % 2 == 0 else 'get_balance'
    row = {'sample': index+1, 'endpoint': method}
    try:
        with api.request_options(timeout=8, retries=0):
            payload = getattr(api, method)()
        row.update(ok=True, holdings_count=len(payload.get('holdings', [])))
    except Exception as exc:
        row.update(ok=False, error_type=type(exc).__name__)
    row['elapsed_s'] = round(time.monotonic()-call_started, 3)
    results.append(row)
    print(json.dumps(row), flush=True)
    time.sleep(max(0, started + (index+1)*15 - time.monotonic()))
report = {'wall_seconds': round(time.monotonic()-started, 2), 'samples': results,
          'successes': sum(row['ok'] for row in results), 'orders_submitted': 0,
          'note': 'GET allowlist only; includes 1.2s pacing per request; not a long-term uptime guarantee'}
path = root / 'data/reconciliation-audits/readonly-soak-20261003.json'
path.write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps({'complete': True, 'successes': report['successes'], 'samples': len(results), 'wall_seconds': report['wall_seconds']}), flush=True)
