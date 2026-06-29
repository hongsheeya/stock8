import { HostListener, OnDestroy, OnInit } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { Service } from '@wiz/libs/portal/season/service';
import { i18n } from '@wiz/libs/portal/trading/i18n';

declare const wiz: any;
const DASHBOARD_CACHE_KEY = '__wizDashboardState';

export class Component implements OnInit, OnDestroy {
    public now: Date = new Date();
    private clockInterval: any;
    private routerSub: Subscription;
    public userMenuOpen: boolean = false;
    public currentPath: string = location.pathname;
    public adminPreviewUserMode: boolean = false;
    public themeMode: 'dark' | 'light' = 'light';
    public daytradeAccess: any = {
        daytrade_feature_enabled: false,
        daytrade_user_authorized: false,
        daytrade_user_confirmed: false,
        daytrade_access_enabled: false,
        daytrade_hard_locked: true,
    };
    private dashboardPreloadPromise: Promise<void> | null = null;
    private dashboardPreloadTimer: any = null;
    private lastDashboardPreloadAtMs: number = 0;

    constructor(public service: Service, private router: Router) { }

    public t = (key: string) => i18n.t(key);
    public get lang() { return i18n.lang; }

    public async ngOnInit() {
        this.loadThemePreference();
        await this.service.init(this);
        this.refreshAdminPreviewMode();
        await this.loadDaytradeAccess(false);

        this.currentPath = this.router.url || location.pathname;
        this.routerSub = this.router.events.subscribe((event) => {
            if (event instanceof NavigationEnd) {
                this.currentPath = event.urlAfterRedirects || event.url || location.pathname;
                this.queueDashboardPreload(80);
                this.service.render();
            }
        });

        this.queueDashboardPreload(150);
        this.clockInterval = setInterval(() => {
            this.now = new Date();
        }, 1000);
    }

    ngOnDestroy() {
        if (this.clockInterval) clearInterval(this.clockInterval);
        if (this.routerSub) this.routerSub.unsubscribe();
        if (this.dashboardPreloadTimer) clearTimeout(this.dashboardPreloadTimer);
        this.dashboardPreloadPromise = null;
    }

    private dashboardSessionKey(): string {
        const session: any = this.service?.auth?.session || {};
        return String(session.id || session.user?.id || session.profile?.id || session.data?.id || session.email || session.user?.email || '').trim();
    }

    private dashboardCacheKey(): string {
        const sessionKey = this.dashboardSessionKey();
        return sessionKey ? `${DASHBOARD_CACHE_KEY}:${sessionKey}` : '';
    }

    private getDashboardCache(): any {
        try {
            const globalWindow: any = typeof window !== 'undefined' ? window : null;
            const cacheKey = this.dashboardCacheKey();
            if (!globalWindow || !cacheKey) return null;
            let raw = globalWindow[cacheKey];
            if (!raw || typeof raw !== 'object') {
                const stored = globalWindow.localStorage?.getItem(cacheKey);
                raw = stored ? JSON.parse(stored) : null;
            }
            if (!raw || typeof raw !== 'object') return null;
            if (raw.sessionKey !== this.dashboardSessionKey()) return null;
            return raw;
        } catch (e) {
            return null;
        }
    }

    private dashboardCacheFresh(ttlMs: number): boolean {
        const raw = this.getDashboardCache();
        if (!raw) return false;
        const ageMs = Date.now() - Number(raw.ts || 0);
        return isFinite(ageMs) && ageMs >= 0 && ageMs < ttlMs;
    }

    private writeDashboardCache(state: any) {
        try {
            const globalWindow: any = typeof window !== 'undefined' ? window : null;
            const sessionKey = this.dashboardSessionKey();
            const cacheKey = this.dashboardCacheKey();
            if (!globalWindow || !sessionKey || !cacheKey) return;
            const payload = {
                ts: Date.now(),
                sessionKey,
                state: state || {},
            };
            globalWindow[cacheKey] = payload;
            try {
                delete globalWindow[DASHBOARD_CACHE_KEY];
            } catch (e) {
            }
            globalWindow.localStorage?.setItem(cacheKey, JSON.stringify(payload));
        } catch (e) {
        }
    }

    private updateDashboardCache(patch: any) {
        const raw = this.getDashboardCache();
        const previous = raw?.state || {};
        this.writeDashboardCache({ ...previous, ...(patch || {}) });
    }

    private dashboardApi(): any {
        try {
            const WizCtor = wiz?.constructor;
            if (typeof WizCtor === 'function') {
                return new WizCtor('/wiz').app('page.dashboard');
            }
        } catch (e) {
        }
        return wiz;
    }

    private stateFromOverview(data: any): any {
        data = data || {};
        const krwOrderableCash = data.krw_orderable_cash !== undefined && data.krw_orderable_cash !== null ? data.krw_orderable_cash : (data.krw_balance || 0);
        const orderableCash = data.buying_power_orderable !== undefined && data.buying_power_orderable !== null ? data.buying_power_orderable : krwOrderableCash;
        return {
            buyingPower: data.buying_power !== undefined && data.buying_power !== null ? data.buying_power : orderableCash,
            orderableCash,
            usdBuyingPower: data.usd_buying_power || 0,
            usdSyncOk: data.usd_sync_ok === true,
            usdSyncMessage: data.usd_sync_message || '',
            usdSyncSource: data.usd_sync_source || '',
            krwBalance: data.krw_balance || 0,
            krwOrderableCash,
            krwOrderableSource: data.krw_orderable_source || '',
            krwOrderableProbe: data.krw_orderable_probe || '',
            krwOrderableGap: data.krw_orderable_gap || 0,
            krwBuyingPowerUsd: data.krw_buying_power_usd || 0,
            portfolioValue: data.portfolio_value || 0,
            totalAsset: data.total_asset || 0,
            exchangeRate: data.exchange_rate || 0,
            balanceSyncOk: data.balance_sync_ok === true,
            balanceSyncMessage: data.balance_sync_message || '',
            balanceSyncSource: data.balance_sync_source || '',
            engineStatus: data.engine_status || {},
            apiConnected: data.api_connected === true,
            cycles: data.cycles || [],
            infiniteBuyCycles: data.infinite_buy_cycles || data.cycles || [],
            infiniteBuySummary: data.infinite_buy_summary || {},
            fireGateBridge: data.fire_gate_bridge || {},
            holdings: data.holdings || [],
            daytradePositions: data.daytrade_positions || [],
            daytradePositionSummary: data.daytrade_position_summary || { count: 0, eval_amount_krw: 0, cost_amount_krw: 0, pnl_krw: 0 },
            recentLogs: data.recent_logs || [],
            watchlistInfo: data.watchlist_info || [],
            daytradeRuntime: data.daytrade_runtime || {},
            automationControls: data.automation_controls || [],
            balanceDiagnostics: data.balance_diagnostics || [],
        };
    }

    private queueDashboardPreload(delayMs: number = 0) {
        if (this.dashboardPreloadPromise) return;
        if (this.dashboardCacheFresh(30000)) return;
        if (this.dashboardPreloadTimer) clearTimeout(this.dashboardPreloadTimer);
        this.dashboardPreloadTimer = setTimeout(() => {
            this.dashboardPreloadTimer = null;
            void this.preloadDashboard();
        }, Math.max(0, delayMs));
    }

    private async preloadDashboard() {
        if (this.dashboardPreloadPromise) {
            await this.dashboardPreloadPromise;
            return;
        }
        const task = this._preloadDashboard();
        this.dashboardPreloadPromise = task;
        try {
            await task;
        } finally {
            if (this.dashboardPreloadPromise === task) {
                this.dashboardPreloadPromise = null;
            }
        }
    }

    private async _preloadDashboard() {
        if (!this.dashboardSessionKey()) return;
        const now = Date.now();
        if (now - this.lastDashboardPreloadAtMs < 30000 && this.dashboardCacheFresh(30000)) return;
        this.lastDashboardPreloadAtMs = now;
        try {
            const dashboard = this.dashboardApi();
            const overview = await dashboard.call("overview", { force_refresh: 'false', _preload: 'true', _ts: now });
            if (overview?.code !== 200) return;
            this.updateDashboardCache(this.stateFromOverview(overview.data || {}));

            const profit1d = dashboard.call("profit_summary", { period: "1D", force_refresh: 'false', _preload: 'true' }).catch(() => null);
            const profit1w = dashboard.call("profit_summary", { period: "1W", force_refresh: 'false', _preload: 'true' }).catch(() => null);
            const tradePreview = dashboard.call("trade_preview", { _preload: 'true' }).catch(() => null);
            const [today, chart, preview] = await Promise.all([profit1d, profit1w, tradePreview]);

            if (today?.code === 200) {
                this.updateDashboardCache({
                    profitData: today.data || {},
                    profitLastRefresh: new Date().toISOString(),
                });
            }
            if (chart?.code === 200) {
                this.updateDashboardCache({ profitChartData: chart.data || {} });
            }
            if (preview?.code === 200) {
                this.updateDashboardCache({
                    tradePreviews: preview.data?.previews || [],
                    tradePreviewApiConnected: preview.data?.api_connected === true || overview.data?.api_connected === true,
                });
            }
        } catch (e) {
        }
    }

    public async toggleLang() {
        i18n.toggleLang();
        await this.service.render();
    }

    private loadThemePreference() {
        try {
            const saved = window.localStorage.getItem('dashboard-theme-mode');
            this.themeMode = saved === 'dark' ? 'dark' : 'light';
        } catch (e) {
            this.themeMode = 'light';
        }
    }

    public get isLightTheme(): boolean {
        return this.themeMode === 'light';
    }

    public get themeModeLabel(): string {
        return this.isLightTheme ? '밝게' : '다크';
    }

    public async toggleThemeMode() {
        this.themeMode = this.isLightTheme ? 'dark' : 'light';
        try {
            window.localStorage.setItem('dashboard-theme-mode', this.themeMode);
            window.dispatchEvent(new CustomEvent('dashboard-theme-changed', { detail: { mode: this.themeMode } }));
        } catch (e) {
        }
        await this.service.render();
    }

    public toggleUserMenu() {
        this.userMenuOpen = !this.userMenuOpen;
    }

    private refreshAdminPreviewMode() {
        try {
            this.adminPreviewUserMode = window.localStorage.getItem('admin_preview_user_mode') === 'true';
        } catch (e) {
            this.adminPreviewUserMode = false;
        }
    }

    public get isRealAdmin(): boolean {
        const session: any = this.service?.auth?.session || {};
        const role = String(session.role || session.user?.role || session.profile?.role || session.data?.role || '').toLowerCase();
        const email = String(session.email || session.user?.email || session.profile?.email || session.data?.email || '').trim().toLowerCase();
        return role === 'admin' || email === 'gigukbyun@gmail.com';
    }

    public get effectiveAdminMode(): boolean {
        return this.isRealAdmin && !this.adminPreviewUserMode;
    }

    public get canShowDaytradeNav(): boolean {
        if (this.daytradeAccess?.daytrade_hard_locked === true) return false;
        if (this.daytradeAccess?.daytrade_feature_enabled !== true) return false;
        if (this.effectiveAdminMode) return true;
        return this.daytradeAccess?.daytrade_access_enabled === true;
    }

    private async loadDaytradeAccess(render: boolean = true) {
        try {
            const { code, data } = await wiz.call("daytrade_access_status");
            if (code === 200) {
                this.daytradeAccess = data || this.daytradeAccess;
            }
        } catch (e) {
            this.daytradeAccess = {
                daytrade_feature_enabled: false,
                daytrade_user_authorized: false,
                daytrade_user_confirmed: false,
                daytrade_access_enabled: false,
                daytrade_hard_locked: true,
            };
        }
        if (render) {
            await this.service.render();
        }
    }

    public get adminPreviewButtonLabel(): string {
        return this.adminPreviewUserMode ? '사용자' : '관리자';
    }

    public get adminPreviewButtonTitle(): string {
        return this.adminPreviewUserMode ? '관리자 화면으로 전환' : '사용자 화면으로 전환';
    }

    public async toggleAdminPreviewMode() {
        if (!this.isRealAdmin) return;
        this.adminPreviewUserMode = !this.adminPreviewUserMode;
        try {
            window.localStorage.setItem('admin_preview_user_mode', this.adminPreviewUserMode ? 'true' : 'false');
            window.dispatchEvent(new CustomEvent('admin-preview-changed'));
        } catch (e) {
        }
        await this.service.render();
    }

    @HostListener('document:click')
    public onDocumentClick() {
        if (this.userMenuOpen) {
            this.userMenuOpen = false;
        }
    }

    @HostListener('window:admin-preview-changed')
    public async onAdminPreviewChanged() {
        this.refreshAdminPreviewMode();
        await this.service.render();
    }

    @HostListener('window:daytrade-access-changed')
    public async onDaytradeAccessChanged() {
        await this.loadDaytradeAccess(true);
    }

    @HostListener('window:dashboard-theme-changed', ['$event'])
    public async onThemeChanged(event: any) {
        const mode = event?.detail?.mode;
        if (mode === 'light' || mode === 'dark') {
            this.themeMode = mode;
        } else {
            this.loadThemePreference();
        }
        await this.service.render();
    }

    public closeUserMenu() {
        this.userMenuOpen = false;
    }

    public async handleLogout() {
        try {
            await this.service.auth.logout('/access');
        } catch (e) {
            console.error("로그아웃 실패", e);
        }
    }

    public async goToSettings() {
        this.closeUserMenu();
        this.service.href('/settings');
    }

    public isActive(link: string) {
        const path = this.currentPath || location.pathname;
        if (link === '/daytrade') {
            return path === '/daytrade';
        }
        if (link === '/daytrade/us') {
            return path.indexOf('/daytrade/us') === 0;
        }
        return path.indexOf(link) === 0;
    }

    public navClass(link: string) {
        if (this.isActive(link)) {
            return "bn-nav-link is-active";
        }
        return "bn-nav-link";
    }

    public settingsButtonClass() {
        if (this.userMenuOpen) {
            return "bn-icon-button is-active";
        }
        return "bn-icon-button";
    }

    public avatarButtonClass() {
        if (this.userMenuOpen) {
            return "bn-avatar-button is-active";
        }
        return "bn-avatar-button";
    }

    private timeParts(timeZone: string) {
        const parts = new Intl.DateTimeFormat('en-GB', {
            timeZone,
            weekday: 'short',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
        }).formatToParts(new Date());
        const read = (type: string) => parts.find((item: any) => item.type === type)?.value || '';
        return {
            weekday: read('weekday'),
            hour: Number(read('hour') || 0),
            minute: Number(read('minute') || 0),
        };
    }

    private isKoreanMarketOpen(): boolean {
        const info = this.timeParts('Asia/Seoul');
        if (info.weekday === 'Sat' || info.weekday === 'Sun') return false;
        const mins = info.hour * 60 + info.minute;
        return mins >= 540 && mins < 930;
    }

    private isUsMarketOpen(): boolean {
        const info = this.timeParts('America/New_York');
        if (info.weekday === 'Sat' || info.weekday === 'Sun') return false;
        const mins = info.hour * 60 + info.minute;
        return mins >= 570 && mins < 960;
    }

    public isMarketOpen(): boolean {
        const path = this.currentPath || location.pathname;
        if (path.indexOf('/daytrade/us') === 0) {
            return this.isUsMarketOpen();
        }
        if (path.indexOf('/daytrade') === 0) {
            return this.isKoreanMarketOpen();
        }
        return this.isKoreanMarketOpen() || this.isUsMarketOpen();
    }

    public get marketStatusLabel(): string {
        return this.isMarketOpen() ? '개장' : '휴장';
    }
}
