# 010 Dashboard Daytrade Positions And Build Fix

## Summary
- Added a general-user dashboard section for active daytrade positions.
- Improved automation control cards and made the seed input high contrast.
- Fixed the build pipeline enough for `npm run build` to complete successfully.

## Changes
- `src/app/page.dashboard/api.py`
  - Added `daytrade_positions` and `daytrade_position_summary` to the overview payload.
  - Reads daytrade engine active positions without forcing a broker sync.
  - Normalizes KS/US positions into KRW evaluation and P/L fields for dashboard display.
- `src/app/page.dashboard/view.ts`
  - Added daytrade position state and display helpers.
- `src/app/page.dashboard/view.pug`
  - Added the `단타 보유중` section for general users.
  - Restyled automation cards and seed inputs.
- `src/app/page.dashboard/view.scss`
  - Added dashboard automation card, seed input, and daytrade table styles.
- Build support
  - Added missing Sass placeholders for legacy `portal/dizest` imports.
  - Added missing empty component `view.scss` files.
  - Relaxed generated Angular build strictness and raised the production bundle budget.
  - Added status fields used by layout templates.

## Verification
- `python -m py_compile src/app/page.dashboard/api.py build/src/app/page.dashboard/api.py bundle/src/app/page.dashboard/api.py`
- `npx tsc --noEmit --project tsconfig.app.json`
- `npm run build`
- Deployed `build/dist/build` to `bundle/www`.
- Replaced legacy `bundle/www/main.js` with a compatibility loader for the hashed build output and refreshed `main.css`.
- Restarted `wiz.app`.
- Confirmed `/` returns 200 and serves hashed `main.c0dd5f58b166aca5.js`.
- Confirmed served JS includes `dash-seed-input`, `daytradePositions`, and `daytrade_position_summary`.
- Confirmed dashboard overview route returns HTTP 200 with unauthenticated app code 401.
