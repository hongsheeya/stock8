# Dashboard API 503 hardening

- Stopped dashboard polling from calling `run_due_automation` every refresh.
  - Browser now calls it only after 17:40 KST on weekdays.
  - Successful non-waiting responses are stored in localStorage for the KST date.
  - Failed attempts are retried no more than once every 5 minutes.
- Added throttled console error logging for dashboard overview, profit summary, due automation, and trade preview loads.
- Converted `run_due_automation` to build a payload first, then respond once.
  - Internal failures now return a degraded HTTP 200 payload instead of bubbling into a framework 503.
- Added a degraded fallback for `trade_preview` when its builder/singleflight path raises.
- Rebuilt the frontend bundle and copied it into `bundle/www`.
- Restarted the WIZ app through `/usr/local/bin/wiz.app`.

Verification:

- `python -m py_compile src/app/page.dashboard/api.py build/src/app/page.dashboard/api.py`
- Local unauthenticated dashboard API endpoints return HTTP 200 with app-level 401:
  - `overview`
  - `trade_preview`
  - `run_due_automation`
- Production unauthenticated dashboard API endpoints return HTTP 200 with app-level 401 for the same routes.
- Local and production `main.js` include the new due-automation guard and admin preview storage key.

Known limitation:

- The authenticated live-account KIS path could not be fully reproduced without the browser login session cookie.
