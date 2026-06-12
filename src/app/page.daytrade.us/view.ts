import { OnDestroy, OnInit, Input } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';

declare const wiz: any;

export class Component implements OnInit, OnDestroy {
    @Input() title: any;

    public loading: boolean = true;
    public refreshing: boolean = false;
    public rankingLoading: boolean = false;
    public verifyLoading: boolean = false;
    public backgroundLoading: boolean = false;
    public seedSaving: boolean = false;
    public readonly rankingSymbolTarget: number = 12;

    public symbol: string = 'TQQQ';
    public strategy: string = 'us_premarket';
    public seed: number = 5000000;
    public seedDraft: string = '5000000';
    private seedDraftDirty: boolean = false;

    public candidates: any[] = [];
    public strategyOptions: any[] = [];
    public universePolicy: any = null;
    public status: any = null;
    public daily: any = null;
    public verify: any = null;
    public autoStatus: any = null;
    public ranking: any[] = [];
    public rankingMeta: any = null;
    public budgetStatus: any = null;
    public researchSummary: any = null;
    public symbolQuery: string = '';
    public symbolResults: any[] = [];
    public searchLoading: boolean = false;
    public briefingCollapsed: boolean = true;
    public advancedControlsCollapsed: boolean = true;

    public errorMessage: string = '';
    private backgroundRefreshTimer: any = null;

    constructor(public service: Service) { }

    private async confirmAutoEnable(): Promise<boolean> {
        const confirmed = await this.service.modal.show({
            title: '미장 단타 자동매매 시작',
            message: '미장 단타 자동매매를 켜면 백그라운드 워커가 후보 탐색, 진입, 자동청산 감시를 즉시 시작합니다. 수동 운용 중이면 보유 종목, 예약 주문, 시드 상태를 먼저 확인하세요.',
            action: '그래도 켜기',
            cancel: '취소',
            status: 'warning',
            actionBtn: 'warning',
        });
        return confirmed === true;
    }

    public toggleBriefingCollapsed() {
        this.briefingCollapsed = !this.briefingCollapsed;
    }

    public toggleAdvancedControls() {
        this.advancedControlsCollapsed = !this.advancedControlsCollapsed;
    }

    public async ngOnInit() {
        await this.service.init(this);
        await this.bootstrap();
        this.loading = false;
        await this.service.render();
    }

    public ngOnDestroy() {
        if (this.backgroundRefreshTimer) {
            clearTimeout(this.backgroundRefreshTimer);
            this.backgroundRefreshTimer = null;
        }
    }

    public async bootstrap() {
        this.refreshing = true;
        this.errorMessage = '';
        await this.service.render();
        try {
            const seedValue = this.currentSeedValue();
            const { code, data } = await wiz.call('us_bootstrap', {
                symbol: this.symbol,
                strategy: this.strategy,
                seed: seedValue,
            });
            if (code === 200) {
                const defaults = data.defaults || {};
                this.symbol = defaults.symbol || this.symbol;
                this.strategy = defaults.strategy || this.strategy;
                this.applySeedFromServer(defaults.seed || this.seed);
                this.candidates = data.us_candidates || [];
                this.universePolicy = data.universe_policy || null;
                this.strategyOptions = data.us_strategy_options || [];
                this.budgetStatus = data.budget_status || null;
                const snapshot = data.snapshot || {};
                this.status = snapshot.status || null;
                this.daily = snapshot.daily || null;
                this.autoStatus = snapshot.auto_status || null;
                this.verify = snapshot.verify || null;
                this.budgetStatus = snapshot.budget_status || this.budgetStatus;
                this.queueBackgroundRefresh(false);
            } else {
                this.errorMessage = data?.message || '미장 초기화 실패';
            }
        } catch (e: any) {
            this.errorMessage = e?.message || '미장 초기화 오류';
        }
        this.refreshing = false;
        await this.service.render();
    }

    private queueBackgroundRefresh(includePrimary: boolean = true) {
        if (this.backgroundRefreshTimer) {
            clearTimeout(this.backgroundRefreshTimer);
        }
        this.backgroundRefreshTimer = setTimeout(async () => {
            this.backgroundLoading = true;
            await this.service.render();
            if (includePrimary) {
                await this.loadSnapshot();
            }
            if ((this.ranking || []).length === 0) {
                await this.loadRanking(false);
            }
            this.backgroundLoading = false;
            await this.service.render();
        }, 120);
    }

    public async loadPrimaryData() {
        await this.loadSnapshot();
        await this.service.render();
    }

    public async loadSnapshot(forceRefresh: boolean = false) {
        try {
            const { code, data } = await wiz.call('us_snapshot', {
                symbol: this.symbol,
                strategy: this.strategy,
                seed: this.currentSeedValue(),
                force_refresh: forceRefresh ? 'true' : 'false',
            });
            if (code === 200) {
                this.status = data.status || null;
                this.daily = data.daily || null;
                this.autoStatus = data.auto_status || null;
                this.verify = data.verify || null;
                this.budgetStatus = data.budget_status || this.budgetStatus;
            }
        } catch (e) {
        }
    }

    public async loadStatus() {
        try {
            const { code, data } = await wiz.call('us_live_status', {
                symbol: this.symbol,
                strategy: this.strategy,
                seed: this.currentSeedValue(),
            });
            if (code === 200) this.status = data.status || null;
        } catch (e) {
        }
    }

    public async loadDaily() {
        try {
            const { code, data } = await wiz.call('us_daily_log', {});
            if (code === 200) this.daily = data.summary || null;
        } catch (e) {
        }
    }

    public async loadAutoStatus() {
        try {
            const { code, data } = await wiz.call('us_get_auto_status', {});
            if (code === 200) this.autoStatus = data || null;
        } catch (e) {
        }
    }

    public async loadVerify() {
        this.verifyLoading = true;
        await this.service.render();
        try {
            const { code, data } = await wiz.call('us_verify_runtime', {
                symbol: this.symbol,
                strategy: this.strategy,
                seed: this.currentSeedValue(),
            });
            if (code === 200) this.verify = data;
        } catch (e) {
        }
        this.verifyLoading = false;
    }

    public async loadRanking(forceRefresh: boolean = false) {
        this.rankingLoading = true;
        await this.service.render();
        try {
            const { code, data } = await wiz.call('us_model_ranking', {
                seed: this.currentSeedValue(),
                symbol: this.symbol,
                max_symbols: this.rankingSymbolTarget,
                period: '10d',
                interval: '5m',
                force_refresh: forceRefresh ? 'true' : 'false',
            });
            if (code === 200) {
                this.ranking = data.rankings || [];
                this.rankingMeta = {
                    symbolCount: data.symbol_count || 0,
                    period: data.period || '10d',
                    interval: data.interval || '5m',
                    cached: data.cached === true,
                    cacheAgeSec: Number(data.cache_age_sec || 0),
                    generatedAt: data.generated_at || '',
                    focusSymbol: data.focus_symbol || '',
                    qualityGate: data.quality_gate || null,
                    recommendedPair: data.recommended_pair || null,
                };
                this.researchSummary = data.research_summary || null;
            }
        } catch (e) {
        }
        this.rankingLoading = false;
        await this.service.render();
    }

    public async syncSeed() {
        const seedValue = Number(this.seedDraft);
        if (!isFinite(seedValue) || seedValue <= 0) {
            this.errorMessage = '미장 시드는 0보다 큰 숫자로 입력해야 합니다.';
            await this.service.render();
            return;
        }
        this.seedSaving = true;
        this.errorMessage = '';
        await this.service.render();
        try {
            const { code, data } = await wiz.call('us_bootstrap', {
                seed: seedValue,
                persist_seed: 'true',
            });
            if (code === 200) {
                const defaults = data.defaults || {};
                this.applySeedFromServer(defaults.seed || seedValue, true);
                this.budgetStatus = data.budget_status || null;
                const snapshot = data.snapshot || {};
                this.status = snapshot.status || null;
                this.daily = snapshot.daily || null;
                this.autoStatus = snapshot.auto_status || null;
                this.verify = snapshot.verify || null;
                this.budgetStatus = snapshot.budget_status || this.budgetStatus;
            } else {
                this.errorMessage = data?.message || '미장 시드 저장 실패';
            }
        } catch (e: any) {
            this.errorMessage = e?.message || '미장 시드 저장 오류';
        }
        this.seedSaving = false;
        await this.service.render();
    }

    public onSeedDraftChange(value: any) {
        this.seedDraft = value === null || value === undefined ? '' : String(value);
        this.seedDraftDirty = true;
    }

    private currentSeedValue(): number {
        const draft = Number(this.seedDraft);
        if (isFinite(draft) && draft > 0) return draft;
        return Number(this.seed || 0) || 5000000;
    }

    private applySeedFromServer(value: any, force: boolean = false) {
        const seedValue = Number(value || 0);
        if (!isFinite(seedValue) || seedValue <= 0) return;
        this.seed = seedValue;
        if (force || this.seedDraftDirty === false) {
            this.seedDraft = String(Math.round(seedValue));
            this.seedDraftDirty = false;
        }
    }

    public async selectSymbol(symbol: string) {
        this.symbol = symbol;
        await this.loadSnapshot(true);
        await this.service.render();
    }

    public async refreshLight() {
        this.refreshing = true;
        await this.service.render();
        await this.loadSnapshot(true);
        this.queueBackgroundRefresh(false);
        this.refreshing = false;
        await this.service.render();
    }

    public async toggleAuto() {
        if (this.isUsAutoEnabled !== true) {
            const confirmed = await this.confirmAutoEnable();
            if (!confirmed) {
                return;
            }
        }
        this.refreshing = true;
        this.errorMessage = '';
        await this.service.render();
        try {
            const { code, data } = await wiz.call('us_toggle_auto', {});
            if (code !== 200) {
                this.errorMessage = data?.message || '미장 자동매매 토글 실패';
            }
            await this.loadSnapshot(true);
        } catch (e: any) {
            this.errorMessage = e?.message || '미장 자동매매 토글 오류';
        }
        this.refreshing = false;
        await this.service.render();
    }

    public async refreshRanking() {
        await this.loadRanking(true);
    }

    public async searchSymbols() {
        const query = this.symbolQuery.trim();
        if (!query) {
            this.symbolResults = [];
            await this.service.render();
            return;
        }
        this.searchLoading = true;
        await this.service.render();
        try {
            const { code, data } = await wiz.call('us_search_symbols', { query, limit: 10 });
            if (code === 200) {
                this.symbolResults = data.results || [];
            }
        } catch (e) {
        }
        this.searchLoading = false;
        await this.service.render();
    }

    public async applySearchResult(item: any) {
        this.symbol = item?.symbol || this.symbol;
        this.symbolQuery = '';
        this.symbolResults = [];
        await this.loadSnapshot(true);
        await this.service.render();
    }

    public get autoStateLabel(): string {
        return String(this.autoStatus?.state_label || 'CHECK').trim() || 'CHECK';
    }

    public get autoStateReason(): string {
        return String(this.autoStatus?.state_reason || '').trim();
    }

    public get autoStateTone(): string {
        return String(this.autoStatus?.state_tone || 'muted').trim();
    }

    public get autoStatusBadgeClass(): string {
        if (this.autoStateTone === 'success') return 'bg-emerald-500/20 text-emerald-300 border border-emerald-400/20';
        if (this.autoStateTone === 'warning') return 'bg-amber-500/20 text-amber-300 border border-amber-400/20';
        if (this.autoStateTone === 'danger') return 'bg-red-500/20 text-red-300 border border-red-400/20';
        return 'bg-white/5 text-slate-300 border border-white/10';
    }

    public get autoStatusPanelClass(): string {
        if (this.autoStateTone === 'success') return 'border-emerald-400/20 bg-emerald-500/10';
        if (this.autoStateTone === 'warning') return 'border-amber-400/20 bg-amber-500/10';
        if (this.autoStateTone === 'danger') return 'border-red-400/20 bg-red-500/10';
        return 'border-white/10 bg-white/5';
    }

    public get isUsAutoEnabled(): boolean {
        return this.autoStatus?.us_auto_enabled === true;
    }

    public get workerStarted(): boolean {
        return this.autoStatus?.worker_status?.started === true;
    }

    public get marketSessionLabel(): string {
        if (this.autoStatus?.market_open) return '본장 진행 중';
        if (this.autoStatus?.premarket_open) return '프리마켓 진행 중';
        return '장외 대기';
    }

    public get autoBuyScheduleLabel(): string {
        return String(this.autoStatus?.auto_buy_window?.label || '미국장 자동환전 매수 대기');
    }

    public get autoBuyScheduleAt(): string {
        return String(this.autoStatus?.auto_buy_window?.scheduled_at || 'US 프리마켓 ET 04:00');
    }

    public get autoBuyCurrentTime(): string {
        return String(this.autoStatus?.auto_buy_window?.current_time || '');
    }

    public get autoBuyReady(): boolean {
        return this.autoStatus?.auto_buy_window?.ready === true;
    }

    public get currentPrice(): number {
        return Number(this.status?.signal?.current_price || 0);
    }

    public get signalAction(): string {
        return String(this.status?.signal?.action || 'HOLD');
    }

    public get signalReason(): string {
        return String(this.status?.signal?.reason || '-');
    }

    public get statusRisk(): string {
        return String(this.status?.runtime?.risk_status || 'SAFE');
    }

    public get usActivePositions(): any[] {
        return Array.isArray(this.autoStatus?.active_positions) ? this.autoStatus.active_positions : [];
    }

    public get budgetUsagePct(): number {
        return Number(this.budgetStatus?.seed_usage_pct || 0);
    }

    public get sharedUsedSeed(): number {
        return Number(this.budgetStatus?.cross_market_used_seed_krw || this.budgetStatus?.used_seed_krw || 0);
    }

    public get totalPlannedSeed(): number {
        if (this.seedDraftDirty) return this.currentSeedValue();
        return Number(this.budgetStatus?.total_seed_krw || this.budgetStatus?.requested_seed || this.seed || 0);
    }

    public get seedLockedByOtherPositions(): boolean {
        return this.totalPlannedSeed > 0 && this.sharedUsedSeed >= this.totalPlannedSeed;
    }

    public get briefReasonList(): string[] {
        const items: string[] = [];
        if (this.autoStateReason) items.push(this.autoStateReason);
        const verifyMessage = this.verifyHardFails.map((item: any) => `${item.label}: ${item.message}`);
        for (const row of verifyMessage) {
            if (!items.includes(row)) items.push(row);
        }
        return items;
    }

    public signalBadgeClass(value: string): string {
        const normalized = String(value || '').toUpperCase();
        if (normalized.includes('BUY')) return 'bg-emerald-500/20 text-emerald-300 border border-emerald-400/20';
        if (normalized.includes('SELL')) return 'bg-red-500/20 text-red-300 border border-red-400/20';
        return 'bg-white/5 text-slate-300 border border-white/10';
    }

    public riskBadgeClass(value: string): string {
        const normalized = String(value || '').toUpperCase();
        if (normalized.includes('SAFE')) return 'bg-emerald-500/20 text-emerald-300 border border-emerald-400/20';
        if (normalized.includes('WARN') || normalized.includes('READY')) return 'bg-amber-500/20 text-amber-300 border border-amber-400/20';
        if (normalized.includes('STOP') || normalized.includes('HALT')) return 'bg-red-500/20 text-red-300 border border-red-400/20';
        return 'bg-white/5 text-slate-300 border border-white/10';
    }

    public formatUsd(value: any): string {
        const num = Number(value || 0);
        if (isNaN(num)) return '$0.00';
        return `$${num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }

    public get selectedStrategySpec(): any {
        return (this.strategyOptions || []).find((item: any) => item.id === this.strategy) || null;
    }

    public get topRanking(): any {
        return (this.ranking || []).length > 0 ? this.ranking[0] : null;
    }

    public get rankingQualityGate(): any {
        return this.rankingMeta?.qualityGate || null;
    }

    public get recommendedPair(): any {
        return this.rankingMeta?.recommendedPair || this.rankingQualityGate?.best_tradable?.best_symbol || null;
    }

    public get blockedStrategies(): any[] {
        return this.researchSummary?.blocked_strategies || [];
    }

    public get researchAnalysis(): any {
        return this.researchSummary?.analysis || null;
    }

    public get verifyHardFails(): any[] {
        return this.verify?.hard_fails || [];
    }

    public formatNumber(value: any): string {
        const num = Number(value || 0);
        return isNaN(num) ? '0' : num.toLocaleString();
    }

    public formatPct(value: any): string {
        const num = Number(value || 0);
        if (isNaN(num)) return '0.00%';
        return `${num >= 0 ? '+' : ''}${num.toFixed(2)}%`;
    }

    public formatMoney(value: any): string {
        const num = Number(value || 0);
        return isNaN(num) ? '0' : Math.round(num).toLocaleString();
    }
}
