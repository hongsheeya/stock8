import { Input, OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';
import { i18n } from '@wiz/libs/portal/trading/i18n';

interface Toast {
    id: number;
    type: 'info' | 'success' | 'warning' | 'error';
    title: string;
    message: string;
    timestamp: Date;
}

const DASHBOARD_CACHE_KEY = '__wizDashboardState';

export class Component implements OnInit {
    @Input() public legacyMode: boolean = false;

    public loading: boolean = true;
    public t = (key: string) => i18n.t(key);
    public Math = Math;
    public showLegacySections: boolean = false;

    // Mock indicator
    public isMock: boolean = false;

    // Summary cards
    public buyingPower: number = 0;
    public orderableCash: number = 0;
    public usdBuyingPower: number = 0;
    public usdSyncOk: boolean = false;
    public usdSyncMessage: string = '';
    public usdSyncSource: string = '';
    public krwBalance: number = 0;
    public krwOrderableCash: number = 0;
    public krwOrderableSource: string = '';
    public krwOrderableProbe: string = '';
    public krwOrderableGap: number = 0;
    public krwBuyingPowerUsd: number = 0;
    public portfolioValue: number = 0;
    public totalAsset: number = 0;
    public exchangeRate: number = 0;
    public balanceSyncOk: boolean = false;
    public balanceSyncMessage: string = '';
    public balanceSyncSource: string = '';
    // Engine status
    public engineStatus: any = { active_cycles: 0, holding_cycles: 0, paused_cycles: 0, pending_extension_cycles: 0, completed_cycles: 0, auto_trade: false };
    public apiConnected: boolean = false;
    public setupRequired: boolean = false;
    public privacyLocked: boolean = false;
    public setupMessage: string = '';

    // Active cycles
    public cycles: any[] = [];
    public infiniteBuyCycles: any[] = [];
    public infiniteBuySummary: any = {
        total: 0,
        active: 0,
        holding: 0,
        paused: 0,
        pending_extension: 0,
        loc_required: 0,
        loc_scheduled: 0,
        loc_waiting: 0,
        loc_attention: 0,
        loc_not_required: 0,
        loc_auto_enabled: false,
        loc_buy_last_date: '',
    };
    public fireGateBridge: any = { enabled: false, configured: false, auto_sync_enabled: true, auto_sync_interval_sec: 180 };

    // Holdings
    public holdings: any[] = [];
    public daytradePositions: any[] = [];
    public daytradePositionSummary: any = { count: 0, eval_amount_krw: 0, cost_amount_krw: 0, pnl_krw: 0 };

    // Trade logs
    public recentLogs: any[] = [];
    public expandedLogs: Set<number> = new Set();

    // Watchlist info (cycle_mode per symbol)
    public watchlistInfo: any[] = [];
    public selectedStartSymbol: string = '';
    public startingCycle: boolean = false;

    // ─── Extension Modal State ───
    public extensionCycleId: string = '';
    public extensionSymbol: string = '';
    public extensionExtraRounds: number = 10;
    public extensionExtraInvestment: number = 0;
    public showExtensionModal: boolean = false;

    // ─── Start Cycle Modal State ───
    public showStartModal: boolean = false;
    public startModalSymbol: string = '';
    public startModalName: string = '';
    public startModalInvestment: number = 0;
    public startModalDivision: number = 40;
    public startModalTarget: number = 10;
    public startModalLoading: boolean = false;

    // ─── Trade Preview State ───
    public tradePreviews: any[] = [];
    public tradePreviewLoading: boolean = false;
    public showTradePreview: boolean = true;
    public tradePreviewApiConnected: boolean = false;

    // ─── Cycle Edit Modal State ───
    public showEditModal: boolean = false;
    public editCycleId: string = '';
    public editSymbol: string = '';
    public editTargetProfit: number = 10;
    public editDivisionCount: number = 40;
    public editTotalInvestment: number = 10000;
    public editCurrentRound: number = 0;
    public editTotalSpent: number = 0;
    public editLoading: boolean = false;

    // ─── Cycle Detail Panel State ───
    public showCycleDetail: boolean = false;
    public detailLoading: boolean = false;
    public detailTab: string = 'summary';
    public detailCycle: any = null;
    public detailTrades: any[] = [];
    public detailChartData: any[] = [];
    public detailLogs: any[] = [];
    public detailTradeFilter: string = 'ALL';

    // ─── Profit Summary State ───
    public profitPeriod: string = '1W';
    public profitLoading: boolean = false;
    public profitData: any = {
        realized_profit: 0, unrealized_profit: 0, total_profit: 0,
        total_invested: 0, total_return: 0,
        completed_cycles: 0, avg_cycle_return: 0,
        best_cycle_return: 0, worst_cycle_return: 0,
        cycle_realized_profit: 0, cycle_unrealized_profit: 0,
        daytrade_realized_profit: 0, daytrade_unrealized_profit: 0,
        ib_realized_profit: 0, ib_unrealized_profit: 0,
        ib_realized_cycle_count: 0,
        realized_return: 0, unrealized_return: 0,
        base_asset: 0, first_snapshot_date: '', elapsed_days: 0,
        daytrade_total_profit: 0, daytrade_trade_count: 0, daytrade_position_count: 0,
        daily_return_avg: 0, daily_return_best: 0, daily_return_worst: 0,
        latest_daily_return_rate: 0, asset_change_prev_day: 0,
        snapshots: [],
    };
    public profitChartData: any = {
        snapshots: [],
        daily_return_avg: 0,
        daily_return_best: 0,
        daily_return_worst: 0,
        first_snapshot_date: '',
        elapsed_days: 0,
    };
    public profitLastRefresh: Date | null = null;
    public profitSyncMessage: string = '';
    private profitLoadPromise: Promise<void> | null = null;
    private profitLastServerRefreshMs: number = 0;
    private profitSeq: number = 0;
    public daytradeRuntime: any = {
        started: false,
        us_enabled: false,
        last_run_at: '',
        us_auto_cycle_executed: false,
        us_auto_cycle_message: '',
        us_exit_watch_executed: false,
        us_exit_watch_message: '',
    };
    public automationControls: any[] = [];
    public automationSaving: { [key: string]: boolean } = {};
    public automationSeedDrafts: { [key: string]: string } = {};
    private automationSeedDirty: { [key: string]: boolean } = {};
    public infiniteBuySeedDrafts: { [key: string]: string } = {};
    private infiniteBuySeedDirty: { [key: string]: boolean } = {};
    public balanceDiagnostics: any[] = [];
    public adminPreviewUserMode: boolean = false;

    // ─── Polling & Toast ───
    private pollInterval: any = null;
    private prevLogCount: number = 0;
    private toastId: number = 0;
    public toasts: Toast[] = [];
    public autoRefresh: boolean = true;
    public lastRefresh: Date = new Date();
    public lastRefreshKst: string = '';
    public profitLastRefreshKst: string = '';
    public pollSeconds: number = 10;
    private countdownTimer: any = null;
    public countdown: number = 10;
    public manualRefreshing: boolean = false;
    private dashboardLoadPromise: Promise<void> | null = null;
    private tradePreviewPromise: Promise<void> | null = null;
    private dueAutomationPromise: Promise<any> | null = null;
    private lastDueAutomationAtMs: number = 0;
    private destroyed: boolean = false;
    private dashboardLoadSeq: number = 0;
    private adminPreviewListener: any = null;

    constructor(public service: Service) { }

    private isDaytradeAutomationItem(item: any): boolean {
        const key = String(item?.key || '').toLowerCase();
        const title = String(item?.title || '').toLowerCase();
        const detail = String(item?.detail || '').toLowerCase();
        return key.includes('daytrade') || title.includes('단타') || title.includes('daytrade') || detail.includes('단타') || detail.includes('daytrade');
    }

    private async confirmAutomationEnable(item: any): Promise<boolean> {
        const title = item?.title || '자동매매';
        const message = this.isDaytradeAutomationItem(item)
            ? `${title}을 켜면 백그라운드 워커가 후보 탐색, 진입, 자동청산 감시를 즉시 시작합니다. 수동 운용 중이면 보유 종목, 예약 주문, 시드 상태를 먼저 확인하세요.`
            : `${title}을 켜면 자동 실행이 즉시 시작됩니다. 현재 보유 상태와 예약 주문을 먼저 확인하세요.`;
        const confirmed = await this.service.modal.show({
            title: `${title} 시작`,
            message,
            action: '그래도 켜기',
            cancel: '취소',
            status: 'warning',
            actionBtn: 'warning',
        });
        return confirmed === true;
    }


    private async renderIfAlive() {
        if (this.destroyed) return;
        await this.service.render();
    }

    private hasVisibleDashboardData(): boolean {
        return Number(this.totalAsset) > 0
            || Number(this.buyingPower) > 0
            || Number(this.portfolioValue) > 0
            || (Array.isArray(this.infiniteBuyCycles) && this.infiniteBuyCycles.length > 0)
            || (Array.isArray(this.holdings) && this.holdings.length > 0);
    }

    private shouldIgnoreEmptyOverview(data: any): boolean {
        if (!this.hasVisibleDashboardData() || !data) return false;
        if (data.setup_required === true || data.privacy_locked === true) return false;
        const incomingTotal = Number(data.total_asset) || 0;
        const incomingBuyingPower = Number(data.buying_power) || 0;
        const incomingPortfolio = Number(data.portfolio_value) || 0;
        const incomingCycles = Array.isArray(data.infinite_buy_cycles || data.cycles) ? (data.infinite_buy_cycles || data.cycles) : [];
        const incomingHoldings = Array.isArray(data.holdings) ? data.holdings : [];
        const emptyNumbers = incomingTotal <= 0 && incomingBuyingPower <= 0 && incomingPortfolio <= 0;
        const emptyLists = incomingCycles.length === 0 && incomingHoldings.length === 0;
        const disconnected = data.api_connected !== true || data.degraded === true || data.balance_sync_ok !== true;
        return emptyNumbers && emptyLists && disconnected;
    }

    private dashboardSessionKey(): string {
        const session: any = this.service?.auth?.session || {};
        return String(session.id || session.user?.id || session.profile?.id || session.data?.id || session.email || session.user?.email || '').trim();
    }

    private dashboardCacheKey(): string {
        const sessionKey = this.dashboardSessionKey();
        return sessionKey ? `${DASHBOARD_CACHE_KEY}:${sessionKey}` : '';
    }

    private emptyProfitSummary(message: string = ''): any {
        const today = this.lastRefreshKst ? this.lastRefreshKst.slice(0, 10) : '';
        return {
            realized_profit: 0, unrealized_profit: 0, total_profit: 0,
            total_invested: 0, total_return: 0,
            completed_cycles: 0, avg_cycle_return: 0,
            best_cycle_return: 0, worst_cycle_return: 0,
            cycle_realized_profit: 0, cycle_unrealized_profit: 0,
            daytrade_realized_profit: 0, daytrade_unrealized_profit: 0,
            daytrade_total_profit: 0,
            ib_realized_profit: 0, ib_unrealized_profit: 0,
            ib_realized_cycle_count: 0,
            realized_return: 0, unrealized_return: 0,
            base_asset: 0, first_snapshot_date: '', elapsed_days: 0,
            daytrade_trade_count: 0, daytrade_position_count: 0,
            daily_return_avg: 0, daily_return_best: 0, daily_return_worst: 0,
            latest_daily_return_rate: 0, asset_change_prev_day: 0,
            setup_required: true,
            privacy_locked: true,
            message,
            snapshots: today ? [{ date: today, total_asset: 0, profit: 0, profit_rate: 0, daily_return_rate: 0 }] : [],
        };
    }

    public get isRealAdmin(): boolean {
        const session: any = this.service?.auth?.session || {};
        const role = String(session.role || session.user?.role || session.profile?.role || session.data?.role || '').toLowerCase();
        const email = String(session.email || session.user?.email || session.profile?.email || session.data?.email || '').trim().toLowerCase();
        return role === 'admin' || email === 'gigukbyun@gmail.com';
    }

    public get showAdminControls(): boolean {
        return this.isRealAdmin && !this.adminPreviewUserMode;
    }

    public get showDaytradeQuickLink(): boolean {
        return this.showAdminControls && this.daytradeRuntime?.daytrade_feature_enabled === true;
    }

    private refreshAdminPreviewMode() {
        try {
            this.adminPreviewUserMode = window.localStorage.getItem('admin_preview_user_mode') === 'true';
        } catch (e) {
            this.adminPreviewUserMode = false;
        }
    }

    public async onAdminPreviewChanged() {
        this.refreshAdminPreviewMode();
        await this.renderIfAlive();
    }

    public async ngOnInit() {
        this.destroyed = false;
        this.showLegacySections = this.legacyMode === true;
        this.refreshAdminPreviewMode();
        this.adminPreviewListener = () => {
            void this.onAdminPreviewChanged();
        };
        try {
            window.addEventListener('admin-preview-changed', this.adminPreviewListener);
        } catch (e) {
        }
        await this.service.init(this);
        if (this.destroyed) return;
        await this.service.auth.allow("/access");
        if (this.destroyed) return;
        const restored = this.restoreCachedState();
        if (restored) {
            this.loading = false;
            await this.renderIfAlive();
        }
        await this.load(restored, false);
        if (this.destroyed) return;
        this.startPolling();

        if (this.legacyMode !== true) {
            setTimeout(() => {
                if (this.destroyed) return;
                void this.loadProfitSummary();
            }, 50);
        }
    }

    ngOnDestroy() {
        this.destroyed = true;
        this.persistCachedState();
        this.dashboardLoadSeq++;
        this.profitSeq++;
        if (this.adminPreviewListener) {
            try {
                window.removeEventListener('admin-preview-changed', this.adminPreviewListener);
            } catch (e) {
            }
            this.adminPreviewListener = null;
        }
        this.stopPolling();
        this.dashboardLoadPromise = null;
        this.tradePreviewPromise = null;
        this.profitLoadPromise = null;
        this.dueAutomationPromise = null;
    }

    private async kickDueAutomation(force: boolean = false): Promise<any> {
        if (this.destroyed || this.legacyMode === true) return null;
        const now = Date.now();
        if (!force && now - this.lastDueAutomationAtMs < 60000) return null;
        if (this.dueAutomationPromise) return this.dueAutomationPromise;
        this.lastDueAutomationAtMs = now;
        this.dueAutomationPromise = wiz.call("run_due_automation")
            .then((res: any) => res?.data || null)
            .catch((e: any) => {
                console.error("Due automation tick error:", e);
                return null;
            })
            .finally(() => {
                this.dueAutomationPromise = null;
            });
        return this.dueAutomationPromise;
    }

    private shouldForceOverviewAfterAutomation(result: any): boolean {
        if (!result || typeof result !== 'object') return false;
        const status = String(result.status || '').toLowerCase();
        const count = (value: any) => Number(value || 0) || 0;
        if (result.executed === true || result.verified === true || result.verification_complete === true) return true;
        if (result.forced === true || result.scheduled === true) return true;
        if (status === 'completed' || status === 'cooldown_wait') return true;
        if (result.rebuild?.executed === true) return true;
        if (count(result.buy?.scheduled_count) > 0 || count(result.sell?.scheduled_count) > 0) return true;
        if (count(result.buy?.already_scheduled_count) > 0 || count(result.sell?.already_scheduled_count) > 0) return true;
        if (count(result.buy?.expected_count) > 0 || count(result.sell?.expected_count) > 0) return true;
        return false;
    }

    // ─── Data Load ───
    public async load(silent: boolean = false, forceRefresh: boolean = false) {
        if (this.destroyed) return;
        if (this.dashboardLoadPromise) {
            await this.dashboardLoadPromise;
            if (!forceRefresh) return;
        }

        const task = this._loadInternal(silent, forceRefresh);
        this.dashboardLoadPromise = task;
        try {
            await task;
        } finally {
            if (this.dashboardLoadPromise === task) {
                this.dashboardLoadPromise = null;
            }
        }
    }

    private async _loadInternal(silent: boolean = false, forceRefresh: boolean = false) {
        const seq = ++this.dashboardLoadSeq;
        if (this.destroyed) return;
        if (!silent) {
            this.loading = true;
            await this.renderIfAlive();
        }

        try {
            const automationResult = await this.kickDueAutomation(forceRefresh);
            if (this.destroyed || seq !== this.dashboardLoadSeq) return;
            const refreshOverview = forceRefresh || this.shouldForceOverviewAfterAutomation(automationResult);
            const { code, data } = await wiz.call("overview", {
                force_refresh: refreshOverview ? 'true' : 'false',
                _ts: Date.now(),
            });
            if (this.destroyed || seq !== this.dashboardLoadSeq) return;
            if (code === 200) {
                if (this.shouldIgnoreEmptyOverview(data)) {
                    this.lastRefresh = new Date();
                    this.lastRefreshKst = data?.server_time_kst || this.lastRefreshKst;
                    this.loading = false;
                    this.countdown = this.pollSeconds;
                    await this.renderIfAlive();
                    return;
                }
                this.usdBuyingPower = data.usd_buying_power || 0;
                this.usdSyncOk = data.usd_sync_ok === true;
                this.usdSyncMessage = data.usd_sync_message || '';
                this.usdSyncSource = data.usd_sync_source || '';
                this.krwBalance = data.krw_balance || 0;
                this.krwOrderableCash = data.krw_orderable_cash !== undefined && data.krw_orderable_cash !== null ? data.krw_orderable_cash : (data.krw_balance || 0);
                this.krwOrderableSource = data.krw_orderable_source || '';
                this.krwOrderableProbe = data.krw_orderable_probe || '';
                this.krwOrderableGap = data.krw_orderable_gap || 0;
                this.exchangeRate = data.exchange_rate || 0;
                this.krwBuyingPowerUsd = data.krw_buying_power_usd || 0;
                this.orderableCash = data.buying_power_orderable !== undefined && data.buying_power_orderable !== null ? data.buying_power_orderable : this.krwOrderableCash;
                this.buyingPower = data.buying_power !== undefined && data.buying_power !== null ? data.buying_power : this.orderableCash;
                this.portfolioValue = data.portfolio_value || 0;
                this.totalAsset = data.total_asset || 0;
                this.balanceSyncOk = data.balance_sync_ok === true;
                this.balanceSyncMessage = data.balance_sync_message || '';
                this.balanceSyncSource = data.balance_sync_source || '';
                this.setupRequired = data.setup_required === true;
                this.privacyLocked = data.privacy_locked === true;
                this.setupMessage = data.setup_message || data.message || '';
                this.lastRefreshKst = data.server_time_kst || this.lastRefreshKst;
                this.engineStatus = data.engine_status || this.engineStatus;
                this.daytradeRuntime = data.daytrade_runtime || this.daytradeRuntime;
                this.automationControls = data.automation_controls || [];
                this.balanceDiagnostics = data.balance_diagnostics || [];
                this.apiConnected = data.api_connected || false;
                this.isMock = data.is_mock || false;
                this.cycles = data.cycles || [];
                this.infiniteBuyCycles = data.infinite_buy_cycles || data.cycles || [];
                this.syncSeedDrafts();
                this.infiniteBuySummary = data.infinite_buy_summary || this.infiniteBuySummary;
                this.fireGateBridge = data.fire_gate_bridge || this.fireGateBridge;
                this.holdings = data.holdings || [];
                this.daytradePositions = data.daytrade_positions || [];
                this.daytradePositionSummary = data.daytrade_position_summary || { count: 0, eval_amount_krw: 0, cost_amount_krw: 0, pnl_krw: 0 };
                this.watchlistInfo = data.watchlist_info || [];
                if (this.setupRequired || this.privacyLocked) {
                    this.tradePreviews = [];
                    this.tradePreviewApiConnected = false;
                    this.profitData = this.emptyProfitSummary(this.setupMessage);
                    this.profitChartData = this.emptyProfitSummary(this.setupMessage);
                    this.profitSyncMessage = this.setupMessage;
                    this.profitLastRefresh = new Date();
                    this.profitLastRefreshKst = data.server_time_kst || this.profitLastRefreshKst;
                } else {
                    this.applyLiveUnrealizedFromOverview();
                    this.queueProfitSummaryRefresh(false);
                }

                // 새 로그 감지
                const newLogs = data.recent_logs || [];
                if (this.prevLogCount > 0 && newLogs.length > 0) {
                    const newCount = this.detectNewLogs(newLogs);
                    if (newCount > 0) {
                        this.notifyNewLogs(newLogs, newCount);
                    }
                }
                this.recentLogs = newLogs;
                this.expandedLogs.clear();
                this.prevLogCount = newLogs.length;

                const startableSymbols = this.watchlistWithoutCycle.map((item: any) => item.symbol);
                if (startableSymbols.length === 0) {
                    this.selectedStartSymbol = '';
                } else if (!startableSymbols.includes(this.selectedStartSymbol)) {
                    this.selectedStartSymbol = startableSymbols[0];
                }
                this.persistCachedState();
            }
        } catch (e) {
            console.error("Dashboard load error:", e);
        }

        if (this.destroyed || seq !== this.dashboardLoadSeq) return;
        this.lastRefresh = new Date();
        this.loading = false;
        this.countdown = this.pollSeconds;
        if (this.legacyMode !== true && !silent && !this.setupRequired && !this.privacyLocked) {
            void this.loadTradePreview();
        }
        await this.renderIfAlive();
    }

    public async refreshDashboard() {
        if (this.manualRefreshing) return;
        this.manualRefreshing = true;
        await this.renderIfAlive();
        try {
            await this.load(false, true);
            if (this.legacyMode !== true) {
                await this.loadProfitSummary(true);
            }
            this.addToast('success', '새로고침', '총자산, 매수가능액, 평가액을 다시 조회했습니다.');
        } catch (e: any) {
            this.addToast('error', '새로고침', e?.message || '새로고침 실패');
        } finally {
            this.manualRefreshing = false;
            await this.renderIfAlive();
        }
    }

    // ─── Profit Summary ───
    private applyLiveUnrealizedFromOverview() {
        if (this.setupRequired || this.privacyLocked) {
            this.profitData = this.emptyProfitSummary(this.setupMessage);
            this.profitChartData = this.emptyProfitSummary(this.setupMessage);
            return;
        }
        const round2 = (value: number) => Math.round((Number(value) || 0) * 100) / 100;
        const fx = Number(this.exchangeRate) || 0;
        const previous = this.profitData || {};
        let ibUnrealized = Number(previous.ib_unrealized_profit) || 0;
        let ibInvested = 0;

        if (fx > 0 && Array.isArray(this.infiniteBuyCycles)) {
            ibUnrealized = this.infiniteBuyCycles.reduce((sum: number, cycle: any) => {
                const qty = Number(cycle?.total_qty) || 0;
                const currentPrice = Number(cycle?.current_price) || 0;
                const spent = Number(cycle?.total_spent) || 0;
                if (spent > 0) ibInvested += spent * fx;
                if (qty <= 0 || currentPrice <= 0 || spent <= 0) return sum;
                return sum + ((qty * currentPrice - spent) * fx);
            }, 0);
        }

        const daytradeUnrealized = Number(this.daytradePositionSummary?.pnl_krw) || 0;
        const daytradeEval = Number(this.daytradePositionSummary?.eval_amount_krw) || 0;
        const daytradeCost = Number(this.daytradePositionSummary?.cost_amount_krw) || Math.max(0, daytradeEval - daytradeUnrealized);
        const liveInvested = round2(Math.max(0, ibInvested) + Math.max(0, daytradeCost));
        const unrealized = round2(ibUnrealized + daytradeUnrealized);
        const realized = Number(previous.realized_profit) || 0;
        const invested = Math.max(Number(previous.total_invested) || 0, liveInvested);
        const totalProfit = round2(realized + unrealized);

        this.profitData = {
            ...previous,
            unrealized_profit: unrealized,
            ib_unrealized_profit: round2(ibUnrealized),
            daytrade_unrealized_profit: round2(daytradeUnrealized),
            total_profit: totalProfit,
            total_invested: invested,
            realized_return: invested > 0 ? round2((realized / invested) * 100) : previous.realized_return,
            unrealized_return: invested > 0 ? round2((unrealized / invested) * 100) : previous.unrealized_return,
            total_return: invested > 0 ? round2((totalProfit / invested) * 100) : previous.total_return,
            daytrade_position_count: this.daytradePositionSummary?.count || previous.daytrade_position_count || 0,
        };
        this.profitLastRefresh = new Date();
    }

    public async loadProfitSummary(forceRefresh: boolean = false) {
        if (this.destroyed) return;
        if (this.setupRequired || this.privacyLocked) {
            this.profitData = this.emptyProfitSummary(this.setupMessage);
            this.profitChartData = this.emptyProfitSummary(this.setupMessage);
            this.profitSyncMessage = this.setupMessage;
            this.profitLoading = false;
            await this.renderIfAlive();
            return;
        }
        if (this.profitLoadPromise && !forceRefresh) {
            await this.profitLoadPromise;
            return;
        }
        const task = this._loadProfitSummary(forceRefresh);
        this.profitLoadPromise = task;
        try {
            await task;
        } finally {
            if (this.profitLoadPromise === task) this.profitLoadPromise = null;
        }
    }

    private queueProfitSummaryRefresh(forceRefresh: boolean = false) {
        if (this.destroyed) return;
        if (this.setupRequired || this.privacyLocked) return;
        const now = Date.now();
        const intervalMs = forceRefresh ? 0 : 30000;
        if (!forceRefresh && this.profitLoading) return;
        if (!forceRefresh && this.profitLastServerRefreshMs > 0 && now - this.profitLastServerRefreshMs < intervalMs) return;
        void this.loadProfitSummary(forceRefresh);
    }

    private async _loadProfitSummary(forceRefresh: boolean = false) {
        if (this.destroyed) return;
        const seq = ++this.profitSeq;
        this.profitLoading = true;
        if (forceRefresh) this.profitSyncMessage = '';
        await this.renderIfAlive();

        try {
            const todayRes = await wiz.call("profit_summary", {
                period: "1D",
                force_refresh: forceRefresh ? 'true' : 'false',
                _ts: forceRefresh ? Date.now() : undefined,
            });
            if (this.destroyed || seq !== this.profitSeq) return;
            if (todayRes?.code === 200) {
                this.profitData = todayRes.data || this.profitData;
                if ((todayRes.data || {}).setup_required === true || (todayRes.data || {}).privacy_locked === true) {
                    this.setupRequired = true;
                    this.privacyLocked = true;
                    this.setupMessage = todayRes.data?.message || this.setupMessage;
                    this.profitChartData = todayRes.data || this.emptyProfitSummary(this.setupMessage);
                    this.profitSyncMessage = this.setupMessage;
                    this.profitLastRefresh = new Date();
                    this.profitLastRefreshKst = todayRes.data?.server_time_kst || this.profitLastRefreshKst;
                    this.profitLastServerRefreshMs = Date.now();
                    this.persistCachedState();
                    this.profitLoading = false;
                    await this.renderIfAlive();
                    return;
                }
                if ((todayRes.data || {}).message) this.profitSyncMessage = todayRes.data.message;
                this.profitLastRefresh = new Date();
                this.profitLastRefreshKst = todayRes.data?.server_time_kst || this.profitLastRefreshKst;
                this.profitLastServerRefreshMs = Date.now();
                this.applyLiveUnrealizedFromOverview();
                this.persistCachedState();
            } else {
                throw new Error(todayRes?.data?.message || '수익현황 조회 실패');
            }
            this.profitLoading = false;
            await this.renderIfAlive();

            const chartPeriod = this.profitPeriod || "1W";
            if (chartPeriod === "1D") {
                this.profitChartData = todayRes?.data || this.profitChartData;
            } else {
                try {
                    const chartRes = await wiz.call("profit_summary", {
                        period: chartPeriod,
                        force_refresh: forceRefresh ? 'true' : 'false',
                        _ts: forceRefresh ? Date.now() : undefined,
                    });
                    if (this.destroyed || seq !== this.profitSeq) return;
                    if (chartRes?.code === 200) {
                        this.profitChartData = chartRes.data || this.profitChartData;
                        if ((chartRes.data || {}).message) this.profitSyncMessage = chartRes.data.message;
                        this.profitLastRefresh = new Date();
                        this.profitLastRefreshKst = chartRes.data?.server_time_kst || this.profitLastRefreshKst;
                        this.profitLastServerRefreshMs = Date.now();
                        this.persistCachedState();
                    }
                } catch (chartError: any) {
                    console.error("Profit chart load error:", chartError);
                }
            }
        } catch (e: any) {
            console.error("Profit summary load error:", e);
            this.applyLiveUnrealizedFromOverview();
            this.profitSyncMessage = e?.message || '수익현황 갱신 실패 — 마지막 값 유지';
        }

        if (this.destroyed || seq !== this.profitSeq) return;
        this.profitLoading = false;
        await this.renderIfAlive();
    }

    public async setProfitPeriod(period: string) {
        this.profitPeriod = period;
        await this.loadProfitSummary(true);
    }

    public profitChangeClass(val: number): string {
        const num = Number(val) || 0;
        if (num > 0) return 'profit-positive';
        if (num < 0) return 'profit-negative';
        return 'profit-neutral';
    }

    public profitBarClass(val: number): string {
        const num = Number(val) || 0;
        if (num > 0) return 'profit-bar-positive';
        if (num < 0) return 'profit-bar-negative';
        return 'profit-bar-neutral';
    }

    public profitChangeIcon(val: number): string {
        const num = Number(val) || 0;
        if (num > 0) return '+';
        if (num < 0) return '-';
        return '';
    }

    public signedKRW(val: number): string {
        const num = Number(val) || 0;
        const sign = num > 0 ? '+' : num < 0 ? '-' : '';
        return `${sign}₩${this.formatKRW(Math.abs(num))}`;
    }

    public profitHintLabel(type: 'ib-realized' | 'dt-realized' | 'ib-unrealized' | 'dt-unrealized'): string {
        if (type === 'ib-realized') {
            const count = Number(this.profitData?.ib_realized_cycle_count) || 0;
            if (count > 0) return `완료 사이클 ${count}건 반영`;
            return '보유 위주라 실현 구간이 드뭅니다';
        }
        if (type === 'dt-realized') {
            const trades = Number(this.profitData?.daytrade_trade_count) || 0;
            return trades > 0 ? `체결 ${trades}건 기준` : '오늘 체결 기준 실현손익';
        }
        if (type === 'ib-unrealized') {
            const count = Number(this.infiniteBuySummary?.holding || 0) + Number(this.infiniteBuySummary?.active || 0);
            return count > 0 ? `보유 사이클 ${count}건 평가손익` : '현재 평가중인 사이클 없음';
        }
        const count = Number(this.daytradePositionSummary?.count) || 0;
        return count > 0 ? `보유 포지션 ${count}건 평가손익` : '현재 보유 단타 포지션 없음';
    }

    public marketLabel(market: string): string {
        const m = String(market || '').toUpperCase();
        if (m === 'US') return '미장';
        if (m === 'KQ') return '코스닥';
        return '국장';
    }

    public marketBadgeClass(market: string): string {
        const m = String(market || '').toUpperCase();
        if (m === 'US') return 'bg-sky-500/15 text-sky-300 border border-sky-400/20';
        if (m === 'KQ') return 'bg-violet-500/15 text-violet-300 border border-violet-400/20';
        return 'bg-emerald-500/15 text-emerald-300 border border-emerald-400/20';
    }

    public formatPositionPrice(position: any, value: number): string {
        const num = Number(value) || 0;
        const market = String(position?.market || '').toUpperCase();
        if (market === 'US') return `$${num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
        return `₩${this.formatKRW(num)}`;
    }

    // Chart helpers for snapshots
    public snapshotBarHeight(value: number): number {
        if (!this.profitChartData.snapshots || this.profitChartData.snapshots.length === 0) return 0;
        const values = this.profitChartData.snapshots.map((s: any) => s.total_asset || 0);
        const max = Math.max(...values);
        const min = Math.min(...values);
        const range = max - min || 1;
        return Math.max(5, Math.round(((value - min) / range) * 100));
    }

    public snapshotProfitBarHeight(value: number): number {
        if (!this.profitChartData.snapshots || this.profitChartData.snapshots.length === 0) return 50;
        const values = this.profitChartData.snapshots.map((s: any) => s.profit_rate || 0);
        const maxAbs = Math.max(Math.abs(Math.max(...values)), Math.abs(Math.min(...values)), 1);
        return Math.max(5, Math.round(50 + (value / maxAbs) * 45));
    }

    public get latestSnapshot(): any {
        const snapshots = this.profitChartData?.snapshots || [];
        return snapshots.length > 0 ? snapshots[snapshots.length - 1] : null;
    }

    public get firstSnapshot(): any {
        const snapshots = this.profitChartData?.snapshots || [];
        return snapshots.length > 0 ? snapshots[0] : null;
    }

    public trendDelta(key: string): number {
        if (!this.firstSnapshot || !this.latestSnapshot) return 0;
        return (Number(this.latestSnapshot[key]) || 0) - (Number(this.firstSnapshot[key]) || 0);
    }

    public assetTrendDelta(): number {
        const snapshots = this.profitChartData?.snapshots || [];
        const len = snapshots.length;
        if (len >= 2) {
            const prev = Number(snapshots[len - 2]?.total_asset) || 0;
            const curr = Number(snapshots[len - 1]?.total_asset) || 0;
            return curr - prev;
        }
        return 0;
    }

    public usDaytradeStatusText(): string {
        if (!this.daytradeRuntime?.us_enabled) return '미장 단타 비활성';
        if (!this.daytradeRuntime?.started) return '워커 미실행';
        if (this.daytradeRuntime?.us_auto_cycle_executed || this.daytradeRuntime?.us_exit_watch_executed) return '실행 검증 완료';
        return this.daytradeRuntime?.us_auto_cycle_message || this.daytradeRuntime?.us_exit_watch_message || '검증 대기';
    }

    public usDaytradeStatusClass(): string {
        if (!this.daytradeRuntime?.us_enabled || !this.daytradeRuntime?.started) return 'text-slate-400';
        if (this.daytradeRuntime?.us_auto_cycle_executed || this.daytradeRuntime?.us_exit_watch_executed) return 'text-emerald-400';
        return 'text-red-400';
    }

    public linePoints(data: any[], key: string, width: number = 320, height: number = 120, padding: number = 12): string {
        if (!data || data.length === 0) return '';

        const values = data.map((item: any) => Number(item?.[key]) || 0);
        const max = Math.max(...values);
        const min = Math.min(...values);
        const range = max - min || 1;
        const stepX = data.length > 1 ? (width - padding * 2) / (data.length - 1) : 0;

        return values.map((value, index) => {
            const x = padding + stepX * index;
            const y = height - padding - (((value - min) / range) * (height - padding * 2));
            return `${x},${y}`;
        }).join(' ');
    }

    public linePointsZeroCentered(data: any[], key: string, width: number = 320, height: number = 120, padding: number = 12): string {
        if (!data || data.length === 0) return '';

        const values = data.map((item: any) => Number(item?.[key]) || 0);
        const maxAbs = Math.max(1, ...values.map((v: number) => Math.abs(v)));
        const stepX = data.length > 1 ? (width - padding * 2) / (data.length - 1) : 0;
        const midY = height / 2;
        const usableHalf = Math.max(1, (height / 2) - padding);

        return values.map((value, index) => {
            const x = padding + stepX * index;
            const y = midY - ((value / maxAbs) * usableHalf);
            return `${x},${y}`;
        }).join(' ');
    }

    public areaPoints(data: any[], key: string, width: number = 320, height: number = 120, padding: number = 12): string {
        if (!data || data.length === 0) return '';

        const points = this.linePoints(data, key, width, height, padding);
        const stepX = data.length > 1 ? (width - padding * 2) / (data.length - 1) : 0;
        const firstX = padding;
        const lastX = padding + stepX * Math.max(data.length - 1, 0);

        return `${firstX},${height - padding} ${points} ${lastX},${height - padding}`;
    }

    /** x축에 고르게 배치할 날짜 tick 목록 (count: 최대 개수) */
    public chartXTicks(count: number = 6): { label: string; pct: number }[] {
        const snapshots = this.profitChartData?.snapshots || [];
        if (snapshots.length === 0) return [];
        const ticks: { label: string; pct: number }[] = [];
        const total = snapshots.length;
        // 첫째 + 마지마 + 중간 (count-2)개
        const indices = new Set<number>([0]);
        const step = Math.max(1, Math.round((total - 1) / (count - 1)));
        for (let i = step; i < total - 1; i += step) indices.add(i);
        indices.add(total - 1);
        Array.from(indices).sort((a, b) => a - b).forEach(i => {
            const date = snapshots[i]?.date || '';
            ticks.push({ label: date.substring(5), pct: total > 1 ? (i / (total - 1)) * 100 : 50 });
        });
        return ticks;
    }

    public assetYAxisLabels(): { max: number; mid: number; min: number } {
        const snapshots = this.profitChartData?.snapshots || [];
        if (!snapshots.length) return { max: 0, mid: 0, min: 0 };
        const values = snapshots.map((s: any) => Number(s.total_asset) || 0);
        const max = Math.max(...values);
        const min = Math.min(...values);
        return { max, mid: (max + min) / 2, min };
    }

    public chartPoints(data: any[], key: string, width: number = 320, height: number = 120, padding: number = 12): Array<{x:number,y:number,val:number,date:string}> {
        if (!data || data.length === 0) return [];
        const values = data.map((item: any) => Number(item?.[key]) || 0);
        const max = Math.max(...values);
        const min = Math.min(...values);
        const range = max - min || 1;
        const stepX = data.length > 1 ? (width - padding * 2) / (data.length - 1) : 0;
        return values.map((value, index) => ({
            x: padding + stepX * index,
            y: height - padding - (((value - min) / range) * (height - padding * 2)),
            val: value,
            date: String(data[index]?.date || ''),
        }));
    }

    // ─── Polling ───
    public startPolling() {
        if (this.pollInterval) return;
        this.pollInterval = setInterval(async () => {
            if (this.destroyed) return;
            if (this.autoRefresh) {
                await this.load(true);
            }
        }, this.pollSeconds * 1000);
        // Countdown timer (매초)
        this.countdownTimer = setInterval(() => {
            if (this.destroyed) return;
            if (this.autoRefresh && this.countdown > 0) {
                this.countdown--;
                if (this.countdown <= 5 || this.countdown % 5 === 0) {
                    void this.renderIfAlive();
                }
            }
        }, 1000);
    }

    public stopPolling() {
        if (this.pollInterval) { clearInterval(this.pollInterval); this.pollInterval = null; }
        if (this.countdownTimer) { clearInterval(this.countdownTimer); this.countdownTimer = null; }
    }

    public async toggleAutoRefresh() {
        this.autoRefresh = !this.autoRefresh;
        if (this.autoRefresh) {
            this.countdown = this.pollSeconds;
        }
        await this.renderIfAlive();
    }

    // ─── New Log Detection ───
    private detectNewLogs(newLogs: any[]): number {
        if (!this.recentLogs || this.recentLogs.length === 0) return 0;
        const prevFirst = this.recentLogs[0];
        if (!prevFirst) return 0;
        let newCount = 0;
        for (const log of newLogs) {
            if (log.created === prevFirst.created && log.symbol === prevFirst.symbol) break;
            newCount++;
        }
        return newCount;
    }

    private notifyNewLogs(logs: any[], count: number) {
        for (let i = Math.min(count, 3) - 1; i >= 0; i--) {
            const log = logs[i];
            const eventType = (log.event_type || '').toLowerCase();
            let type: Toast['type'] = 'info';
            if (eventType.includes('error')) type = 'error';
            else if (eventType.includes('sell')) type = 'success';
            else if (eventType.includes('buy')) type = 'info';
            else if (eventType.includes('cycle_complete')) type = 'success';

            this.addToast(type, `${log.symbol} - ${log.event_type}`, log.message || '');
        }
        if (count > 3) {
            this.addToast('info', 'Trade Activity', `${count} new events since last refresh`);
        }
    }

    // ─── Toast Management ───
    public addToast(type: Toast['type'], title: string, message: string) {
        const toast: Toast = {
            id: ++this.toastId,
            type, title, message,
            timestamp: new Date(),
        };
        this.toasts.push(toast);
        if (this.toasts.length > 5) this.toasts.shift();
        setTimeout(() => this.removeToast(toast.id), 5000);
    }

    public removeToast(id: number) {
        if (this.destroyed) return;
        this.toasts = this.toasts.filter(t => t.id !== id);
        void this.renderIfAlive();
    }

    public toastBorderClass(type: string): string {
        switch (type) {
            case 'success': return 'border-l-emerald-400';
            case 'error': return 'border-l-red-400';
            case 'warning': return 'border-l-amber-400';
            default: return 'border-l-indigo-400';
        }
    }

    public toastIconClass(type: string): string {
        switch (type) {
            case 'success': return 'text-emerald-400 bg-emerald-500/20';
            case 'error': return 'text-red-400 bg-red-500/20';
            case 'warning': return 'text-amber-400 bg-amber-500/20';
            default: return 'text-indigo-400 bg-indigo-500/20';
        }
    }

    // ─── Cycle Utils ───
    public cycleProgress(cycle: any): number {
        if (!cycle.division_count) return 0;
        return Math.round((cycle.current_round / cycle.division_count) * 100);
    }

    public profitClass(rate: number): string {
        return this.profitChangeClass(rate);
    }

    public statusBadge(status: string): string {
        switch (status) {
            case 'ACTIVE': return 'bg-indigo-500/20 text-indigo-300 border border-indigo-400/30';
            case 'HOLDING': return 'bg-amber-500/20 text-amber-300 border border-amber-400/30';
            case 'PAUSED': return 'bg-slate-500/20 text-slate-300 border border-slate-400/30';
            case 'PENDING_EXTENSION': return 'bg-orange-500/20 text-orange-300 border border-orange-400/30';
            case 'COMPLETED': return 'bg-emerald-500/20 text-emerald-300 border border-emerald-400/30';
            default: return 'bg-slate-500/20 text-slate-400 border border-slate-400/30';
        }
    }

    public locStatusBadge(status: string): string {
        const s = String(status || '').toLowerCase();
        if (s === 'scheduled' || s === 'done' || s === 'submitted') {
            return 'px-1.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-400/20';
        }
        if (s === 'waiting' || s === 'ready') {
            return 'px-1.5 py-0.5 rounded-full bg-indigo-500/15 text-indigo-300 border border-indigo-400/20';
        }
        if (s === 'attention' || s === 'failed' || s === 'error') {
            return 'px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-300 border border-amber-400/20';
        }
        if (s === 'not_required' || s === 'none' || s === 'disabled') {
            return 'px-1.5 py-0.5 rounded-full bg-slate-500/15 text-slate-400 border border-slate-400/20';
        }
        return 'px-1.5 py-0.5 rounded-full bg-slate-500/15 text-slate-300 border border-slate-400/20';
    }

    public locStatusLabel(cycle: any): string {
        const status = String(cycle?.loc_buy_status || '').toLowerCase();
        if (cycle?.loc_buy_status_label) return cycle.loc_buy_status_label;
        if (status === 'scheduled' || status === 'done' || status === 'submitted') return '예약 접수';
        if (status === 'attention' || status === 'failed' || status === 'error') return '확인 필요';
        if (status === 'waiting' || status === 'ready') return cycle?.loc_buy_status_label || '대기';
        if (status === 'not_required' || status === 'none' || status === 'disabled') return cycle?.loc_buy_status_label || '대상 아님';
        return cycle?.loc_buy_status_label || '-';
    }

    public cyclePriceMeta(cycle: any): string {
        const rawSource = String(cycle?.price_source || '').trim();
        const source = rawSource.toLowerCase().includes('alpaca')
            ? '24시간 시세'
            : rawSource.toLowerCase().includes('yahoo')
            ? 'Yahoo'
            : rawSource.startsWith('KIS:')
                ? rawSource.replace('KIS:', 'KIS ')
                : rawSource;
        const rawKst = String(cycle?.price_timestamp_kst || '').trim();
        const rawIso = String(cycle?.price_timestamp || '').trim();
        let timeLabel = '';
        if (rawKst) {
            timeLabel = rawKst.replace(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}).*$/, '$2.$3 $4:$5');
        } else if (rawIso) {
            const parsed = new Date(rawIso);
            if (!Number.isNaN(parsed.getTime())) {
                timeLabel = parsed.toLocaleString('ko-KR', {
                    timeZone: 'Asia/Seoul',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    hour12: false,
                }).replace(/\.\s?/g, '.').replace(/,$/, '');
            }
        }
        const age = Number(cycle?.price_age_sec) || 0;
        let ageLabel = '';
        if (age >= 3600) ageLabel = `${Math.floor(age / 3600)}시간 전`;
        else if (age >= 60) ageLabel = `${Math.floor(age / 60)}분 전`;
        const parts = [source, timeLabel, ageLabel].filter(Boolean);
        return parts.join(' · ');
    }

    public cycleStatusLabel(status: string): string {
        const s = String(status || '').toUpperCase();
        if (s === 'ACTIVE') return '진행중';
        if (s === 'HOLDING') return '보유감시';
        if (s === 'PAUSED') return '일시정지';
        if (s === 'PENDING_EXTENSION') return '추가설정';
        if (s === 'COMPLETED') return '완료';
        return s || '-';
    }

    public infiniteBuyCycleToggleLabel(cycle: any): string {
        const status = String(cycle?.status || '').toUpperCase();
        if (status === 'PAUSED') return 'OFF';
        if (status === 'COMPLETED') return '완료';
        if (status === 'PENDING_EXTENSION') return '설정필요';
        return 'ON';
    }

    public infiniteBuyCycleToggleClass(cycle: any): string {
        const status = String(cycle?.status || '').toUpperCase();
        if (status === 'PAUSED') {
            return 'bg-slate-500/10 border-slate-400/30 text-slate-300 hover:bg-slate-500/20';
        }
        if (status === 'COMPLETED' || status === 'PENDING_EXTENSION') {
            return 'bg-slate-500/10 border-slate-400/20 text-slate-500';
        }
        return 'bg-emerald-500/10 border-emerald-400/30 text-emerald-300 hover:bg-emerald-500/20';
    }

    public async toggleAutoTrade() {
        if (this.isMock) {
            this.addToast('warning', this.t('dash.demo_mode'), this.t('dash.demo_desc'));
            return;
        }
        try {
            const { code, data } = await wiz.call("toggle_auto_trade");
            if (code === 200) {
                this.engineStatus.auto_trade = data?.auto_trade === true;
                this.engineStatus.loc_auto_schedule_enabled = data?.loc_auto_schedule_enabled === true;
                this.infiniteBuySummary.loc_auto_enabled = data?.loc_auto_schedule_enabled === true;
                const state = this.engineStatus.auto_trade ? 'ON' : 'OFF';
                this.addToast(this.engineStatus.auto_trade ? 'success' : 'warning',
                    '무한매수 매매', `무한매수 매매 ${state}`);
            } else {
                this.addToast('error', this.t('engine.auto_trading'), data?.message || '자동매매 설정 변경 실패');
            }
        } catch (e: any) {
            this.addToast('error', this.t('engine.auto_trading'), e?.message || '자동매매 설정 변경 중 오류가 발생했습니다.');
        }
        await this.renderIfAlive();
    }

    public async toggleAutomationItem(item: any) {
        if (!item?.key || this.automationSaving[item.key]) return;
        if (this.isMock) {
            this.addToast('warning', this.t('dash.demo_mode'), this.t('dash.demo_desc'));
            return;
        }
        if (item.enabled !== true && this.isDaytradeAutomationItem(item)) {
            const confirmed = await this.confirmAutomationEnable(item);
            if (!confirmed) {
                return;
            }
        }
        this.automationSaving[item.key] = true;
        await this.renderIfAlive();
        try {
            const { code, data } = await wiz.call("toggle_automation", { key: item.key });
            if (code === 200) {
                item.enabled = data?.enabled === true;
                if (data?.automation_controls) {
                    this.automationControls = data.automation_controls;
                    this.syncAutomationSeedDrafts();
                }
                if (item.key === 'infinite_buy') this.engineStatus.auto_trade = item.enabled;
                this.addToast(item.enabled ? 'success' : 'warning', item.title || '자동매매', item.enabled ? '자동 실행을 켰습니다.' : '자동 실행을 껐습니다.');
            } else {
                this.addToast('error', item.title || '자동매매', data?.message || '자동매매 설정 변경 실패');
            }
        } catch (e: any) {
            this.addToast('error', item.title || '자동매매', e?.message || '자동매매 설정 변경 실패');
        } finally {
            this.automationSaving[item.key] = false;
            await this.renderIfAlive();
        }
    }

    public async saveAutomationItem(item: any) {
        if (!item?.key || this.automationSaving[item.key]) return;
        if (this.isMock) {
            this.addToast('warning', this.t('dash.demo_mode'), this.t('dash.demo_desc'));
            return;
        }
        const seedKrw = this.parseSeedDraft(this.automationSeedDraft(item), 0);
        if (!isFinite(seedKrw) || seedKrw < 0) {
            this.addToast('error', item.title || '시드', '시드는 0 이상의 숫자로 입력해야 합니다.');
            return;
        }
        this.automationSaving[item.key] = true;
        await this.renderIfAlive();
        try {
            const { code, data } = await wiz.call("save_automation", {
                key: item.key,
                seed_krw: seedKrw,
            });
            if (code === 200) {
                this.automationSeedDirty[item.key] = false;
                item.seed_krw = seedKrw;
                this.automationSeedDrafts[item.key] = this.seedDraftText(seedKrw);
                if (data?.automation_controls) {
                    this.automationControls = data.automation_controls;
                    this.syncAutomationSeedDrafts();
                }
                this.addToast('success', item.title || '시드', '시드를 저장했습니다.');
                await this.load(true, true);
            } else {
                this.addToast('error', item.title || '시드', data?.message || '시드 저장 실패');
            }
        } catch (e: any) {
            this.addToast('error', item.title || '시드', e?.message || '시드 저장 실패');
        } finally {
            this.automationSaving[item.key] = false;
            await this.renderIfAlive();
        }
    }

    public async runEngineNow() {
        if (this.isMock) {
            this.addToast('warning', this.t('dash.demo_mode'), this.t('dash.demo_desc'));
            return;
        }
        this.addToast('info', '엔진', this.t('engine.run_now') + '...');
        this.loading = true;
        await this.renderIfAlive();
        const { code, data } = await wiz.call("run_engine");
        if (code === 200) {
            const results = data.results || [];
            this.addToast('success', '엔진 실행 완료', `${results.length}개 종목을 처리했습니다.`);
            await this.load();
        } else {
            this.addToast('error', '엔진 오류', data?.message || '알 수 없는 오류가 발생했습니다.');
        }
        this.loading = false;
        await this.renderIfAlive();
    }

    // ─── Cycle Management ───
    public async startCycle(symbol: string) {
        if (!symbol) {
            this.addToast('warning', this.t('engine.start'), this.t('engine.select_symbol'));
            return;
        }
        if (this.isMock) {
            this.addToast('warning', this.t('dash.demo_mode'), this.t('dash.demo_desc'));
            return;
        }
        await this.openStartModal(symbol);
    }

    // ─── Start Cycle Modal ───
    public async openStartModal(symbol: string) {
        this.startModalSymbol = symbol;
        this.startModalName = '';
        this.startModalLoading = true;
        this.showStartModal = true;
        await this.renderIfAlive();

        try {
            const { code, data } = await wiz.call("get_watchlist_defaults", { symbol });
            if (code === 200) {
                this.startModalName = data.name || '';
                this.startModalInvestment = data.total_investment || 0;
                this.startModalDivision = data.division_count || 40;
                this.startModalTarget = data.target_profit || 10;
            }
        } catch (e) {
            console.error("Watchlist defaults load error:", e);
        }

        this.startModalLoading = false;
        await this.renderIfAlive();
    }

    public async closeStartModal() {
        this.showStartModal = false;
        await this.renderIfAlive();
    }

    public async confirmStartCycle() {
        if (!this.startModalSymbol) return;
        this.startModalLoading = true;
        await this.renderIfAlive();

        const { code, data } = await wiz.call("start_cycle", {
            symbol: this.startModalSymbol,
            total_investment: this.startModalInvestment,
            division_count: this.startModalDivision,
            target_profit: this.startModalTarget,
        });
        this.showStartModal = false;
        this.startModalLoading = false;
        if (code === 200) {
            this.addToast('success', '사이클 시작', `${this.startModalSymbol} - $${this.startModalInvestment}, ${this.startModalDivision}분할, 목표 ${this.startModalTarget}%`);
            await this.load();
        } else {
            this.addToast('error', '오류', data?.message || '사이클 시작에 실패했습니다.');
        }
        await this.renderIfAlive();
    }

    // ─── Trade Preview ───
    public async loadTradePreview() {
        if (this.destroyed) return;
        if (this.tradePreviewPromise) {
            await this.tradePreviewPromise;
            return;
        }

        const task = this._loadTradePreviewInternal();
        this.tradePreviewPromise = task;
        try {
            await task;
        } finally {
            if (this.tradePreviewPromise === task) {
                this.tradePreviewPromise = null;
            }
        }
    }

    private async _loadTradePreviewInternal() {
        if (this.destroyed) return;
        this.tradePreviewLoading = true;
        await this.renderIfAlive();

        try {
            const { code, data } = await wiz.call("trade_preview");
            if (this.destroyed) return;
            if (code === 200) {
                this.tradePreviews = data.previews || [];
                this.tradePreviewApiConnected = data.api_connected === true || this.apiConnected === true;
                this.persistCachedState();
            }
        } catch (e) {
            console.error("Trade preview load error:", e);
            this.tradePreviewApiConnected = this.apiConnected === true;
        }

        if (this.destroyed) return;
        this.tradePreviewLoading = false;
        await this.renderIfAlive();
    }

    private restoreCachedState(): boolean {
        try {
            const globalWindow: any = typeof window !== 'undefined' ? window : null;
            if (!globalWindow) return false;
            const cacheKey = this.dashboardCacheKey();
            if (!cacheKey) return false;
            let raw = globalWindow[cacheKey];
            if (!raw || typeof raw !== 'object') {
                const stored = globalWindow.localStorage?.getItem(cacheKey);
                raw = stored ? JSON.parse(stored) : null;
            }
            if (!raw || typeof raw !== 'object') return false;
            const sessionKey = this.dashboardSessionKey();
            if (!sessionKey || raw.sessionKey !== sessionKey) return false;
            const ageMs = Date.now() - Number(raw.ts || 0);
            if (!isFinite(ageMs) || ageMs > 1800000) return false;
            const state = raw.state || {};
            this.buyingPower = Number(state.buyingPower) || 0;
            this.orderableCash = Number(state.orderableCash) || 0;
            this.usdBuyingPower = Number(state.usdBuyingPower) || 0;
            this.usdSyncOk = state.usdSyncOk === true;
            this.usdSyncMessage = String(state.usdSyncMessage || '');
            this.usdSyncSource = String(state.usdSyncSource || '');
            this.krwBalance = Number(state.krwBalance) || 0;
            this.krwOrderableCash = Number(state.krwOrderableCash) || 0;
            this.krwOrderableSource = String(state.krwOrderableSource || '');
            this.krwOrderableProbe = String(state.krwOrderableProbe || '');
            this.krwOrderableGap = Number(state.krwOrderableGap) || 0;
            this.krwBuyingPowerUsd = Number(state.krwBuyingPowerUsd) || 0;
            this.portfolioValue = Number(state.portfolioValue) || 0;
            this.totalAsset = Number(state.totalAsset) || 0;
            this.exchangeRate = Number(state.exchangeRate) || 0;
            this.balanceSyncOk = state.balanceSyncOk === true;
            this.balanceSyncMessage = String(state.balanceSyncMessage || '');
            this.balanceSyncSource = String(state.balanceSyncSource || '');
            this.setupRequired = state.setupRequired === true;
            this.privacyLocked = state.privacyLocked === true;
            this.setupMessage = String(state.setupMessage || '');
            this.engineStatus = state.engineStatus || this.engineStatus;
            this.apiConnected = state.apiConnected === true;
            this.cycles = Array.isArray(state.cycles) ? state.cycles : [];
            this.infiniteBuyCycles = Array.isArray(state.infiniteBuyCycles) ? state.infiniteBuyCycles : this.cycles;
            this.infiniteBuySummary = state.infiniteBuySummary || this.infiniteBuySummary;
            this.fireGateBridge = state.fireGateBridge || this.fireGateBridge;
            this.holdings = Array.isArray(state.holdings) ? state.holdings : [];
            this.daytradePositions = Array.isArray(state.daytradePositions) ? state.daytradePositions : [];
            this.daytradePositionSummary = state.daytradePositionSummary || this.daytradePositionSummary;
            this.recentLogs = Array.isArray(state.recentLogs) ? state.recentLogs : [];
            this.watchlistInfo = Array.isArray(state.watchlistInfo) ? state.watchlistInfo : [];
            this.tradePreviews = Array.isArray(state.tradePreviews) ? state.tradePreviews : [];
            this.tradePreviewApiConnected = state.tradePreviewApiConnected === true;
            this.profitData = state.profitData || this.profitData;
            this.profitChartData = state.profitChartData || this.profitChartData;
            this.daytradeRuntime = state.daytradeRuntime || this.daytradeRuntime;
            this.automationControls = Array.isArray(state.automationControls) ? state.automationControls : this.automationControls;
            this.balanceDiagnostics = Array.isArray(state.balanceDiagnostics) ? state.balanceDiagnostics : this.balanceDiagnostics;
            this.lastRefresh = raw.ts ? new Date(raw.ts) : new Date();
            this.lastRefreshKst = String(state.lastRefreshKst || '');
            this.profitLastRefresh = state.profitLastRefresh ? new Date(state.profitLastRefresh) : this.profitLastRefresh;
            this.profitLastRefreshKst = String(state.profitLastRefreshKst || '');
            this.syncSeedDrafts();
            if (this.setupRequired || this.privacyLocked) {
                this.profitData = this.emptyProfitSummary(this.setupMessage);
                this.profitChartData = this.emptyProfitSummary(this.setupMessage);
            } else {
                this.applyLiveUnrealizedFromOverview();
            }
            return true;
        } catch (e) {
            return false;
        }
    }

    private persistCachedState() {
        try {
            const globalWindow: any = typeof window !== 'undefined' ? window : null;
            if (!globalWindow) return;
            const cacheKey = this.dashboardCacheKey();
            const sessionKey = this.dashboardSessionKey();
            if (!cacheKey || !sessionKey) return;
            const payload = {
                ts: Date.now(),
                sessionKey,
                state: {
                    buyingPower: this.buyingPower,
                    orderableCash: this.orderableCash,
                    usdBuyingPower: this.usdBuyingPower,
                    usdSyncOk: this.usdSyncOk,
                    usdSyncMessage: this.usdSyncMessage,
                    usdSyncSource: this.usdSyncSource,
                    krwBalance: this.krwBalance,
                    krwOrderableCash: this.krwOrderableCash,
                    krwOrderableSource: this.krwOrderableSource,
                    krwOrderableProbe: this.krwOrderableProbe,
                    krwOrderableGap: this.krwOrderableGap,
                    krwBuyingPowerUsd: this.krwBuyingPowerUsd,
                    portfolioValue: this.portfolioValue,
                    totalAsset: this.totalAsset,
                    exchangeRate: this.exchangeRate,
                    balanceSyncOk: this.balanceSyncOk,
                    balanceSyncMessage: this.balanceSyncMessage,
                    balanceSyncSource: this.balanceSyncSource,
                    setupRequired: this.setupRequired,
                    privacyLocked: this.privacyLocked,
                    setupMessage: this.setupMessage,
                    engineStatus: this.engineStatus,
                    apiConnected: this.apiConnected,
                    cycles: this.cycles,
                    infiniteBuyCycles: this.infiniteBuyCycles,
                    infiniteBuySummary: this.infiniteBuySummary,
                    fireGateBridge: this.fireGateBridge,
                    holdings: this.holdings,
                    daytradePositions: this.daytradePositions,
                    daytradePositionSummary: this.daytradePositionSummary,
                    recentLogs: this.recentLogs,
                    watchlistInfo: this.watchlistInfo,
                    tradePreviews: this.tradePreviews,
                    tradePreviewApiConnected: this.tradePreviewApiConnected,
                    profitData: this.profitData,
                    profitChartData: this.profitChartData,
                    profitLastRefresh: this.profitLastRefresh ? this.profitLastRefresh.toISOString() : '',
                    profitLastRefreshKst: this.profitLastRefreshKst,
                    daytradeRuntime: this.daytradeRuntime,
                    automationControls: this.automationControls,
                    balanceDiagnostics: this.balanceDiagnostics,
                    lastRefreshKst: this.lastRefreshKst,
                },
            };
            globalWindow[cacheKey] = payload;
            try {
                globalWindow.localStorage?.removeItem(DASHBOARD_CACHE_KEY);
                globalWindow.localStorage?.setItem(cacheKey, JSON.stringify(payload));
            } catch (e) {
            }
        } catch (e) {
        }
    }

    public tradePreviewBuyClass(preview: any): string {
        if (!preview.should_buy) return 'bg-slate-500/20 text-slate-400';
        if (preview.order_type === 'MARKET') return 'bg-amber-500/20 text-amber-300';
        return 'bg-indigo-500/20 text-indigo-300';
    }

    public tradePreviewSellClass(preview: any): string {
        if (!preview.should_sell) return 'bg-slate-500/20 text-slate-400';
        if (preview.sell_type === 'PARTIAL_SELL') return 'bg-amber-500/20 text-amber-300';
        return 'bg-emerald-500/20 text-emerald-300';
    }

    public async selectStartSymbol(symbol: string) {
        this.selectedStartSymbol = symbol;
        await this.renderIfAlive();
    }

    public async startSelectedCycle() {
        if (!this.selectedStartSymbol || this.startingCycle) {
            return;
        }
        await this.startCycle(this.selectedStartSymbol);
    }

    public async forceCloseCycle(cycle: any, event?: Event) {
        if (event) event.stopPropagation();
        if (this.isMock) {
            this.addToast('warning', this.t('dash.demo_mode'), this.t('dash.demo_desc'));
            return;
        }
        const confirmed = await this.service.modal.show({
            title: '사이클 강제 종료',
            message: `${cycle.symbol} #${cycle.cycle_number || '?'} - 강제로 종료할까요? 보유 수량은 시장가 기준으로 매도됩니다.`,
            action: '종료',
            cancel: '취소',
        });
        if (!confirmed) return;

        this.addToast('info', '사이클', `${cycle.symbol} 종료 중...`);
        const { code, data } = await wiz.call("force_close_cycle", { cycle_id: cycle.id });
        if (code === 200) {
            this.addToast('success', '사이클 종료', `${cycle.symbol} 강제 종료 완료`);
            await this.load();
        } else {
            this.addToast('error', '오류', data?.message || '사이클 종료에 실패했습니다.');
        }
        await this.renderIfAlive();
    }

    public async pauseCycle(cycle: any, event?: Event) {
        if (event) event.stopPropagation();
        if (this.isMock) {
            this.addToast('warning', this.t('dash.demo_mode'), this.t('dash.demo_desc'));
            return;
        }
        const { code, data } = await wiz.call("pause_cycle", { cycle_id: cycle.id });
        if (code === 200) {
            this.addToast('info', '사이클 일시정지', `${cycle.symbol} 일시정지 완료`);
            await this.load();
        } else {
            this.addToast('error', '오류', data?.message || '사이클 일시정지에 실패했습니다.');
        }
        await this.renderIfAlive();
    }

    public async resumeCycle(cycle: any, event?: Event) {
        if (event) event.stopPropagation();
        if (this.isMock) {
            this.addToast('warning', this.t('dash.demo_mode'), this.t('dash.demo_desc'));
            return;
        }
        const { code, data } = await wiz.call("resume_cycle", { cycle_id: cycle.id });
        if (code === 200) {
            this.addToast('success', '사이클 재개', `${cycle.symbol} 재개 완료`);
            await this.load();
        } else {
            this.addToast('error', '오류', data?.message || '사이클 재개에 실패했습니다.');
        }
        await this.renderIfAlive();
    }

    public async toggleInfiniteBuyCycle(cycle: any, event?: Event) {
        if (event) event.stopPropagation();
        const status = String(cycle?.status || '').toUpperCase();
        if (status === 'COMPLETED' || status === 'PENDING_EXTENSION') return;
        if (status === 'PAUSED') {
            await this.resumeCycle(cycle, event);
        } else {
            await this.pauseCycle(cycle, event);
        }
    }

    public async retryLocBuyReservation(cycle: any, event?: Event) {
        if (event) event.stopPropagation();
        if (!cycle?.symbol) return;
        if (this.isMock) {
            this.addToast('warning', this.t('dash.demo_mode'), this.t('dash.demo_desc'));
            return;
        }
        const key = `loc_retry_${cycle.id || cycle.symbol}`;
        if (this.automationSaving[key]) return;
        this.automationSaving[key] = true;
        await this.renderIfAlive();
        try {
            const { code, data } = await wiz.call("retry_loc_buy_reservation", {
                symbol: cycle.symbol,
                cycle_id: cycle.id,
            });
            if (code === 200) {
                const result = data?.result || {};
                const scheduled = Number(result.scheduled_count || 0);
                const already = Number(result.already_scheduled_count || 0);
                const errors = Number(result.error_count || 0);
                if (scheduled > 0) {
                    this.addToast('success', 'LOC 예약 재시도', `${cycle.symbol} 예약매수 ${scheduled}건을 다시 접수했습니다.`);
                } else if (already > 0) {
                    this.addToast('success', 'LOC 예약 확인', `${cycle.symbol} 예약매수가 이미 접수되어 있습니다.`);
                } else if (errors > 0) {
                    const reason = result.errors?.[0]?.reason || data?.message || '예약 재시도 실패';
                    this.addToast('error', 'LOC 예약 재시도', reason);
                } else {
                    this.addToast('info', 'LOC 예약 재시도', result.message || result.reason || `${cycle.symbol} 예약 대상이 없습니다.`);
                }
                await this.load(true, true);
            } else {
                this.addToast('error', 'LOC 예약 재시도', data?.message || '예약 재시도 실패');
            }
        } catch (e: any) {
            this.addToast('error', 'LOC 예약 재시도', e?.message || '예약 재시도 실패');
        } finally {
            this.automationSaving[key] = false;
            await this.renderIfAlive();
        }
    }

    public async saveInfiniteBuySeed(cycle: any, event?: Event) {
        if (event) event.stopPropagation();
        if (!cycle?.id || this.isMock) return;
        if (this.isInfiniteBuySeedReadOnly()) {
            this.addToast('info', '종목별 시드', '무한매수 종목별 시드는 FireGate 포트폴리오에서 수정한 뒤 자동 동기화로 반영됩니다.');
            return;
        }
        const key = `ib_seed_${cycle.id}`;
        if (this.automationSaving[key]) return;
        const seedUsd = this.parseSeedDraft(this.infiniteBuySeedDraft(cycle), -1);
        if (!isFinite(seedUsd) || seedUsd <= 0) {
            this.addToast('error', '종목별 시드', '종목별 시드는 0보다 큰 USD 숫자로 입력해야 합니다.');
            return;
        }
        this.automationSaving[key] = true;
        await this.renderIfAlive();
        try {
            const { code, data } = await wiz.call("update_infinite_buy_seed", {
                symbol: cycle.symbol,
                cycle_id: cycle.id,
                seed_usd: seedUsd,
            });
            if (code === 200) {
                const savedSeed = Number(data?.seed_usd || seedUsd);
                this.infiniteBuySeedDirty[cycle.id] = false;
                cycle.total_investment = savedSeed;
                this.infiniteBuySeedDrafts[cycle.id] = this.seedDraftText(savedSeed);
                this.addToast('success', '종목별 시드', `${cycle.symbol} 시드를 $${this.formatUSD(savedSeed)}로 저장했습니다.`);
                await this.load(true, true);
            } else {
                this.addToast('error', '종목별 시드', data?.message || '시드 저장 실패');
            }
        } catch (e: any) {
            this.addToast('error', '종목별 시드', e?.message || '시드 저장 실패');
        } finally {
            this.automationSaving[key] = false;
            await this.renderIfAlive();
        }
    }

    public async deleteCycle(cycle: any, event?: Event) {
        if (event) event.stopPropagation();
        const confirmed = await this.service.modal.show({
            title: this.t('cycle.delete_title'),
            message: `${cycle.symbol} #${cycle.cycle_number || '?'} — ${this.t('cycle.delete_confirm')}`,
            action: this.t('cycle.delete_btn'),
            cancel: this.t('engine.start_cancel'),
        });
        if (!confirmed) return;
        const { code, data } = await wiz.call("delete_cycle", { cycle_id: cycle.id });
        if (code === 200) {
            this.addToast('success', this.t('cycle.delete_title'), `${cycle.symbol} ${this.t('cycle.deleted')}`);
            await this.load();
        } else {
            this.addToast('error', '오류', data?.message || '사이클 삭제에 실패했습니다.');
        }
        await this.renderIfAlive();
    }

    // ─── Cycle Edit ───
    public async openEditModal(cycle: any, event?: Event) {
        if (event) event.stopPropagation();
        if (this.isMock) {
            this.addToast('warning', this.t('dash.demo_mode'), this.t('dash.demo_desc'));
            return;
        }
        this.editCycleId = cycle.id;
        this.editSymbol = cycle.symbol;
        this.editTargetProfit = cycle.target_profit;
        this.editDivisionCount = cycle.division_count;
        this.editTotalInvestment = cycle.total_investment;
        this.editCurrentRound = cycle.current_round;
        this.editTotalSpent = cycle.total_spent;
        this.showEditModal = true;
        await this.renderIfAlive();
    }

    public async closeEditModal() {
        this.showEditModal = false;
        await this.renderIfAlive();
    }

    public async saveEditCycle() {
        this.editLoading = true;
        await this.renderIfAlive();

        const { code, data } = await wiz.call("update_cycle", {
            cycle_id: this.editCycleId,
            target_profit: this.editTargetProfit,
            division_count: this.editDivisionCount,
            total_investment: this.editTotalInvestment,
        });

        this.editLoading = false;
        if (code === 200) {
            this.addToast('success', this.t('cycle.edit_title'), `${this.editSymbol} ${this.t('cycle.edit_saved')}`);
            this.showEditModal = false;
            await this.load();
        } else {
            this.addToast('error', '오류', data?.message || '사이클 수정에 실패했습니다.');
        }
        await this.renderIfAlive();
    }

    // ─── Extension (추가 매수 확인) ───
    public async openExtensionModal(cycle: any, event?: Event) {
        if (event) event.stopPropagation();
        this.extensionCycleId = cycle.id;
        this.extensionSymbol = cycle.symbol;
        this.extensionExtraRounds = 10;
        this.extensionExtraInvestment = 0;
        this.showExtensionModal = true;
        await this.renderIfAlive();
    }

    public async closeExtensionModal() {
        this.showExtensionModal = false;
        await this.renderIfAlive();
    }

    public async extendCycle() {
        if (this.isMock) {
            this.addToast('warning', this.t('dash.demo_mode'), this.t('dash.demo_desc'));
            this.showExtensionModal = false;
            await this.renderIfAlive();
            return;
        }
        const { code, data } = await wiz.call("extend_cycle", {
            cycle_id: this.extensionCycleId,
            extra_rounds: this.extensionExtraRounds,
            extra_investment: this.extensionExtraInvestment,
        });
        this.showExtensionModal = false;
        if (code === 200) {
            this.addToast('success', '사이클 연장', `${this.extensionSymbol} ${this.extensionExtraRounds}회차 추가`);
            await this.load();
        } else {
            this.addToast('error', '오류', data?.message || '사이클 연장에 실패했습니다.');
        }
        await this.renderIfAlive();
    }

    public async keepHolding(cycle: any, event?: Event) {
        if (event) event.stopPropagation();
        if (this.isMock) {
            this.addToast('warning', this.t('dash.demo_mode'), this.t('dash.demo_desc'));
            return;
        }
        const confirmed = await this.service.modal.show({
            title: '보유 유지',
            message: `${cycle.symbol} #${cycle.cycle_number || '?'} - 추가 매수 없이 보유만 유지할까요? 목표 수익에 도달하면 매도만 진행합니다.`,
            action: '보유 유지',
            cancel: '취소',
        });
        if (!confirmed) return;

        const { code, data } = await wiz.call("keep_holding", { cycle_id: cycle.id });
        if (code === 200) {
            this.addToast('info', '보유 유지', `${cycle.symbol} 보유 유지로 변경했습니다.`);
            await this.load();
        } else {
            this.addToast('error', '오류', data?.message || '보유 유지 처리에 실패했습니다.');
        }
        await this.renderIfAlive();
    }

    // ─── Cycle Detail ───
    public async openCycleDetail(cycle: any) {
        this.detailLoading = true;
        this.detailTab = 'summary';
        this.detailTradeFilter = 'ALL';
        this.showCycleDetail = true;
        this.detailCycle = cycle;
        this.detailTrades = [];
        this.detailChartData = [];
        this.detailLogs = [];
        await this.renderIfAlive();

        try {
            const { code, data } = await wiz.call("cycle_detail", { cycle_id: cycle.id });
            if (code === 200) {
                this.detailCycle = data.cycle || cycle;
                this.detailTrades = data.trades || [];
                this.detailChartData = data.chart_data || [];
                this.detailLogs = data.logs || [];
            }
        } catch (e) {
            console.error("Cycle detail load error:", e);
        }

        this.detailLoading = false;
        await this.renderIfAlive();
    }

    public async closeCycleDetail() {
        this.showCycleDetail = false;
        await this.renderIfAlive();
    }

    public async setDetailTab(tab: string) {
        this.detailTab = tab;
        await this.renderIfAlive();
    }

    public setDetailTradeFilter(filter: string) {
        this.detailTradeFilter = filter;
        void this.renderIfAlive();
    }

    public async deleteTrade(trade: any, event?: Event) {
        if (event) event.stopPropagation();
        if (!trade?.id || trade.id.startsWith('mock-')) {
            this.addToast('warning', 'Demo', 'Mock 데이터는 삭제할 수 없습니다.');
            return;
        }
        const confirmed = await this.service.modal.show({
            title: '거래 삭제',
            message: `Round ${trade.round || '?'} ${trade.action} — 이 거래를 삭제하시겠습니까? 사이클 통계가 재계산됩니다.`,
            action: '삭제',
            cancel: '취소',
        });
        if (!confirmed) return;

        const { code, data } = await wiz.call("delete_trade", { trade_id: trade.id });
        if (code === 200) {
            this.addToast('success', '삭제 완료', '거래가 삭제되었습니다.');
            // 상세 데이터 새로고침
            if (this.detailCycle?.id) {
                await this.openCycleDetail(this.detailCycle);
            }
            await this.load();
        } else {
            this.addToast('error', '오류', data?.message || '거래 삭제 실패');
        }
        await this.renderIfAlive();
    }

    public get filteredDetailTrades(): any[] {
        if (this.detailTradeFilter === 'ALL') return this.detailTrades;
        return this.detailTrades.filter(t => t.action === this.detailTradeFilter);
    }

    public detailActionClass(action: string): string {
        switch (action) {
            case 'BUY': return 'bg-indigo-500/20 text-indigo-300';
            case 'SELL': return 'bg-emerald-500/20 text-emerald-300';
            case 'SKIP': return 'bg-slate-500/20 text-slate-400';
            case 'EXTEND': return 'bg-orange-500/20 text-orange-300';
            default: return 'bg-slate-500/20 text-slate-400';
        }
    }

    public detailLogTypeClass(eventType: string): string {
        const et = (eventType || '').toLowerCase();
        if (et.includes('error')) return 'bg-red-500/20 text-red-300';
        if (et.includes('sell') || et.includes('complete')) return 'bg-emerald-500/20 text-emerald-300';
        if (et.includes('buy') || et.includes('fill')) return 'bg-indigo-500/20 text-indigo-300';
        if (et.includes('start') || et.includes('cycle')) return 'bg-violet-500/20 text-violet-300';
        if (et.includes('skip') || et.includes('price')) return 'bg-slate-500/20 text-slate-400';
        return 'bg-white/5 text-slate-400';
    }

    // Chart: max/min for simple bar visualization
    public chartBarHeight(value: number, data: any[], key: string): number {
        if (!data || data.length === 0) return 0;
        const values = data.map(d => d[key] || 0);
        const max = Math.max(...values);
        const min = Math.min(...values);
        const range = max - min || 1;
        return Math.max(5, Math.round(((value - min) / range) * 100));
    }

    // 종목의 cycle_mode 조회
    public getCycleMode(symbol: string): string {
        const info = this.watchlistInfo.find((w: any) => w.symbol === symbol);
        return info?.cycle_mode || 'auto';
    }

    // 해당 종목에 활성 사이클이 있는지 확인
    public hasActiveCycle(symbol: string): boolean {
        return this.cycles.some(c => c.symbol === symbol);
    }

    // 워치리스트에서 사이클 없는 종목 목록
    public get watchlistWithoutCycle(): any[] {
        return this.watchlistInfo.filter((w: any) => !this.hasActiveCycle(w.symbol));
    }

    public quickNavGridClass(): string {
        if (this.showDaytradeQuickLink) {
            return 'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3 mb-6';
        }
        return 'grid grid-cols-1 md:grid-cols-3 gap-3 mb-6';
    }

    public automationSeedDraft(item: any): string {
        const key = String(item?.key || '');
        if (key && this.automationSeedDrafts[key] !== undefined) return this.automationSeedDrafts[key];
        return this.seedDraftText(item?.seed_krw || 0);
    }

    public onAutomationSeedInput(item: any, value: any) {
        const key = String(item?.key || '');
        if (!key) return;
        this.automationSeedDrafts[key] = value === null || value === undefined ? '' : String(value);
        this.automationSeedDirty[key] = true;
    }

    public infiniteBuySeedDraft(cycle: any): string {
        const key = String(cycle?.id || '');
        if (key && this.infiniteBuySeedDrafts[key] !== undefined) return this.infiniteBuySeedDrafts[key];
        return this.seedDraftText(cycle?.total_investment || 0);
    }

    public isInfiniteBuySeedReadOnly(): boolean {
        return !!(this.fireGateBridge?.enabled && this.fireGateBridge?.configured);
    }

    public onInfiniteBuySeedInput(cycle: any, value: any) {
        const key = String(cycle?.id || '');
        if (!key) return;
        this.infiniteBuySeedDrafts[key] = value === null || value === undefined ? '' : String(value);
        this.infiniteBuySeedDirty[key] = true;
    }

    private syncSeedDrafts() {
        this.syncAutomationSeedDrafts();
        this.syncInfiniteBuySeedDrafts();
    }

    private syncAutomationSeedDrafts() {
        const liveKeys = new Set<string>();
        for (const item of this.automationControls || []) {
            const key = String(item?.key || '');
            if (!key) continue;
            liveKeys.add(key);
            if (!this.automationSeedDirty[key] && !this.automationSaving[key]) {
                this.automationSeedDrafts[key] = this.seedDraftText(item?.seed_krw || 0);
            }
        }
        for (const key of Object.keys(this.automationSeedDrafts)) {
            if (!liveKeys.has(key) && !this.automationSeedDirty[key]) delete this.automationSeedDrafts[key];
        }
    }

    private syncInfiniteBuySeedDrafts() {
        const liveKeys = new Set<string>();
        for (const cycle of this.infiniteBuyCycles || []) {
            const key = String(cycle?.id || '');
            if (!key) continue;
            liveKeys.add(key);
            const savingKey = `ib_seed_${key}`;
            if (!this.infiniteBuySeedDirty[key] && !this.automationSaving[savingKey]) {
                this.infiniteBuySeedDrafts[key] = this.seedDraftText(cycle?.total_investment || 0);
            }
        }
        for (const key of Object.keys(this.infiniteBuySeedDrafts)) {
            if (!liveKeys.has(key) && !this.infiniteBuySeedDirty[key]) delete this.infiniteBuySeedDrafts[key];
        }
    }

    private parseSeedDraft(value: any, fallback: number): number {
        if (value === null || value === undefined || String(value).trim() === '') return fallback;
        const parsed = Number(String(value).replace(/,/g, ''));
        return isFinite(parsed) ? parsed : fallback;
    }

    private seedDraftText(value: any): string {
        const parsed = Number(value);
        if (!isFinite(parsed)) return '';
        return Number.isInteger(parsed) ? String(parsed) : String(parsed);
    }

    public formatUSD(value: number): string {
        if (value == null || isNaN(value)) return '0.00';
        return value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    public seedKrwFromUsd(value: number): number {
        const usd = Number(value) || 0;
        const fx = Number(this.exchangeRate) || 0;
        if (usd <= 0 || fx <= 0) return 0;
        return usd * fx;
    }

    public formatKRW(value: number): string {
        if (value == null || isNaN(value)) return '0';
        return Math.round(value).toLocaleString('ko-KR');
    }
}
