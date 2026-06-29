import { HostListener, Input, OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';
import { i18n } from '@wiz/libs/portal/trading/i18n';

export class Component implements OnInit {
    @Input() public mode: string = 'settings';
    public tab: string = 'api';
    public t = (key: string) => i18n.t(key);

    // API Settings
    public brokerProvider: string = 'kis';
    public brokerOptions: any[] = [];
    public brokerDropdownOpen: boolean = false;
    public appKey: string = '';
    public appSecret: string = '';
    public accountNo: string = '';
    public tossClientId: string = '';
    public tossClientSecret: string = '';
    public tossAccountSeq: string = '';
    public isMock: boolean = true;

    // Account Profile
    public accountUserId: string = '';
    public accountLoginId: string = '';
    public accountEmail: string = '';
    public currentPassword: string = '';
    public newPassword: string = '';
    public confirmPassword: string = '';
    public changingPassword: boolean = false;

    // Watchlist
    public watchlist: any[] = [];
    public newSymbol: string = '';
    public newName: string = '';
    public newInvestment: number = 5000;
    public newExchange: string = 'NASD';

    // Symbol Search
    public searchResults: any[] = [];
    public searchLoading: boolean = false;
    public showSearchResults: boolean = false;
    private searchTimer: any = null;

    // Parameters
    public divisionCount: number = 40;
    public targetProfit: number = 10;
    public autoTrade: boolean = false;

    // Commission & Tax
    public buyCommissionRate: number = 0.25;
    public sellCommissionRate: number = 0.25;
    public taxRate: number = 0;

    // Strategy
    public sellStrategy: string = 'firegate';
    public buyMethod: string = 'firegate';
    public sellMethod: string = 'firegate';
    public advancedOrderSettingsOpen: boolean = false;
    public partialSellStages: any[] = [];
    public crashBuyEnabled: boolean = false;
    public crashBuyDropPct: number = 5;
    public crashBuyMaDropPct: number = 10;
    public crashBuyRatio: number = 10;
    public crashBuyMaxPerCycle: number = 3;
    public daytradeDefaultSeedKrw: number = 5000000;
    public daytradeUsDefaultSeedKrw: number = 5000000;
    public daytradeAutoEnabled: boolean = false;
    public daytradeUsAutoEnabled: boolean = false;
    public daytradeDailyLossLimitKrw: number = 50000;
    public daytradeAutoMaxSymbols: number = 5;
    public daytradeEntryAggressiveness: string = 'balanced';
    public daytradeProbeEntryEnabled: boolean = true;
    public daytradeProbeEntryRatio: number = 0.35;
    public daytradeJackpotTakeProfitPct: number = 2.0;
    public daytradeJackpotPreSellGapPct: number = 0.5;
    public daytradeUsJackpotTakeProfitPct: number = 3.0;
    public daytradeUsJackpot2TakeProfitPct: number = 5.0;
    public locAutoScheduleEnabled: boolean = true;
    public isAdmin: boolean = false;
    public daytradeFeatureEnabled: boolean = false;
    public daytradeAuthorizedUserIds: string = '';
    public daytradeAuthorizedUserEmails: string = '';
    public daytradeUserAuthorized: boolean = false;
    public daytradeUserConfirmed: boolean = false;
    public daytradeHardLocked: boolean = true;
    public daytradeLockMessage: string = '단타 기능은 현재 운영 안정화를 위해 완전히 봉인되어 있습니다.';
    public daytradeConfirmationPhrase: string = '확인했습니다';
    public daytradeConfirmationInput: string = '';
    public adminPreviewUserMode: boolean = false;

    // UI
    public loading: boolean = false;
    public testResult: string = '';
    public testOk: boolean = false;
    public apiDiagnostics: string[] = [];
    public showSecret: boolean = false;
    public loadError: string = '';

    constructor(public service: Service) { }

    private defaultPartialSellStages(): any[] {
        return [
            { min_round: 11, max_round: 20, profit_threshold: 5, sell_ratio: 20 },
            { min_round: 21, max_round: 30, profit_threshold: 4, sell_ratio: 30 },
            { min_round: 31, max_round: null, profit_threshold: 3, sell_ratio: 40 },
        ];
    }

    private normalizePartialSellStages(stages: any[] = []): any[] {
        const source = Array.isArray(stages) && stages.length > 0 ? stages : this.defaultPartialSellStages();
        return source.map((stage: any) => ({
            roundLabel: stage.max_round == null ? `R${stage.min_round}+` : `R${stage.min_round}-${stage.max_round}`,
            triggerLabel: `+${stage.profit_threshold}%`,
            sellLabel: `${stage.sell_ratio}%`,
        }));
    }

    public async ngOnInit() {
        await this.service.init(this);
        await this.service.auth.allow("/access");
        this.refreshAdminPreviewMode();
        this.tab = this.isInfiniteBuyMode() ? 'watchlist' : 'api';
        await this.loadSettings();
    }

    public isInfiniteBuyMode(): boolean {
        return this.mode === 'infinitebuy';
    }

    public async switchTab(t: string) {
        this.tab = t;
        await this.service.render();
    }

    public showDaytradeSettingsTab(): boolean {
        if (this.daytradeHardLocked) return false;
        return this.effectiveAdminMode() || (this.daytradeFeatureEnabled && this.daytradeUserAuthorized);
    }

    public effectiveAdminMode(): boolean {
        return this.isAdmin && !this.adminPreviewUserMode;
    }

    private refreshAdminPreviewMode() {
        try {
            this.adminPreviewUserMode = window.localStorage.getItem('admin_preview_user_mode') === 'true';
        } catch (e) {
            this.adminPreviewUserMode = false;
        }
    }

    private fallbackTab(): string {
        return this.isInfiniteBuyMode() ? 'watchlist' : 'api';
    }

    private ensureVisibleTab() {
        if (this.tab === 'params') {
            this.tab = this.fallbackTab();
        }
        if (this.tab === 'risk' && !this.showDaytradeSettingsTab()) {
            this.tab = this.fallbackTab();
        }
    }

    private canUseDaytrade(): boolean {
        if (this.daytradeHardLocked) return false;
        return this.daytradeFeatureEnabled && this.daytradeUserAuthorized && this.daytradeUserConfirmed;
    }

    public tabClass(t: string): string {
        if (this.tab === t) {
            return "flex items-center gap-1.5 px-4 py-2 rounded-lg text-[13px] font-medium text-white bg-white/10 border border-white/10";
        }
        return "flex items-center gap-1.5 px-4 py-2 rounded-lg text-[13px] font-medium text-slate-400 hover:text-white hover:bg-white/5 transition-colors cursor-pointer";
    }

    // ─── Load Settings ───
    public async loadSettings() {
        this.loading = true;
        this.loadError = '';
        await this.service.render();

        try {
            const { code, data } = await wiz.call("load_settings");
            if (code !== 200) {
                this.loadError = data?.message || '설정 정보를 불러오지 못했습니다.';
            } else {
                this.brokerProvider = data.broker_provider || 'kis';
                this.brokerOptions = data.broker_options || this.defaultBrokerOptions();
                this.appKey = data.app_key || '';
                this.appSecret = data.app_secret || '';
                this.accountNo = data.account_no || '';
                this.tossClientId = data.toss_client_id || '';
                this.tossClientSecret = data.toss_client_secret || '';
                this.tossAccountSeq = data.toss_account_seq || '';
                this.isMock = data.is_mock !== false;
                this.accountUserId = data.account_user_id || '';
                this.accountLoginId = data.account_login_id || '';
                this.accountEmail = data.account_email || '';
                this.watchlist = data.watchlist || [];
                this.divisionCount = data.division_count ?? 40;
                this.targetProfit = data.target_profit ?? 10;
                this.autoTrade = data.auto_trade === true;
                this.buyCommissionRate = data.buy_commission_rate ?? 0.25;
                this.sellCommissionRate = data.sell_commission_rate ?? 0.25;
                this.taxRate = data.tax_rate ?? 0;

                this.sellStrategy = data.sell_strategy || 'firegate';
                this.buyMethod = this.normalizeOrderMethod(data.buy_method, true);
                this.sellMethod = this.normalizeOrderMethod(data.sell_method, false);
                this.partialSellStages = this.normalizePartialSellStages(data.partial_sell_stages);
                this.crashBuyEnabled = data.crash_buy_enabled === true;
                this.crashBuyDropPct = data.crash_buy_drop_pct ?? 5;
                this.crashBuyMaDropPct = data.crash_buy_ma_drop_pct ?? 10;
                this.crashBuyRatio = data.crash_buy_ratio ?? 10;
                this.crashBuyMaxPerCycle = data.crash_buy_max_per_cycle ?? 3;
                this.daytradeDefaultSeedKrw = Number(data.daytrade_default_seed ?? 5000000);
                this.daytradeUsDefaultSeedKrw = Number(data.daytrade_us_default_seed ?? this.daytradeDefaultSeedKrw ?? 5000000);
                this.daytradeAutoEnabled = data.daytrade_auto_enabled !== false;
                this.daytradeUsAutoEnabled = data.daytrade_us_auto_enabled === true;
                this.daytradeDailyLossLimitKrw = data.daytrade_daily_loss_limit_krw ?? 50000;
                this.daytradeAutoMaxSymbols = data.daytrade_auto_max_symbols ?? 16;
                this.daytradeEntryAggressiveness = data.daytrade_entry_aggressiveness || 'balanced';
                this.daytradeProbeEntryEnabled = data.daytrade_probe_entry_enabled !== false;
                this.daytradeProbeEntryRatio = data.daytrade_probe_entry_ratio ?? 0.35;
                this.daytradeJackpotTakeProfitPct = Number(data.daytrade_jackpot_take_profit_pct ?? 2.0);
                this.daytradeJackpotPreSellGapPct = Number(data.daytrade_jackpot_pre_sell_gap_pct ?? 0.5);
                this.daytradeUsJackpotTakeProfitPct = Number(data.daytrade_us_jackpot_take_profit_pct ?? 3.0);
                this.daytradeUsJackpot2TakeProfitPct = Number(data.daytrade_us_jackpot2_take_profit_pct ?? 5.0);
                this.locAutoScheduleEnabled = data.loc_auto_schedule_enabled !== false;
                this.isAdmin = data.is_admin === true;
                this.daytradeFeatureEnabled = data.daytrade_feature_enabled === true;
                this.daytradeHardLocked = data.daytrade_hard_locked !== false;
                this.daytradeLockMessage = data.daytrade_lock_message || this.daytradeLockMessage;
                this.daytradeAuthorizedUserIds = data.daytrade_authorized_user_ids || '';
                this.daytradeAuthorizedUserEmails = data.daytrade_authorized_user_emails || '';
                this.daytradeUserAuthorized = data.daytrade_user_authorized === true;
                this.daytradeUserConfirmed = data.daytrade_user_confirmed === true;
                this.daytradeConfirmationPhrase = data.daytrade_confirmation_phrase || '확인했습니다';
                if (this.daytradeHardLocked || !this.daytradeFeatureEnabled || !this.daytradeUserAuthorized || !this.daytradeUserConfirmed) {
                    this.daytradeAutoEnabled = false;
                    this.daytradeUsAutoEnabled = false;
                }
                this.ensureVisibleTab();
            }
        } catch (e: any) {
            this.loadError = e?.responseJSON?.message || e?.statusText || '설정 요청 중 오류가 발생했습니다.';
        }

        this.loading = false;
        await this.service.render();
    }

    private defaultBrokerOptions(): any[] {
        return [
            { id: 'kis', name: '한국투자증권', logo: 'KIS', status: '지원', enabled: true, summary: '현재 운영 중인 기본 브로커입니다.' },
            { id: 'toss', name: '토스증권', logo: 'TOSS', status: '지원', enabled: true, summary: '토스증권 API로 무한매수 주문을 처리합니다.' },
        ];
    }

    public selectedBrokerOption(): any {
        const options = this.brokerOptions?.length ? this.brokerOptions : this.defaultBrokerOptions();
        return options.find((item: any) => item.id === this.brokerProvider) || options[0];
    }

    public brokerLogoClass(item: any): string {
        const id = String(item?.id || '').toLowerCase();
        const base = 'broker-logo';
        if (id === 'kis') return `${base} broker-logo-kis`;
        if (id === 'toss') return `${base} broker-logo-toss`;
        return base;
    }

    public brokerOptionClass(item: any): string {
        const active = item?.id === this.brokerProvider;
        const disabled = item?.enabled !== true;
        let cls = 'broker-option';
        if (disabled) cls += ' is-disabled';
        if (active) cls += ' is-active';
        return cls;
    }

    public async toggleBrokerDropdown() {
        this.brokerDropdownOpen = !this.brokerDropdownOpen;
        await this.service.render();
    }

    public async selectBrokerOption(item: any) {
        if (!item || item.enabled !== true) {
            await this.service.modal.show({
                title: '지원 준비중',
                message: item?.summary || '아직 무한매수 실주문 지원이 검증되지 않은 증권사입니다.',
                action: '확인',
            });
            this.brokerDropdownOpen = false;
            await this.service.render();
            return;
        }
        this.brokerProvider = item.id;
        this.brokerDropdownOpen = false;
        await this.service.render();
    }

    @HostListener('document:click')
    public async onDocumentClick() {
        if (!this.brokerDropdownOpen) return;
        this.brokerDropdownOpen = false;
        await this.service.render();
    }

    private apiSettingsPayload() {
        return {
            broker_provider: this.brokerProvider,
            app_key: this.appKey,
            app_secret: this.appSecret,
            account_no: this.accountNo,
            toss_client_id: this.tossClientId,
            toss_client_secret: this.tossClientSecret,
            toss_account_seq: this.tossAccountSeq,
            is_mock: this.isMock,
        };
    }

    private apiSettingsValidationError(): string {
        if (this.brokerProvider !== 'toss') return '';
        const clientId = String(this.tossClientId || '').trim();
        const clientSecret = String(this.tossClientSecret || '').trim();
        const accountSeq = String(this.tossAccountSeq || '').trim();
        if (!clientId) return '토스증권 클라이언트 ID를 입력해주세요.';
        if (!clientSecret) return '토스증권 클라이언트 비밀키를 입력해주세요.';
        if (clientId.startsWith('tssk_') || clientSecret.startsWith('tsck_')) {
            return '토스증권 키 입력 위치가 반대로 보입니다. api key(tsck_...)는 첫 번째 칸, secret key(tssk_...)는 두 번째 칸에 입력해주세요.';
        }
        if (!clientId.startsWith('tsck_')) {
            return '토스증권 API key 칸에는 api key(tsck_...) 값을 입력해야 합니다.';
        }
        if (!clientSecret.startsWith('tssk_')) {
            return '토스증권 Secret key 칸에는 secret key(tssk_...) 값을 입력해야 합니다.';
        }
        if (accountSeq && !/^\d+$/.test(accountSeq)) {
            return '토스증권 accountSeq는 숫자만 입력할 수 있습니다. 일반 계좌번호는 입력하지 말고 비워두세요.';
        }
        if (accountSeq && /^0\d{1,5}$/.test(accountSeq)) {
            return '토스증권 accountSeq는 계좌 뒷번호가 아닙니다. 이 칸은 비워둔 뒤 연결 테스트를 누르세요.';
        }
        return '';
    }

    private async showApiValidationError(message: string) {
        this.loading = false;
        this.testOk = false;
        this.testResult = message;
        this.apiDiagnostics = [];
        await this.service.modal.show({
            title: '입력 확인',
            message,
            action: '확인',
        });
        await this.service.render();
    }

    private applyApiSettingsResponse(data: any) {
        if (!data) return;
        const provider = data?.broker_provider || this.brokerProvider;
        this.brokerProvider = provider;
        if (provider === 'kis') {
            this.accountNo = data?.account_no || this.accountNo;
        }
        this.tossAccountSeq = data?.toss_account_seq || this.tossAccountSeq;
        this.apiDiagnostics = Array.isArray(data?.diagnostics) ? data.diagnostics : [];
        if (typeof data?.is_mock === 'boolean') {
            this.isMock = data.is_mock;
        }
    }

    // ─── Save API Settings ───
    public async saveApiSettings() {
        this.loading = true;
        this.testResult = '';
        this.apiDiagnostics = [];
        await this.service.render();

        const validationError = this.apiSettingsValidationError();
        if (validationError) {
            await this.showApiValidationError(validationError);
            return;
        }

        try {
            const { code, data } = await wiz.call("save_api_settings", this.apiSettingsPayload());

            this.loading = false;
            if (code === 200) {
                this.applyApiSettingsResponse(data);
                this.testOk = data?.success === true;
                this.testResult = data?.message || (this.testOk ? this.t('set.conn_ok') : this.t('set.conn_fail'));

                await this.service.modal.show({
                    title: this.testOk ? '완료' : '오류',
                    message: this.testResult,
                    action: '확인',
                });
            } else {
                this.testOk = false;
                this.testResult = data?.message || '설정 저장에 실패했습니다.';
                await this.service.modal.show({
                    title: '오류',
                    message: this.testResult,
                    action: '확인',
                });
            }
        } catch (e: any) {
            this.loading = false;
            this.testOk = false;
            this.testResult = e?.responseJSON?.message || e?.statusText || '설정 저장 중 오류가 발생했습니다.';
            await this.service.modal.show({
                title: '오류',
                message: this.testResult,
                action: '확인',
            });
        }

        await this.service.render();
    }

    public async saveAccountProfile() {
        this.loading = true;
        await this.service.render();

        const { code, data } = await wiz.call("save_account_profile", {
            login_id: this.accountLoginId,
            email: this.accountEmail,
        });

        this.loading = false;
        if (code === 200) {
            this.accountUserId = data.user_id || this.accountUserId;
            this.accountLoginId = data.login_id || this.accountLoginId;
            this.accountEmail = data.email || this.accountEmail;
            await this.service.modal.show({
                title: '완료',
                message: '계정 정보가 저장되었습니다.',
                action: '확인',
            });
        } else {
            await this.service.modal.show({
                title: '오류',
                message: data?.message || '계정 정보 저장에 실패했습니다.',
                action: '확인',
            });
        }
        await this.service.render();
    }

    public async changeAccountPassword() {
        if (!this.currentPassword) {
            await this.service.modal.show({ title: '오류', message: '현재 비밀번호를 입력해주세요.', action: '확인' });
            return;
        }
        if (!this.newPassword) {
            await this.service.modal.show({ title: '오류', message: '새 비밀번호를 입력해주세요.', action: '확인' });
            return;
        }
        if (this.newPassword.length < 8) {
            await this.service.modal.show({ title: '오류', message: '새 비밀번호는 8자 이상이어야 합니다.', action: '확인' });
            return;
        }
        if (this.newPassword !== this.confirmPassword) {
            await this.service.modal.show({ title: '오류', message: '새 비밀번호가 일치하지 않습니다.', action: '확인' });
            return;
        }

        this.changingPassword = true;
        await this.service.render();

        const { code, data } = await wiz.call("change_account_password", {
            current_password: this.currentPassword,
            new_password: this.newPassword,
        });

        this.changingPassword = false;
        if (code === 200) {
            this.currentPassword = '';
            this.newPassword = '';
            this.confirmPassword = '';
            await this.service.modal.show({
                title: '완료',
                message: '비밀번호가 변경되었습니다.',
                action: '확인',
            });
        } else {
            await this.service.modal.show({
                title: '오류',
                message: data?.message || '비밀번호 변경에 실패했습니다.',
                action: '확인',
            });
        }
        await this.service.render();
    }

    // ─── Test Connection ───
    public async testApiConnection() {
        this.testResult = '';
        this.apiDiagnostics = [];
        this.loading = true;
        await this.service.render();

        const validationError = this.apiSettingsValidationError();
        if (validationError) {
            await this.showApiValidationError(validationError);
            return;
        }

        try {
            const { code, data } = await wiz.call("test_connection", this.apiSettingsPayload());
            this.applyApiSettingsResponse(data);
            this.testOk = code === 200 && data?.success === true;
            this.testResult = this.testOk
                ? (data?.message || this.t('set.conn_ok'))
                : `${this.t('set.conn_fail')}${data?.message ? ` ${data.message}` : ''}`;
        } catch (e: any) {
            this.testOk = false;
            this.testResult = e?.responseJSON?.message || e?.statusText || 'API 연결 테스트 중 오류가 발생했습니다.';
        }

        this.loading = false;
        await this.service.render();
    }

    // ─── Watchlist ───
    public async addSymbol() {
        if (!this.newSymbol.trim()) return;
        this.loading = true;
        this.showSearchResults = false;
        await this.service.render();

        const { code, data } = await wiz.call("add_watchlist", {
            symbol: this.newSymbol.toUpperCase().trim(),
            name: this.newName.trim(),
            investment: this.newInvestment,
            exchange: this.newExchange,
        });

        if (code === 200) {
            this.watchlist = data.watchlist || this.watchlist;
            this.newSymbol = '';
            this.newName = '';
            this.newInvestment = 5000;
            this.newExchange = 'NASD';
            this.searchResults = [];
        }

        this.loading = false;
        await this.service.render();
    }

    // ─── Symbol Search ───
    public async onSymbolInput() {
        const symbol = this.newSymbol.trim().toUpperCase();
        if (symbol.length < 1) {
            this.searchResults = [];
            this.showSearchResults = false;
            await this.service.render();
            return;
        }

        // Debounce 400ms
        if (this.searchTimer) clearTimeout(this.searchTimer);
        this.searchTimer = setTimeout(async () => {
            await this.searchSymbol(symbol);
        }, 400);
    }

    private async searchSymbol(symbol: string) {
        this.searchLoading = true;
        this.showSearchResults = true;
        await this.service.render();

        try {
            const { code, data } = await wiz.call("search_symbol", { symbol });
            if (code === 200) {
                this.searchResults = data.results || [];
            }
        } catch (e) {
            console.error("Symbol search error:", e);
        }

        this.searchLoading = false;
        await this.service.render();
    }

    public async selectSearchResult(result: any) {
        this.newSymbol = result.symbol;
        this.newName = result.name || '';
        this.newExchange = result.exchange || 'NASD';
        this.showSearchResults = false;
        this.searchResults = [];
        await this.service.render();
    }

    public closeSearchResults() {
        // Delay to allow click on result
        setTimeout(() => {
            this.showSearchResults = false;
            this.service.render();
        }, 200);
    }

    public async removeSymbol(id: string) {
        this.loading = true;
        await this.service.render();

        const { code, data } = await wiz.call("remove_watchlist", { id });
        if (code === 200) {
            this.watchlist = data.watchlist || this.watchlist;
        }

        this.loading = false;
        await this.service.render();
    }

    public async updateWatchlistItem(item: any) {
        const { code, data } = await wiz.call("update_watchlist_item", {
            symbol: item.symbol,
            investment: item.total_investment,
            division_count: item.division_count,
            target_profit: item.target_profit,
            cycle_mode: item.cycle_mode,
            is_active: item.is_active,
        });
        if (code === 200) {
            this.watchlist = data.watchlist || this.watchlist;
        }
        await this.service.render();
    }

    public async toggleSymbol(item: any) {
        item.is_active = !item.is_active;
        await this.updateWatchlistItem(item);
    }

    private async confirmDaytradeAutoEnable(target: string): Promise<boolean> {
        const confirmed = await this.service.modal.show({
            title: '단타 자동매매 시작 확인',
            message: `${target} 자동매매를 켜면 백그라운드 워커가 후보 탐색, 진입, 자동청산 감시를 즉시 시작합니다. 수동 운용 중이면 보유 종목, 예약 주문, 시드 상태를 먼저 확인하세요.`,
            action: '그래도 켜기',
            cancel: '취소',
            status: 'warning',
            actionBtn: 'warning',
        });
        return confirmed === true;
    }

    public async toggleDaytradeAutoEnabled() {
        if (this.daytradeHardLocked) {
            await this.service.modal.show({
                title: '단타 기능 봉인',
                message: this.daytradeLockMessage,
                action: '확인',
                status: 'warning',
            });
            this.daytradeAutoEnabled = false;
            return;
        }
        if (!this.canUseDaytrade()) {
            await this.service.modal.show({
                title: '단타 기능 비활성',
                message: '관리자 전역 활성화, 사용자 인증, 위험 확인 문구 입력이 모두 완료되어야 단타 자동매매를 켤 수 있습니다.',
                action: '확인',
                status: 'warning',
            });
            return;
        }
        if (this.daytradeAutoEnabled !== true) {
            const confirmed = await this.confirmDaytradeAutoEnable('국장 단타');
            if (!confirmed) {
                return;
            }
        }
        this.daytradeAutoEnabled = !this.daytradeAutoEnabled;
        await this.service.render();
    }

    public async toggleDaytradeUsAutoEnabled() {
        if (this.daytradeHardLocked) {
            await this.service.modal.show({
                title: '단타 기능 봉인',
                message: this.daytradeLockMessage,
                action: '확인',
                status: 'warning',
            });
            this.daytradeUsAutoEnabled = false;
            return;
        }
        if (!this.canUseDaytrade()) {
            await this.service.modal.show({
                title: '단타 기능 비활성',
                message: '관리자 전역 활성화, 사용자 인증, 위험 확인 문구 입력이 모두 완료되어야 단타 자동매매를 켤 수 있습니다.',
                action: '확인',
                status: 'warning',
            });
            return;
        }
        if (this.daytradeUsAutoEnabled !== true) {
            const confirmed = await this.confirmDaytradeAutoEnable('미장 단타');
            if (!confirmed) {
                return;
            }
        }
        this.daytradeUsAutoEnabled = !this.daytradeUsAutoEnabled;
        await this.service.render();
    }

    // ─── Parameters ───
    public async saveParams() {
        if (this.daytradeHardLocked || !this.canUseDaytrade()) {
            this.daytradeAutoEnabled = false;
            this.daytradeUsAutoEnabled = false;
        }
        this.buyMethod = this.normalizeOrderMethod(this.buyMethod, true);
        this.sellMethod = this.normalizeOrderMethod(this.sellMethod, false);
        this.daytradeDefaultSeedKrw = Math.max(100000, Math.round(Number(this.daytradeDefaultSeedKrw) || 5000000));
        this.daytradeUsDefaultSeedKrw = Math.max(100000, Math.round(Number(this.daytradeUsDefaultSeedKrw) || this.daytradeDefaultSeedKrw || 5000000));
        this.daytradeDailyLossLimitKrw = Math.max(0, Math.round(Number(this.daytradeDailyLossLimitKrw) || 0));
        this.daytradeAutoMaxSymbols = Math.max(1, Math.min(40, Math.round(Number(this.daytradeAutoMaxSymbols) || 5)));
        this.daytradeProbeEntryRatio = Math.max(0.05, Math.min(0.8, Number(this.daytradeProbeEntryRatio) || 0.35));
        this.daytradeJackpotTakeProfitPct = Math.max(0.1, Math.min(20, Number(this.daytradeJackpotTakeProfitPct) || 2.0));
        this.daytradeJackpotPreSellGapPct = Math.max(0, Math.min(5, Number(this.daytradeJackpotPreSellGapPct) || 0.5));
        this.daytradeUsJackpotTakeProfitPct = Math.max(0.1, Math.min(50, Number(this.daytradeUsJackpotTakeProfitPct) || 3.0));
        this.daytradeUsJackpot2TakeProfitPct = Math.max(this.daytradeUsJackpotTakeProfitPct, Math.min(100, Number(this.daytradeUsJackpot2TakeProfitPct) || 5.0));
        this.loading = true;
        await this.service.render();

        const { code } = await wiz.call("save_params", {
            division_count: this.divisionCount,
            target_profit: this.targetProfit,
            auto_trade: this.autoTrade,
            buy_commission_rate: this.buyCommissionRate,
            sell_commission_rate: this.sellCommissionRate,
            tax_rate: this.taxRate,
            sell_strategy: this.sellStrategy,
            buy_method: this.buyMethod,
            sell_method: this.sellMethod,
            crash_buy_enabled: this.crashBuyEnabled,
            crash_buy_drop_pct: this.crashBuyDropPct,
            crash_buy_ma_drop_pct: this.crashBuyMaDropPct,
            crash_buy_ratio: this.crashBuyRatio,
            crash_buy_max_per_cycle: this.crashBuyMaxPerCycle,
            daytrade_default_seed: this.daytradeDefaultSeedKrw,
            daytrade_us_default_seed: this.daytradeUsDefaultSeedKrw,
            daytrade_auto_enabled: this.daytradeAutoEnabled,
            daytrade_us_auto_enabled: this.daytradeUsAutoEnabled,
            daytrade_daily_loss_limit_krw: this.daytradeDailyLossLimitKrw,
            daytrade_auto_max_symbols: this.daytradeAutoMaxSymbols,
            daytrade_entry_aggressiveness: this.daytradeEntryAggressiveness,
            daytrade_probe_entry_enabled: this.daytradeProbeEntryEnabled,
            daytrade_probe_entry_ratio: this.daytradeProbeEntryRatio,
            daytrade_jackpot_take_profit_pct: this.daytradeJackpotTakeProfitPct,
            daytrade_jackpot_pre_sell_gap_pct: this.daytradeJackpotPreSellGapPct,
            daytrade_us_jackpot_take_profit_pct: this.daytradeUsJackpotTakeProfitPct,
            daytrade_us_jackpot2_take_profit_pct: this.daytradeUsJackpot2TakeProfitPct,
            loc_auto_schedule_enabled: this.locAutoScheduleEnabled,
        });

        this.loading = false;
        if (code === 200) {
            await this.service.modal.show({
                title: '완료',
                message: this.t('set.save_params'),
                action: '확인',
            });
        }
        await this.service.render();
    }

    public async saveDaytradeAdminSettings() {
        if (this.daytradeHardLocked) {
            this.daytradeFeatureEnabled = false;
        }
        if (!this.effectiveAdminMode()) {
            await this.service.modal.show({
                title: '오류',
                message: '관리자만 단타 기능 노출과 인증 대상을 변경할 수 있습니다.',
                action: '확인',
            });
            return;
        }

        this.loading = true;
        await this.service.render();

        try {
            const { code, data } = await wiz.call("save_daytrade_admin_settings", {
                daytrade_feature_enabled: this.daytradeFeatureEnabled,
                daytrade_authorized_user_ids: this.daytradeAuthorizedUserIds,
                daytrade_authorized_user_emails: this.daytradeAuthorizedUserEmails,
            });
            this.loading = false;
            if (code === 200) {
                this.daytradeFeatureEnabled = data?.daytrade_feature_enabled === true;
                this.daytradeHardLocked = data?.daytrade_hard_locked !== false;
                this.daytradeLockMessage = data?.message || this.daytradeLockMessage;
                this.daytradeAuthorizedUserIds = data?.daytrade_authorized_user_ids || this.daytradeAuthorizedUserIds;
                this.daytradeAuthorizedUserEmails = data?.daytrade_authorized_user_emails || this.daytradeAuthorizedUserEmails;
                if (!this.daytradeFeatureEnabled) {
                    this.daytradeAutoEnabled = false;
                    this.daytradeUsAutoEnabled = false;
                }
                window.dispatchEvent(new CustomEvent('daytrade-access-changed'));
                await this.service.modal.show({
                    title: '완료',
                    message: data?.message || '단타 관리자 설정이 저장되었습니다.',
                    action: '확인',
                });
                await this.loadSettings();
                return;
            }
            await this.service.modal.show({
                title: '오류',
                message: data?.message || '단타 관리자 설정 저장에 실패했습니다.',
                action: '확인',
            });
        } catch (e: any) {
            this.loading = false;
            await this.service.modal.show({
                title: '오류',
                message: e?.responseJSON?.message || e?.statusText || '단타 관리자 설정 저장 중 오류가 발생했습니다.',
                action: '확인',
            });
        }

        await this.service.render();
    }

    public async confirmDaytradeWarning() {
        if (this.daytradeHardLocked) {
            await this.service.modal.show({
                title: '단타 기능 봉인',
                message: this.daytradeLockMessage,
                action: '확인',
                status: 'warning',
            });
            return;
        }
        const phrase = String(this.daytradeConfirmationInput || '').trim();
        if (phrase !== this.daytradeConfirmationPhrase) {
            await this.service.modal.show({
                title: '확인 문구 불일치',
                message: `'${this.daytradeConfirmationPhrase}' 문구를 정확히 입력해주세요.`,
                action: '확인',
                status: 'warning',
            });
            return;
        }

        this.loading = true;
        await this.service.render();

        try {
            const { code, data } = await wiz.call("confirm_daytrade_warning", { phrase });
            this.loading = false;
            if (code === 200) {
                this.daytradeUserConfirmed = true;
                this.daytradeConfirmationInput = '';
                window.dispatchEvent(new CustomEvent('daytrade-access-changed'));
                await this.service.modal.show({
                    title: '확인 완료',
                    message: data?.message || '단타 위험 확인 문구가 저장되었습니다.',
                    action: '확인',
                });
                await this.loadSettings();
                return;
            }
            await this.service.modal.show({
                title: '오류',
                message: data?.message || '단타 위험 확인 저장에 실패했습니다.',
                action: '확인',
            });
        } catch (e: any) {
            this.loading = false;
            await this.service.modal.show({
                title: '오류',
                message: e?.responseJSON?.message || e?.statusText || '단타 위험 확인 저장 중 오류가 발생했습니다.',
                action: '확인',
            });
        }

        await this.service.render();
    }

    public jackpotPreSellProfitPct(): number {
        const target = Math.max(0, Number(this.daytradeJackpotTakeProfitPct) || 0);
        const gap = Math.max(0, Number(this.daytradeJackpotPreSellGapPct) || 0);
        return Math.max(0, ((1 + target / 100) * (1 - gap / 100) - 1) * 100);
    }

    public async setDailyLossPreset(amount: number) {
        this.daytradeDailyLossLimitKrw = amount;
        await this.service.render();
    }

    public async setSeedPreset(market: string, amount: number) {
        if ((market || '').toUpperCase() === 'US') {
            this.daytradeUsDefaultSeedKrw = amount;
        } else {
            this.daytradeDefaultSeedKrw = amount;
        }
        await this.service.render();
    }

    public async setStrategy(strategy: string) {
        if (!['firegate', 'full', 'partial'].includes(strategy)) {
            strategy = 'firegate';
        }
        this.sellStrategy = strategy;
        await this.service.render();
    }

    public normalizeOrderMethod(method: string, allowMarket: boolean = false): string {
        const normalized = String(method || '').toLowerCase();
        if (normalized === 'loc') return 'loc';
        if (allowMarket && normalized === 'market') return 'market';
        return 'firegate';
    }

    public async setBuyMethod(method: string) {
        this.buyMethod = this.normalizeOrderMethod(method, true);
        await this.service.render();
    }

    public async setSellMethod(method: string) {
        this.sellMethod = this.normalizeOrderMethod(method, false);
        await this.service.render();
    }

    public applyPreset(preset: string) {
        if (preset === 'us') {
            this.buyCommissionRate = 0.25;
            this.sellCommissionRate = 0.25;
            this.taxRate = 0;
        } else if (preset === 'kr') {
            this.buyCommissionRate = 0.015;
            this.sellCommissionRate = 0.015;
            this.taxRate = 0.18;
        } else if (preset === 'none') {
            this.buyCommissionRate = 0;
            this.sellCommissionRate = 0;
            this.taxRate = 0;
        }
        this.service.render();
    }

    @HostListener('window:admin-preview-changed')
    public async onAdminPreviewChanged() {
        this.refreshAdminPreviewMode();
        this.ensureVisibleTab();
        await this.service.render();
    }
}
