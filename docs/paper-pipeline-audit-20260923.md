# PAPER pipeline audit — 2026-09-23

## Implemented and tested

- Domestic daily fills use VTTC0081R. Broker query failures propagate instead of appearing as empty history; continuation requests send N.
- A background, read-only reconciliation checks dated orders even after holdings reach zero. Broker-confirmed fills take precedence over pending local logs. History uses filled quantity and price, with date-qualified normalized order IDs.
- WIZ model reloads share the KIS request budget, cooldown, token lock and GET cache through process state. This does not coordinate separate hosts/processes.
- Building the app must not start the trading worker (STOCK8_BUILD_ONLY).
- Trading POST requests are not automatically retried after unknown submission outcomes.
- PAPER automatic execution waits for the regular session. A paper overseas sell checks broker quantity before submission; stale local holdings cannot authorize a sell.
- Overseas balance query errors are not treated as a confirmed empty account.
- Stock exposure excludes account equity/cash/profit fallback fields. The dashboard accepts zero rather than retaining an old positive browser-cache value.
- Domestic candidates prioritize volume/turnover movers with rotating fallback stocks and deduplicate symbols.
- /live is a separate locked management view, not a functioning live trading terminal. Live trading writes remain server-blocked even with the legacy unlock flag.

## Evidence

- Python regression suite: 216 tests passed before the final dashboard zero-value change; final frontend build succeeded.
- KIS reconciliation after shared limiter deployment: errors=[] at 02:58:42, 02:59:45, 03:00:31 and 03:02:32 KST.
- Browser history displayed realized P&L and identified three sells with unknown cost basis (excluded, not assigned invented profits).
- Browser inspection reproduced the stale positive portfolioValue bug after the backend returned zero; the frontend condition was corrected.

## Not yet proven / remaining

- KIS account reset completion has NOT been verified. No broker balances or historical trades were manually reset/deleted.
- Local SOXL/TQQQ cycle holdings and broker sell rejection (no holdings) disagree. Do not infer completed sells or realized profits from disappearing balances. Reconcile the account-reset boundary and strategy ownership before claiming full readiness.
- Two historical dates remain unresolved in the reconciler. Read-only checks continue; errors and remaining dates are in data/paper/daytrade/reconciliation.json.
- API token availability does not prove complete balance synchronization. Dashboard can still report partial USD-balance failures and local cycle estimates; those are not certified broker balances.
- Full end-to-end market-session/reset validation and browser cold-load timings remain outstanding. HTTP 200 alone is not page-load completion.
