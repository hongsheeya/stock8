# ADMIN GATING (restricting a new /coin page and its /wiz/api/page.coin/* endpoints to admins, using the same approach as 단타)

Day trading is limited to admins by four separate layers. Only the server-side layers actually block anything.

(1) Controller layer. WIZ instantiates the controller named in app.json before it dispatches an API function. The dispatch path is season/data/plugin/workspace/filter.py:3-15, which calls model/app.py:25-28 `wiz.controller(ctrl)()`, then looks the function up with `function in fn`.
- src/controller/user.py:7-8 returns 401 when there is no session.
- src/controller/user.py:10-15 is the PAPER subscription gate (403).
- src/controller/user.py:17-21 has a `/daytrade` path check. It never fires. SPA page URLs are served as index.html by season/lib/binding/handler/service.py:7-19 with no controller, and API calls have path `/wiz/api/page.daytrade/...`, which that check does not match.
- src/controller/admin.py:3-8 checks `wiz.session.get('role') != 'admin'` and returns 401. page.members and page.simulation use it.

(2) API layer.
- page.daytrade/api.py has `_is_admin_user` (96-99), `_session_user` (102-110), `_daytrade_access_payload` (121-135), `_require_daytrade_access` (138-149) and `access_status` (152-153).
- Guards are applied by `_guard_daytrade_api` plus an explicit allowlist loop (1827-1872).
- Admin-only helpers check inline: `if not _is_admin_user(_session_user()): wiz.response.status(403, ...)` at 1878-1879 and 1903-1904.
- page.daytrade.us/api.py repeats this at 248-305 and 1115-1142.

(3) Model / order layer.
- struct.py:647-657 `_current_user_is_admin` reads the DB role, with a hardcoded email fallback.
- struct.py:1392-1400 `_daytrade_feature_enabled` checks admin first.
- order_policy.py:52-57 `daytrade_allowed`, re-checked in update (135-136) and assert_order (171-172).
- LIVE workers run under the owner's session (struct.py:1042-1046), re-check admin on every tick (1060), and skip non-admin owners (1114-1116).

(4) Client layer.
- component.nav.trading/api.py:78-106 `daytrade_access_status` fails closed. It uses the base controller, so it answers 200 with `is_admin` false when nobody is logged in.
- view.ts:17-25 sets fail-closed defaults (`hard_locked: true`).
- view.ts:289-305 defines isRealAdmin (session role/email), effectiveAdminMode (`&& !adminPreviewUserMode`) and canShowDaytradeNav.
- view.ts:307-325 is loadDaytradeAccess.
- view.pug:23-28 shows the nav link only when `*ngIf="canShowDaytradeNav"`.
- Admin preview mode (`localStorage 'admin_preview_user_mode'` plus the `admin-preview-changed` event) only changes the view. It is not a security check.
- page.daytrade/view.ts:100-162 does not redirect non-admins. It only shows `data.message` from a non-200 bootstrap.

Plan for /coin:
- Add a gate in user.py on the API prefix `/wiz/api/page.coin/`, not on `/coin`. Alternatively use controller "admin", but that returns a 401 and does not apply the email fallback.
- Add a module-level `_require_coin_access()` and call it first in every public function, outside any try block, or deny by default with a wrap-all loop.
- Return 403 `{message}` responses. WIZ sends these as HTTP 200 with `{code:403}` in the JSON body.
- Mutating calls must be POST and same-origin.
- Coin runs on LIVE only.
- Add a nav `coin_access_status` and a `canShowCoinNav` that needs both server `is_admin===true` and `effectiveAdminMode`.
- On page init, call `access_status` before anything else; on 401/403 or `is_admin!==true`, show a denied state or redirect to /dashboard, and start no polling.
- Add a page-meta entry `/^\/coin\/?$/` → '코인' with `trail: [HOME]`. It gets noindex by default, and robots.txt already disallows everything except /access.

- **C:\dev\stock8\src\controller\user.py** 7-8, 10-15, 17-21: Base user gate. 7-8 returns 401 when there is no session. 10-15 is the PAPER subscription gate (403 unless the path starts with /settings, /wiz/api/page.settings/ or /wiz/api/component.nav.trading/). 17-21 checks `request.path == '/daytrade' or startswith('/daytrade/')` and calls `_current_user_is_admin`, then returns 403 '단타는 관리자 전용 기능입니다…'. That check is dead code: it never matches an SPA page load or a /wiz/api/page.daytrade/* call.
  -> After line 21, add a check on the API prefix. The controller runs before function lookup, so this covers every module-level name in page.coin/api.py:
```python
if request.path.startswith('/wiz/api/page.coin/'):
    trading = wiz.model('struct').trading
    if not trading._current_user_is_admin(wiz.session.get('id')):
        wiz.response.status(403, message='코인은 관리자 전용 기능입니다.')
```
A check on '/coin' alone would not block anything. A cheaper option is to read `wiz.session.get('role')/('email')` here (refreshed by /auth/check) and leave the DB-authoritative check to api.py. On PAPER the subscription gate at 10-15 fires first.
- **C:\dev\stock8\src\controller\admin.py** 1-8: Alternative controller: `class Controller(wiz.controller("user"))`, then `if wiz.session.get("role") != 'admin': wiz.response.status(401)`. Used by page.members/app.json and page.simulation/app.json, which rely on it alone with no in-function check.
  -> Option B: set `"controller": "admin"` in page.coin/app.json. Downsides: it returns 401 with empty data, not 403 with a message. It checks only the session role, with no 'gigukbyun@gmail.com' fallback; the operator is already role=admin because page.access/api.py:71-73 makes the first real user admin. The page must treat 401 as access denied.
- **C:\dev\stock8\.venv\Lib\site-packages\season\data\plugin\workspace\filter.py** 3-15: WIZ API dispatch for /wiz/api/<app_id>/<function>. It calls App.api(app_id) (model/app.py:13-41, which instantiates the app.json controller at lines 25-28 before anything else), then `if function in fn` calls `season.util.compiler(fn[function]).call(wiz=wiz, segment=segment)`. util/compiler.py:21-38 passes None for every parameter except wiz and segment. App.api reads api.py from bundle/src/app/<id>.
  -> Any module-level callable in page.coin/api.py, including `_helpers`, is an HTTP endpoint that receives None arguments. Keep side-effecting logic in the model, or give helpers required arguments. Because the controller gate runs before this lookup, it is the only layer that covers names you forgot.
- **C:\dev\stock8\.venv\Lib\site-packages\season\lib\core\struct\response.py** 183-199, 202-220: `wiz.response.status(code, **data)` serializes `{code, data}` and raises ResponseException. exception.py:1 shows ResponseException subclasses Exception. The HTTP status is 200 unless status_code is set, so 403 appears only in the JSON `code` field.
  -> Call guards outside any `try/except Exception`, otherwise the 403 is swallowed. Clients must check `code === 403 || code === 401`. src/angular/wiz.ts:80-107 `wiz.call` never rejects.
- **C:\dev\stock8\src\app\page.daytrade\api.py** 36-39, 44-64, 96-99, 102-110, 121-135, 138-149, 152-153, 1827-1872, 1875-1879, 1899-1904: Module-level env constants (_TRADING_MODE, _DAYTRADE_HARD_LOCKED, _PAPER_DAYTRADE_FULL_ACCESS, _DAYTRADE_LOCK_MESSAGE) and the lazy _get_struct. _is_admin_user(user) checks role=='admin' or the hardcoded email. _session_user() returns 401 with no session id and 404 when the user is missing, reading the DB with `_get_struct().user.get(id=user_id)`. _daytrade_access_payload builds is_admin, feature_enabled, authorized, confirmed, access_enabled, hard_locked and message. _require_daytrade_access sends ordered 403s (hard lock → feature off → not authorized → not confirmed). access_status is unguarded and returns 200. `_guard_daytrade_api(name)` replaces a global with `_wrapped`, which calls `_require_daytrade_access()` first, and is applied over an explicit allowlist. kis_call_stats and ks_minute_backfill use the inline admin check instead.
  -> Copy into page.coin/api.py: _get_struct, _is_admin_user, _session_user, then
```python
_TRADING_MODE = str(_os.environ.get('TRADING_MODE','PAPER') or 'PAPER').strip().upper()
_COIN_HARD_LOCKED = str(_os.environ.get('STOCK8_COIN_HARD_LOCK','false')).lower() in ('1','true','yes','on')
def _coin_access_payload():
    user = _session_user(); is_admin = _is_admin_user(user)
    return {'is_admin': is_admin, 'coin_hard_locked': _COIN_HARD_LOCKED, 'coin_runtime_enabled': _TRADING_MODE == 'LIVE',
            'coin_access_enabled': is_admin and not _COIN_HARD_LOCKED}
def _require_coin_access(mutating=False):
    p = _coin_access_payload()
    if p['coin_hard_locked']: wiz.response.status(403, message='코인 기능이 봉인되어 있습니다.', **p)
    if not p['is_admin']: wiz.response.status(403, message='코인은 관리자 전용 기능입니다.', **p)
    if mutating and not p['coin_runtime_enabled']: wiz.response.status(403, message='코인 자동매매는 실투자 서버에서만 실행됩니다.', **p)
    return p
```
Prefer deny-by-default to an allowlist. Either call `_require_coin_access()` as the first line of every public def, or wrap every function defined in this file: `for n,f in list(globals().items()): if inspect.isfunction(f) and not n.startswith('_') and n != 'access_status' and f.__code__.co_filename == __file__: globals()[n] = wrap(f)`.
- **C:\dev\stock8\src\app\page.daytrade.us\api.py** 37-39, 248-251, 254-262, 273-287, 290-301, 304-305, 877-880, 1115-1142: The same gating is duplicated for US. Existing gap: us_momentum_candidates (877) is missing from the guard allowlist (1127-1141), so any logged-in user can call it, and it triggers refresh_us_dynamic_candidate_universe.
  -> This is evidence that allowlist guard loops drift. For coin, use the controller gate plus deny-by-default, and add an AST test asserting every public def is guarded.
- **C:\dev\stock8\src\portal\trading\model\struct.py** 25-36, 139-140, 640-657, 712-716, 724-738, 763-781, 1042-1086, 1114-1116, 1392-1400, 1412-1425: DAYTRADE_HARD_LOCKED, LOCK_MESSAGE and ENABLE_KEYS are module consts (25-36). `_current_user_id` reads the session; `_current_user_is_admin(user_id=None)` returns False for an empty uid, otherwise `orm.use('user').get(id=uid)` and role=='admin' or the email fallback (647-657). get_config falls back to the legacy global value for admins only (712-716). set_config forces ENABLE_KEYS to 'false' under the lock (729-730), and for an admin writes both `user:{uid}:key` and the global key (733-736). The daytrade_hard_locked property and _seal_daytrade_runtime are at 763-781. LIVE account_job runs in `test_request_context('/')` with `flask.session['id']=owner` (1042-1046) and re-checks `order_policy.daytrade_allowed()` on every loop (1060). Dispatch skips non-admin owners for daytrade jobs (1114-1116). `_daytrade_feature_enabled` requires uid and admin before anything else (1392-1400).
  -> Add module consts `COIN_HARD_LOCKED` and `COIN_ENABLE_KEYS`, plus a `coin_hard_locked` property like 763-765 so every file reads one source. Force coin enable keys to 'false' in set_config like 729-730. Model gate: `def _coin_feature_enabled(self): uid=self._current_user_id(); return bool(uid and self._current_user_is_admin(uid)) and not COIN_HARD_LOCKED and TRADING_MODE=='LIVE'`. Run the coin worker the way account_job does: under the admin owner's session, re-checking `_current_user_is_admin(owner)` on every tick, and only when TRADING_MODE=='LIVE'. Keep its registry in `sys.__dict__`.
- **C:\dev\stock8\src\portal\trading\model\order_policy.py** 17, 52-57, 126-129, 135-136, 171-172: Order-boundary admin check: `daytrade_allowed()` = uid and `_current_user_is_admin(uid)`. status() strips daytrade lanes for non-admins. update() and assert_order() raise '단타는 관리자 전용 기능입니다' for daytrade lanes. LANES = ('infinite_buy','daytrade_ks','daytrade_us').
  -> Before every UpbitApi.buy_market_krw / sell_market / cancel_order call, re-check admin and the LIVE runtime in the same way (e.g. `coin_allowed()`). Do not trust the gate run at request time for background orders.
- **C:\dev\stock8\src\app\component.nav.trading\api.py** 7-10, 13-33, 53-56, 59-67, 78-106, 107-108: Nav API (app.json controller 'base', so no login gate). `_session_user()` returns None instead of 401. `daytrade_access_status()` returns 200 with everything false when logged out; otherwise it returns is_admin, daytrade_feature_enabled, daytrade_user_authorized/confirmed, daytrade_access_enabled, daytrade_hard_locked and message. `account_context()` returns the mode (LIVE/PAPER).
  -> Add `def coin_access_status():` copying 78-106. Logged out: `logged_in=False, is_admin=False, coin_access_enabled=False, coin_hard_locked=_COIN_HARD_LOCKED`. Logged in: `is_admin=_is_admin_user(user)`, `coin_runtime_enabled=_TRADING_MODE=='LIVE'`, `coin_access_enabled=is_admin and not _COIN_HARD_LOCKED`. Define `_COIN_HARD_LOCKED` as a module const next to line 8. You could instead add these fields to daytrade_access_status to save a request.
- **C:\dev\stock8\src\app\component.nav.trading\view.ts** 17-25, 35-62, 281-305, 307-325, 335-344, 353-362, 392-399, 452-461: Fail-closed `daytradeAccess` defaults (hard_locked:true). ngOnInit calls refreshAdminPreviewMode() and then `await this.loadDaytradeAccess(false)` (46-47). isRealAdmin uses session role/email (289-294). effectiveAdminMode = isRealAdmin && !adminPreviewUserMode (296-298). canShowDaytradeNav returns false on hard lock or feature off, otherwise effectiveAdminMode (300-305). loadDaytradeAccess calls `wiz.call("daytrade_access_status")` and resets to locked defaults on exception (307-325). toggleAdminPreviewMode writes localStorage and dispatches 'admin-preview-changed' (335-344). HostListeners for admin-preview-changed and daytrade-access-changed are at 353-362. isActive has a /daytrade prefix special case (392-399). isMarketOpen is path-based (452-461).
  -> Add `public coinAccess: any = { is_admin: false, coin_access_enabled: false, coin_hard_locked: true };` and `loadCoinAccess()` copying 307-325 with `wiz.call('coin_access_status')`. Call it after line 47. Getter:
```ts
public get canShowCoinNav(): boolean {
    if (this.coinAccess?.coin_hard_locked === true) return false;
    if (this.coinAccess?.is_admin !== true) return false; // server/DB authoritative
    return this.effectiveAdminMode;                      // session + preview mode
}
```
Optionally also require `this.accountMode === 'LIVE'`. The default isActive branch already handles '/coin'. For 24/7 crypto, optionally add `if (path.indexOf('/coin') === 0) return true;` in isMarketOpen. Never write the literal 'export class Component' in comments.
- **C:\dev\stock8\src\app\component.nav.trading\view.pug** 23-28, 29-33, 41-46: Daytrade link: `a(*ngIf="canShowDaytradeNav", routerLink="/daytrade", [class]="navClass('/daytrade')")` with svg and `span 단타`. Simulation link uses `*ngIf="effectiveAdminMode"`. The admin preview toggle button shows only `*ngIf="isRealAdmin"`.
  -> Insert after line 28: `a(*ngIf="canShowCoinNav", routerLink="/coin", [class]="navClass('/coin')")`, then an svg, then `span 코인`. Edit view.pug. The sibling view.html is stale (last committed Jun 29), and the WIZ builder (season/data/plugin/workspace/model/builder.py:321-331, 368-372) compiles pug over it.
- **C:\dev\stock8\src\app\page.daytrade\view.ts** 100-113, 126-132, 134-162: Page init: `service.init`, then `service.auth.allow('/access')` (login only). There is no admin or preview-mode check. bootstrap() races against a 4s timeout. On non-200 it sets `errorMessage = data?.message`. If the late response is a 403, it is silently ignored because line 149 only handles code 200.
  -> For page.coin/view.ts ngOnInit:
```ts
await this.service.init(this);
await this.service.auth.allow('/access');
const { code, data } = await wiz.call('access_status');
const preview = (() => { try { return localStorage.getItem('admin_preview_user_mode') === 'true'; } catch { return false; } })();
if (code !== 200 || data?.is_admin !== true || preview) {
    this.accessDenied = true;
    this.errorMessage = data?.message || '코인은 관리자 전용 기능입니다.';
    await this.service.render(); return; // or location.href = '/dashboard'
}
```
Start polling only after this passes. Stop polling on any later 401/403. Do not put the access check inside a timeout race. `service.auth.allow.role('admin','/dashboard')` (auth.ts:107-114) also works as a fast client redirect, but it reads the session only.
- **C:\dev\stock8\src\app\page.daytrade\app.json** 1-12: Page registration: id page.daytrade, mode page, viewuri '/daytrade', controller 'user', layout 'layout.trading', template 'wiz-page-daytrade()'.
  -> Create src/app/page.coin/app.json: `{"id":"page.coin","mode":"page","title":"/coin","namespace":"coin","category":"coin","viewuri":"/coin","preview":"","controller":"user","layout":"layout.trading","template":"wiz-page-coin()"}`. Use 'user' with the new user.py prefix check, or 'admin'. layout.trading is required for theming and breadcrumbs.
- **C:\dev\stock8\src\portal\trading\libs\page-meta.ts** 15, 17-33, 35-41: PAGES regex table → {title, trail, index}. Consumed by layout.trading/view.ts:16-20 (breadcrumb crumbs and crumbCurrent) and angular/app/app.component.ts:31-35 (applyPageMeta: document.title '<title> | ∞stock', robots noindex unless index:true, canonical).
  -> Add `{ pattern: /^\/coin\/?$/, meta: { title: '코인', trail: [HOME] } },`, e.g. after line 22. Leave out `index`, so it stays noindex. robots.txt (route/seo.robots/controller.py) already disallows everything except /access, and the sitemap lists only /access.
- **C:\dev\stock8\src\app\page.settings\view.ts** 81, 169-171, 173-179, 271: Server-authoritative admin flag: `this.isAdmin = data.is_admin === true` from the API (271), and `effectiveAdminMode() = this.isAdmin && !this.adminPreviewUserMode`.
  -> Use this pattern on the coin page and in the nav: decide admin status from the server's is_admin, not from session role/email strings.
- **C:\dev\stock8\src\app\component.trading.controls\api.py** 3-7, 32-37, 42-43: Mutation hardening: `_trading()` returns 401 with no session. save() returns 405 unless the method is POST, and 403 when the Origin header differs from `request.host_url.rstrip('/')`. It returns 403 '단타는 관리자 전용 기능입니다.' when `not trading.order_policy.daytrade_allowed()`. page.settings/api.py:978 has a one-line version.
  -> Apply the POST and same-origin check to every coin endpoint that places, cancels or toggles anything (in addition to `_require_coin_access(mutating=True)`).
- **C:\dev\stock8\src\app\page.dashboard\view.ts** 335-349, 351-357, 367-373, 401-407: Client admin preview handling: isRealAdmin, showAdminControls = isRealAdmin && !adminPreviewUserMode, showDaytradeQuickLink, and add/remove of the window 'admin-preview-changed' listener. page.history/view.ts:10-15 (showDaytrade) and component.trading.controls/view.ts:16-18 follow the same pattern.
  -> If you add a coin quick link, coin trades in 거래이력, or a coin lock switch, gate them with showAdminControls-style getters. Server-side filtering must still enforce admin (history api uses `db._is_admin(uid)` at page.history/api.py:785).
- **C:\dev\stock8\tests\test_admin_daytrade_access.py** 1-33: AST test: extracts `_daytrade_access_payload` from each api.py, execs it with a stub scope over PAPER/LIVE × admin/non-admin, and asserts access_enabled == admin. It also checks `_set_config` ignores daytrade_ keys for regular users.
  -> Add tests/test_admin_coin_access.py with the same approach: (a) `_coin_access_payload` / `_require_coin_access` deny non-admins; (b) every public def in src/app/page.coin/api.py is guarded (AST walk); (c) src/controller/user.py contains '/wiz/api/page.coin/'; (d) page-meta.ts contains the /coin entry.

## patterns
- user.py prefix gate (runs before function dispatch):
```python
if request.path.startswith('/wiz/api/page.coin/'):
    trading = wiz.model('struct').trading
    if not trading._current_user_is_admin(wiz.session.get('id')):
        wiz.response.status(403, message='코인은 관리자 전용 기능입니다.')
```
- API helpers from page.daytrade/api.py:96-110:
```python
def _is_admin_user(user):
    role = str((user or {}).get('role', '') or '').lower()
    email = str((user or {}).get('email', '') or '').strip().lower()
    return role == 'admin' or email == 'gigukbyun@gmail.com'

def _session_user():
    session = wiz.model('portal/season/session').use()
    user_id = session.get('id')
    if not user_id:
        wiz.response.status(401, message='로그인이 필요합니다.')
    user = _get_struct().user.get(id=user_id)
    if not user:
        wiz.response.status(404, message='사용자 정보를 찾을 수 없습니다.')
    return user
```
- Inline admin check from page.daytrade/api.py:1878-1879: `if not _is_admin_user(_session_user()): wiz.response.status(403, message='관리자만 볼 수 있습니다.')`
- Guard wrapper from page.daytrade/api.py:1827-1836. Copy the wrapper, but drive it from a deny-by-default loop instead of a name list:
```python
def _guard(name):
    original = globals().get(name)
    if not callable(original): return
    def _wrapped(*args, **kwargs):
        _require_coin_access()
        return original(*args, **kwargs)
    globals()[name] = _wrapped
```
- Mutation hardening from component.trading.controls/api.py:33-37:
```python
if request.method != 'POST': wiz.response.status(405, message='POST 요청만 허용됩니다.')
origin = request.headers.get('Origin')
if origin and origin != request.host_url.rstrip('/'): wiz.response.status(403, message='다른 출처에서 변경할 수 없습니다.')
```
- Fail-closed nav loader from nav view.ts:307-325:
```ts
private async loadCoinAccess(render = true) {
  try { const { code, data } = await wiz.call('coin_access_status'); if (code === 200) this.coinAccess = data || this.coinAccess; }
  catch (e) { this.coinAccess = { is_admin: false, coin_access_enabled: false, coin_hard_locked: true }; }
  if (render) await this.service.render();
}
```
- Nav link (view.pug, after line 28): `a(*ngIf="canShowCoinNav", routerLink="/coin", [class]="navClass('/coin')")`, then an svg icon, then `span 코인`.
- Page-meta entry: `{ pattern: /^\/coin\/?$/, meta: { title: '코인', trail: [HOME] } },`
- Background worker identity from struct.py:1042-1046 and 1060: `with wiz.server.app.flask.test_request_context('/'): flask.session['id'] = owner`, then on every tick `if not trading._current_user_is_admin(owner) or TRADING_MODE != 'LIVE': state['status']='off'; continue`.
- Hard-lock forcing from struct.py:729-730: `if COIN_HARD_LOCKED and key in COIN_ENABLE_KEYS: value = 'false'`.

## pitfalls
- The `/daytrade` check in src/controller/user.py:17-21 never runs. SPA URLs are served as index.html by season ServiceHandler.route with no controller, and API calls have path /wiz/api/page.daytrade/*. A '/coin' path check would block nothing. Gate the '/wiz/api/page.coin/' prefix instead.
- Guard allowlists drift. page.daytrade.us/api.py us_momentum_candidates (line 877) is not in the guard list at 1127-1141, so any logged-in user can call it. ping and access_status are also unguarded by design. Use deny-by-default plus the controller gate.
- Every module-level callable in api.py is HTTP-reachable, including `_underscore` helpers. season compiler.call passes None for every parameter other than wiz and segment. Never leave side-effecting module-level helpers in page.coin/api.py whose arguments all have defaults.
- `wiz.response.status(403, ...)` works by raising ResponseException, which subclasses Exception. A guard called inside `try: ... except Exception` is swallowed and turned into the except branch's 400 or 200. Call guards as the first statement, outside any try.
- The 403 is sent as HTTP 200 with `{code:403, data:{message,...}}`, and `wiz.call` never rejects. Client code must branch on `code`. The admin controller returns code 401 with empty data, so handle both.
- controller/admin.py checks only the session 'role'. It has no 'gigukbyun@gmail.com' fallback and returns 401. The session role is refreshed from the DB on /auth/check (portal/season/route/auth/controller.py:6-29), but the API-level check should still re-read the user row with `_get_struct().user.get(id=uid)`.
- Admin preview mode (localStorage 'admin_preview_user_mode') only changes the view. Server APIs still allow the admin. Do not treat it as a security control; only mirror it in the nav and page UI.
- Nav isRealAdmin is based on session role/email (view.ts:289-294). For the coin nav, also require the server's `is_admin === true` from coin_access_status. Keep fail-closed defaults (hard_locked:true) and reset them in the catch, like loadDaytradeAccess.
- `_current_user_is_admin()` with no session returns False (struct.py:649-651), and some gates treat a missing uid as allowed (daytrade_engine.py:380-381). A sessionless coin worker would either never trade or bypass checks. Run it inside `test_request_context` with `flask.session['id']=owner` (struct.py:1042-1046) and re-check admin on every tick.
- The ORM silently drops unknown filter kwargs, so `user.get(user_id=uid)` returns the first user row, which is likely the admin, and makes everyone admin. Always use `get(id=uid)` and check that uid is non-empty first, as `_current_user_is_admin` and `_session_user` do.
- The hard-lock env var is read separately as a module constant in at least six files: struct.py:25, page.daytrade/api.py:37, page.daytrade.us/api.py:37, component.nav.trading/api.py:8, page.settings/api.py:34 and scheduler controller.py:22. A coin kill switch must be read in every gating file, or exposed once through a struct property (like `daytrade_hard_locked` at 763-765). Use module-level consts, not class statics.
- The hardcoded admin email 'gigukbyun@gmail.com' is duplicated: struct.py:655, page.daytrade/api.py:99, page.daytrade.us/api.py:251, nav api.py:56, page.settings/api.py:298, nav view.ts:293, dashboard view.ts:338, history view.ts:13. Copy it exactly, or call `trading._current_user_is_admin(uid)` so there is one definition.
- page.daytrade/view.ts bootstrap drops a late 403 after its 4s timeout race (only code 200 is handled at line 149). On the coin page, run the access check before any race or polling.
- On PAPER, the user controller's subscription gate (user.py:10-15) fires before any coin check. Coin must run only on LIVE (port 3001), so return 403 from mutating coin endpoints when TRADING_MODE != 'LIVE', and consider hiding the nav item unless accountMode === 'LIVE'.
- Module-level state in api.py resets on every request, because the compiled module is re-executed per call. wiz.model re-exec also resets class caches. Keep the worker registry and locks in `sys.__dict__.setdefault(...)`, as struct.py:116 does.
- For an admin, set_config writes both `user:{uid}:key` and the global key (struct.py:733-736). If coin keys (e.g. Upbit secrets) are added to USER_SCOPED_CONFIG_KEYS, an admin's save also creates a global copy, and get_config's legacy fallback (712-716) serves it only to admins.
- The nav has both view.pug and a stale view.html. Edit view.pug. Write only view.pug, view.ts and view.scss for the new page, and never put the literal 'export class Component' text in comments.
- App.api reads api.py from bundle/src/app/<id> (season workspace model/app.py:14), so the new page and its API exist on the server only after a rebuild or deploy into the bundle.

# 설정 및 키 저장 (page.settings + struct.py config 헬퍼 + secret_box/trading_config 암호화)

코드를 직접 읽어 확인했고 파일은 하나도 바꾸지 않았습니다.

[저장 경로] 화면의 저장 요청은 다음 순서로 내려갑니다.
- page.settings/api.py의 `_set_config`(349-375)가 `trading.set_config`(struct.py 724-761)를 부릅니다.
- `set_config`는 `_write_config_value`(struct.py 688-699)를 거쳐 season ORM의 insert/update(src/portal/season/model/orm.py 284-333)로 갑니다. insert는 `db.create(**item)`, update는 `db.update(**item)`를 호출합니다.
- 이 호출은 `trading_config.Model.create/update`의 `_seal`(db/trading_config.py 21-46)로 이어집니다. `_seal`은 같은 dict 안에서 `is_secret`이 truthy일 때만 `secret_box.encrypt`를 거쳐 값을 "enc:v1:<Fernet>"로 저장합니다.
- 읽을 때는 `SecretAwareTextField.python_value`(trading_config.py 14-18)가 자동으로 복호화합니다. 그래서 `trading.db("trading_config").get(...)`도 평문을 돌려줍니다. 키 파일을 잃어버리면 `decrypt`가 ""를 돌려주고(secret_box.py 68-77), 이 경우는 '미등록'으로 다루면 됩니다.
- 이전 평문 secret 행은 `Struct._encrypt_plain_secrets`(struct.py 612-627)가 프로세스당 한 번 다시 저장하면서 암호화합니다.

[사용자별 키 user:<uid>:key]
- `USER_SCOPED_CONFIG_KEYS`(struct.py 38-102)에 들어 있는 키는 `_user_config_key`(662-663)가 `f"user:{uid}:{key}"`로 바꿔 저장합니다.
- `get_config`(701-722) 동작:
  - 세션 uid가 있으면 scoped 행만 읽습니다.
  - scoped 행이 없으면 관리자만 전역(legacy) 값을 scoped로 복사해서 돌려줍니다. 이때 is_secret은 이름으로 추정합니다(`_secret`, `token`, `key`, `account`).
  - 일반 사용자는 default를 받습니다.
  - 세션이 없으면(백그라운드 스레드) 전역 키를 읽습니다.
- `set_config`(724-761)는 관리자일 때 scoped 키와 전역 키에 모두 씁니다(735-736). 그 뒤 kis_/toss_ 키가 바뀌면 `_kis_api_obj`/`_toss_api_obj`를 무효화합니다(740-747).
- `_lookup_config_value`(665-686)는 'user:', 'kis_', 'toss_'로 시작하는 키를 클래스 캐시 `Struct._cfg`를 건너뛰고 DB에서 바로 읽습니다. 나머지 키는 `Struct._cfg` 캐시를 씁니다.
- KIS 키(`kis_live_*`/`kis_paper_*`)와 Toss 키는 `_persist_api_settings`(api.py 214-269)가 is_secret=True로 저장합니다(240-246). 계정 정보가 바뀌면 토큰을 비웁니다(258-264).

[마스킹 — 요청서 전제와 다름]
- KIS/Toss 비밀값은 실제로 마스킹되지 않습니다.
  - `load_settings`가 app_key, app_secret, toss_client_id/secret을 평문 그대로 브라우저에 보냅니다(api.py 445-449, 518-525).
  - view.ts 216-221이 그 값을 input에 채웁니다.
  - view.pug 54·71의 `[type]="showSecret ? 'text' : 'password'"`와 '보기' 버튼은 화면에서만 가립니다.
- 저장도 같은 구조입니다. `_api_settings_payload_from_request`(158-183)는 `_API_SETTING_QUERY_KEYS`(131-140) 중 하나라도 요청에 있으면 모든 값을 화면 값으로 씁니다. 그래서 빈칸으로 보내면 저장값이 지워지고, 브라우저는 매번 비밀값 전체를 다시 보내야 합니다.
- 코인 기능은 이 방식을 따라 하면 안 됩니다. 대신 다음 네 가지를 따라 하면 됩니다.
  - page.infinitebuy/api.py `_public_bridge_config`(146-163): configured/has_* 불리언과 마스킹된 이메일만 돌려줍니다.
  - page.infinitebuy/api.py `save_fire_gate_bridge`(913-946): 922-925줄에서 빈칸이면 기존 값을 유지합니다.
  - struct/kis_api.py `get_settings`(878-888): `value[:4] + "****"`로 마스킹합니다.
  - page.live/api.py `status`(6-18)와 view.pug 24: `credentials_configured`에 따라 '보관됨'/'미등록'만 표시합니다.

[연결 테스트]
- 화면에서 실제로 쓰는 버튼은 '저장 후 연결 확인'(view.pug 79)입니다.
- 흐름은 `saveApiSettings`(view.ts 453-500) → `save_api_settings`(api.py 577-590)입니다.
- `save_api_settings`는 payload를 만들고, 검증하고, 저장한 다음 `_selected_broker_api(trading)`(126-128)로 연결을 확인합니다. LIVE는 `test_connection()`(kis_api.py 798-810: 토큰 발급과 잔고 조회), PAPER는 `validate_paper_readiness()`를 씁니다. 결과는 `_api_settings_response`(272-289)가 돌려줍니다.
- `test_connection`(api.py 606-630)과 `testApiConnection`(view.ts 578-616)은 있지만 템플릿 어디에도 연결되어 있지 않습니다.

[탭 구조]
- 탭 버튼은 view.pug 20-25의 `nav.dx-tabs.st-tabs`에 있습니다. 선택 상태 스타일은 공용 styles.scss 305-314의 `.dx-tabs > .is-active`입니다.
- 탭 값은 다음과 같습니다.
  - 'api': 증권사 연결(30-90)
  - 'watchlist': 관심 종목(303-441)
  - 'strategy': 매매전략(446-685)
  - 'risk': 단타(120-298), `showDaytradeSettingsTab()`일 때만 보입니다.
  - 'account': 계정(95-114)
- 관련 메서드는 `tabClass`(view.ts 199-201), `switchTab`(159-162), `ensureVisibleTab`(185-192)입니다.
- 관리자 판정은 `showDaytradeSettingsTab`(164-167)이 `!daytradeHardLocked && effectiveAdminMode()`로 하고, `effectiveAdminMode`(169-171)는 `isAdmin && !adminPreviewUserMode`입니다.
- 서버 쪽 관리자 판정은 `_is_admin_user`(api.py 296-299: role이 admin이거나 이메일이 gigukbyun@gmail.com)이고, `load_settings`가 `is_admin`(499, 561)으로 내려줍니다.
- st-* 클래스는 view.scss 512-744에 있습니다: st-card, st-card-head, st-status(.is-ok/.is-error), st-form, st-row(160px 그리드), st-field, st-field-inline, st-actions, st-btn(.is-primary), st-link, st-result(.is-error), st-diag, st-note. 640px 이하 반응형 규칙은 692-696입니다.
- 새 디자인(st-*)은 'api' 탭만 씁니다. 단타·관심·전략 탭은 아직 예전 glass-card/tailwind 마크업입니다.

[코인 키 저장 권장안]
- 관리자 전용 탭 'coin'을 만들거나 코인 페이지에 같은 폼을 둡니다.
- 엔드포인트는 따로 둡니다: `save_coin_keys`, `test_coin_connection`, `clear_coin_keys`. 기존 `save_api_settings`/`test_connection`은 KIS/Toss 키를 덮어쓰므로 재사용하면 안 됩니다.
- 모든 엔드포인트 첫 줄에서 `_require_coin_admin()`으로 관리자가 아니면 403을 냅니다. PAPER 서버에서는 저장을 거부합니다. LIVE와 PAPER는 DB 파일이 달라서(data/live/trading.db, data/paper/trading.db) PAPER에서 저장한 키는 LIVE 워커가 볼 수 없습니다.
- 키는 `upbit_access_key`, `upbit_secret_key`를 USER_SCOPED_CONFIG_KEYS에 추가하고, 저장할 때마다 is_secret=True로 `_set_config`를 부릅니다.
- 입력이 빈칸이면 기존 키를 유지합니다. 키를 바꿀 때는 두 키를 함께 받습니다.
- 저장한 뒤 행을 다시 읽어 확인합니다(component.trading.controls/api.py 62-68 패턴).
- 응답에는 configured, has_*, access_key_hint(앞 4자 + ****), updated_at만 담습니다.
- 연결 테스트는 읽기 전용인 `UpbitApi(access, secret).balances()`(GET /v1/accounts)만 호출합니다.
- 코인 워커는 LIVE 전용 `_ensure_live_policy_workers`(struct.py 1028-1134)의 `account_job`(1043-1047)처럼 `test_request_context` 안에서 `flask.session['id'] = owner`를 설정한 뒤 실행합니다. 그래야 `user:<admin uid>:upbit_*` 값을 읽습니다.

- **C:\dev\stock8\src\portal\trading\model\struct.py** 38-102: USER_SCOPED_CONFIG_KEYS: 여기 있는 키는 user:<uid>:<key>로 사용자별로 저장됩니다. KIS(kis_live_*/kis_paper_*)와 Toss(toss_*) 키가 여기에 들어 있습니다.
  -> "upbit_access_key", "upbit_secret_key"를 추가합니다. 코인 런타임 설정(예: coin_auto_enabled)도 사용자별로 둘 때만 추가합니다. 관리자가 저장하면 735-736줄 때문에 전역 키(upbit_access_key)에도 암호화된 사본이 생깁니다. 키 이름은 26자 이하로 둡니다. 'user:'(5) + uid(32) + ':'(1) + 이름이 key 칼럼 CharField(max_length=64)에 들어가야 하기 때문입니다(trading_config.py 33). SQLite가 길이를 강제하지는 않습니다.
- **C:\dev\stock8\src\portal\trading\model\struct.py** 659-686: _is_user_scoped_config_key와 _user_config_key(663: f"user:{uid}:{key}")가 있습니다. _lookup_config_value의 669줄은 'user:', 'kis_', 'toss_'로 시작하는 키를 캐시 없이 DB에서 바로 읽고, 나머지 키는 클래스 캐시 Struct._cfg를 씁니다.
  -> 669줄 튜플을 storage_key.startswith(('kis_', 'toss_', 'upbit_'))로 바꿉니다. 그러면 관리자 전역 사본도 클래스 캐시를 건너뜁니다. 이 캐시는 wiz.model 재실행 때 클래스마다 따로 생기므로 키를 바꿔도 반영이 늦을 수 있습니다.
- **C:\dev\stock8\src\portal\trading\model\struct.py** 688-699: _write_config_value: DB 행을 insert하거나 update하는데, 매번 value·description·is_secret을 함께 씁니다. 그 뒤 Struct._cfg에 평문을 캐시합니다.
  -> 수정은 필요 없습니다. 다만 upbit 키는 지울 때도 포함해 항상 is_secret=True로 써야 합니다. False로 한 번 쓰면 플래그가 내려가고 평문으로 저장됩니다.
- **C:\dev\stock8\src\portal\trading\model\struct.py** 701-761: get_config/set_config. 세션 uid로 사용자별 키를 고르고, 세션이 없으면 전역 키를 읽습니다. 관리자는 scoped와 전역 양쪽에 씁니다. 740-747줄은 kis_/toss_ 키가 바뀔 때 API 객체 캐시를 무효화합니다.
  -> _upbit_api_obj 같은 캐시를 새로 둘 때만 740-747줄에 `if key.startswith("upbit_"): self._upbit_api_obj = None`을 추가합니다. 권장은 캐시 없이 쓸 때마다 wiz.model("portal/trading/upbit_api")(access, secret)로 새로 만드는 것입니다.
- **C:\dev\stock8\src\portal\trading\model\struct.py** 940-945, 1028-1134: _ensure_background_worker는 LIVE에서 _ensure_live_policy_workers만 호출합니다. account_job(1043-1047)은 `with wiz.server.app.flask.test_request_context('/'): flask.session['id'] = owner` 안에서 Struct()를 만들어 사용자별 설정을 읽습니다. 레지스트리는 sys 속성(_stock8_live_policy_workers)에 둡니다.
  -> 코인 워커(LIVE 프로세스 하나에서만 실행)도 같은 방식으로 관리자 owner 세션을 만든 뒤 trading.get_config('upbit_access_key')를 읽습니다. 세션 없이 읽으면 관리자 전역 사본으로 넘어가는데, 이는 1029-1031줄 docstring 원칙('LIVE never runs against the legacy global/admin credential fallback')에 어긋납니다. 프로세스 단위 레지스트리는 sys.__dict__.setdefault('_stock8_coin_worker', {})로 둡니다.
- **C:\dev\stock8\src\portal\trading\model\db\trading_config.py** 14-46: SecretAwareTextField.python_value가 읽을 때 복호화합니다. _seal(21-25)은 values.get('is_secret')가 참이고 'value'가 있을 때만 암호화합니다. Model.create/update가 _seal을 거칩니다.
  -> 수정은 필요 없습니다. 테스트 하네스는 tests/test_secret_config.py 18-80을 복사해 쓰면 됩니다(인메모리 peewee에 _load(SRC/'db'/'trading_config.py', wiz)). 'user:<uid>:upbit_secret_key' 행의 raw 값이 'enc:v1:'로 시작하는지 단언합니다.
- **C:\dev\stock8\src\portal\trading\model\secret_box.py** 18-77: Fernet 키를 STOCK8_CONFIG_KEY에서 읽고, 없으면 STOCK8_CONFIG_KEY_FILE, 그것도 없으면 ~/.stock8/config.key를 씁니다. LIVE와 PAPER가 같은 키 파일을 공유하고(O_EXCL로 생성), 상태는 sys.__dict__['_stock8_secret_box']에 둡니다. 복호화에 실패하면 ''를 돌려줍니다.
  -> 수정은 필요 없습니다. _public_coin_config에서 복호화 결과가 ''이면 configured=False('미등록', 다시 입력 필요)로 표시합니다.
- **C:\dev\stock8\src\app\page.settings\api.py** 32-41, 85-94, 143-155, 296-299: 모듈 상수 _TRADING_MODE/_PAPER_MODE(32-33), _session_user()(85-94: 로그인이 없으면 401), _query_text/_query_present(143-148), _is_admin_user(296-299)가 있습니다.
  -> 코인 가드는 이 헬퍼들로 만듭니다: `def _require_coin_admin(): _,_,user=_session_user(); if not _is_admin_user(user): wiz.response.status(403, message='코인 자동매매는 관리자 전용 기능입니다.'); if _PAPER_MODE: wiz.response.status(403, message='코인 API 키는 실투자(LIVE) 서버 설정에서만 저장합니다.'); return user`
- **C:\dev\stock8\src\app\page.settings\api.py** 131-140, 158-269: _API_SETTING_QUERY_KEYS, _api_settings_payload_from_request(키가 하나라도 오면 화면 값 전체를 쓰므로 빈칸이 저장값을 지움), _validate_api_settings_payload, _persist_api_settings(KIS/Toss 키 저장과 토큰 초기화)가 있습니다.
  -> upbit 필드를 _API_SETTING_QUERY_KEYS에 넣지 않습니다. 코인 요청이 save_api_settings나 test_connection으로 가면 _persist_api_settings가 KIS/Toss 키를 빈 값으로 덮어쓰고 토큰도 비웁니다(239-264). 코인 전용 엔드포인트를 따로 둡니다.
- **C:\dev\stock8\src\app\page.settings\api.py** 337-375: _get_config/_set_config는 trading.get_config/set_config를 감쌉니다. 352줄은 관리자가 아닐 때 'daytrade_'·'us_daytrade_' 키 저장을 조용히 무시합니다. 362-375줄 fallback의 update는 is_secret을 넘기지 않아 평문으로 저장됩니다. 실제로는 setter가 항상 있어서 쓰이지 않습니다.
  -> 추가 방어로 352줄 튜플에 'upbit_', 'coin_'을 넣을 수 있습니다. 그래도 코인 엔드포인트는 조용히 무시하지 말고 _require_coin_admin()으로 명시적인 403을 내야 합니다. 저장은 항상 _set_config('upbit_secret_key', v, 'Upbit secret key (coin admin)', True)처럼 is_secret=True로 합니다.
- **C:\dev\stock8\src\app\page.settings\api.py** 437-575: load_settings: 499줄에서 is_admin을 계산하고, 511줄 except가 모든 예외를 500으로 바꿉니다. 200 응답은 514-575줄에서 try 밖에 있습니다. 518-525줄이 KIS/Toss 비밀값을 평문으로 응답합니다.
  -> try 블록 안(505줄 근처)에서 `coin = _public_coin_config() if is_admin else None`을 계산하고, 561줄 is_admin 다음에 `coin=coin`을 추가합니다. upbit 원문 값은 응답에 넣지 않습니다. 518-525줄 평문 응답 방식은 코인에 복사하지 않습니다.
- **C:\dev\stock8\src\app\page.settings\api.py** 577-630, 801-846: save_api_settings/test_connection(연결 테스트 흐름)과 save_daytrade_admin_settings(관리자 전용 엔드포인트 예: 803-805줄 403, 836-839줄 refresh_config_cache)가 있습니다.
  -> 846줄 다음, confirm_daytrade_warning(849) 앞에 _public_coin_config, _coin_probe, save_coin_keys, test_coin_connection, clear_coin_keys를 추가합니다. 응답 모양은 _api_settings_response(272-289)처럼 success, message, diagnostics[{step, success, message}]로 맞춥니다. 그러면 화면의 st-result/st-diag를 그대로 쓸 수 있습니다.
- **C:\dev\stock8\src\app\page.settings\view.pug** 20-25: 탭 nav(dx-tabs st-tabs)입니다. 각 버튼은 `(click)="switchTab('x')"`과 `[class]="tabClass('x')"`를 씁니다. 단타 탭은 `*ngIf="!isInfiniteBuyMode() && showDaytradeSettingsTab()"`로 감춥니다.
  -> 24줄(단타) 다음에 추가합니다: `button(*ngIf="!isInfiniteBuyMode() && showCoinSettingsTab()", type="button", (click)="switchTab('coin')", [class]="tabClass('coin')") 코인`
- **C:\dev\stock8\src\app\page.settings\view.pug** 30-90: 증권사 연결 탭으로, st-* 신규 디자인의 기준 예입니다(st-card > st-card-head(h2, p, st-status) > st-form > st-row(label + st-field) > st-actions > st-result > st-diag > st-note).
  -> 90줄 뒤(계정 탭 앞)에 `div(*ngIf="tab === 'coin' && showCoinSettingsTab() && accountContext")` 블록을 같은 구조로 추가합니다. 비밀 입력칸은 `type="password", autocomplete="new-password"`로 두고, 저장값으로 채우지 않습니다. placeholder에 '<hint> 저장됨 · 바꾸려면 새 키 입력'을 보여 주고, '보기' 토글은 넣지 않습니다. PAPER(isMock)이면 dx-alert is-warn과 accountContext.live_settings_url 링크를 보여 주고 버튼을 비활성화합니다.
- **C:\dev\stock8\src\app\page.settings\view.ts** 81-101, 159-201: 상태 필드(isAdmin 81, loading/testResult/testOk/apiDiagnostics 94-101), switchTab, showDaytradeSettingsTab, effectiveAdminMode, ensureVisibleTab, fallbackTab, tabClass가 있습니다.
  -> 101줄 뒤에 필드를 추가합니다: coinConfigured, coinHasSecret, coinAccessKeyHint, coinUpdatedAt, upbitAccessKeyInput='', upbitSecretKeyInput='', coinLoading, coinTestOk, coinTestResult, coinDiagnostics:any[]=[]. `public showCoinSettingsTab(): boolean { return this.effectiveAdminMode(); }`을 추가합니다. ensureVisibleTab(185-192)에는 `if (this.tab === 'coin' && !this.showCoinSettingsTab()) this.tab = this.fallbackTab();`을 추가합니다. 공용 loading을 쓰면 증권사 탭 버튼까지 잠기므로 coinLoading을 따로 둡니다.
- **C:\dev\stock8\src\app\page.settings\view.ts** 204-292, 453-500: loadSettings는 data를 필드에 매핑합니다(271: isAdmin). saveApiSettings는 wiz.call, modal.show, service.render 순서를 따르고 try/catch에서 e?.responseJSON?.message를 처리합니다.
  -> 271줄 다음에 `this.applyCoinConfig(data.coin);`을 넣습니다. applyCoinConfig는 비밀값 없이 플래그와 hint만 세팅하고 입력 두 칸을 ''로 비웁니다. saveCoinKeys와 testCoinConnection은 saveApiSettings(453-500) 구조를 그대로 복사하되 wiz.call('save_coin_keys', {upbit_access_key, upbit_secret_key})를 부르고, finally에서 입력값을 반드시 ''로 비웁니다.
- **C:\dev\stock8\src\app\page.settings\view.scss** 512-744: st-* 클래스 정의입니다(st-card 537, st-status 563-574, st-row 578-595, st-field 596-623, st-actions 625, st-btn 632-651, st-result 659-670, st-diag 672-682, st-note 684-690, 반응형 692-696, 다크 테마 primary 버튼 698). 페이지 scss는 캡슐화되어 있습니다.
  -> 설정 탭 안에서는 그대로 재사용하면 되고 새 CSS는 필요 없습니다. 코인 페이지에 폼을 따로 두면 st-* 규칙은 공유되지 않습니다(캡슐화). 공용 dx-* 클래스(src/angular/styles/styles.scss 176-211, 305-314)를 쓰거나 st-* 규칙을 그 페이지 scss로 복사합니다.
- **C:\dev\stock8\src\app\page.infinitebuy\api.py** 57-60, 131-163, 913-946: 비밀값을 저장하고 공개용 요약만 내보내는 기존 예입니다. _save_bridge_config는 is_secret=True로 저장합니다. _public_bridge_config는 configured, has_id_token, has_refresh_token, email_masked만 돌려줍니다. save_fire_gate_bridge의 922-925줄은 빈칸이면 기존 값을 유지합니다. _is_response_exception은 except에서 wiz 응답 예외를 다시 던질 때 씁니다.
  -> _public_coin_config와 save_coin_keys의 템플릿으로 그대로 따라 합니다.
- **C:\dev\stock8\src\portal\trading\model\struct\kis_api.py** 282-288, 798-810, 878-888: _get_config/_set_config는 struct.get_config/set_config로 위임합니다. test_connection(LIVE)은 토큰을 발급받고 잔고를 조회한 뒤 {success, message}를 돌려줍니다. get_settings는 `app_key[:4] + "****"`로 마스킹합니다.
  -> _coin_probe도 같은 {success, message, diagnostics} 모양으로 돌려줍니다. 마스킹 hint는 같은 [:4] + '****' 규칙을 씁니다.
- **C:\dev\stock8\src\app\page.live\api.py** 6-18: status()는 credentials_configured를 all(bool(get_config(k)))로 계산하고, view.pug 24줄이 '보관됨'/'미등록'만 표시합니다.
  -> 코인 상태 칩(st-status)도 같은 문구로 씁니다: 연결 확인에 성공하면 '연결됨', 저장만 되어 있으면 '보관됨', 저장값이 없으면 '미등록'.
- **C:\dev\stock8\src\app\component.trading.controls\api.py** 62-68: set_config 뒤에 trading.db('trading_config').get(key=trading._user_config_key(uid, key))로 다시 읽어 저장을 검증하고, 실패하면 OFF를 유지합니다.
  -> save_coin_keys에서 저장한 뒤 같은 방식으로 row를 읽고 row['is_secret'] is True인지, 값이 비어 있지 않은지 확인합니다. 값 자체는 응답에 넣지 않습니다. trading_config는 USER_SCOPED_TABLES(struct.py 103-110)에 없으므로 storage key를 직접 만들어야 합니다.
- **C:\dev\stock8\src\controller\user.py** 20-24: /daytrade 페이지 경로를 _current_user_is_admin으로 막는 게이트입니다(403). /wiz/api/page.*/ API 호출은 이 경로 검사에 걸리지 않습니다.
  -> 코인 페이지를 만들면 `request.path == '/coin' or request.path.startswith('/coin/')` 게이트를 추가합니다. 페이지 api.py의 각 함수에서도 관리자 검사를 따로 해야 합니다.
- **C:\dev\stock8\src\portal\trading\model\upbit_api.py** 56-65, 113-125, 155: UpbitApi(access_key, secret_key)와 configured 속성, 읽기 전용인 accounts()/balances()가 있습니다. Model = UpbitApi만 노출하므로 UpbitError는 wiz.model로 가져올 수 없습니다.
  -> 연결 테스트에서는 balances()만 부르고 주문 함수는 부르지 않습니다. 예외는 except Exception as e로 잡고 getattr(e,'name','')과 getattr(e,'status',0)으로 원인을 표시합니다. 키가 등록된 IP는 LIVE 서버 호스트여야 합니다.
- **C:\dev\stock8\tests** test_settings_api_payload.py 1-80; test_admin_daytrade_access.py 25-32; test_secret_config.py 18-97: page.settings/api.py를 builtins.wiz 스텁(_RequestStub, _ResponseStub가 _ResponseStatus를 raise)으로 불러오는 하네스, AST로 _set_config만 떼어 내 관리자 가드를 확인하는 테스트, 암호화 테스트가 있습니다.
  -> 다음 회귀 테스트를 추가합니다. (1) 관리자가 아니면 save_coin_keys가 403. (2) PAPER_MODE에서 403. (3) load_settings 응답과 save 응답에 저장한 비밀 문자열이 없음. (4) 빈칸으로 저장해도 기존 키가 유지됨. (5) 'user:<uid>:upbit_secret_key' raw 값이 'enc:v1:'로 시작함.

## patterns
- 공개 요약(비밀값 없음). page.settings/api.py에 추가합니다.
```python
def _public_coin_config():
    trading = _trading()
    access = str(_get_config("upbit_access_key", "") or "")
    secret = str(_get_config("upbit_secret_key", "") or "")
    row = trading.db("trading_config").get(key=trading._user_config_key(trading._current_user_id(), "upbit_access_key")) or {}
    return {
        "configured": bool(access and secret),
        "has_access_key": bool(access), "has_secret_key": bool(secret),
        "access_key_hint": (access[:4] + "****") if len(access) > 4 else ("****" if access else ""),
        "updated_at": str(row.get("updated", "") or ""),
        "live_only": True, "server_mode": _TRADING_MODE,
    }
```
- 관리자이면서 LIVE일 때만 통과하는 가드. 모든 코인 엔드포인트 첫 줄에서 부릅니다.
```python
def _require_coin_admin():
    _, _, user = _session_user()
    if not _is_admin_user(user):
        wiz.response.status(403, message="코인 자동매매는 관리자 전용 기능입니다.")
    if _PAPER_MODE:
        wiz.response.status(403, message="코인 API 키는 실투자(LIVE) 서버 설정에서만 저장합니다.")
    return user
```
- 저장(빈칸이면 유지, 쌍으로 교체, 항상 is_secret=True, 다시 읽어 검증, 응답에 비밀값 없음).
```python
def save_coin_keys():
    _require_coin_admin()
    access = _query_text("upbit_access_key")
    secret = _query_text("upbit_secret_key")
    if bool(access) != bool(secret):
        wiz.response.status(400, message="Access key와 Secret key를 함께 입력해야 교체됩니다. 둘 다 비우면 저장된 키를 유지합니다.")
    if access:
        if any(ch.isspace() for ch in access + secret) or len(access) > 128 or len(secret) > 128:
            wiz.response.status(400, message="업비트 키 형식을 확인해주세요.")
        _set_config("upbit_access_key", access, "Upbit access key (coin, admin only)", True)
        _set_config("upbit_secret_key", secret, "Upbit secret key (coin, admin only)", True)
        trading = _trading()
        uid = trading._current_user_id()
        for k in ("upbit_access_key", "upbit_secret_key"):
            row = trading.db("trading_config").get(key=trading._user_config_key(uid, k)) or {}
            if not row.get("value") or row.get("is_secret") is not True:
                wiz.response.status(500, message="업비트 키 저장을 확인하지 못했습니다.")
    result = _coin_probe()
    wiz.response.status(200, saved=bool(access), success=result["success"], message=result["message"],
                        diagnostics=result.get("diagnostics", []), coin=_public_coin_config())
```
- 읽기 전용 연결 테스트. 주문을 내지 않으며 test_coin_connection과 save_coin_keys가 함께 씁니다.
```python
def _coin_probe():
    access = str(_get_config("upbit_access_key", "") or "")
    secret = str(_get_config("upbit_secret_key", "") or "")
    if not (access and secret):
        return {"success": False, "message": "업비트 API 키가 저장되어 있지 않습니다.", "diagnostics": []}
    try:
        balances = wiz.model("portal/trading/upbit_api")(access, secret).balances()  # GET /v1/accounts
        krw = float((balances.get("KRW") or {}).get("balance", 0) or 0)
        coins = len([c for c in balances if c != "KRW"])
        return {"success": True, "message": "업비트 인증 및 잔고 조회 성공",
                "diagnostics": [{"step": "auth", "success": True, "message": f"KRW {krw:,.0f} · 보유 코인 {coins}종"}]}
    except Exception as e:  # UpbitError is not exported by wiz.model
        reason = getattr(e, "name", "") or type(e).__name__
        return {"success": False, "message": f"업비트 연결 실패({reason}): {str(e)[:160]}",
                "diagnostics": [{"step": "auth", "success": False, "message": reason}]}

def test_coin_connection():
    _require_coin_admin()
    wiz.response.status(200, **_coin_probe(), coin=_public_coin_config())
```
- 키 삭제. OFF는 아무 동작도 하지 않아야 하므로 청산이나 주문 취소는 하지 않습니다.
```python
def clear_coin_keys():
    _require_coin_admin()
    _set_config("upbit_access_key", "", "Upbit access key (cleared)", True)
    _set_config("upbit_secret_key", "", "Upbit secret key (cleared)", True)
    wiz.response.status(200, success=True, message="업비트 키를 삭제했습니다.", coin=_public_coin_config())
```
- load_settings 연결(api.py). try 블록 안 505줄 근처와 200 응답(561줄 뒤)에 추가합니다.
```python
        coin = _public_coin_config() if is_admin else None
...
        is_admin=is_admin,
        coin=coin,
```
- struct.py 변경. 38-102 집합에 키를 추가하고 669줄 prefix에 'upbit_'를 넣습니다.
```python
    "upbit_access_key",
    "upbit_secret_key",
...
        if storage_key.startswith('user:') or storage_key.startswith(('kis_', 'toss_', 'upbit_')):
```
- view.pug 탭 버튼(24줄 다음)과 탭 본문(90줄 다음). st-* 구조를 그대로 씁니다.
```pug
    button(*ngIf="!isInfiniteBuyMode() && showCoinSettingsTab()", type="button", (click)="switchTab('coin')", [class]="tabClass('coin')") 코인

div(*ngIf="tab === 'coin' && showCoinSettingsTab() && accountContext")
    div(*ngIf="isMock", class="dx-alert is-warn")
        strong LIVE 전용
        span 코인 자동매매와 키 저장은 실투자 서버에서만 합니다.
        a(class="st-link", [href]="accountContext.live_settings_url") 실투자 설정 열기
    section(class="st-card")
        header(class="st-card-head")
            div
                h2 업비트 연결
                p 관리자 전용 · KRW 현물. 저장된 키는 화면에 다시 표시하지 않습니다.
            span(class="st-status", [class.is-ok]="coinConfigured && coinTestOk", [class.is-error]="coinTestResult && !coinTestOk") {{coinConfigured ? (coinTestOk ? '연결됨' : '보관됨') : '미등록'}}
        div(class="st-form")
            div(class="st-row")
                label(for="st-upbit-access") Access key
                div(class="st-field")
                    input(id="st-upbit-access", [(ngModel)]="upbitAccessKeyInput", type="password", autocomplete="new-password", [disabled]="isMock", [placeholder]="coinAccessKeyHint ? coinAccessKeyHint + ' 저장됨 · 바꾸려면 새 키 입력' : 'Access key'")
            div(class="st-row")
                label(for="st-upbit-secret") Secret key
                div(class="st-field")
                    input(id="st-upbit-secret", [(ngModel)]="upbitSecretKeyInput", type="password", autocomplete="new-password", [disabled]="isMock", [placeholder]="coinHasSecret ? '저장됨 · 바꾸려면 새 키 입력' : 'Secret key'")
                    small 업비트 Open API 키는 자산조회·주문조회·주문하기만 허용하고 출금은 끄세요. 이 서버의 IP를 등록해야 합니다.
        div(class="st-actions")
            button(type="button", class="st-btn is-primary", (click)="saveCoinKeys()", [disabled]="coinLoading || isMock") {{coinLoading ? '확인 중…' : '저장 후 연결 확인'}}
            button(type="button", class="st-btn", (click)="testCoinConnection()", [disabled]="coinLoading || !coinConfigured || isMock") 연결 테스트
        div(*ngIf="coinTestResult", class="st-result", [class.is-error]="!coinTestOk")
            span {{coinTestResult}}
        ul(*ngIf="coinDiagnostics.length > 0", class="st-diag")
            li(*ngFor="let item of coinDiagnostics", [class.is-error]="item.success === false")
                span {{item.success === false ? '실패' : '정상'}}
                | {{item.step ? item.step + ' · ' : ''}}{{item.message}}
        p(class="st-note") 키는 암호화되어 이 관리자 계정에만 저장됩니다. 연결 확인은 잔고 조회만 하며 주문을 내지 않습니다.
```
- view.ts 메서드. saveApiSettings(453-500)의 구조를 복사하되 입력값은 항상 비우고, 비밀값은 받지도 보관하지도 않습니다.
```ts
public showCoinSettingsTab(): boolean { return this.effectiveAdminMode(); }

private applyCoinConfig(coin: any) {
    this.coinConfigured = coin?.configured === true;
    this.coinHasSecret = coin?.has_secret_key === true;
    this.coinAccessKeyHint = coin?.access_key_hint || '';
    this.coinUpdatedAt = coin?.updated_at || '';
    this.upbitAccessKeyInput = '';
    this.upbitSecretKeyInput = '';
}

public async saveCoinKeys() {
    this.coinLoading = true; this.coinTestResult = ''; this.coinDiagnostics = [];
    await this.service.render();
    try {
        const { code, data } = await wiz.call('save_coin_keys', {
            upbit_access_key: String(this.upbitAccessKeyInput || '').trim(),
            upbit_secret_key: String(this.upbitSecretKeyInput || '').trim(),
        });
        this.coinTestOk = code === 200 && data?.success === true;
        this.coinTestResult = data?.message || (this.coinTestOk ? '연결을 확인했습니다.' : '업비트 연결을 확인하지 못했습니다.');
        this.coinDiagnostics = Array.isArray(data?.diagnostics) ? data.diagnostics : [];
        if (data?.coin) this.applyCoinConfig(data.coin);
    } catch (e: any) {
        this.coinTestOk = false;
        this.coinTestResult = e?.responseJSON?.message || e?.statusText || '업비트 키 저장 중 오류가 발생했습니다.';
    } finally {
        this.upbitAccessKeyInput = '';
        this.upbitSecretKeyInput = '';
        this.coinLoading = false;
    }
    await this.service.modal.show({ title: this.coinTestOk ? '완료' : '연결 확인 필요', message: this.coinTestResult, action: '확인' });
    await this.service.render();
}
```
loadSettings 271줄 다음에 `this.applyCoinConfig(data.coin);`을 넣고, ensureVisibleTab에 `if (this.tab === 'coin' && !this.showCoinSettingsTab()) this.tab = this.fallbackTab();`을 추가합니다.
- LIVE 워커가 사용자별 키를 읽는 방법(struct.py 1043-1047 패턴). 세션 없이 읽지 않습니다.
```python
import flask
with wiz.server.app.flask.test_request_context('/'):
    flask.session['id'] = owner  # admin user id
    trading = Struct()
    access = trading.get_config('upbit_access_key', '')  # -> user:<owner>:upbit_access_key, decrypted
```

## pitfalls
- 요청서는 KIS/Toss 키가 마스킹되어 내려간다고 전제하지만 실제로는 아닙니다. load_settings(api.py 518-525)가 app_key, app_secret, toss_client_secret을 평문으로 응답하고, view.ts 216-221이 그 값을 input에 채웁니다. password 타입과 '보기' 토글은 화면에서만 가립니다. 코인 기능은 이 방식을 복사하지 않고 _public_bridge_config 방식(불리언과 hint만 응답)을 씁니다.
- _api_settings_payload_from_request(158-183)는 API 키가 하나라도 오면 화면 값 전체를 씁니다. 그래서 빈칸으로 보내면 저장값이 지워집니다. 코인 저장은 '빈칸이면 기존 값 유지'로 만들어야 합니다(infinitebuy 922-925줄 패턴). 그래야 브라우저가 비밀값을 다시 가질 필요가 없습니다.
- 기존 save_api_settings/test_connection을 재사용하거나 upbit 필드를 _API_SETTING_QUERY_KEYS(131-140)에 넣으면 안 됩니다. _persist_api_settings가 KIS/Toss 키를 빈 값으로 덮어쓰고(239-246) 토큰을 초기화합니다(258-264).
- is_secret은 키를 지울 때도 포함해 매번 True로 넘겨야 합니다. _write_config_value(694)가 매번 is_secret 플래그까지 덮어씁니다. _seal(trading_config.py 21-25)은 같은 dict에 is_secret이 truthy일 때만 암호화하므로, False로 한 번 쓰면 평문으로 저장됩니다. page.settings/api.py 362-375줄 fallback update는 is_secret을 빠뜨리지만, setter가 항상 있어서 실제로는 쓰이지 않습니다.
- set_config는 관리자 계정이면 사용자별 키와 전역 키 양쪽에 씁니다(struct.py 735-736). 그래서 전역 'upbit_access_key' 행(암호화됨)도 생깁니다. 세션이 없는 스레드가 get_config를 부르면 이 전역 사본을 읽게 됩니다(704-722). 코인 워커는 test_request_context와 owner 세션 안에서 읽어야 합니다. 669줄 prefix에 'upbit_'를 넣지 않으면 전역 사본은 클래스 캐시 Struct._cfg를 거치는데, wiz.model 재실행 때 클래스마다 캐시가 따로 생겨 키를 바꿔도 반영이 늦을 수 있습니다.
- LIVE와 PAPER는 DB 파일이 다릅니다(data/live/trading.db, data/paper/trading.db; scripts/start-stock8-paper.ps1 44-45). PAPER(3002)에서 저장한 업비트 키는 LIVE 워커가 볼 수 없습니다. 저장은 _PAPER_MODE(api.py 33)에서 403으로 막고, 화면에는 accountContext.live_settings_url 링크를 보여 줍니다. 암호화 키 파일(~/.stock8/config.key)은 두 서버가 함께 씁니다.
- wiz.response.status는 예외를 던져 응답합니다. load_settings(439-512)처럼 except Exception으로 감싸면 401/403도 500으로 바뀝니다. 코인 함수에서 try를 쓸 때는 page.infinitebuy/api.py 57-60의 _is_response_exception으로 응답 예외를 다시 던지거나, 가드를 try 밖에 둡니다.
- settings/api.py의 _set_config(352)는 관리자가 아닐 때 daytrade_ 키 저장을 조용히 무시합니다. 코인 엔드포인트는 조용히 무시하지 말고 명시적인 403을 내야 합니다. /wiz/api/page.settings/* 호출은 controller/user.py의 경로 게이트(20-24, /daytrade만 검사)에 걸리지 않으므로 함수마다 관리자 검사가 필요합니다.
- UpbitError는 wiz.model로 가져올 수 없습니다. upbit_api.py는 Model = UpbitApi만 노출합니다. except Exception으로 잡고 getattr(e,'name')과 getattr(e,'status')를 씁니다. 업비트 키는 등록된 IP에서만 동작하므로 테스트는 LIVE 서버 프로세스에서 해야 합니다. 키를 로그, print, 오류 메시지에 넣지 않습니다(작업 규칙: 키·토큰 출력 금지).
- trading.db('trading_config')는 사용자별 테이블이 아닙니다(USER_SCOPED_TABLES 103-110에 없음). 행을 직접 읽을 때는 trading._user_config_key(uid, key)로 storage key를 만들어 key= 조건으로만 조회합니다. ORM은 모르는 필터 kwargs를 오류 없이 버리기 때문에 __startswith 같은 조건은 무시되고 전체 행이 나올 수 있습니다.
- key 칼럼은 CharField(64)이고 'user:'+uid(32)+':' 접두가 38자를 차지합니다. 코인 키 이름은 26자 이하로 둡니다. SQLite가 길이를 강제하지 않아서 넘쳐도 오류 없이 저장됩니다.
- 비밀 입력칸에 autocomplete="off"(현재 KIS 칸 50·54줄)를 쓰면 브라우저가 무시하고 로그인 비밀번호를 자동 입력할 수 있습니다. 코인 칸은 type=password와 autocomplete="new-password"로 두고, 저장한 뒤 ngModel 값을 ''로 비웁니다. '보기' 토글(showSecret)은 저장값을 보여 주지 않으므로 넣지 않습니다.
- testApiConnection(view.ts 578-616)과 test_connection(api.py 606-630)은 템플릿에 연결되어 있지 않습니다. 실제 UX는 '저장 후 연결 확인'(view.pug 79)입니다. 코인도 이 버튼 하나를 기본으로 두고, '연결 테스트' 버튼은 저장된 키로 재검증하는 용도로만 둡니다.
- WIZ 특이사항이 있습니다. view.ts 안 어디에도, 주석에도 'export class' 바로 뒤에 'Component'가 붙은 문구를 새로 쓰지 않습니다. 정적 클래스 멤버 대신 모듈 상수를 씁니다. 코인 페이지를 따로 만들면 app.json에 "layout": "layout.trading"(page.settings/app.json 10)을 넣어야 테마가 적용됩니다. 페이지 scss는 캡슐화되어 있어 settings의 st-* 규칙은 다른 페이지에 적용되지 않습니다.
- 공용 loading 플래그(view.ts 94)를 코인 폼에 같이 쓰면 증권사 탭 저장 버튼이 함께 잠깁니다. coinLoading을 따로 둡니다. 화면이 바뀔 때마다 await this.service.render()를 호출해야 갱신됩니다.
- AGENTS.md 원칙상 OFF와 키 삭제(clear_coin_keys)는 아무 동작도 하지 않아야 합니다. 보유 코인 청산이나 미체결 주문 취소를 자동으로 하지 않습니다. 연결 테스트는 balances()만 부르고 주문 함수는 절대 부르지 않습니다.

# BACKGROUND EXECUTION: where and how to run a LIVE-only Upbit coin worker (C:\dev\stock8\src\portal\trading\model\struct.py and its boot/test harness)

I read the code in C:\dev\stock8 and changed nothing. In LIVE (TRADING_MODE=LIVE) the PAPER heartbeat `_background_worker_loop` (struct.py:2418-2646) never runs. `_ensure_background_worker` (940-982) stops at its LIVE branch (943-945) and calls `_ensure_live_policy_workers` (1028-1134). That method claims a registry `sys._stock8_live_policy_workers` once per process and starts one `stock8-live-policy-dispatch` thread. Every 5 seconds that thread reads the `order_policy_v1:*` rows straight from the database (1097-1098), checks that each owner exists and is an admin (1112, 1115), and starts any missing `stock8-live-<job>` thread (1122). Each job thread (`account_job`, 1043-1090) pushes `wiz.server.app.flask.test_request_context('/')`, sets `flask.session['id'] = owner` and builds `Struct()` inside it (1046-1052). That session context is what lets LIVE day trading resolve the admin's config and broker keys with no browser login. The admin check is repeated on every pass (1061, via order_policy.daytrade_allowed at order_policy.py:52-57).

Nobody has to log in for this to start. deploy/boot-local-paper.py is identical to the runtime C:\stock8-runtime2\app\config\boot.py (diff was empty), and both servers use it. About 2 seconds after start its `warm_paper_worker` (lines 19-49) calls `server.wiz().model("struct").trading`. That runs Struct.__init__, which calls `_ensure_background_worker()` (610) and then `worker_status()` (2649). In LIVE this starts the dispatcher.

These pieces only exist inside the PAPER loop: the KS minute-bar archive (2451-2468, explicitly `PAPER_MODE and ... >= 1540`), fill reconcile (2441-2450) and `_run_background_maintenance` (2399-2416, called at 2575). LIVE only trims logs, from the dispatcher (1129-1130). `_account_worker_target` (924-938) carries the owner session into child threads only in PAPER; in LIVE it returns the callback unwrapped. `resume_paper_worker` (984-995) is PAPER-only.

RECOMMENDED PLACE: add a new method `Struct._ensure_live_coin_worker()` and call it from the LIVE branch of `_ensure_background_worker`, right after `self._ensure_live_policy_workers()` at line 944, before the `return` at 945. Do not put it inside `dispatch()` / `_ensure_live_policy_workers`, and not in `_background_worker_loop`. In that spot it:
- inherits the build guard (941);
- starts at boot with no session;
- can never run in PAPER;
- is isolated from the KIS lanes and from the tests that inspect `_ensure_live_policy_workers` by AST.

How the method should work:
- Claim a slot in `sys.__dict__` under a process-wide lock.
- Start one long-lived `stock8-live-coin` supervisor thread.
- On every pass, read the coin switch row straight from the database. When it is OFF, set status 'off' and sleep, with no Upbit call of any kind.
- Only when it is ON: resolve the stored admin `owner_user_id`, recheck that the owner exists and is an admin, then run one cycle inside test_request_context with flask.session['id'] = owner.
- Re-read the switch immediately before every order.

- **C:\dev\stock8\src\portal\trading\model\struct.py** 21-27, 116-117: Module-level mode constants: TRADING_MODE (raises if not PAPER/LIVE), `PAPER_MODE = TRADING_MODE == "PAPER"`, the env kill switch `DAYTRADE_HARD_LOCKED`, and the process-wide lock pattern `_LOC_RESERVATION_PROCESS_LOCK = _sys.__dict__.setdefault('_stock8_loc_reservation_process_lock', threading.Lock())`.
  -> Add coin constants here as module-level values, not class attributes. Suggested: `COIN_HARD_LOCKED = str(_os.environ.get("STOCK8_COIN_HARD_LOCK", "false")).lower() in ("1","true","yes","on")`, `_COIN_POLICY_KEY = "coin_policy_v1"`, `_COIN_WORKER_KEY = "_stock8_live_coin_worker"`, and `_COIN_WORKER_LOCK = _sys.__dict__.setdefault("_stock8_live_coin_worker_lock", threading.Lock())`, copying line 116 exactly.
- **C:\dev\stock8\src\portal\trading\model\struct.py** 555-573 (esp. 561), 575-610: Class-level caches, including `_worker_lock = threading.Lock()`. These are re-created on every wiz.model exec. __init__ ends with `self._ensure_background_worker()` (610), which runs on every `wiz.model("portal/trading/struct")` call: every request, every account_job `Struct()`, and the bootstrap. Lines 594-598 show the per-pid sys guard `_trading_struct_tables_ok_{pid}`.
  -> The coin ensure must cost one dict lookup when the worker is already running: no DB or Upbit calls before the 'already claimed' check. Do not rely on `Struct._worker_lock` for once-per-process semantics. Use the module-level lock taken from sys.__dict__.
- **C:\dev\stock8\src\portal\trading\model\struct.py** 640-657: `_current_user_id()` reads flask.session through the season session model. Outside a request context the access raises, the error is swallowed and it returns "". `_current_user_is_admin(user_id)` works without a session when given an explicit id (role=='admin' or the hard-coded owner email).
  -> The supervisor can call `self._current_user_is_admin(owner)` and `self.orm.use('user').get(id=owner)` before entering any request context, exactly as dispatch does (1112, 1115). Everything that reads per-user config or keys must run inside test_request_context with session['id'] = owner.
- **C:\dev\stock8\src\portal\trading\model\struct.py** 665-686, 701-722, 724-761: How config is read and written. `_lookup_config_value` goes to the database only for keys starting with 'user:', 'kis_' or 'toss_' (669). Every other key is served from `Struct._cfg`, a per-exec class dict with no TTL. `get_config` resolves user-scoped keys to `user:<uid>:<key>` only when a session uid exists. With no uid it falls through to the global/legacy key (719). For admins it also falls back to and copies the legacy global (712-716). `set_config` for admins writes both the scoped key and the global key (733-736). auto_keys force-run (748-761) is KIS-specific.
  -> Read the coin ON/OFF row straight from the database on every pass: `self.orm.use('trading_config', module='trading').get(key=_COIN_POLICY_KEY)`, never through get_config. Upbit keys should be per-owner secrets (`user:<owner>:upbit_*`, is_secret=True) read under the owner session. If they go through get_config, add them to USER_SCOPED_CONFIG_KEYS (38-102) and add 'upbit_' to the prefix tuple at line 669 so they never come from the stale cache. To wake the worker on toggle, set a `threading.Event` kept in the sys registry rather than adding to auto_keys.
- **C:\dev\stock8\src\portal\trading\model\struct.py** 924-938: `_account_worker_target`: the pattern for running a callback as a given owner. It pushes `wiz.server.app.flask.test_request_context('/')`, sets `flask.session['id'] = owner`, checks that `self.orm.use('user').get(id=owner)` still exists, and fails closed when there is no owner. It is a no-op in LIVE (926-927 return the callback unchanged).
  -> Copy the body (import flask inside the function, the context, the session id, the owner-exists check, and the RuntimeError when the owner is empty) into the coin job. Do NOT call `self._account_worker_target(...)` expecting a session in LIVE: it returns the raw callback, so any child thread would run with no session and with global/legacy config.
- **C:\dev\stock8\src\portal\trading\model\struct.py** 940-945: `_ensure_background_worker`. Line 941 is the build guard (`STOCK8_BUILD_ONLY == '1' or 'build' in sys.argv`). Lines 943-945 are the LIVE branch: `if not PAPER_MODE: self._ensure_live_policy_workers(); return`.
  -> Hook point. Change the LIVE branch to call `self._ensure_live_coin_worker()` right after `self._ensure_live_policy_workers()`, optionally each wrapped in its own try/except, before the `return`. Never add the coin call to the PAPER part (946-982).
- **C:\dev\stock8\src\portal\trading\model\struct.py** 984-1020: `resume_paper_worker` and the remembered-owner helpers. They are PAPER-only (990) and resume the owner after a restart using the config key `paper_worker_owner_user_id`.
  -> The LIVE equivalent of 'resume without login' is to store `owner_user_id` in the coin policy row when the admin turns it ON. This mirrors order_policy.update (order_policy.py:146-149), and the supervisor reads it from the database. Do not reuse `_PAPER_WORKER_OWNER_KEY`.
- **C:\dev\stock8\src\portal\trading\model\struct.py** 1028-1134: `_ensure_live_policy_workers`, the LIVE template:
- registry_key '_stock8_live_policy_workers' claimed once per process (1035-1041);
- `account_job`: test_request_context plus session owner (1043-1047), a lazily built `Struct()` with retry on init failure (1048-1052), a per-pass policy re-read (1055-1061), status/last_check/error fields (1060-1089) and fixed sleeps (1090);
- `dispatch`: rows read straight from the database with a lambda field predicate (1097-1098), tolerant JSON parsing (1102-1108), owner existence and admin gating (1109-1116), respawn of dead threads (1117-1125), thread naming `name='stock8-live-' + job` (1122) and `'stock8-live-policy-dispatch'` (1132).
  -> Copy the shape into a new sibling method `_ensure_live_coin_worker` rather than editing this one. Keep the free names `wiz`, `Struct`, `time`, `_kst_now` and `registry` inside the nested job function so tests can exec it with injected fakes, as tests/test_live_worker_paths.py:38-42 does.
- **C:\dev\stock8\src\portal\trading\model\struct.py** 2388-2416: `_maybe_trim_trade_logs` uses a process-wide throttle stamp `_sys.__dict__.setdefault("_stock8_log_trim", {"ts": 0.0})` (2390). `_run_background_maintenance` runs only from the PAPER loop (2575).
  -> Copy the `_sys.__dict__.setdefault("_stock8_coin_...", {...})` stamp for any coin cooldown or once-per-period state. The coin worker should not do DB maintenance; LIVE already trims from dispatch (1129-1130).
- **C:\dev\stock8\src\portal\trading\model\struct.py** 2418-2468, 2547-2617: `_background_worker_loop` (PAPER only: it is started solely from the PAPER part of `_ensure_background_worker`, line 972). Inside it:
- a generation check at 2422 ends stale loops;
- reconcile thread `stock8-fill-reconcile` (2441-2450);
- KS minute-bar archive `stock8-ks-minute-archive` (2451-2468): weekday and >= 15:40 KST, once a day, retried every 300 s while the thread handle is kept in the state dict;
- exits run first, before the slow work (2547-2562).
  -> Not a place for coin code, because it never runs in LIVE. Reuse its gating idiom inside the coin supervisor for any daily coin job: `(t is None or not t.is_alive()) and state.get('x_day') != today and now_ts - state.get('x_try_ts', 0) >= 300`, with the thread handle stored in the sys registry. Keep the 'risk exits first, slow discovery detached' ordering.
- **C:\dev\stock8\src\portal\trading\model\struct.py** 2648-2662: LIVE branch of `worker_status()`: it reads `getattr(_sys, '_stock8_live_policy_workers', {})` and reports the thread as alive/started plus registry['error'].
  -> Expose coin status the same way from a separate method or API: `_sys.__dict__.get(_COIN_WORKER_KEY, {})`, dropping the 'thread' and 'wake' objects before returning JSON (see order_policy.py:103-104).
- **C:\dev\stock8\src\portal\trading\model\order_policy.py** 11-15, 52-57, 99-104, 134-164, 166-193: Sys-guarded process-wide ContextVar/RLock (11-15). `daytrade_allowed()` is an admin recheck from the session (52-57). Status reads registry jobs, filtered by the KIS account key, with 'thread' stripped (99-104). `update()` serializes changes under LOCK, requires the WARNING_VERSION confirmation and stamps `owner_user_id` from the session (134-164). `assert_order` re-reads the policy at every broker mutation and blocks when the lane is not True in LIVE (166-193).
  -> The coin policy row should follow this: a JSON row with `enabled` and `owner_user_id`, written under a sys-level RLock, with confirmation needed to turn it ON. The coin engine should run an assert_order-style re-read of the coin row (`policy.get('enabled') is True` and the owner is still an admin) immediately before every `buy_market_krw` / `sell_market`. Coin jobs must not be keyed into the KIS registry: status() filters by `self._key()` (KIS account hash).
- **C:\dev\stock8\deploy\boot-local-paper.py** 19-49: Bootstrap, byte-identical to the runtime C:\stock8-runtime2\app\config\boot.py that both servers use. A daemon thread `stock8-paper-bootstrap` sleeps 2 s, enters `app.flask.test_request_context("/stock8-paper-bootstrap")` with no session, loads `server.wiz().model("struct").trading` (which constructs Struct and calls `_ensure_background_worker`), then calls `worker_status()`.
  -> No change is needed. Once the coin ensure is in the LIVE branch, the coin supervisor starts here at LIVE boot with no browser session. Threads do not inherit this request context, so the coin thread must push its own. Note that deploy/boot.py (docker/public, lines 21-22) has no warm-up, so there the worker starts on the first request that loads struct.
- **C:\dev\stock8\src\portal\trading\model\upbit_api.py** 27-29, 67-72: Module-level `_LOCK = threading.Lock()` and `_LAST_CALL` / `_MIN_GAP` drive `_throttle`. Each `wiz.model("portal/trading/upbit_api")` re-executes the module, so every exec gets a fresh lock and timestamps.
  -> Either hold a single UpbitApi class reference for the supervisor's lifetime, or (preferred) change to `_RATE = sys.__dict__.setdefault("_stock8_upbit_rate", {"lock": threading.Lock(), "quote": 0.0, "exchange": 0.0})` so the 8 orders/s and 30 exchange calls/s limits hold process-wide.
- **C:\dev\stock8\src\portal\trading\model\struct\kis_api.py** 88-136: `_shared_paper_gateway`: a cross-process OS file lock (msvcrt.locking LK_NBLCK on Windows, fcntl.flock otherwise) on a file under tempfile.gettempdir().
  -> Optional defense-in-depth for 'exactly one process': in the coin supervisor, open e.g. `<data/live>/coin/worker.lock` and take a non-blocking lock held for the thread's lifetime. If it is not acquired, set status 'locked_elsewhere' and never place orders. The OS releases the lock when the process dies, which covers overlapping LIVE restarts and a second LIVE instance on the same DB.
- **C:\dev\stock8\.venv\Lib\site-packages\season\lib\core\wiz.py** 36-51 (and season\util\compiler.py:8-16): Proof of the re-exec behavior: `wiz.model` caches only compiled code and execs it into a fresh globals dict on every call (compiler.build line 9). `print` maps to the WIZ logger.
  -> Every class attribute and module global in a model is per call. Anything a long-lived coin thread must share with requests (status, wake event, rate limiter, in-flight order ids, cooldowns) goes in `sys.__dict__` or the database.
- **C:\dev\stock8\src\portal\season\model\dbbase\mysql.py** 8-19: The trading DB path is chosen by TRADING_MODE, and LIVE and PAPER must be physically separate files (data/live/trading.db vs data/paper/trading.db).
  -> The coin switch and Upbit keys must be written through the LIVE server (3001). The PAPER server's coin page should be read-only and say it is LIVE-only, because a toggle on 3002 writes the PAPER DB and nothing would ever run.
- **C:\dev\stock8\tests\test_live_worker_paths.py** 16-44: Harness that pulls the nested `account_job` out of `_ensure_live_policy_workers` by AST and execs it with an injected `registry`, `wiz` (a real Flask app), `Struct` factory, `_kst_now`, and `time=NS(sleep=stop)`, where stop raises a BaseException to end the loop. It asserts that OFF calls no engine (64-70) and that non-admins never run day trading (72-77).
  -> Write tests/test_live_coin_worker.py the same way: extract `coin_job` from `_ensure_live_coin_worker` and assert:
- OFF / missing row / corrupt JSON / non-admin / deleted owner make zero Upbit calls;
- the switch flipping OFF mid-run stops the next order;
- flask.session['id'] equals the owner inside the cycle.
Also add a test that `_ensure_background_worker` with PAPER_MODE=True never starts a coin thread.
- **C:\dev\stock8\tests\test_paper_worker_owner.py** 118-183, 235-241: Executes the real `_ensure_background_worker` / `resume_paper_worker` against a StructDouble whose attrs list (171-182) stubs `_ensure_live_policy_workers` but has no coin method. `_sys` is a SimpleNamespace.
  -> If the coin call is added only inside the `if not PAPER_MODE:` branch, these tests stay green, because the LIVE test returns from resume before reaching it. If it is placed anywhere a PAPER test can reach, add `_ensure_live_coin_worker=lambda _self: ...` to the attrs. Using `_sys.__dict__` works with the SimpleNamespace stand-in.
- **C:\dev\stock8\tests\test_live_dispatch_filter.py** 11-18: Takes the FIRST `.rows(...)` call found by `ast.walk` (breadth-first) inside `_ensure_live_policy_workers` and requires a `key=` lambda predicate on it.
  -> This is a further reason to keep the coin code out of `_ensure_live_policy_workers`: a coin `rows()` call there could be picked up first and break this test.
- **C:\dev\stock8\src\app\page.daytrade\api.py** 96-110, 1899-1923: Admin gating helpers `_is_admin_user` and `_session_user`. `ks_minute_backfill` starts an admin-owned daemon thread `stock8-ks-backfill` that enters `wiz.server.app.flask.test_request_context('/')` and sets `flask.session['id'] = owner` (1911-1915), with state kept in `sys.__dict__.setdefault("_stock8_ks_backfill", ...)` (1905).
  -> Use it as a second reference for running request-time admin work in a thread. Do NOT copy line 1916: it sets `state["running"] = False` before the work starts, so a second start can run concurrently. Clear such flags in `finally`.
- **C:\dev\stock8\scripts\start-stock8-live.ps1** 13, 20 (and start-stock8-paper.ps1:43): The supervisors set TRADING_MODE=LIVE for port 3001 and PAPER for 3002. `STOCK8_LIVE_TRADING_UNLOCK` is set to "" on the real LIVE server.
  -> Gate the coin worker on `not PAPER_MODE` plus its own kill-switch env and the database switch. Never gate it on STOCK8_LIVE_TRADING_UNLOCK: it is empty on LIVE, so coin would be permanently off.

## patterns
- Hook (struct.py:943-945 becomes): `if not PAPER_MODE:\n    self._ensure_live_policy_workers()\n    self._ensure_live_coin_worker()\n    return`. This keeps the build guard at 941 in front, and the PAPER part (946-982) stays untouched.
- Process-wide claim that survives re-exec (from struct.py:116 and 1035-1041, made race-free): module level `_COIN_WORKER_LOCK = _sys.__dict__.setdefault('_stock8_live_coin_worker_lock', threading.Lock())`, then inside the method: `if PAPER_MODE or COIN_HARD_LOCKED: return` / `with _COIN_WORKER_LOCK:` / `    if _sys.__dict__.get(_COIN_WORKER_KEY) is not None: return` / `    registry = {'status': 'starting', 'error': '', 'last_check': '', 'wake': threading.Event()}` / `    _sys.__dict__[_COIN_WORKER_KEY] = registry`. Claim before `thread.start()`, so the `Struct()` built inside the thread (which calls `_ensure_background_worker` again) is a no-op.
- Thread creation and naming (struct.py:1122, 1132-1134): `thread = threading.Thread(target=coin_job, daemon=True, name='stock8-live-coin')`, then `registry['thread'] = thread`, then `thread.start()`. Thread names show up in diagnostics (kis_api.py:656-658), so keep the `stock8-live-` prefix.
- Session-less admin execution (struct.py:1043-1052 and 930-937): `def coin_job():\n    import flask\n    trading, trading_owner = None, ''\n    while True:\n        try:\n            ...\n            with wiz.server.app.flask.test_request_context('/'):\n                flask.session['id'] = owner\n                if trading is None or trading_owner != owner:\n                    trading, trading_owner = Struct(), owner\n                ...one cycle...\n        except Exception as exc:\n            registry['status'] = 'error'; registry['error'] = str(exc)[:200]\n        registry['wake'].wait(30); registry['wake'].clear()`. A plain `time.sleep(30)` also works, matching line 1090, and makes test injection easier.
- Strict OFF check with no session and no cache (struct.py:1097-1116): `row = self.orm.use('trading_config', module='trading').get(key=_COIN_POLICY_KEY)`. Then `try: policy = _json.loads((row or {}).get('value', '') or '{}') except (ValueError, TypeError): policy = {}`, `owner = str(policy.get('owner_user_id', '') or '') if isinstance(policy, dict) else ''`, and `on = isinstance(policy, dict) and policy.get('enabled') is True and owner and self.orm.use('user').get(id=owner) and self._current_user_is_admin(owner)`. If not on: `registry['status'] = 'off'`, make no Upbit call, run no cleanup, and go back to waiting.
- Owner stamping when the switch turns ON (order_policy.py:138-163): under a sys-level RLock, `uid = str(self.struct._current_user_id() or ''); if not uid: raise ValueError('로그인이 필요합니다.')`, set `state['owner_user_id'] = uid`, require the admin and a confirmation token, then insert or update the single row through `struct.db('trading_config')`.
- Per-order re-check (order_policy.py:171-193): right before each `UpbitApi.buy_market_krw` / `sell_market`, re-read the coin row from the database and raise or skip unless `enabled is True` and the session owner is still an admin.
- Process-wide stamps and caches (struct.py:2390, secret_box.py:18, order_policy.py:11-15): `state = _sys.__dict__.setdefault('_stock8_coin_<name>', {...})` for cooldowns, in-flight order uuids, the rate limiter and the status shown to the UI.
- Once-per-day sub-job gating, if needed (struct.py:2454-2468): `if (t is None or not t.is_alive()) and state.get('x_day') != today and now_ts - float(state.get('x_try_ts', 0) or 0) >= 300: state['x_try_ts'] = now_ts; start the thread; store the handle in state`. Wrap the child explicitly with test_request_context and the owner, because `_account_worker_target` is a no-op in LIVE.
- Status exposure (struct.py:2650-2662; order_policy.py:103-104): `{k: v for k, v in _sys.__dict__.get(_COIN_WORKER_KEY, {}).items() if k not in ('thread', 'wake')}` plus `alive = bool(t and t.is_alive())`.
- Test harness (tests/test_live_worker_paths.py:16-44): `ast.parse` struct.py, find `_ensure_live_coin_worker`, then the nested `coin_job`, and exec it with scope `{'registry': {...}, 'wiz': NS(server=NS(app=NS(flask=flask_app))), 'Struct': factory, '_kst_now': ..., 'time': NS(sleep=stop), '_json': json}`. Bind `self` through a SimpleNamespace closure, or keep `self.orm` / `self._current_user_is_admin` reachable through an injected `self` in the scope.

## pitfalls
- `_background_worker_loop` (struct.py:2418), the KS archive (2451-2468), the reconcile thread (2441-2450) and `_run_background_maintenance` (2399/2575) run ONLY in PAPER. Coin code placed there would never run in LIVE and would run in PAPER, which is the exact opposite of the requirement.
- `Struct._worker_lock` (struct.py:561) is a class attribute, so every wiz.model exec makes a new Lock. The `getattr`/`setattr` registry check at 1036-1041 is therefore not strictly race-free between two concurrent execs (for example the bootstrap thread and the first HTTP request). For the coin worker, use a lock taken from `_sys.__dict__.setdefault(...)` (copy line 116) or an atomic `sys.__dict__.setdefault(key, claim) is claim` claim.
- Config cache staleness: `_lookup_config_value` (665-686) serves any key without a 'user:'/'kis_'/'toss_' prefix from `Struct._cfg` of the exec that created the thread. `set_config` calls from later requests update a different class's dict (wiz.py:36-51 re-exec into fresh globals), so a long-lived worker reading a global `coin_auto_enabled` through get_config would never see it turned OFF. Always read the switch straight from the database.
- With no request context, `_current_user_id()` returns '' (640-645). `get_config` then silently falls back to the global/legacy key (704-722), and `_UserScopedDb` reads and writes `user_id=''` rows (188-197, 234-237). The coin cycle must fail closed when the owner is empty, as `_account_worker_target` does at 931-932, and must always run inside test_request_context with session['id'] = owner.
- `_account_worker_target` returns the callback unchanged in LIVE (926-927). Any child thread the coin worker spawns through it has NO session and will use global/legacy config or credentials. Wrap children explicitly with test_request_context and the owner.
- Struct.__init__ calls `_ensure_background_worker()` on every `wiz.model('portal/trading/struct')` call (struct.py:610). The coin ensure must do nothing beyond a dict check once it is claimed: no DB query and no Upbit call. devlog/2026-04-14/014 records 135 duplicate worker threads and 12.8 GB of memory from exactly this re-exec pattern.
- A long-lived thread's closure keeps the first exec's `self` and `Struct`, so a code change only reaches it after a LIVE restart. Conversely, a coin engine loaded with `wiz.model(...)` on each pass loses all class-level state on every pass. Keep positions, cooldowns, daily P&L and in-flight order uuids in the DB or in `sys.__dict__`.
- upbit_api.py:27-29 keeps `_LOCK` and `_LAST_CALL` at module level. They reset on every `wiz.model('portal/trading/upbit_api')`, so the throttle is not process-wide unless one class reference is held or the state moves to `sys.__dict__.setdefault`.
- Do not add coin logic inside `_ensure_live_policy_workers` / `dispatch()`:
- its except at 1127-1128 sets registry['error'], which the KIS UI shows as `dispatcher_failed` (order_policy.py:131);
- an exception thrown before the KIS loop skips respawning dead KIS lanes;
- the once-per-process early return at 1038-1039 means a dead coin thread would never be restarted;
- order_policy.status filters jobs by the KIS account key (103-104);
- tests/test_live_dispatch_filter.py:13-18 picks the first `.rows` call by breadth-first AST walk.
- OFF must be a true no-op (AGENTS.md: 'OFF는 무동작이어야 한다. 정리, 강제청산, 예약취소를 자동으로 하지 않는다'): no ticker, balances, cancel_order or sell when OFF. The switch can flip mid-cycle, so re-check it right before every order, as assert_order does at order_policy.py:192-193.
- LIVE and PAPER use physically separate trading DBs (season/model/dbbase/mysql.py:8-19). The coin switch and Upbit keys only matter in data/live/trading.db. A toggle made on the 3002 UI writes the PAPER DB and never trades, so the UI must say LIVE-only.
- Do not gate on STOCK8_LIVE_TRADING_UNLOCK. scripts/start-stock8-live.ps1:20 sets it to '' on the real LIVE server, which would keep coin permanently off. Use a dedicated kill switch modeled on DAYTRADE_HARD_LOCKED (struct.py:25) together with the database switch.
- TRADING_MODE alone separates LIVE from PAPER, but it does not stop two LIVE processes from sharing one DB (overlapping restarts, a manual second run). Consider a non-blocking OS file lock held for the worker's lifetime (kis_api.py:88-136 pattern), plus storing each order uuid before or right after submission and reconciling it with get_order instead of resubmitting after a crash. The current client does not send an idempotency identifier.
- deploy/boot.py (the docker/public boot) has no warm-up. In that deployment the worker starts only when the first request loads struct. Only boot-local-paper.py, which is identical to the runtime config/boot.py, starts it at boot.
- Do not copy page.daytrade/api.py:1916: it sets `state['running'] = False` before the work starts, so a second start can run concurrently. Clear running flags in `finally`.
- trade_log trimming (struct.py:2340-2347) deletes event_type values matching %_RUN, %SKIPPED%, %ALREADY_SCHEDULED%, %MISSING_FOR_REBUILD% and %MISMATCH% after 14 days, and %ERROR% after 60 days. Name real coin fills (for example COIN_BUY / COIN_SELL) so they never match these patterns.
- The ORM silently drops filter kwargs it cannot resolve (season orm.py:110-179; only `__startswith` is special-cased). Use a lambda field predicate (`key=lambda f: f.startswith('coin_')`) or an exact `key=` match, never Django-style suffixes, or you get the whole table back.

# PAGE AND API CONVENTIONS (admin page under layout.trading, wiz.call/wiz.response contract, polling without flicker, dx-*/--bn-* theming, WIZ-free unit-test harness)

I read the code directly and changed no files. The only commands I ran were 4 existing tests, with -B so no bytecode was written: 9 tests passed. I also ran an AST scan of the guard lists in the daytrade api.py files.

How access works for a /coin page:
- **app.json:** use controller "user" and layout "layout.trading", the same as page.daytrade.
- **Hard page loads:** the only admin gate is a path check in src/controller/user.py:17-21.
- **API calls:** these go to /wiz/api/page.<id>/<fn>, which that path check does not match. So every public API function must be wrapped by the guard loop at the bottom of api.py (page.daytrade/api.py:1827-1872).
- **Coverage gap found:** in page.daytrade.us/api.py, `us_momentum_candidates` (line 877) is missing from the guard list (1127-1141). It is gated only by login.

WIZ response contract, checked in .venv/Lib/site-packages/season/lib/core/struct/response.py:183-219:
- `wiz.response.status(code, **kw)` always sends HTTP 200 with JSON `{code, data: kw}`.
- It then raises ResponseException, which subclasses Exception. So a success status() inside `try/except Exception` gets swallowed.
- The client side, `wiz.call` (src/angular/wiz.ts:76-104), POSTs form-encoded data with a 60 s default timeout. It resolves on both done and fail and never rejects, so the view checks `code !== 200` and shows `data?.message`.

Theming:
- The `dx-*` layout pieces are global, in src/angular/styles/styles.scss:161-367.
- They are built only on `--bn-*` / `--dx-*` CSS variables. Those variables get their dark and light values on `.trading-bg` / `.trading-bg.theme-light` in layout.trading (view.scss:7-63, view.pug:1).
- So a new page built from `dx-*` classes and `var(--bn-*)` needs no light-mode overrides. Pages built with Tailwind fixed colours do need `:host-context(.theme-light)` overrides, as in page.daytrade/view.scss.

Polling without flicker:
- Render the page shell first, then hydrate.
- Race the bootstrap call against a 4 s timeout and show a "delayed" banner.
- Poll every 5 s behind an in-flight flag. Render only on success and keep the old data when a request fails.
- Use `trackBy` on table rows. Ignore cache_miss results instead of showing zero.
- On the server, use TTL caches (monotonic time + deepcopy) that return `cached`/`degraded` flags, plus singleflight.

Test harness, three reusable styles:
- **(a) Single function:** AST-extract one function or method, then exec it with a stub scope dict and SimpleNamespace standing in for `self`.
- **(b) Whole module:** load the module with `importlib` while `builtins.wiz` is a stub whose `model()` raises on unexpected names, then monkeypatch instance I/O.
- **(c) Model file:** exec the whole file with `wiz` injected and take `env['Model']`. This is the ideal fit for upbit_api.py (`Model = UpbitApi`) and a new coin engine model.

To run the tests: `.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q`. The `season` package is in .venv; `cryptography` is not, so test_secret_config is skipped locally.

- **C:\dev\stock8\src\app\page.daytrade\app.json** 1-12: Admin page manifest. Fields: id, mode=page, title, namespace, category, viewuri, preview, controller=user, layout=layout.trading, template=wiz-page-daytrade(). Routes come from viewuri via wiz.routes() (src/angular/app/app-routing.module.ts:9).
  -> Create src/app/page.coin/app.json: {"id":"page.coin","mode":"page","title":"/coin","namespace":"coin","category":"coin","viewuri":"/coin","preview":"","controller":"user","layout":"layout.trading","template":"wiz-page-coin()"}. Templates list @Inputs as [public<name>]="" (see page.daytrade.us/app.json and component.trading.controls/app.json); a page with no inputs uses wiz-page-coin().
- **C:\dev\stock8\src\controller\user.py** 7-21: Every 'user' page and API call goes through this controller. Steps: login check (401). In PAPER mode, require a paper subscription except for /settings and /wiz/api/page.settings/ (lines 10-15). Then the admin path gate for /daytrade and /daytrade/*, using trading._current_user_is_admin, which accepts role=admin or the owner email (struct.py:647-657).
  -> Add `or request.path == '/coin' or request.path.startswith('/coin/')` (or a separate if-block) with a 403 coin-specific message. This only covers direct page loads: SPA routerLink navigation and /wiz/api/page.coin/* calls do not match this path, so the API guard below is mandatory. Do not switch to controller 'admin' (src/controller/admin.py:7-8): it checks session role only, rejects the email-based admin with a bare 401, and has no message.
- **C:\dev\stock8\src\app\page.daytrade\api.py** 36-39, 88-153: Module constants _TRADING_MODE / _DAYTRADE_HARD_LOCKED read from env once. Helpers: _truthy, _is_admin_user (role=='admin' or the owner email), _session_user (401/404 through wiz.response.status), _daytrade_access_payload (dict of flags), _require_daytrade_access (403 with message plus flags), and access_status() returning the payload.
  -> Copy into page.coin/api.py as _is_admin_user, _session_user, _coin_access_payload (is_admin, coin_owner_process=_TRADING_MODE=='LIVE', hard_locked), _require_coin_access(), and coin_access_status(). Keep the payload a plain dict so the AST test pattern in tests/test_admin_daytrade_access.py:10-23 can exec it with stubs.
- **C:\dev\stock8\src\app\page.daytrade\api.py** 1827-1872: Guard wrapper: _guard_daytrade_api(name) replaces globals()[name] with a wrapper that calls _require_daytrade_access() first. A for-loop over an explicit list of public function names applies it at module bottom.
  -> Put the same block at the END of page.coin/api.py, after every def, and list every public coin function in it. Add a unit test that AST-scans api.py and asserts every non-underscore def is in the guard list or is explicitly exempt (access status, ping). page.daytrade.us/api.py already misses us_momentum_candidates (def at 877; list at 1127-1141).
- **C:\dev\stock8\src\app\page.daytrade\api.py** 535-605, 1329-1368: Endpoint conventions. Functions take no arguments. Params come from wiz.request.query(key, default) as strings (`.lower() != 'false'`, float(...)). Work happens inside try; `except Exception as e: wiz.response.status(400|500, message=str(e))`; success is `wiz.response.status(200, field=..., ...)` AFTER the try. Toggles persist via trading.set_config(key, 'true'/'false', description=...), and OFF also turns off exit watch (1360-1362).
  -> Coin endpoints: coin_bootstrap, coin_snapshot (cheap and poll-safe), coin_toggle_auto(enabled='true'|'false'), coin_daily_log. Put mutations (toggle, manual sell) behind both _require_coin_access and a LIVE-owner check that returns 409/403 with a message on the PAPER server.
- **C:\dev\stock8\src\app\page.daytrade\api.py** 1875-1923: Admin-only endpoints outside the guard list. Inline check: `if not _is_admin_user(_session_user()): wiz.response.status(403, ...)`. Process-wide state lives in `_sys.__dict__.setdefault('_stock8_ks_backfill', {...})`. A background thread runs under the starting admin's session through `wiz.server.app.flask.test_request_context('/')` with `flask.session['id']=owner`.
  -> Use this for coin admin and debug endpoints and for any coin background job started from the page. Claim the running flag before Thread.start(), and keep state on sys so a re-exec does not reset it.
- **C:\dev\stock8\src\app\page.daytrade.us\api.py** 66-99, 169-192, 706-815: Server-side caching that avoids UI flicker. _cache_get/_cache_set (monotonic ts + deepcopy) return (payload, age). _singleflight(key, builder) uses threading.Event so concurrent identical requests share one build. Responses carry cached/cache_age_sec, and on exception the last cached payload is returned with degraded=True instead of an error (807-812, 829-834). The struct object is kept on sys (`_page_daytrade_us_struct_obj`) with a 5 s error TTL.
  -> Copy _cache_get, _cache_set and _singleflight for coin_snapshot (TTL about 3-5 s for tickers) and coin_bootstrap. Keep a long-lived client or struct on sys.__dict__ rather than in module globals.
- **C:\dev\stock8\src\app\page.daytrade\view.ts** 1-13, 86-117, 130-162, 164-202, 240-286: Page component skeleton. Header: `/// <reference path="../../types/wiz-modules.d.ts" />`, Service import, module-level consts (WIZ renames the class, line 7). Constructor: (public service: Service). ngOnInit: service.init(this), then auth.allow('/access'), then loading=false, then render, then bootstrap, then render. ngOnDestroy clears timers. A private api(name, params) wrapper calls wiz.call. bootstrap races the request against a 4 s timer that resolves {code:202, data:{delayed:true}}, then applies the late response. Polling: setInterval 5000 with an activePositionRefreshing in-flight guard, cheap params (refresh_quotes:'false'), render only on success, silent catch keeps old data. trackByPositionCard. applyBudgetStatus ignores cache_miss/unavailable instead of zeroing.
  -> Use the same layout for page.coin/view.ts: module const lookups, an api() wrapper, the bootstrap race, a startPolling/stopPolling pair, `if (inFlight) return` guards, trackBy by market code (e.g. 'KRW-BTC'), and service.modal.show({title, message, action, cancel, status:'warning', actionBtn:'warning'}) to confirm turning auto ON (88-98).
- **C:\dev\stock8\src\app\page.daytrade.us\view.ts** 1-13, 99-208, 387-418: Variant: `declare const wiz: any;`. Renders the full control surface before the Python model loads. The same 4 s race sets bootstrapDelayed, then awaits the real response. queueBackgroundRefresh is a one-shot 120 ms setTimeout. loadSnapshot passes the 3rd options argument {timeout: 8000}; on failure it sets a 'may be stale' errorMessage but keeps the shown data. refreshLight swaps the button label (refreshing) instead of blanking content.
  -> Use the 3rd-argument timeout for coin snapshot polls (e.g. {timeout: 8000}). Show stale or degraded state as a dx-alert or a dx-updated timestamp rather than clearing tables.
- **C:\dev\stock8\src\app\component.trading.controls\view.ts** 82-114, 164-180: Low-frequency status polling: setInterval 30000 that skips while busy or pending; on failure, retry after 3000*n ms up to 3 times; timers cleared in ngOnDestroy. save() sets busy, posts with {timeout:10000}, and on uncertain failure sets state=null and asks the user to re-check instead of assuming success.
  -> Use this for the coin ON/OFF state card: never mark an order or toggle as applied when the response could not be confirmed.
- **C:\dev\stock8\src\angular\wiz.ts** 71-104: wiz.call(fn, data, options): POST to /wiz/api/<namespace>/<fn> with jQuery form encoding, dataType text, timeout 60000 (overridable). Responses are JSON-parsed after NaN/Infinity are mapped to null. Both the done and fail paths resolve; nothing rejects. An unparseable response resolves to the raw jqXHR, so code is undefined.
  -> Send flat scalar params only. Send booleans as 'true'/'false' strings (as view.ts does: force ? 'true' : 'false'). Always branch on `code !== 200` and use `data?.message`.
- **C:\dev\stock8\.venv\Lib\site-packages\season\lib\core\struct\response.py** 183-219: status(code, **kw) serializes {code, data} with HTTP status 200 (the default) and _build() raises season.lib.exception.ResponseException, whose MRO is ResponseException -> Exception.
  -> Inside broad try/except, re-raise it, as page.infinitebuy/api.py:8-12 and 57-60 do (_is_response_exception) and page.dashboard/api.py:3276-3278 does (`if e.__class__.__name__ == 'ResponseException': raise`).
- **C:\dev\stock8\src\app\page.daytrade\view.pug** 1-106, 108-166, 168-172: Markup using the shared primitives: loading block, then div.dx-page > div.dx-head (div.dx-title with h1, div.dx-seg tabs, span.dx-chip with .is-on/.is-off/.is-warn/.is-live) + div.dx-tools (button.dx-tool, label swaps while busy). Then div.dx-alerts (dx-alert is-info/is-danger/is-ok/is-warn with a dismiss button), div.dx-kpis > div.dx-kpi (dx-kpi-label/value/sub, [class]="tone(x)"), and section.dx-card (dx-card-head h2 + span.dx-count + small). dx-empty and dx-table-wrap > table.dx-table use th/td.num, tr.is-click/.is-selected, trackBy, div.dx-sym strong/small, and span.dx-tag .is-buy/.is-sell/.is-ok/.is-warn. Also dx-grid-2, dx-detail-grid/dx-detail, and details.dx-card.dx-details with (toggle) lazy load.
  -> Build page.coin/view.pug only from these classes. Example: KPI row (KRW balance, coin valuation, today's realized P&L, daily loss buffer), a holdings dx-table per market, a signals/watch card and a recent-orders card. Avoid the legacy Tailwind blocks (lines 173-277), which need light-theme overrides.
- **C:\dev\stock8\src\angular\styles\styles.scss** 64-89, 161-367: Root fallback tokens (--bn-* dark) on html/body/app-root. All dx-* classes are global and styled only with var(--bn-canvas|card|elevated|hairline|body|muted|muted-strong|primary) and --dx-up/--dx-down (Korean convention: up=red #f6465d/#dc2626, down=blue #4f8cff/#2563eb, lines 162-167). Legacy Tailwind remaps for light mode are at 340-357. Responsive breakpoints at 1100/860/560 px are at 359-367.
  -> No new global CSS is needed. Page-specific SCSS should use var(--bn-*) with fallbacks (as page.history/view.scss:4-33 does) and `:host { display:block; height:100%; }`.
- **C:\dev\stock8\src\app\layout.trading\view.scss** 7-63, 83-99: Token values: .trading-bg is dark (canvas #0b0e11, card #1e2329, primary #fcd535) and .trading-bg.theme-light is light (canvas #f5f7fb, card #fff, hairline #d8e0ec, body #162033, primary #2563eb). The class is toggled in layout.trading/view.pug:1 by themeMode, read from localStorage 'dashboard-theme-mode' and the 'dashboard-theme-changed' event (view.ts:31-68).
  -> The page must render inside layout.trading (app.json layout) so the tokens resolve. Anything outside .trading-bg falls back to the dark root tokens.
- **C:\dev\stock8\src\app\page.daytrade\view.scss** 1-99: `:host{display:block;height:100%}` plus many `:host-context(.theme-light)` !important overrides that exist only because the page still uses Tailwind fixed colors. Lines 92-99 hardcode `.signal-overview{background:#fff}`, which is not theme-aware.
  -> Do not copy. A coin page built on dx-* plus var(--bn-*) needs only the :host block.
- **C:\dev\stock8\src\app\component.nav.trading\view.pug** 23-33: Nav links. The daytrade link is gated by `*ngIf="canShowDaytradeNav"`; admin-only /simulation is gated by `*ngIf="effectiveAdminMode"`. Classes come from [class]="navClass('/path')". view.ts:290-304 defines isRealAdmin (role or owner email) and effectiveAdminMode (excludes admin 'user preview' mode); isActive (392-399) uses prefix matching.
  -> Add `a(*ngIf="effectiveAdminMode", routerLink="/coin", [class]="navClass('/coin')")` with an svg and `span 코인`. Do NOT gate it on daytradeAccess flags (those are the KS/US feature flags).
- **C:\dev\stock8\src\portal\trading\libs\page-meta.ts** 15-33: PAGES regex table that drives the document title and the breadcrumb in layout.trading (view.pug:10-15).
  -> Add `{ pattern: /^\/coin\/?$/, meta: { title: '코인', trail: [HOME] } }` before the generic entries.
- **C:\dev\stock8\tests\test_paper_page_budget.py** 10-14, 23-54: Generic helper method(path, name, env): ast.parse the file, find the FunctionDef via ast.walk (works for class methods too), exec it alone in env, and return env[name]. Tests pass module constants like {'_TRADING_MODE':'LIVE'} and SimpleNamespace or Mock collaborators. Lines 23-30 also assert on view.ts source text by slicing between two method signatures.
  -> Use it for coin api.py helpers (_coin_access_payload, cache and LIVE-owner gates) and for coin engine methods called with SimpleNamespace as self. Use the view.ts source-slice assertion to pin UI safety rules (e.g. a confirm modal before enabling auto).
- **C:\dev\stock8\tests\test_admin_daytrade_access.py** 1-32: Role-boundary test without a server: extracts _daytrade_access_payload from both page api.py files, execs it with a stub scope (_session_user, _is_admin_user, _TRADING_MODE, _get_config, ...) for PAPER/LIVE x admin/non-admin, and asserts access flags. Also checks that page.settings _set_config ignores daytrade keys for regular users.
  -> Clone it for page.coin: assert non-admins are denied in both modes, coin_owner_process is True only for LIVE, and every public def is wrapped by the guard list.
- **C:\dev\stock8\tests\test_daytrade_engine_regressions.py** 17-111, 164-198: Whole-module load: set builtins.wiz = _WizStub() whose model(name) returns stubs for known names and raises AssertionError otherwise, then importlib.util.spec_from_file_location(...).loader.exec_module(...). _engine_with_state builds the engine with a _StructStub (get_config dict, broker stub recording buy_orders) and monkeypatches the persistence and clock seams (_load_state_map/_save_state_map/_timestamp/_fetch_*).
  -> For a coin engine at src/portal/trading/model/struct/coin_engine.py, design explicit seams (_load_state/_save_state/_now/_client) and stub UpbitApi with a recorder that captures buy_market_krw/sell_market calls, so tests can assert that no order is sent when OFF, when on the PAPER process, or during in-flight or duplicate cycles.
- **C:\dev\stock8\tests\test_settings_api_payload.py** 15-111: Loads a page api.py as a module. _RequestStub.values feeds wiz.request.query, and _ResponseStub.status raises _ResponseStatus(code, data), so tests use assertRaises and inspect .code/.data. builtins.wiz is set before load and restored in setUp/tearDown, and module caches (_STRUCT_CACHE) are reset per test.
  -> Use it to test coin api endpoints end to end (params to response code and message) without WIZ. Always restore builtins.wiz, because other test modules install their own stub at import.
- **C:\dev\stock8\tests\test_secret_config.py** 18-47: _load(path, wiz=None) execs a whole model file in env {'__name__':..., 'wiz': wiz} and returns env, then takes env['Model'] (WIZ model convention). wiz = SimpleNamespace(model=lambda name: models[name]). Uses peewee with in-memory sqlite and skips when cryptography is missing (it is missing in the local .venv).
  -> The best fit for src/portal/trading/model/upbit_api.py (`Model = UpbitApi`, line 155). Load it, replace `api._session` with a fake exposing request(method, url, **kw) that returns an object with status_code and json(), and set env['_MIN_GAP'].update(quote=0, exchange=0) to skip throttle sleeps. Then assert the JWT/query_hash, the 5,000 KRW minimum and the error mapping.
- **C:\dev\stock8\tests\test_paper_worker_owner.py** 10-25, 118-183: Extracts Struct methods (_account_worker_target, _ensure_background_worker, resume_paper_worker, _worker_state) and execs them with PAPER_MODE, a real flask.Flask test_request_context for session ids, and a SimpleNamespace standing in for _sys so the 'process-wide' worker registry is observable. test_live_never_resumes_paper_owner flips PAPER_MODE.
  -> Use it to prove the coin worker starts only in the LIVE process, once per process (registry on sys), and never from a PAPER request or a session-less load.
- **C:\dev\stock8\tests\test_daytrade_order_serialization.py** 7-42: Extracts _execute_live_locked/execute_live from daytrade_engine.py via ast.walk and calls them with SimpleNamespace self. It covers: a non-blocking global lock returns ORDER_IN_FLIGHT without touching the broker; a pending order number blocks a new order (PENDING_ORDER); a stale exit after a full sale is discarded (STALE_SIGNAL).
  -> Mirror these three invariants for the coin order path (lock, then pending uuid check via get_order, then re-validation of position before sell_market).

## patterns
- app.json for an admin page: {"id":"page.coin","mode":"page","title":"/coin","namespace":"coin","category":"coin","viewuri":"/coin","preview":"","controller":"user","layout":"layout.trading","template":"wiz-page-coin()"}
- Controller gate (src/controller/user.py:17-21): `if request.path == '/coin' or request.path.startswith('/coin/'): trading = wiz.model('struct').trading; if not trading._current_user_is_admin(wiz.session.get('id')): wiz.response.status(403, message='코인은 관리자 전용 기능입니다.')`
- API guard at the bottom of api.py (page.daytrade/api.py:1827-1872): `def _guard_coin_api(name):\n    original = globals().get(name)\n    if not callable(original): return\n    def _wrapped(*a, **kw):\n        _require_coin_access()\n        return original(*a, **kw)\n    globals()[name] = _wrapped\nfor _n in ['coin_bootstrap','coin_snapshot','coin_toggle_auto', ...]: _guard_coin_api(_n)`
- Endpoint shape (page.daytrade/api.py:1329-1347): `def coin_snapshot():\n    force = wiz.request.query('force_refresh','false').lower() == 'true'\n    try:\n        payload = _build_snapshot(force)\n    except Exception as e:\n        wiz.response.status(400, message=str(e))\n    wiz.response.status(200, **payload)`. Never put the success status() inside a broad try, or re-raise with `if e.__class__.__name__ == 'ResponseException': raise`.
- Module mode constant (page.daytrade/api.py:36): `_TRADING_MODE = str(_os.environ.get('TRADING_MODE','PAPER') or 'PAPER').strip().upper()`. The coin owner process is `_TRADING_MODE == 'LIVE'`; on PAPER, return read-only payloads and refuse mutations.
- Server TTL cache + degrade (page.daytrade.us/api.py:66-80, 798-815): `_cache_get(store,key,ttl)` returns (deepcopy(payload), age) when `time.monotonic()-ts < ttl`; on exception return the cached payload with cached=True, degraded=True, cache_age_sec; otherwise status(400). Process-wide stores: `sys.__dict__.setdefault('_stock8_coin_<name>', {})` (struct/daytrade.py:48-53, 1520-1525; page.daytrade/api.py:1905).
- Background job under the admin's session (page.daytrade/api.py:1906-1922): claim `state['running']=True` before Thread.start(); inside the thread use `with wiz.server.app.flask.test_request_context('/'): flask.session['id'] = owner; ...`
- view.ts header (page.daytrade/view.ts:1-13): `/// <reference path="../../types/wiz-modules.d.ts" />`, `import { OnDestroy, OnInit } from '@angular/core'; import { Service } from '@wiz/libs/portal/season/service';`, module-level `const MARKET_LABEL: any = {...}` (no static class members), then the component class whose constructor is `constructor(public service: Service) {}`.
- ngOnInit (view.ts:100-113): `await this.service.init(this); await this.service.auth.allow('/access'); this.loading = false; await this.service.render(); try { await this.bootstrap(); } finally { await this.service.render(); }`; `ngOnDestroy() { this.stopPolling(); }`
- Call wrapper + result handling (view.ts:130-132, 1145-1161): `private async api(name: string, params: any = {}) { return await (wiz.call(name, params) as Promise<{code:number; data:any}>); }` then `const { code, data } = await this.api('coin_toggle_auto', { enabled: on ? 'true' : 'false' }); if (code !== 200) this.errorMessage = data?.message || '...'; else {...}` inside try/catch, with the busy flag reset and `await this.service.render()` after.
- Bootstrap race (view.ts:139-155): `const request = this.api('coin_bootstrap', {}); const timeout = new Promise(r => window.setTimeout(() => r({code:202, data:{delayed:true}}), 4000)); const {code, data} = await Promise.race([request, timeout]); if (code === 202 && data?.delayed) { this.bootstrapDelayed = true; this.startPolling(); void request.then(async late => { if (late?.code === 200) { this.apply(late.data); this.bootstrapDelayed = false; await this.service.render(); } }).catch(() => undefined); return; }`
- Flicker-free polling (view.ts:190-202, 244-267): `this.timer = window.setInterval(() => void this.refreshQuick(true), 5000);` and `if (this.refreshingQuick) return; this.refreshingQuick = true; let changed = false; try { const {code,data} = await this.api('coin_snapshot', {force_refresh:'false'}); if (code === 200) { this.rows = data.rows || []; changed = true; } } catch (e) {} this.refreshingQuick = false; if (render && changed) await this.service.render();`. Also trackBy on rows and never overwrite with zeros on a cache_miss (view.ts:269-271).
- Confirm before enabling auto (view.ts:88-98): `await this.service.modal.show({ title: '코인 자동매매 시작', message: '...', action: '그래도 켜기', cancel: '취소', status: 'warning', actionBtn: 'warning' }) === true`
- Pug skeleton (page.daytrade/view.pug:8-106): `div(*ngIf="!loading", class="dx-page")` > `div.dx-head` (`div.dx-title` h1 코인 + `span.dx-chip(...)`; `div.dx-tools` `button.dx-tool((click)="refreshAll()", [disabled]="refreshing") {{refreshing ? '갱신 중' : '새로고침'}}`) > `div.dx-alerts` (`div.dx-alert.is-danger` strong + span + dismiss button) > `div.dx-kpis` > `div.dx-kpi` (dx-kpi-label / `div.dx-kpi-value([class]="tone(pnl)")` / dx-kpi-sub) > `section.dx-card` (`div.dx-card-head` h2 + span.dx-count + small; `div.dx-empty`; `div.dx-table-wrap > table.dx-table` with `th.num`/`td.num`, `tr(*ngFor="let r of rows; trackBy: trackByMarket")`, `div.dx-sym strong/small`, `span.dx-tag.is-buy/.is-sell`).
- P&L helpers (view.ts:1051-1064): `tone(v) => v>0 ? 'dx-up' : v<0 ? 'dx-down' : 'dx-flat'`; `signedKrw(v)`; `signedPct(v)`; `formatNumber(value, '1.0-8')` (783-802) for coin volumes.
- Page SCSS: `:host { display: block; height: 100%; }` plus only var(--bn-card|elevated|hairline|body|muted|muted-strong|primary) with fallbacks; no hex colors, no :host-context overrides needed.
- Nav + breadcrumb: component.nav.trading/view.pug add `a(*ngIf="effectiveAdminMode", routerLink="/coin", [class]="navClass('/coin')")`; page-meta.ts add `{ pattern: /^\/coin\/?$/, meta: { title: '코인', trail: [HOME] } }`.
- Test, single function (tests/test_paper_page_budget.py:10-14): `def method(path, name, env): tree = ast.parse((ROOT/path).read_text(encoding='utf-8-sig')); fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name); exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), env); return env[name]`
- Test, model file (tests/test_secret_config.py:18-21): `def _load(path, wiz=None): env = {'__name__': str(path), 'wiz': wiz}; exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), env); return env` then `Api = _load(SRC/'upbit_api.py')['Model']`
- Test, response stub (tests/test_settings_api_payload.py:21-39): `class _ResponseStatus(Exception): def __init__(self, code, data): self.code, self.data = code, data` / `class _ResponseStub: @staticmethod def status(code, **data): raise _ResponseStatus(code, data)`. Or use the real `from season.lib.exception import ResponseException` (available in .venv, tests/test_profit_response_boundary.py:8-18).
- Run tests: `.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -q` (README.md:62; -B avoids writing .pyc).

## pitfalls
- wiz.response.status() always raises season ResponseException, a subclass of Exception, and sends HTTP 200 with {code, data}. If it is called inside `try: ... except Exception:` the response is swallowed and replaced by the except branch. Call the success status() after the try, or re-raise ResponseException (page.infinitebuy/api.py:57-60, page.dashboard/api.py:3276-3278).
- The HTTP status is always 200 and errors live in the JSON `code`. wiz.call never rejects for server errors, and a non-JSON reply resolves to the raw jqXHR (code undefined). Always test `code !== 200` and read `data?.message`.
- wiz.call form-encodes params, so the server receives strings. Send booleans as 'true'/'false' and parse numbers with float(); keep params flat because no page sends nested objects or arrays.
- The user.py path gate only matches page URLs. /wiz/api/page.coin/* calls and in-app routerLink navigation bypass it, so each public api.py function must be in the guard list. Existing gap: page.daytrade.us/api.py us_momentum_candidates (line 877) is not in its guard list (1127-1141), so any logged-in or subscribed user can call it. Add an AST test that fails when a coin public def is unguarded.
- Controller 'admin' (src/controller/admin.py) checks session role only and returns a bare 401, so it would lock out the email-based admin that Struct._current_user_is_admin accepts (struct.py:647-657). Mirror daytrade: use controller 'user' plus the path gate plus the API guard.
- In PAPER mode the user controller also requires a paper subscription for every page and API except /settings (user.py:10-15). The coin page on the PAPER server needs that too, or a whitelist entry, if it should be viewable there.
- One bundle serves both LIVE (3001) and PAPER (3002). Decide 'owner process' from TRADING_MODE at module level and refuse order or toggle endpoints on PAPER with a clear message. Never let a page request start the coin worker in the PAPER process (see tests/test_paper_worker_owner.py test_live_never_resumes_paper_owner for the testing pattern).
- wiz.model() re-executes model modules, so module globals and class attributes reset per load. upbit_api.py keeps its rate-limit `_LOCK`/`_LAST_CALL` at module level (lines 26-29), so throttling is not process-wide across re-exec'd instances. Keep shared limiters, worker registries and caches in `sys.__dict__.setdefault('_stock8_coin_...', ...)` (struct.py:116, struct/daytrade.py:48-53).
- WIZ renames the component class at build time and rewrites that literal text anywhere: never write the phrase in comments or strings, and keep lookup tables as module-level consts rather than static members (view.ts:7).
- The dx-* classes and --bn-* tokens only take theme values inside `.trading-bg` (layout.trading). Content outside it, such as a component rendered without layout.trading, falls back to the dark root tokens in styles.scss:64-89 and ignores light mode.
- P&L colors follow the Korean convention: .dx-up/--dx-up is red for profit and .dx-down/--dx-down is blue for loss (styles.scss:162-167). --bn-up is green and --bn-down red (Binance), and legacy profitClass() uses emerald/red Tailwind. Use tone() so coin P&L matches the dashboard and daytrade.
- Do not copy page.daytrade/view.scss's :host-context(.theme-light) !important block or `.signal-overview{background:#fff}` (lines 92-99). They exist only because that page still uses Tailwind fixed colors; dx-* plus var(--bn-*) needs no overrides.
- Polling pitfalls: without an in-flight guard, slow responses pile up. Clearing arrays on failure makes tables flash empty. Treating cache_miss/unavailable as 0 shows a fake ₩0 (view.ts:269-271 guards this). Uncleared intervals leak after route change, so clear them in ngOnDestroy.
- Testing: tests that set builtins.wiz at import time must restore it (test_settings_api_payload.py:88-105), because several test modules install different stubs. _WizStub.model should raise on unexpected names so new hidden dependencies fail loudly. cryptography is missing in the local .venv, so secret-config tests skip locally; exec'ing upbit_api.py needs `requests` (present) or a fake `_session`.
- page.daytrade has a 0-byte view.html next to view.pug, while page.daytrade.us uses only view.html. Give the new page a single template file to avoid confusion over which one WIZ compiles.

# LOGGING, HISTORY, DASHBOARD: trade_log recording, history grouping and filters, dashboard realized P&L, and retention/trim for a new admin-only Upbit "코인" module

All trade/event logging goes into one user-scoped sqlite table, `trade_log` (C:\dev\stock8\src\portal\trading\model\db\trade_log.py). LIVE and PAPER each have their own DB (data/live/trading.db and data/paper/trading.db, see docs/account-isolation-20260927.md:17-19), so COIN rows written by the LIVE process (port 3001) only show up on the LIVE history and dashboard. The existing prefixes are IB_ and DT_ (each with its own lane), plus untagged SYSTEM-symbol events:
- **IB_**: the infinite-buy writer `Engine._log_event` (engine.py:4929) forces this prefix on every event.
- **DT_KS_ / DT_US_**: day-trade fills and orders (`_dt_event_type`, daytrade_engine.py:90).
- **Untagged SYSTEM-symbol events**: struct.py:2253/2304 and route/scheduler/controller.py:451/459 call `Engine._log_event` with symbol "SYSTEM", so they are also stored as IB_*. (Correction to an earlier claim: there is no un-prefixed "anything else" writer.)

Every reader filters by prefix:
- 거래이력 (history performance and fills): `substr(event_type,1,3)='DT_'` (history api.py:837).
- Dashboard realized P&L: `DomesticDaytradeEngine.period_trade_summary`, which reads `event_type__startswith="DT_"` (daytrade_engine.py:5218).
- Day-trade allocation score: DT_ only (daytrade_engine.py:3257).
- Order-log tab (`trade_logs`, history api.py:1473): all rows except an exact-name `_SYSTEM_EVENT_TYPES` blocklist. Rows are grouped per day by (symbol, event_type, action, message, order_price, order_qty).

**Recommended prefix: `COIN_`.** It is unused anywhere in src today (grep finds no COIN_, KRW- or 'coin' strings). Because it is not DT_ or IB_, coin rows never leak into the day-trade or infinite-buy P&L, fee books or allocation. Use event_type = `COIN_<detail>[_PENDING|_ERROR]`, where detail comes from the existing DT vocabulary (BUY, SELL_FULL, SELL_STOP_LOSS, SELL_MANUAL, SELL_PARTIAL), so `_DT_EVENT_LABELS` and `_exit_kind` can be reused.

Four hard schema facts:
- **Quantity is truncated.** `order_qty` and `filled_qty` are peewee IntegerField; peewee 3.19 `IntegerField.adapt` is `int(value)`, so 0.00123 BTC is stored as 0. The exact volume must go into the `raw_response` JSON (and the message), or a new REAL column must be added via `Struct._migrate_schema` (struct.py:2729).
- **Unknown columns are dropped.** ORM `insert` (season/model/orm.py:309-312) silently discards keys that are not columns, so fee, P&L, market and strategy must go in `raw_response`.
- **Use the full Upbit code as the symbol.** It must be the market code `KRW-BTC`. A bare `BTC` is classified as US by `_daytrade_market` (history api.py:111-122) and `_market_key` (daytrade_engine.py:63-74) because it is at most 8 alphabetic characters, and gets $ formatting. `KRW-BTC` falls through to the KS/KRW fallback because the hyphen fails `isalpha`.
- **Column length limits.** event_type ≤32, action ≤8, symbol ≤16, cycle_id ≤32, order_no ≤64 (an Upbit uuid is 36 characters).

**Retention** (`Struct._trim_trade_logs`, struct.py:2349-2386, constants at 2340-2347): rows whose event_type ends in `_RUN` or contains SKIPPED, ALREADY_SCHEDULED, MISSING_FOR_REBUILD or MISMATCH are archived and deleted after 14 days (3 days once the table passes 60,000 rows). `%ERROR%` rows go after 60 days. Everything else, including COIN_BUY, COIN_SELL_* and *_PENDING, is kept forever. LIVE trims from the policy dispatcher loop (struct.py:1129-1130) and PAPER from `_run_background_maintenance` (struct.py:2399-2403), at most every 6 hours per process. Any repeating coin event that matches none of those patterns grows the table without bound and slows the grouped log page; the struct.py:2335-2338 benchmark is 0.5 s at 100k rows and 5.7 s at 1M.

**Dashboard.** `profit_summary` is KRW-denominated (`currency="KRW"`, dashboard api.py:3154). Infinite-buy cycle P&L is converted from USD via `usd_to_krw`. Day-trade P&L comes from `period_trade_summary` `pnl_net`, which already sums KS (KRW) and US (USD) P&L without FX (daytrade_engine.py:5562); do not copy that. Coin P&L is KRW-native. Expose it as a separate `coin_realized_profit` field rather than folding it into `realized_profit`/`total_profit`, because the return denominators (`total_invested`/`base_asset`) and `total_asset` are KIS-only. If it is merged later, extend `_combine_profit_components` and `combined_daily_realized`, and bump the cached view key `broker-realized-v2` (dashboard api.py:2623).

- **C:\dev\stock8\src\portal\trading\model\db\trade_log.py** 12-29: trade_log model with these columns:
- id: CharField(32), random primary key.
- user_id
- cycle_id: CharField(32)
- symbol: CharField(16)
- event_type: CharField(32), indexed.
- action: CharField(8)
- order_no: CharField(64)
- order_price: Float
- order_qty: IntegerField
- filled_price: Float, nullable.
- filled_qty: IntegerField
- message: Text
- raw_response: Text
- created: DateTime, default _kst_now (naive KST).
  -> Do not change the existing columns.
- **Keep the volume exact.** The int columns truncate fractional coin volume, so put the exact volume (as a string, as Upbit returns it), funds, fee and P&L in raw_response JSON.
- **Optional REAL column.** If the history tab must show volume natively, add a column via Struct._migrate_schema (struct.py:2729-2766) following the ('trade_log','user_id',...) entry, e.g. ('trade_log','filled_volume','REAL DEFAULT 0.0'), plus a matching pw.FloatField on the model.
- **Timestamps.** Let `created` default to _kst_now. Never pass Upbit's created_at (ISO with +09:00); keep it in raw_response.order.created_at, or set raw['created_kst'], which history reads at api.py ~297.
- **C:\dev\stock8\src\portal\trading\model\struct\engine.py** 171-172, 4920-4967: Engine._log_event is the infinite-buy writer. It forces the IB_ prefix on every event (4932-4934).

Dedupe uses _LOG_REPEATS = sys.__dict__.setdefault('_stock8_ib_log_repeats', {}):
- The key is (uid, cycle_id, symbol, event_type, action).
- The signature is (day, message, order_no, order_price, order_qty).
- On a repeat it UPDATEs the first row's raw_response to {'repeat': n, 'last_at': ...} instead of inserting.
  -> Do NOT call trading.engine._log_event from the coin module. It would store IB_COIN_*, which history labels lane '무한매수' (api.py:1442) and formats in $ (api.py:1509 falls back to US for IB_).

Copy the dedupe idea into a coin-only helper with its own process-wide state:
- Use a module-level _COIN_LOG_REPEATS = sys.__dict__.setdefault('_stock8_coin_log_repeats', {}) (module level because of WIZ re-exec).
- Apply it ONLY to noise/status rows whose raw_response is empty. The repeat path overwrites raw_response (4945-4948), which would destroy fill data.
- Never dedupe rows that carry an order_no.
- **C:\dev\stock8\src\portal\trading\model\struct\daytrade_engine.py** 8741-8774 (_log_order_pending), 8776-8818 (_log_execution), 8820-8852 (_log_order_failure), 90-92 (_dt_event_type), 1454-1462 (_normalize_trade_action): These are the templates for order logging:
- **Pending:** event `<prefix>_<ACTION>_PENDING`, action 'PENDING', execution_status ACCEPTED_UNVERIFIED, filled_price/qty 0.
- **Fill:** event `<prefix>_<ACTION>`, e.g. DT_KS_BUY1 or DT_KS_SELL_STOP_LOSS; action normalized to BUY/SELL; filled_price/qty set.
- **Rejection:** event `<prefix>_<ACTION>_ERROR`, action 'ERROR', execution_status REJECTED.

All three:
- use cycle_id f'daytrade:{market.lower()}:{symbol}';
- store raw_response = json.dumps({symbol, market, name, action, strategy_id, qty, price, order, runtime, message}, ensure_ascii=False);
- write through self.struct.db('trade_log').insert(...) inside try/except, falling back to _append_runtime_log on failure.
  -> Create three matching coin methods: _log_coin_pending, _log_coin_fill and _log_coin_failure.
- event_type = f'COIN_{detail}' + ('' | '_PENDING' | '_ERROR').
- action is 'BUY'/'SELL'/'PENDING'/'ERROR'.
- cycle_id = f'coin:{market_code}' (e.g. 'coin:KRW-BTC').
- symbol = market_code.
- order_no = Upbit uuid.
- order_price = decision price (ticker trade_price).
- filled_price = Σtrades.funds / Σtrades.volume from get_order.
- order_qty / filled_qty = 0, since the exact volume lives in raw_response.

reuse the same raw_response key names so the history parsers work unchanged: action, strategy_id, execution_status, order, runtime.realized (gross), runtime.fee, runtime.matched_buy_amount, runtime.avg_buy_price, runtime.post_avg_price. Add volume (string), funds, fee, pnl_net, currency:'KRW' and market:'COIN'.
- **C:\dev\stock8\src\portal\trading\model\struct\daytrade_engine.py** 4546-4586: Day-trade fill message format. History parses it with _labeled_money('수수료') and ('순손익'). Example: f"{symbol} {action} 실행 | {qty}주 · 체결가 ₩{round(price):,} | 손익 ₩{gross:+,} | 수수료 ₩{fee:,} | 순손익 ₩{net:+,} | {reason}".
  -> Use the same '| 손익 ₩{gross:+,} | 수수료 ₩{fee:,} | 순손익 ₩{net:+,} |' layout, with gross/fee/net rounded to int KRW, and state the volume in text, e.g. '0.00123456 BTC'.

The sign must come after ₩ ('₩-1,234'). '-₩1,234' does not match the regex at history api.py:141-144.
- **C:\dev\stock8\src\portal\trading\model\struct\daytrade_engine.py** 2616-2658: _append_runtime_log keeps a per-market JSON file of at most 300 entries, deduplicated by dedup_sec=300 and held under a global lock. This is where day-trade puts high-frequency judgement and status lines instead of in trade_log.
  -> Send per-tick, scan and signal chatter from the coin loop to a similar file (e.g. data/live/coin/runtime_logs.json), not to trade_log. Write to trade_log only orders, fills, rejections, enable/halt transitions and low-frequency named noise.
- **C:\dev\stock8\src\portal\trading\model\struct\daytrade_engine.py** 83-88, 3253-3285, 5148-5218, 5562: DT_-only readers: _market_from_event_type, _recent_daytrade_allocation_performance (event_type__startswith='DT_') and period_trade_summary (reads DT_ at 5218, KS/US books, KIS broker merge, total_pnl_net at 5562 that mixes KRW and USD).
  -> Do not change anything; the COIN_ prefix keeps coin out. If coin used a DT_ prefix:
- 'KRW-BTC' would map to KS, so KS commission (1.5bps) and sell tax (18bps) would be applied.
- filled_qty would be int-truncated to 0, so the fill would be skipped.
- KIS broker sync could delete or merge rows.
- **C:\dev\stock8\src\portal\trading\model\struct.py** 103-110, 120-276 (insert 234-237), 640-660, 1043-1047, 2822-2827: trade_log is in USER_SCOPED_TABLES, so struct.db('trade_log') returns _UserScopedDb.
- insert() setdefaults user_id to the session user.
- rows() returns [uid] for a normal user, plus '' rows for an admin.

LIVE account_job runs under wiz.server.app.flask.test_request_context('/') with flask.session['id'] = owner, so background rows get the owner's user_id.
  -> Run the coin worker the same way: one LIVE-only thread created inside _ensure_live_policy_workers' registry or a sibling sys.__dict__ registry, inside test_request_context with session['id'] set to the admin owner. Coin rows then belong to the admin and are invisible to regular users (history _scoped_user_ids, api.py:778-786).

Alternatively, write user_id='' explicitly; those legacy-owner rows are visible only to admins.
- **C:\dev\stock8\src\portal\trading\model\struct.py** 2335-2347, 2349-2386, 2388-2396, 1129-1130, 2399-2403: _trim_trade_logs works as follows:
- **Noise** (_LOG_NOISE_SQL: event ends with '_RUN', or contains SKIPPED, ALREADY_SCHEDULED, MISSING_FOR_REBUILD or MISMATCH) is archived and deleted after 14 days.
- **Errors** ('%ERROR%') go after 60 days.
- **Soft cap:** if count > 60000, noise older than 3 days is trimmed.
- **Archive:** deleted rows are appended to <db dir>/log-archive/trade_log-YYYYMMDD.jsonl.gz.
- **Schedule:** _maybe_trim_trade_logs runs at most every 6 hours per process (sys.__dict__['_stock8_log_trim']). LIVE calls it from the policy dispatcher loop and PAPER from background maintenance.
  -> Name coin events to fit these rules:
- **Ledger (kept forever):** COIN_BUY, COIN_SELL_*, COIN_*_PENDING, COIN_ENABLED, COIN_DISABLED, COIN_HALT. These must never contain ERROR, SKIPPED or MISMATCH and must not end in _RUN.
- **Noise (14 days):** COIN_SCAN_RUN, COIN_BUY_SKIPPED, COIN_BALANCE_MISMATCH.
- **Errors (60 days):** COIN_BUY_ERROR, COIN_SELL_*_ERROR, COIN_API_ERROR.

Avoid names like COIN_BUY_DRY_RUN for real records, because they are deleted after 14 days.

Add COIN rows to the fixture in C:\dev\stock8\tests\test_trade_log_retention.py to lock this in.
- **C:\dev\stock8\src\app\page.history\api.py** 1388-1442 (_LOG_COLUMNS, _SYSTEM_EVENT_TYPES, _DT_EVENT_LABELS, _IB_EVENT_LABELS, _event_label): _event_label returns (label, tone, lane).
- **DT_ branch:** uses event[6:], strips _ERROR (' 거절', tone error) or _PENDING (' 접수', tone pending), and looks up _DT_EVENT_LABELS.
- **Everything else:** title-cased label, tone from ERROR/CANCEL/MISMATCH/BUY/SELL, and lane '무한매수' if IB_, else '시스템'.
- **Default log view:** excludes the exact names in _SYSTEM_EVENT_TYPES.
  -> Add a COIN_ branch before the generic one:

if event.startswith('COIN_'):
    body, suffix, tone = event[5:], '', ''
    if body.endswith('_ERROR'): body, suffix, tone = body[:-6], ' 거절', 'error'
    elif body.endswith('_PENDING'): body, suffix, tone = body[:-8], ' 접수', 'pending'
    tone = tone or ('buy' if body.startswith('BUY') else 'sell' if body.startswith('SELL') else 'info')
    return _DT_EVENT_LABELS.get(body, body) + suffix, tone, '코인'

Also append the coin noise names (COIN_SCAN_RUN, COIN_BUY_SKIPPED, COIN_BALANCE_MISMATCH) to _SYSTEM_EVENT_TYPES. Without that change, COIN_BUY shows as label 'Coin Buy', lane '시스템'.
- **C:\dev\stock8\src\app\page.history\api.py** 1446-1470 (_LOG_GROUP_KEY, _LOG_REPEAT_SQL, _grouped_log_rows), 1473-1512 (trade_logs): _grouped_log_rows groups trade_log rows by (day, symbol, event_type, action, message, order_price, order_qty).
- repeat = sum of json_extract(raw_response,'$.repeat') when that key is present, else 1.
- Selected columns exclude raw_response.

trade_logs filters:
- kind=error: event LIKE '%ERROR%' OR action IN ('ERROR','SKIP').
- default: NOT IN _SYSTEM_EVENT_TYPES.
- symbol: exact match.
- search: LIKE on message, event_type and symbol.

At line 1509 it sets row['market'] = _daytrade_market(event, symbol, 'US' if IB_ else 'KS').
  -> In trade_logs, set row['market'] = 'COIN' when the event starts with COIN_, so the view can format KRW with decimals.

To show the exact coin volume in this tab, either:
- put it in the message, or
- add "json_extract(raw_response,'$.volume') AS volume" (aggregated with max) to the inner SELECT and to the columns tuple.

Coin raw_response must never contain a top-level 'repeat' key, which would inflate the count.

Keep coin action values inside ('BUY','SELL','PENDING','ERROR','SKIP') so the error filter works.
- **C:\dev\stock8\src\app\page.history\api.py** 837-848 (_DT_FILL_WHERE/_daytrade_log_rows), 282-372 (_daytrade_record_from_log), 85-102 (_is_executable_daytrade_record), 1045-1154 (_closed_trades), 1192-1212 (_fill_row), 1214-1315 (_build_trades_payload), 1317-1330 (trades), 971-977 (_STRATEGY_LABELS), 1030-1035 (_estimated_fee): 거래이력 (performance and fills) is built only from DT_ rows (excluding _ERROR), day-trade state, and cycle_trade. Several steps assume integer quantities and only the KS/US markets:
- quantity is cast to int (_safe_int) at lines 95, 1059 and 1206;
- market is collapsed to 'US' or 'KS' at lines 1057 and 1193;
- the summary loops over ('KS','US') only (1248);
- daily buckets are {'KS','US'} (1288);
- the trades() whitelist is ('','KS','US') (1322);
- _estimated_fee uses the KS stock fee and tax for any non-US market.

Coin rows are therefore currently absent, which is safe.
  -> Use a separate coin path. Do not feed coin rows into _closed_trades.
- Add _coin_log_rows with where "substr(event_type,1,5)='COIN_' AND action IN ('BUY','SELL')" through _json_rows (same columns as _DT_LOG_COLUMNS).
- Build one trip per COIN_SELL row directly from raw_response: entry=avg_buy_price, exit=filled_price, volume (float), cost=matched_buy_amount, fee, net=pnl_net. The engine must log all of these on every sell.
- Then extend these places with 'COIN' (currency 'KRW'): summary keys (1248), daily bucket keys (1288), the market whitelist (1322), _STRATEGY_LABELS for the coin strategy ids, and a coin-aware _fill_row that keeps float qty.
- The tabs stay admin-only via view.ts showDaytrade (10-15).
- **C:\dev\stock8\src\app\page.history\view.ts** 10-15, 22, 135-137, 172-183, 341-357, 389-391: These front-end helpers assume only the KS and US markets:
- the admin gate showDaytrade (10-15);
- markets=[''/KS/US] (22);
- summaryMarkets and dailyMarkets are hard-coded to ['KS','US'];
- money() and price() print $ only for 'US' and otherwise Math.round KRW, so sub-₩1 coins show ₩0;
- marketLabel shows 'US' as 미장 and everything else as 국장.

view.pug:365-368 shows '{{filled_qty || order_qty}}주', or '-' when 0.
  -> Add 'COIN' (label '코인'):
- add it to markets, summaryMarkets, dailyMarkets and marketLabel;
- in price() and money(), show decimals when market === 'COIN' and the value is below 100;
- show the coin volume with its unit instead of '주'.

Avoid writing the literal 'export class Component' anywhere new (WIZ rewrite quirk).
- **C:\dev\stock8\src\app\page.history\api.py** 37-46, 141-197, 1332-1343: Message and payload parsing helpers:
- _sanitize_user_log_message strips '(... qty=|price=|exchange=|tr_id ...)' groups and everything after '| symbol='.
- _labeled_money and _realized_from_payload read realized/fee/pnl_net keys from runtime, raw, order and row.
- symbols() lists distinct symbols from etf_watchlist, trading_cycle, cycle_trade and trade_log.
  -> In coin messages, never put 'qty=' or 'price=' inside parentheses and never use '| symbol='; that text would be hidden.

KRW-* symbols will automatically appear in the log and cycle symbol dropdowns. The log filter works with them; the cycle filter will just come back empty.
- **C:\dev\stock8\src\app\page.dashboard\api.py** 526-537 (_combine_profit_components), 2620-2661 (_fast_profit_summary, key 'broker-realized-v2' at 2623, store only when aggregation_complete at 2640-2641), 2663-3195 (_profit_summary_data: usd_to_krw 2729, period_trade_summary 2826-2861, combine 2896, payload 3152-3195 currency='KRW'): profit_summary realized P&L is the sum of two components:
- infinite-buy cycle P&L, converted from USD to KRW;
- day-trade pnl_net from period_trade_summary (DT_ only).

Returns use total_invested/base_asset, which are KIS-based. The rendered view is cached in profit_cache under a versioned name and written only when aggregation_complete (daytrade broker_sync_ok) is true.
  -> Leave it unchanged for v1; coin is already excluded.

To show coin P&L, add a separate block that sums raw_response pnl_net of COIN_SELL rows within filter_from/filter_to. Read them via a direct SQL json_extract, like history's _json_rows, rather than ORM rows() of the whole table. Then:
- return coin_realized_profit, coin_trade_count and coin_daily_breakdown as NEW keys;
- wrap the block in try/except so a coin failure cannot flip aggregation_complete;
- do NOT add it to realized_profit/total_profit unless total_asset also includes Upbit balances.

If you do merge it later:
- add a coin_realized_profit=0.0 parameter to _combine_profit_components;
- add coin values into combined_daily_realized;
- bump 'broker-realized-v2' to 'broker-realized-v3' so cached views are not mixed;
- add zero defaults in view.ts (143-149, 314-321).
- **C:\dev\stock8\src\app\page.dashboard\api.py** 1491-1497 (_safe_recent_logs), 2218-2222, 2459/2540-2548 (cycle_detail logs by cycle_id); view.ts 580-591, 1061-1086: The overview shows the last 20 trade_log rows of any type for the user. The view turns new rows into toasts titled '{symbol} - {event_type}', tinting them by error/sell/buy substrings. cycle_detail lists logs by cycle_id.
  -> Coin fills will appear and toast automatically, e.g. 'KRW-BTC - COIN_BUY'. High-frequency coin rows would push infinite-buy and day-trade events out of the 20-row list and spam toasts, so keep noise out of trade_log or deduplicate it (the repeat update does not change `created`). Use cycle_id 'coin:KRW-BTC' so it never collides with trading_cycle ids.
- **C:\dev\stock8\src\portal\trading\model\upbit_api.py** 130-152: Order methods: buy_market_krw (ord_type=price, minimum ₩5,000), sell_market (volume string to 8 decimals), get_order(uuid), cancel_order. The POST returns a uuid only; fills must be read via get_order.
  -> Logging sequence:
1. Log COIN_<detail>_PENDING with order_no=uuid right after the POST.
2. Poll get_order, then log COIN_<detail> with avg price = Σtrades[].funds / Σtrades[].volume, volume = executed_volume, fee = paid_fee.
3. On exception, log COIN_<detail>_ERROR.

Treat executed_volume > 0 as filled, not only state == 'done'. My understanding of Upbit (not verified against this code) is that a market bid by price can end in state 'cancel' with a partial fill and a refund. Check this against a real get_order response before relying on it.
- **C:\dev\stock8\src\portal\season\model\orm.py** 111-122, 284-312: _build supports only the `field__startswith` suffix. Other `__xxx` kwargs (e.g. __in, __isnull) are silently dropped and return the whole table. insert() keeps only keys that are model columns and generates a random 32-character id.
  -> Coin readers should use rows(event_type__startswith='COIN_', orderby='created', order='DESC', dump=N), or raw SQL through history's _json_rows/_execute_one pattern (api.py:788-829) for anything heavier.

## patterns
- Coin fill insert (mirrors daytrade_engine.py:8800-8816):

self.struct.db('trade_log').insert({'cycle_id': f'coin:{mkt}', 'symbol': mkt, 'event_type': f'COIN_{detail}', 'action': 'BUY' if detail.startswith('BUY') else 'SELL', 'order_no': uuid, 'order_price': decision_price, 'order_qty': 0, 'filled_price': avg_fill, 'filled_qty': 0, 'message': msg, 'raw_response': json.dumps(payload, ensure_ascii=False)})

mkt is e.g. 'KRW-BTC'. order_qty and filled_qty stay 0 because the columns are IntegerField; the exact volume lives in raw_response.
- raw_response payload for COIN fills, reusing the key names history already parses:

{'symbol': 'KRW-BTC', 'market': 'COIN', 'exchange': 'UPBIT', 'currency': 'KRW', 'name': 'BTC', 'action': detail, 'strategy_id': 'coin_<id>', 'execution_status': 'FILLED', 'volume': '0.00123456', 'funds': 123456.0, 'price': avg_fill, 'fee': paid_fee_krw, 'avg_buy_price': entry_avg, 'matched_buy_amount': cost_basis_incl_buy_fee, 'realized': gross_krw, 'pnl_net': net_krw, 'post_position_volume': '0.0', 'created_kst': fill_ts_kst, 'order': {get_order subset: uuid, ord_type, state, executed_volume, paid_fee, trades_count}, 'runtime': {'realized': gross_krw, 'fee': fee_krw, 'post_avg_price': avg_after, 'reason': signal_reason}}
- Message format parsed by history (_labeled_money, api.py:141):

f"{mkt} {detail} 실행 | {volume} {base} · 체결가 ₩{price:,.0f} · 체결금액 ₩{round(funds):,} | 손익 ₩{gross:+,} | 수수료 ₩{fee:,} | 순손익 ₩{net:+,} | {reason}"

Compute gross, fee and net as ints first.
- Event catalog:
- Fills: COIN_BUY, COIN_SELL_FULL, COIN_SELL_STOP_LOSS, COIN_SELL_MANUAL, COIN_SELL_PARTIAL. These reuse _DT_EVENT_LABELS and _exit_kind; put '익절' or '목표가' in the message for target exits.
- Pending: COIN_<detail>_PENDING with action 'PENDING'.
- Rejection: COIN_<detail>_ERROR with action 'ERROR'.
- Lifecycle (kept forever): COIN_ENABLED, COIN_DISABLED, COIN_HALT.
- Noise (trimmed after 14 days): COIN_SCAN_RUN, COIN_BUY_SKIPPED, COIN_BALANCE_MISMATCH.
- Process-wide state lives at module level (WIZ re-exec resets class attributes):

_COIN_LOG_REPEATS = sys.__dict__.setdefault('_stock8_coin_log_repeats', {})

This mirrors engine.py:4927 and daytrade_engine.py:24.
- Run the worker under the LIVE owner session (struct.py:1043-1047):

with wiz.server.app.flask.test_request_context('/'): flask.session['id'] = owner; trading = Struct(); ...

All trade_log inserts then carry the admin's user_id.
- History lane branch:

if event.startswith('COIN_'): ... return label, tone, '코인'

In trade_logs, set row['market'] = 'COIN' for COIN_ rows (api.py:1421-1442, 1509).
- Read coin rows with a prefix SQL filter, never a full-table ORM read:

_json_rows(trading, 'trade_log', _DT_LOG_COLUMNS, where="substr(event_type,1,5)='COIN_' AND action IN ('BUY','SELL')", limit=N)

This follows history api.py:811-848.
- Retention test: extend C:\dev\stock8\tests\test_trade_log_retention.py with old COIN_SELL_STOP_LOSS rows (must remain), COIN_SCAN_RUN rows (trimmed after 14 days) and COIN_BUY_ERROR rows (trimmed after 60 days). Test the dedupe helper like C:\dev\stock8\tests\test_log_repeats.py, and history labels/trips via the AST loader in C:\dev\stock8\tests\test_history_trades.py.

## pitfalls
- filled_qty and order_qty are IntegerField. peewee 3.19 IntegerField.adapt does int(value) (verified in .venv/Lib/site-packages/peewee.py:4901-4908), so fractional coin volume is stored as 0. History's _is_executable_daytrade_record (api.py:95-99) and _closed_trades (1059) then drop the record, and the log tab shows '-'. Keep the exact volume in raw_response (or add a REAL column via _migrate_schema).
- The symbol must be the Upbit market code 'KRW-BTC'. A bare 'BTC' is at most 8 alphabetic characters, so _daytrade_market (history api.py:118-120) and _market_key (daytrade_engine.py:72-73) classify it as US and show $ prices.
- Never use the DT_ prefix. period_trade_summary (daytrade_engine.py:5218), the allocation score (3257) and history 거래이력 (api.py:837) would ingest it: KRW-BTC would be treated as KS with the 0.015% commission plus 0.18% stock sell tax, quantities would be int-truncated, and KIS broker sync could merge or delete the rows.
- Never call trading.engine._log_event for coin events. It forces an IB_ prefix (engine.py:4932-4934), so history shows lane '무한매수' and the US market fallback (api.py:1442, 1509).
- The _LOG_REPEATS-style dedupe overwrites raw_response with {repeat, last_at} (engine.py:4945-4948). Only dedupe rows with empty raw_response and no order_no, never fills. A coin raw_response must not have a top-level 'repeat' key, because _LOG_REPEAT_SQL (history api.py:1447) would read it as a repeat count.
- Trim side effects:
- An event name containing ERROR, SKIPPED or MISMATCH, or ending in _RUN, is deleted after 60 or 14 days (e.g. 'COIN_BUY_DRY_RUN', 'COIN_FILL_AFTER_ERROR').
- Repeating events that match none of these are never trimmed, so the 60k soft cap cannot reclaim space and the grouped log page slows (0.5 s at 100k rows, 5.7 s at 1M; struct.py:2335-2338).
- The ORM insert silently drops non-column keys (orm.py:309-312), so passing fee=, pnl=, market= or strategy_id= at top level loses them; they must go in raw_response.
- action is VARCHAR(8) and event_type VARCHAR(32). Keep action in {'BUY','SELL','PENDING','ERROR','SKIP'} so the history kind=error filter (api.py:1483-1484: action IN ('ERROR','SKIP')) and the _normalize_trade_action mapping keep working.
- _sanitize_user_log_message (history api.py:37-46) removes '(... qty=... )' and '| symbol=...' fragments, so coin messages must not rely on them.
- _labeled_money needs the sign after the currency symbol ('순손익 ₩-1,234'). '-₩1,234' parses as 0.
- LIVE and PAPER use separate DBs (data/live vs data/paper trading.db). COIN rows from the LIVE-only worker never appear on PAPER :3002 history or dashboard. PAPER verification therefore needs fixture or dry-run rows (named so they are not trimmed) and cannot use real Upbit fills.
- The dashboard profit view is cached under 'broker-realized-v2' (dashboard api.py:2623) and stored only when aggregation_complete is true (2640-2641). If coin fields are added: bump the key, and make sure a coin read failure cannot raise inside _profit_summary_data. Folding coin into realized_profit/total_return would skew returns, because the denominators and total_asset are KIS-only.
- The dashboard overview shows the newest 20 trade_log rows and toasts new ones (dashboard api.py:1491-1497, view.ts 1061-1086). Chatty coin rows push out infinite-buy and day-trade events and spam toasts, so route per-tick output to a runtime JSON file like _append_runtime_log (daytrade_engine.py:2616-2658).
- Do not pass Upbit created_at into the `created` column. History assumes naive KST (_to_kst_string, assume_naive_kst). Let `created` default to _kst_now, or use the same naive KST.
- Run the worker under a session (flask.session['id'] = admin owner), as in struct.py:1043-1047. With no session, user_id becomes '' (legacy owner rows): visible to every admin, invisible to regular users. Run it under the owner's session so ownership is explicit.

# CRITIC
## missing
- i18n (src/portal/trading/libs/i18n.ts): nav 키는 en 5-13줄, ko 414-422줄에 있습니다. 'nav.daytrade'(10/419줄)는 정의만 있고, 실제 단타 링크는 component.nav.trading/view.pug:28에 '단타'로 하드코딩되어 있습니다. `t('nav.coin')`을 쓰려면 en·ko 두 사전에 모두 넣어야 합니다. i18n.ts:830 `t()`는 없는 키를 키 문자열 그대로 돌려주므로 화면에 'nav.coin'이 보입니다. '코인'을 하드코딩하면 i18n 수정은 필요 없습니다.
- 온보딩 가이드: 맵에 언급이 없습니다. component.onboarding.guide는 layout.trading/view.pug:18에서 모든 사용자에게 렌더되고, 퀘스트는 api.py:65-80(api/firegate/cycle/auto)에 있습니다. 코인 퀘스트나 진행 키는 추가하지 않아야 합니다(관리자 전용 기능이 일반 사용자 가이드에 노출됨). onboarding_progress(struct.py:100)도 건드리지 않습니다.
- 테스트 계정 격리: 코인 상태 파일(data/live/coin/...)은 사용자 스코프 테이블(USER_SCOPED_TABLES, struct.py:103-110)이 아닙니다. 그래서 daytrade_engine.py:365-408의 `_daytrade_state_visible` / `_save_state_map`처럼 비관리자의 읽기와 쓰기를 막아야 합니다. 10-20 격리 사고(신규 PAPER 사용자가 관리자의 단타 32건을 봄)와 같은 유형입니다. 테스트 템플릿은 tests/test_paper_state_isolation.py:27-41입니다. 대시보드에 coin_realized_profit을 넣는다면 그것도 관리자 전용으로 해야 합니다. 검증 항목: 일반 사용자 테스트 계정(data/paper/test-accounts.local.json)으로 3001에서 /wiz/api/page.coin/*가 403인지, component.nav.trading/coin_access_status가 is_admin=false인지 확인합니다.
- 브로커 경계의 주문 가드: KIS는 LIVE에서 non-GET /trading/ 호출마다 kis_api.py:510-520에서 `order_policy.assert_order()`를 강제하고, PAPER에서는 kis_api.py:500-509에서 실서버 주문을 막습니다. UpbitApi._request(upbit_api.py:74-97)에는 이런 단일 관문이 없어서, buy_market_krw/sell_market/cancel_order(130-152)를 누가 호출하든 바로 주문이 나갑니다. 맵은 엔진에서 다시 확인하라고만 합니다.
- 코인 정책 행을 업비트 계정에 묶는 문제: order_policy._key()(order_policy.py:63-69)는 provider+계좌 해시이고, account_job은 매 루프 `_key() != policy_key`이면 'account_changed'로 끝납니다(struct.py:1055-1057). 맵 #3의 단일 전역 키 `coin_policy_v1`로는 업비트 키를 다른 계정으로 바꿔도 ON 상태가 그대로 이어집니다.
- 상태 저장소와 원자적 쓰기: 코인 포지션, 쿨다운, 일 손익, 진행 중 주문 uuid를 어디에 저장할지 맵에 없습니다. 단타는 data/<mode>/daytrade/<live_data_scope>/live_state.json(daytrade_engine.py:19, 55-61, 392-408)을 쓰는데, fs.write.json은 open('w') 후 write라 원자적이지 않습니다(season/util/filesystem.py:124-137). 쓰는 중에 죽으면 파일이 잘리고, 다음 읽기에서 default {}가 되어 포지션을 잊습니다. 코인 상태는 data/live/coin/ 아래에 둬야 합니다. .gitignore:125 `data/live/`에 걸리기 때문이며, data/coin/은 무시 대상이 아닙니다. live_data_scope(struct.py:1022-1026)는 KIS 계좌 해시이므로 쓰면 안 됩니다.
- 하드락 확장(주문 한도): order_policy.assert_order는 LIVE에서 종목이 기본 잠금이고(order_policy.py:190 `state['symbols'].get(symbol, self.live)`), 해당 레인이 ON인지도 확인합니다(192-193). 코인 맵은 ON/owner만 다룹니다. 코인에도 필요한 것: 마켓 허용 목록(기본 잠금), 일일 손실 한도 중단(LIVE KS의 ₩50,000 한도에 해당), 1회 최대 주문금액, 진행 중 주문 락. 단타 `_global_lock`(daytrade_engine.py:276-289)과 tests/test_daytrade_order_serialization.py:7-42의 세 가지 불변식이 참고 대상입니다.
- supervisor 스크립트의 env: 단타 하드락은 start-stock8-live.ps1:21과 start-stock8-paper.ps1:48에서 명시적으로 설정됩니다. 코인용 env(잠금/opt-in)도 두 스크립트에 명시해야 하고 PAPER는 항상 잠가야 합니다. 주의: env는 supervisor PowerShell이 시작할 때 한 번만 설정되고, 그 뒤 루프가 wiz.exe를 다시 띄웁니다(live.ps1:13-38). 그래서 메모리의 재시작 절차(wiz.exe 자식만 kill)로는 새 env가 들어가지 않고, supervisor 프로세스 자체를 재시작해야 합니다. compose.yaml:17 `TRADING_MODE: ${TRADING_MODE:-PAPER}`로 도커 배포도 LIVE로 띄울 수 있습니다.
- 재빌드/배포 캐시: scripts/rebuild-stock8-frontend.ps1:61-68은 bundle/www와 bundle/src를 함께 바꾸므로 LIVE에 새 nav와 페이지가 바로 나갑니다. 하지만 컴파일된 코드는 캐시됩니다. api.py는 plugin/workspace/model/app.py:33-39('app.api.code#main'), 모델은 season/lib/core/wiz.py:40-48('model.code#main')에 캐시되어, struct.py의 워커 훅은 LIVE를 재시작해야 반영됩니다. page.coin/api.py는 첫 요청 때 컴파일되므로 그 뒤 수정도 재시작이 필요합니다. 메모리 규칙상 재빌드는 Git Bash가 아닌 PowerShell 도구로 실행합니다.
- 유지보수와의 상호작용: maintenance.py:130-163 `remove_incomplete_trade_entries`는 LIVE에서 7일 지난 PENDING cycle_trade를 삭제합니다. rebuild_daily_summaries(169-221)는 cycle_trade/trading_cycle로 daily_trade_summary를 만듭니다. 따라서 코인 기록을 cycle_trade/trading_cycle에 넣으면 안 됩니다. 스케줄러 라우트(src/portal/trading/route/scheduler/controller.py:238-251)는 scheduler_token이 없으면 인증이 없고, 493-496줄에서 `struct.trading`을 생성하므로 LIVE에서 코인 워커 ensure가 실행될 수 있습니다. 한 번만 claim하는 구조라 무해해야 하고, 스케줄러에 코인 액션을 추가하면 안 됩니다.
- 백업: scripts/create_private_recovery_backup.sh:31-37은 config/와 data/만 담고, secret_box 키(~/.stock8/config.key, secret_box.py:22-26)는 담지 않습니다. 이 백업으로 복원하면 업비트 키가 ''로 복호화됩니다(secret_box.py:68-77). 이때 코인 워커는 '키 없음'으로 주문 0건(fail-closed)이어야 하고, UI는 '미등록'을 표시해야 합니다.
- 문서: AGENTS.md:35는 문서를 실동작 기준으로 유지하라고 합니다. docs/operations.md:38-45의 주문 게이트 체크리스트에 코인 레인을 추가해야 합니다. 관리자 전용이므로 docs/user-guide에는 넣지 않습니다.
- 누락된 테스트: (a) tests/test_upbit_api.py. test_secret_config.py:18-21의 `_load`로 upbit_api.py를 exec하고 `api._session`을 가짜로 바꿔 JWT/query_hash, 최소 5,000원, 매도 수량 포맷, 4xx→UpbitError 매핑, non-GET 가드 차단을 검증합니다. (b) test_paper_worker_owner.py:171-182의 StructDouble에는 `_ensure_live_coin_worker`가 없습니다. PAPER 경로가 이를 호출하면 AttributeError가 나도록 그대로 두어 카나리아로 씁니다. (c) test_live_dispatch_filter.py:15-16은 `_ensure_live_policy_workers` 안의 첫 `.rows` 호출을 집습니다. 그래서 코인 코드는 그 메서드 밖에 둡니다. (d) 컨트롤러 게이트 테스트와, page.coin의 모든 public def가 가드되는지 보는 AST 테스트. (e) test_trade_log_retention.py에 COIN_ 행 추가. (f) 정책 키를 계정에 묶고, 계정이 바뀌면 워커가 종료되는지.
- 의존성: requirements.txt에 requests가 명시되어 있지 않습니다(yfinance의 전이 의존뿐). upbit_api.py:20-23은 import에 실패하면 requests=None으로 두고, 호출할 때 'requests 라이브러리가 없습니다' 오류를 냅니다. 명시하는 것을 권장합니다. 로컬 dev .venv에는 cryptography도 없어서(requirements.txt:7에는 있음) secret 관련 테스트가 로컬에서는 skip됩니다.
- upbit_api.py는 git에서 untracked 상태입니다(`?? src/portal/trading/model/upbit_api.py`). 기능 PR에 함께 커밋해야 하며, 맵의 어디에도 이 점이 없습니다.
## wrong
- 맵 #2의 touchpoint 'src/controller/user.py lines 20-24'와 '/daytrade 페이지 경로를 _current_user_is_admin으로 막는 게이트(403)', 그리고 '`request.path == /coin` 게이트 추가' 권장은 틀립니다. 실제 줄은 17-21이고, 이 게이트는 페이지를 직접 로드할 때도 실행되지 않습니다. ServiceHandler.route(season/lib/binding/handler/service.py:7-20)는 plugin filter만 돌린 뒤 bundle/www/index.html을 컨트롤러 없이 내려줍니다. filter(C:\stock8-runtime2\app\plugin\workspace\filter.py:3-21)가 컨트롤러를 실행하는 경우는 두 가지뿐입니다. 하나는 /wiz/api/* 디스패치이고, 다른 하나는 bundle/src/route 앱(plugin/workspace/model/route.py:26-35)인데, 그 앱은 auth, pwa.swjs, scheduler, seo.robots, seo.sitemap 다섯 개뿐입니다.
- 맵 #4의 'Hard page loads: the only admin gate is a path check in src/controller/user.py:17-21', 'This only covers direct page loads', 그리고 패턴 'Controller gate ... if request.path == /coin ...'은 같은 이유로 틀립니다. 직접 로드도 막지 못하며, '/coin' 경로 검사로는 아무것도 막을 수 없습니다. 효과가 있는 것은 '/wiz/api/page.coin/' 접두 검사이거나, page.coin/app.json에 지정한 컨트롤러입니다(맵 #1의 결론이 맞음).
- 맵 #4의 pitfall 'page.daytrade has a 0-byte view.html next to view.pug'는 틀립니다. src/app/page.daytrade/view.html은 71,630바이트로, 6월 29일에 커밋된 오래된 컴파일 HTML입니다. component.nav.trading/view.html(9,471바이트)도 같은 상황입니다. 그래서 편집 대상은 view.pug라는 맵 #1의 설명이 맞습니다.
- 맵 #1과 #4의 user.py 스니펫(`wiz.model('struct').trading._current_user_is_admin(...)`)은 결과는 맞지만, 비용이 싸다는 암시는 틀립니다. wiz.model은 호출마다 모듈을 다시 실행하고(season/lib/core/wiz.py:36-52), portal/trading/model/struct.py 끝의 `Model = Struct()`가 매번 Struct.__init__(struct.py:575-610)을 돌립니다. __init__은 `_migrate_schema`의 ALTER TABLE 약 20개, `_seal_daytrade_runtime`, `_encrypt_plain_secrets`, `_ensure_background_worker`를 실행합니다. 이것이 5초 폴링되는 코인 API 호출마다 한 번씩 더해집니다. 사용자 정보만 필요하면 `wiz.model('struct').user.get(id=...)`(src/model/struct/user.py:55-66)로 충분합니다.
- 맵 #1의 'LIVE workers ... re-check admin on every tick (1060)'은 줄 번호가 하나 어긋납니다. 확인은 struct.py:1061의 `policy.get(lane) is True and (lane == 'infinite_buy' or trading.order_policy.daytrade_allowed())`에서 일어나고, 계정 변경 시 종료는 1055-1057입니다. 경미합니다.
- 맵 #3의 'boot ... loads struct ... then calls worker_status()'는 단계 하나가 빠져 있습니다. boot-local-paper.py:23-27(런타임 config/boot.py와 동일하며 diff 결과 일치)은 그 사이에 `resume_paper_worker()`를 먼저 호출합니다. LIVE에서는 struct.py:990 때문에 ''을 돌려줍니다. 또 worker_status 자체가 `_ensure_background_worker`를 다시 호출합니다(struct.py:2649). 결론(부팅 때 로그인 없이 LIVE 워커 ensure가 실행됨)은 맞습니다.
## risks
- 관리자 게이트의 위치. 공용 user.py(모든 페이지의 컨트롤러)에 접두 검사를 넣으면 범위가 넓어집니다. 맵의 스니펫은 호출마다 무거운 trading Struct를 만듭니다. 맵이 제안한 allowlist 가드 루프는 이미 한 번 어긋난 이력이 있습니다(page.daytrade.us/api.py:877 us_momentum_candidates가 1127-1141 목록에 없고, AST로 확인함). api.py의 밑줄 헬퍼까지 포함한 모든 module-level callable이 HTTP로 호출 가능합니다(filter.py:12-13, util/compiler.py:21-38은 인자를 None으로 넘김).
  -> src/controller/coin.py를 새로 만들고(admin.py:3-8 패턴, `class Controller(wiz.controller("user"))`) page.coin/app.json의 controller로 지정합니다. 그 안에서 `wiz.model("struct").user.get(id=wiz.session.get("id"))`로 role=='admin'이거나 지정 이메일인지 확인하고, 아니면 `wiz.response.status(403, message='코인은 관리자 전용 기능입니다.')`를 냅니다. 이렇게 하면 함수 lookup 전에 모든 함수가 막히고, user.py와 무거운 `.trading` 생성도 피합니다. api.py 함수마다 try 밖 첫 줄에서 `_require_coin_access()`를 부르는 것은 2차 방어로 두고, public def 전체가 가드되는지 AST 테스트로 확인합니다.
- '정확히 한 프로세스'를 TRADING_MODE 하나로만 보장하는 문제. 다음 경우에 두 번째 LIVE 프로세스가 생길 수 있습니다: compose.yaml:17 도커를 LIVE로 띄울 때, 수동 `wiz run`, start-stock8.ps1:5-9가 두 번 실행되어 LIVE supervisor 두 개가 3001 바인딩을 경쟁할 때(boot의 warm 스레드는 2초 뒤 시작). 맵의 STOCK8_COIN_HARD_LOCK은 기본값이 'false'라 열린 상태(fail-open)입니다.
  -> 세 겹으로 막습니다. (1) `not PAPER_MODE`. (2) 명시적 opt-in env(예: STOCK8_COIN_WORKER=1)를 scripts/start-stock8-live.ps1에만 설정하고, 기본은 꺼짐으로 둡니다. (3) 워커가 사는 동안 data/live/coin/worker.lock에 비차단 OS 파일락을 잡습니다(kis_api.py:88-136의 msvcrt.locking/fcntl 패턴). 락을 못 잡으면 status='locked_elsewhere'로 두고 주문은 0건입니다. env를 바꾼 뒤에는 wiz.exe만이 아니라 supervisor 자체를 재시작해야 합니다.
- 주문 단일 관문이 없음. UpbitApi는 호출되는 즉시 실제 주문을 냅니다(upbit_api.py:130-152). 엔진, 수동 매도 엔드포인트, 앞으로 추가될 코드 중 하나라도 재확인을 빠뜨리면 OFF 상태에서도 주문이 나갑니다. AGENTS.md:32는 'OFF는 무동작'을 요구합니다.
  -> kis_api.py:510-520과 같은 구조로, UpbitApi 생성자에 guard callable을 받게 합니다. `_request`에서 method != 'GET'이면 guard()를 반드시 호출하고, guard가 없으면 무조건 차단합니다(fail-closed). guard는 DB에서 코인 정책 행을 새로 읽어 다음을 모두 확인합니다: enabled is True, owner가 여전히 관리자, 마켓 잠금 해제, 일일 손실 미초과, TRADING_MODE=='LIVE', opt-in env. 하나라도 어긋나면 raise합니다. 엔진 쪽 재확인은 그 위에 한 번 더 둡니다.
- 중복 주문. upbit_api.py:84-89는 타임아웃이 8초이고 `identifier`(클라이언트 주문 ID)를 보내지 않습니다. POST가 타임아웃되면 주문이 실제로 들어갔는지 알 수 없고, 다음 패스나 재시작 후에 재시도하면 이중 매수가 됩니다. 시장가 금액 매수는 일부 체결 뒤 state가 'cancel'로 끝날 수 있다는 맵 #5의 설명은 실제 응답으로 검증되지 않았습니다.
  -> 주문마다 uuid4 identifier를 만들고, POST 전에 상태 파일에 in_flight로 기록하고 COIN_<detail>_PENDING 로그를 남깁니다. 실패하거나 타임아웃되면 다시 보내지 않고 `GET /v1/order?identifier=`로 확정합니다. get_order가 identifier를 받도록 확장하되, 업비트 문서와 실제 응답으로 확인한 뒤 씁니다. 체결 판단은 executed_volume > 0 기준으로 합니다. 프로세스 전역 비차단 주문 락은 sys.__dict__에 두고, 진행 중 uuid가 있으면 새 주문을 막습니다(test_daytrade_order_serialization.py의 세 불변식을 그대로 적용).
- 업비트 키를 저장하는 방식. USER_SCOPED_CONFIG_KEYS에 넣고 set_config로 저장하면, 관리자일 때 struct.py:733-736이 전역 'upbit_access_key'/'upbit_secret_key' 사본도 만듭니다(암호화는 됨). 세션 없는 get_config는 이 전역 사본을 읽습니다(struct.py:719, tests/test_trading_config_scope.py:193). 이는 'LIVE never runs against the legacy global/admin credential fallback' 원칙(struct.py:1029-1031)에 어긋날 수 있습니다. 669줄 prefix에 'upbit_'를 넣지 않으면 전역 사본은 클래스 캐시 Struct._cfg를 거쳐 오래된 값이 남을 수도 있습니다.
  -> USER_SCOPED_CONFIG_KEYS에 넣지 않습니다. 저장은 `trading._write_config_value(trading._user_config_key(uid, 'upbit_access_key'), v, desc, True)`로 명시 키에만 하고, 워커는 `_lookup_config_value(_user_config_key(owner, ...))`로 읽습니다. 'user:' prefix라 669줄에서 캐시를 우회하고, 복호화는 trading_config.py:14-18에서 됩니다. 세션 없이도 owner를 명시하므로 전역 사본이 생기지 않습니다. 저장 경로와 삭제 경로 모두 is_secret=True로 씁니다(struct.py:694가 매번 플래그를 덮어씀). 응답에는 configured와 hint만 담습니다(page.infinitebuy/api.py:146-163 패턴). load_settings처럼 평문을 응답하는 방식(page.settings/api.py:518-525)은 따르지 않습니다.
- 검증 경로의 충돌. 사용자 규칙은 'PAPER와 오프라인에서만 검증하고 LIVE 스위치를 바꾸지 않는다'인데, 업비트에는 모의투자가 없고 코인은 LIVE 전용입니다. 그래서 실주문 경로를 사전에 검증할 수 없습니다.
  -> 정책 모드를 off|shadow|live로 둡니다. shadow는 LIVE 프로세스에서 시세와 잔고 GET만 하고, 가상 체결은 runtime 로그(data/live/coin/runtime_logs.json)나 trim 규칙에 맞는 이벤트명으로 기록합니다. 기본값은 off로 배포하고, shadow에서 live로 바꾸는 것(경고 확인 포함)은 사용자가 직접 합니다. 단위 테스트는 가짜 session으로 하고, 첫 실주문은 최소 금액(5,000원)으로 사용자가 지켜보는 가운데 냅니다.
- 배포할 때 LIVE를 재시작해야 함. struct.py의 워커 훅은 재시작해야 반영됩니다(모델 코드 캐시, wiz.py:40-48). 그런데 메모리 규칙은 'LIVE 재시작은 LIVE 단타가 OFF일 때만'이고, 10-19부터 LIVE KS 단타가 ON입니다. FireGate SOXL 예약도 살아 있습니다.
  -> 재시작은 사용자 승인을 받아 KS 장 마감(15:30 KST) 이후에 합니다. 3001을 리스닝하는 프로세스를 커맨드라인으로 찾고, 재시작 뒤에는 그 프로세스의 생성 시각과 FireGate 예약이 그대로인지 확인합니다. 코인은 정책 off와 opt-in 꺼짐 상태로 배포해서, 재시작해도 업비트 호출이 0건이 되게 합니다. env를 추가했다면 supervisor도 재시작합니다.
- 수수료와 수량 반올림. buy_market_krw는 KRW 금액만 보내는데, 업비트 매수 수수료(bid_fee)는 따로 차감되므로 잔고 전액으로 매수하면 insufficient_funds_bid가 납니다. sell_market은 `f"{volume:.8f}"`로 반올림하므로(upbit_api.py:145) 보유 수량보다 큰 수량을 보낼 수 있습니다. trade_log의 order_qty/filled_qty는 IntegerField라(trade_log.py:24-27, peewee.py:4904-4908 `int(value)`) 소수 수량이 0으로 저장됩니다.
  -> 주문 전에 order_chance(upbit_api.py:127-128)로 bid_fee, ask_fee, min_total을 조회합니다. 매수액은 floor(available_krw/(1+bid_fee))에 여유를 두고 정하고, 매도 수량은 Decimal ROUND_DOWN으로 소수 8자리까지 자르며 `locked` 수량을 뺍니다. trade_log에는 cycle_id 'coin:KRW-BTC', symbol 'KRW-BTC', COIN_ 접두를 쓰고, 정확한 수량은 raw_response 문자열로 남깁니다(맵 #5대로).
- 호출 한도와 인증 오류. upbit_api.py:27-29의 throttle 상태는 모듈 레벨이라 wiz.model이 다시 실행될 때마다 초기화됩니다. 그래서 페이지 폴링과 워커가 동시에 부르면 초당 한도를 넘을 수 있습니다. 429와 Remaining-Req 처리가 없습니다. 가정용 동적 IP가 바뀌면 no_authorization_ip가 반복되어 재시도가 폭주합니다.
  -> throttle 상태를 `_RATE = sys.__dict__.setdefault('_stock8_upbit_rate', {...})`로 프로세스 전역에 두고, 주문용 버킷(초당 8회)을 따로 둡니다. 429나 IP/JWT 오류가 나면 워커를 halt하고 그 상태를 표시하며 재시도를 멈춥니다. 페이지는 private API를 직접 부르지 말고, 워커 상태(sys registry)와 캐시된 잔고를 읽게 합니다.
- 24시간 시장과 PC 슬립/재부팅. 메모리에 따르면 AC 전원에서 15분 뒤 절전, Windows Update 강제 재부팅, 사용자의 의도적 절전이 있습니다. 그동안 코인 포지션은 보호 없이 남고, 깨어난 직후 오래된 신호로 주문할 위험이 있습니다.
  -> 재시작하거나 깨어난 뒤 첫 패스는 다음 순서로 합니다: balances()로 상태를 다시 맞추고(브로커 우선, AGENTS.md:33), 손절과 청산 확인을 먼저 하고, 신규 진입은 마지막으로 닫힌 봉 시각이 현재-1봉 이내일 때만 합니다(10-17 단타의 오래된 신호 거부 방식). 업비트에는 서버측 스탑 주문이 없다는 점을 UI에 알립니다.
- 상태 손실로 인한 재매수, 그리고 정책이 다른 계정으로 이어짐. fs.write.json은 원자적이지 않고(season/util/filesystem.py:124-137), 단일 전역 'coin_policy_v1' 키는 업비트 계정과 묶여 있지 않습니다.
  -> 상태 파일은 tmp에 쓴 뒤 os.replace로 바꾸고, data/live/coin/<sha256(owner_uid+access_key)[:24]>/ 아래에 둡니다. 정책 키는 'coin_policy_v1:<같은 해시>'로 하고, 워커는 매 패스 키 해시를 다시 계산해 바뀌었으면 'account_changed'로 종료합니다(struct.py:1055-1057 패턴). 프로세스 등록부와 락은 sys.__dict__에 두고, 클래스 static 멤버는 쓰지 않습니다.