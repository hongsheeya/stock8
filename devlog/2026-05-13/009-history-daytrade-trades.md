# 009. History daytrade trades

- Added a user-facing daytrade trade history endpoint to `page.history`.
- The endpoint merges:
  - `trade_log` rows with `DT_` event types.
  - `data/daytrade/live_state.json` order records, so older BUY orders that were not written to `trade_log` still appear.
- Added active daytrade position summary, buy/sell totals, realized P&L, market/action/symbol/search filters, and simple pagination.
- Expanded the history symbol list to include daytrade symbols from logs and live state.
- Added a `단타 거래` tab as the default history view.
- Rebuilt the history view template into `build/src/app/page.history/view.html`.
- Synced API changes to `build/src` and `bundle/src`.
- `npm run build` still fails on existing project-wide Angular/Sass/type errors unrelated to this change, so the served `bundle/www/main.js` was manually synchronized and verified with `node --check`.

Verification:

- `python -m py_compile` passed for source/build/bundle history API files.
- Local unauthenticated `page.history/daytrade_trades` route returns HTTP 200 with app-level 401, confirming the route is served.
- Served `/main.js` contains `loadDaytradeTrades`, `daytrade_trades`, and the new daytrade history template strings.
