# PAPER gateway coordination — 2026-10-13

The previous `sys` registry coordinated WIZ model reloads and threads but not
separate Python processes. The PAPER worker and standalone read-only audit
could therefore each respect 1.1 seconds while jointly exceeding the gateway
limit.

PAPER requests now acquire an OS file lock keyed by SHA-256 of broker host and
app key. Windows uses a one-byte `msvcrt` lock; POSIX uses `flock`. Timing state
shares the last request slot and rate-limit cooldown across processes. No key,
account number, token or broker response is stored in the lock file. Storage
or deadline failure blocks the request instead of bypassing the limiter.

The same-host processes must use this updated code and the same OS temporary
directory. Other machines, unrelated API clients and broker-side throttling
remain outside this local coordinator. LIVE pacing is unchanged. Trading POSTs
still have no automatic transport replay.

Verification: two real spawned processes issue four request-slot acquisitions;
all adjacent slots are at least 1.1 seconds apart (test tolerance 0.03 seconds).
A second test asserts a shared cooldown cannot overrun a caller deadline by
sending anyway. Full local suite: 437 tests passed. These tests do not submit
orders; live PAPER endpoint probe results are stored under ignored
`data/reconciliation-audits/` rather than committed.
