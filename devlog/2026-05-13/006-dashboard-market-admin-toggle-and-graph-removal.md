# Dashboard market status, admin preview toggle, and graph removal

## Context
- Dashboard was showing market closed during Korean market hours.
- Admin preview toggle was not visible even though the source view had been updated.
- Asset trend and return-rate trend graphs were no longer wanted on the dashboard.

## Root cause
- The served bundle was stale relative to source/build edits, so the browser did not actually receive the admin preview toggle.
- Dashboard navigation status defaulted to the US market check when the route was not market-specific.
- The build dashboard template/component lagged behind the source dashboard files.

## Changes
- Dashboard market status now treats the neutral dashboard route as Korea OR US market open.
- Admin preview mode is available to real admins and explicitly allows `gigukbyun@gmail.com`.
- Dashboard build component now includes admin preview state, automation controls, and balance diagnostics.
- Removed the dashboard asset trend and return-rate graph surface, and stopped the 1W profit-summary fetch used only for the removed chart.
- Rebuilt and copied the compiled assets into `bundle/www`.

## Verification
- Served `main.js` contains `admin_preview_user_mode`, `gigukbyun@gmail.com`, `effectiveAdminMode`, `showAdminControls`, `automationControls`, and `balanceDiagnostics`.
- Served `main.js` no longer contains the old `service.auth.session?.role` template check.
- Served `main.js` no longer contains `assetTrendDelta`, `linePointsZeroCentered`, or a `profit_summary` 1W fetch.
- KST market check at `Wed 13:59` returned `korean_market_open=true`.
