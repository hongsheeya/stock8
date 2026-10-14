# Verification 2026-10-03 (KST)

## Final follow-up after user confirmed OFF

The sections below this follow-up describe the earlier investigation and are
superseded where the outcome below is newer.

- Confirmed all three current LIVE strategy flags OFF before every restart;
  did not turn any strategy ON, change locks or submit/cancel broker orders.
- Full suite now **285 tests passed** (5.409s). Added repeat-recalculation
  cost-basis tests, archived portfolio/reconciled-fill replay tests and OFF
  snapshot no-network-path tests.
- Final deployment stamp: **20261003-215037**. Both frontend and backend rebuilt;
  earlier deployed model/API SHA-256 checks matched sources. Windows IDE's
  optional termios import warning did not prevent successful EsBuild/artifacts.
- Browser verified KS page has only KS switch, US page only US switch, both OFF.
  Global navigation still links both pages. Redundant in-page tabs removed.
- Fixed US OFF initial snapshot doing signal/balance/history work, and a
  hidden broker/quote fetch in shared_budget_status(use_cache_only=True).
  Actual warm page reload to visible OFF status: **2505ms**, one measured sample,
  not a claim about ON diagnostics or all networks. Stored state is labeled as
  stored, not current. No timeout alert during that verification.
- KIS read-only holding: **SOXL 45 shares @ 158.6427**; confirmed one SELL
  **15 @ 163 on 2026-10-02, order 0030955142**, no other fill in Oct 1–3 query.
- Restored original FireGate portfolio 1780022179464 as canonical, linked to
  current local cycle. Added the missing confirmed SELL. It now has 32 records.
  Duplicate 1790947379164 is stopped/archived, not deleted; its 27 records remain.
  Browser showed only the original 45-share portfolio. Clicking “지금 동기화”
  succeeded (5 portfolios pulled, 0 cycles created); local SOXL stayed 45 shares.
- Reconciliation audit/backups:
  `data/reconciliation-audits/soxl-identity-repair-20261003.json` and `.db`.
  Read-only repeated planning confirmed already_repaired=true, no duplicate fill.
- Found/fixed historical recalculation subtracting sale proceeds from acquisition
  cost and writing post-sale average into a SELL. Now removes proportional cost
  and preserves pre-sale average. Confirmed SOXL SELL basis is 158.6427, remaining
  qty45, local return2.49%. Local calculated net P&L is $59.25 using the existing
  $6.11 fee estimate; broker-confirmed gross gain before fees is $65.3595.
  This does not certify actual charged fees. A verified basis anchor handles the
  incomplete older ledger without inventing buys and survives future recalculation.
- Post-restart browser history loaded successfully and displayed the Oct 2 SOXL
  SELL (15 shares at $163) with **$59.25** realized P&L and the remaining SOXL
  position **45 shares at $158.64**. Older unmatched-basis sells are explicitly
  excluded by the existing page; they were not fabricated or certified in this repair.

## Validation boundaries

No live orders were placed to test exchange acceptance or fills. Long-duration
outage recovery and exact combined net-asset agreement with KIS statements are
not established by unit tests/read-only snapshots. Those are not silently marked
complete. All currently available automated regression tests passed; the actual
screen/deployment and duplicate reconciliation checks above were performed.

## Verified, without submitting orders

- Full unittest discovery: 279 tests passed, 5.216 seconds (final run).
- Coverage includes account isolation, strategy/market permission boundaries,
  symbol locks, OFF worker paths, GET token recovery, no POST replay,
  domestic session routing, confirmed-fill history/P&L and infinite-buy scheduling.
- New external SELL replay regression: records the historical fill but does not
  auto-start another investment cycle.
- New migrated FireGate identity regression: an existing running managed
  portfolio prevents silently creating another portfolio for a different local ID.
  Manual portfolios are not adopted or overwritten.
- Read-only KIS balance requests succeeded at approximately 00:45 KST:
  domestic 1.312s, overseas 3.641s, present balance 1.422s. These include a
  deliberate 1.2-second per-request pacing delay. One bounded sample is not
  evidence of long-term uptime. Audit forbids POST, token refresh and DB writes.
- Browser confirms current serving page still has both market switches, and
  embedded FireGate really has two running SOXL portfolios. Not a display-cache
  diagnosis alone.

## Source changes prepared, NOT deployed

- Domestic page receives market=KS, US page market=US; only its own market
  switch and worker status are rendered. Redundant in-page market tabs removed.
  Global navigation remains available.
- Dashboard distinguishes intentionally deferred USD buying-power lookup from
  failed lookup.
- Historical replay does not create a trailing empty cycle.
- FireGate refuses a new running managed portfolio when an older identity
  already represents that symbol. It does not guess which records to overwrite.

## Recoverable local cleanup already applied

Only empty completed TQQQ #4 was removed from local LIVE trading_cycle.
It had no shares, no cycle_trade records and no filled/order-linked logs.
Full SQLite backup: data/reconciliation-audits/before-empty-tqqq-20261003.db.
All other cycles and fill/audit records remain. The one-shot cleanup script
refuses repeat execution. This is separate from the visible SOXL duplicate.

## Actual FireGate duplication

- Original SOXL portfolio 1780022179464: 60 shares, 31 transactions,
  old sourceCycleId 4ab3c049b40646bbbb110a4347acbb37.
- New SOXL portfolio 1790947379164: 36 shares, 27 transactions,
  current sourceCycleId tsevwkrrjetkjjunnsamosnumiuskebe.
- Both are running, same managed source/group. Identity mismatch during account
  separation caused the new portfolio. Neither is an unused empty record.
- Neither remote record was deleted or modified in this verification.
  Current broker holdings/fills must be reconciled before selecting one active
  canonical record. Do not restore 60 shares merely because the older record says so.

## Blocking live deployment / remaining evidence

At 00:43–00:44 KST, both DB policy and the actual domestic page confirmed
the currently connected LIVE account has infinite_buy, daytrade_ks and
daytrade_us ON. This differs from the earlier OFF state. No switch or lock was
changed. User permission to temporarily turn OFF has been requested.

Do not hot-replace/restart this active engine as part of an assumed OFF test.
After OFF approval: reconcile remote duplicate with backed-up records, build,
restart, verify deployed artifact identity and market-specific rendered controls.
Actual order acceptance/fills are deliberately not tested by placing live orders.
Broker-comparable combined net assets and prolonged outage recovery are not
certified by this test run; the previous accounting caveat remains applicable.

This report is not a claim that all production verification is complete.
