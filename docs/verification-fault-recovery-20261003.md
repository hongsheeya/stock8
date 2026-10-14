# Failure and recovery verification — 2026-10-03 22:07 KST

## Scope and live state

No live orders were submitted, amended or cancelled. Current connected account
infinite_buy, daytrade_ks and daytrade_us were checked OFF before restarting.
Browser dashboard after restart displays all three OFF, connection available,
six domestic holdings, one SOXL cycle with 45 shares and average 158.6427.
Per-cycle ON is not a master strategy permission; the master remains OFF.

## Executed evidence

- Entire unittest suite: **293 passed**, 6.313 seconds.
- Actual broker READ-only soak: **40/40 successful over 600 seconds**. Alternating
  domestic/overseas holdings, 15-second cadence, allowlisted GET endpoints only,
  no token refresh/config mutation. Detailed results in
  `data/reconciliation-audits/readonly-soak-20261003.json`.
- Fault injection: worker initialization failure recovers; engine timeout
  recovers next iteration; turning OFF between failed iterations prevents retry.
- Auth: 24 concurrent rejected-token callers issue one token; three virtual days
  renew once per expiry; read auth rejection recovers with transport retries=0;
  POST timeout/auth rejection never automatically replays the write.
- Pending cancellation: successful response and lost-response timeout both keep
  tracking; persisted/reloaded state does not repeat cancel; subsequent broker
  fill creates one execution and expected realized P&L; confirmed cancellation
  clears tracking. Partial 4/10 fill followed by remainder cancellation retains
  4 filled shares and FIFO basis 400, without inventing 10-share execution.
- Deployed build **20261003-220559**, source/bundle comparison performed.
- Actual service process restarted (3176 -> 42468), HTTP dashboard returns 200,
  authenticated browser dashboard renders holdings and OFF controls.

## Defects fixed in this verification

1. Struct initialization outside worker recovery loop could kill the worker.
2. A malformed policy JSON could interrupt dispatch for other account rows.
3. Failed or merely accepted cancellation prematurely removed pending sell
   tracking. Stop-loss replacement path had the same issue. Both now retain the
   order and block replacement until broker confirms its outcome.
4. Partial/cancelled pending sells did not update cumulative fill data in state
   order history. Executed quantity now remains visible to FIFO history.

## Explicit limits — not a release certification

Ten minutes is not overnight/multiday reliability evidence. Virtual time and
broker doubles do not prove exchange acceptance, settlement, live partial fills
or actual outage recovery. Actual live order initiation is user-operated.
The combined net-asset calculation remains unreconciled against broker-wide
account totals; prior accounting caveat is not resolved by these tests. The
dashboard's confident net-asset label is not evidence of accounting agreement.
No claim is made that every trading state transition or accounting path is now
certified. Do not use this report as blanket authorization to turn trading ON.
