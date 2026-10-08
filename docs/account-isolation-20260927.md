# LIVE main / PAPER test account separation

## Local runtime

- LIVE main: `http://127.0.0.1:3001`, `scripts/start-stock8-live.ps1`.
- PAPER: `http://127.0.0.1:3002`, `scripts/start-stock8-paper.ps1`.
- Start both hidden PowerShell supervisors only once. Build the shared bundle with
  `scripts/rebuild-stock8-frontend.ps1` before restarting workers.
- Both use the existing service-login database and Flask session signing key.
  Same hostname is required for shared cookies. Do not expose these local HTTP
  ports on the network; remote deployment needs HTTPS and explicit origins.
- Login returns to LIVE. Settings contains the only account-switch controls.
  The nav badge is informational. Switching screens does not change automation.

## Isolation and safety

`trading_database_path` pins every trading ORM table to `data/live/trading.db`
or `data/paper/trading.db`. It rejects equivalent resolved paths. The old
unscoped `data/trading.db` is never imported. Runtime memory and background
workers are separate processes; daytrade files already use mode directories.

Dashboard browser storage now uses a V3 mode + login-user namespace. The old
PAPER cache at port 3001 is ignored when that origin becomes LIVE.

KIS keys/account numbers/tokens stay in separate environment-prefixed settings.
The same literal app-key value can be entered in each environment if appropriate;
neither credentials nor historical records are copied automatically.

LIVE reads do not require order permission. All KIS trading writes require BOTH
server unlock and freshly read `live_orders_enabled=true`; Toss writes obey the
same guard, and Toss cannot run from PAPER. The local LIVE supervisor explicitly
clears the server unlock: **LIVE remains read-only/OFF**. The settings page shows
this lock rather than claiming that API connection authorizes trading.

## Verification and remaining work

- Browser verified settings LIVE -> PAPER -> LIVE without another login.
- Live DB: zero cycles / zero cycle trades; paper DB: six cycles / 49 cycle trades
  at verification. LIVE order consent absent (defaults OFF).
- Added isolation tests and LIVE read-vs-write safety tests.
- Existing PAPER records are preserved, not reset. This change does NOT claim
  that the earlier broker reset reconciliation or trading-profit audit is done.
- No actual LIVE orders were submitted, nor was LIVE order permission enabled.
- NAS deployment is deferred. The existing single-container deployment is still
  PAPER-only; it has not been converted into a dual-environment remote deployment.
