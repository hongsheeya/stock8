/// <reference path="../../types/wiz-modules.d.ts" />

import { OnDestroy, OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';
import { kstDateString } from '../utils/kst';

export class Component implements OnInit, OnDestroy {
    public loading: boolean = true;
    public liveRefreshing: boolean = false;
    public recommending: boolean = false;
    public recommendationRefreshing: boolean = false;
    public training: boolean = false;
    public togglingAuto: boolean = false;
    public autoCycling: boolean = false;
    public dailyLogLoading: boolean = false;
    public periodLoading: boolean = false;
    public searching: boolean = false;
    public manualSelling: boolean = false;
    public marketMode: string = 'KS';
    public symbol: string = '035420';
    public selectedName: string = '';
    public strategyCode: string = 'vrev';
    public seed: number = 5000000;
    public showSearch: boolean = false;
    public showDailyLog: boolean = false;
    public showPeriodView: boolean = false;
    public showLogList: boolean = true;
    public autoEnabled: boolean = false;
    public symbolQuery: string = '';
    public symbolResults: any[] = [];
    public strategyOptions: any[] = [];
    public candidates: any[] = [];
    public recommendation: any = null;
    public selectedLeaderboardItem: any = null;
    public budgetStatus: any = {};
    public kisStatus: any = null;
    public workerStatus: any = null;
    public runtimeStatus: any = {};
    public chartSignal: any = {};
    public chartTriggers: any = {};
    public tradePlan: any = {};
    public featureSnapshot: any = {};
    public backtestSummary: any = null;
    public activePositions: any[] = [];
    public liveOrders: any[] = [];
    public autoCycleResult: any = null;
    public executionResult: any = null;
    public dailyLog: any = null;
    public periodSummary: any = null;
    public logDate: string = '';
    public logDateFrom: string = '';
    public logDateTo: string = '';
    public successMessage: string = '';
    public errorMessage: string = '';
    public manualSellEnabled: boolean = false;
    public manualSellTargetPrice: number = 0;
    public stopLossEnabled: boolean = false;
    public stopLossPrice: number = 0;
    public searchFocusAt: number = 0;
    public totalSeedKrw: number = 0;
    public usedSeedKrw: number = 0;
    public remainingSeedKrw: number = 0;
    public totalAssetKrw: number = 0;
    public recommendationPriceCap: number = 0;
    public recommendationPerSymbolSeed: number = 0;
    public recommendationSlotTargetCount: number = 0;
    public recommendationAvailableSlotCount: number = 0;
    public recommendationRequestedSeed: number = 0;
    public hiddenSeedExceededCount: number = 0;
    public briefingCollapsed: boolean = true;
    public advancedControlsCollapsed: boolean = true;
    private activePositionTimer: any = null;
    private activePositionRefreshing: boolean = false;

    constructor(public service: Service) { }

    private async confirmAutoEnable(): Promise<boolean> {
        const confirmed = await this.service.modal.show({
            title: '국장 단타 자동매매 시작',
            message: '국장 단타 자동매매를 켜면 백그라운드 워커가 후보 탐색, 진입, 자동청산 감시를 즉시 시작합니다. 수동 운용 중이면 보유 종목, 예약 주문, 시드 상태를 먼저 확인하세요.',
            action: '그래도 켜기',
            cancel: '취소',
            status: 'warning',
            actionBtn: 'warning',
        });
        return confirmed === true;
    }

    public async ngOnInit() {
        await this.service.init(this);
        await this.service.auth.allow('/access');
        this.initializeDates();
        try {
            await this.bootstrap();
        } finally {
            this.loading = false;
            await this.service.render();
        }
        void this.refreshRecommendationIfMissing(false);
    }

    public ngOnDestroy() {
        this.stopActivePositionPolling();
    }

    private initializeDates() {
        const value = kstDateString();
        this.logDate = value;
        this.logDateFrom = value;
        this.logDateTo = value;
    }

    private goTo(url: string) {
        window.location.href = url;
    }

    private async api(name: string, params: any = {}): Promise<{ code: number; data: any }> {
        return await (wiz.call(name, params) as Promise<{ code: number; data: any }>);
    }

    private async bootstrap() {
        this.errorMessage = '';
        const { code, data } = await this.api('bootstrap', { seed: this.seed });
        if (code !== 200) {
            this.errorMessage = data?.message || '단타 연구실 초기화 실패';
            return;
        }

        const defaults = data.defaults || {};
        this.marketMode = 'KS';
        this.symbol = defaults.symbol || this.symbol;
        this.selectedName = data.selected_name || this.selectedName;
        this.strategyCode = defaults.strategy || this.strategyCode;
        this.seed = Number(defaults.seed || this.seed || 5000000);
        this.candidates = data.default_candidates || [];
        this.strategyOptions = data.strategy_options || [];
        this.kisStatus = data.kis_status || null;
        this.workerStatus = data.worker_status || null;
        this.activePositions = data.active_positions || [];
        this.autoEnabled = data.auto_enabled === true;
        this.applyBudgetStatus(data.budget_status || {}, data.max_affordable_per_share || 0);
        this.applyRecommendation(data.recommendation || null);
        this.startActivePositionPolling();
        setTimeout(() => {
            void this.refreshActivePositionsQuick(false);
            void this.loadLiveStatus(false);
            if (this.showDailyLog) {
                void this.loadDailyLog();
            }
        }, 0);
    }

    private startActivePositionPolling() {
        this.stopActivePositionPolling();
        this.activePositionTimer = window.setInterval(() => {
            void this.refreshActivePositionsQuick(true);
        }, 5000);
    }

    private stopActivePositionPolling() {
        if (this.activePositionTimer) {
            clearInterval(this.activePositionTimer);
            this.activePositionTimer = null;
        }
    }

    private syncSelectedPositionCard(item: any) {
        if (!item) return;
        if (String(item.symbol || '') !== String(this.symbol || '')) return;
        if (Number(item.position_qty || 0) <= 0) return;

        if (Number(this.chartSignal?.position_qty || 0) > 0) {
            this.chartSignal = {
                ...this.chartSignal,
                avg_price: Number(item.avg_price || this.chartSignal?.avg_price || 0),
                current_price: Number(item.current_price || this.chartSignal?.current_price || 0),
                position_qty: Number(item.position_qty || this.chartSignal?.position_qty || 0),
            };
            this.chartTriggers = {
                ...this.chartTriggers,
                current: Number(item.current_price || this.chartTriggers?.current || 0),
            };
        }

        if (Number(this.tradePlan?.position?.qty || 0) > 0) {
            const qty = Number(item.position_qty || this.tradePlan.position.qty || 0);
            const price = Number(item.current_price || this.tradePlan.position.current_price || 0);
            this.tradePlan = {
                ...this.tradePlan,
                position: {
                    ...this.tradePlan.position,
                    qty,
                    avg_price: Number(item.avg_price || this.tradePlan.position.avg_price || 0),
                    current_price: price,
                    pnl: Number(item.pnl || this.tradePlan.position.pnl || 0),
                    pnl_pct: Number(item.pnl_pct || this.tradePlan.position.pnl_pct || 0),
                    value: Math.round(price * qty),
                },
            };
        }
    }

    public trackByPositionCard(index: number, item: any): string {
        return `${String(item?.market || 'KS')}:${String(item?.symbol || '')}:${String(item?.strategy_id || '')}`;
    }

    public async refreshActivePositionsQuick(render: boolean = true) {
        if (this.marketMode !== 'KS' || this.activePositionRefreshing) return;
        this.activePositionRefreshing = true;
        let shouldRender = false;
        try {
            const { code, data } = await this.api('active_positions_snapshot', {
                market: 'KS',
                refresh_quotes: 'true',
            });
            if (code === 200) {
                this.activePositions = data.active_positions || [];
                const selected = this.activePositions.find((item: any) => String(item?.symbol || '') === String(this.symbol || ''));
                if (selected) {
                    this.syncSelectedPositionCard(selected);
                }
                shouldRender = true;
            }
        } catch (e) {
        }
        this.activePositionRefreshing = false;
        if (render && shouldRender) {
            await this.service.render();
        }
    }

    private applyBudgetStatus(budgetStatus: any = {}, priceCap: number = 0) {
        this.budgetStatus = budgetStatus || {};
        this.totalSeedKrw = Number(this.budgetStatus.total_seed_krw || 0);
        this.usedSeedKrw = Number(this.budgetStatus.used_seed_krw || 0);
        this.remainingSeedKrw = Number(this.budgetStatus.remaining_seed_krw || 0);
        this.totalAssetKrw = Math.max(
            Number(this.budgetStatus.total_asset_krw || 0),
            Number(this.budgetStatus.direct_total_asset_krw || 0),
            Number(this.budgetStatus.fallback_total_asset_krw || 0),
            Number(this.budgetStatus.summary_total_asset_krw || 0),
        );
        this.recommendationPriceCap = Number(priceCap || this.budgetStatus.slot_seed_limit_krw || 0);
        this.recommendationPerSymbolSeed = Number(this.budgetStatus.per_symbol_seed_krw || 0);
        this.recommendationSlotTargetCount = Number(this.budgetStatus.slot_target_count || 0);
        this.recommendationAvailableSlotCount = Number(this.budgetStatus.available_slot_count || 0);
    }

    public async toggleBriefingCollapsed() {
        this.briefingCollapsed = !this.briefingCollapsed;
        await this.service.render();
    }

    public async toggleAdvancedControls() {
        this.advancedControlsCollapsed = !this.advancedControlsCollapsed;
        await this.service.render();
    }

    private applyRecommendation(recommendation: any) {
        this.recommendation = recommendation || null;
        this.selectedLeaderboardItem = this.recommendation?.selected || null;
        this.recommendationRequestedSeed = Number(this.recommendation?.requested_seed || this.seed || 0);
        this.recommendationPriceCap = Number(this.recommendation?.price_cap_krw || this.recommendationPriceCap || 0);
        this.recommendationPerSymbolSeed = Number(this.recommendation?.per_symbol_seed_krw || this.recommendationPerSymbolSeed || 0);
        this.recommendationSlotTargetCount = Number(this.recommendation?.slot_target_count || this.recommendationSlotTargetCount || 0);
        this.recommendationAvailableSlotCount = Number(this.recommendation?.available_slot_count || this.recommendationAvailableSlotCount || 0);
        this.hiddenSeedExceededCount = this.leaderboard.filter((item: any) => this.isSeedExceeded(item)).length;
    }

    public get leaderboard(): any[] {
        return Array.isArray(this.recommendation?.leaderboard) ? this.recommendation.leaderboard : [];
    }

    public get signalAction(): string {
        return String(this.chartSignal?.action || 'HOLD');
    }

    public get signalReason(): string {
        return String(this.chartSignal?.reason || this.chartSignal?.signal_reason || '대기 중');
    }

    public get strategyName(): string {
        const item = (this.strategyOptions || []).find((row: any) => row?.id === this.strategyCode);
        return item?.name || this.strategyCode || '-';
    }

    public get activePositionCount(): number {
        return Array.isArray(this.activePositions) ? this.activePositions.length : 0;
    }

    public get hasPosition(): boolean {
        return Number(this.tradePlan?.position?.qty || this.chartSignal?.position_qty || 0) > 0;
    }

    public get canManualSell(): boolean {
        return this.manualSelling === false && this.hasPosition;
    }

    public get tradingModeLabel(): string {
        return String(this.runtimeStatus?.trading_mode || (this.autoEnabled ? 'AUTO' : 'MANUAL'));
    }

    public get aggregate(): any {
        return this.recommendation?.aggregate || null;
    }

    public get autoCycleResultItems(): any[] {
        return this.autoCycleResult?.items || this.autoCycleResult?.results || [];
    }

    public get autoCycleExcludedItems(): any[] {
        return this.autoCycleResult?.excluded_items || [];
    }

    public get dailyPnlClass(): string {
        return this.profitClass(Number(this.dailyLog?.total_pnl || 0));
    }

    public get recommendationEmptyReason(): string {
        if (this.leaderboard.length > 0) return '';
        return String(this.recommendation?.reason || this.recommendation?.message || '추천 캐시가 아직 준비되지 않았습니다.');
    }

    public get workerWaitingItems(): any[] {
        return this.workerStatus?.waiting_items || [];
    }

    public get autoCycleWaitSummary(): any {
        const direct = this.autoCycleResult?.wait_summary;
        if (direct?.message) return direct;
        const worker = this.workerStatus?.auto_cycle_wait_summary || this.workerStatus?.us_auto_cycle_wait_summary || {};
        return worker || {};
    }

    public get autoCycleWaitMessage(): string {
        return String(this.autoCycleWaitSummary?.message || '').trim();
    }

    public get autoCycleReasonSummary(): any[] {
        const rows = this.autoCycleWaitSummary?.reason_summary || [];
        return Array.isArray(rows) ? rows : [];
    }

    public get recentRuntimeLogs(): any[] {
        return this.runtimeStatus?.recent_logs || [];
    }

    public get recentRuntimeErrors(): any[] {
        return this.runtimeStatus?.recent_errors || [];
    }

    public get uniqueRuntimeErrors(): any[] {
        const rows = Array.isArray(this.recentRuntimeErrors) ? this.recentRuntimeErrors : [];
        const seen = new Set<string>();
        const result: any[] = [];
        for (const item of rows) {
            const key = [
                this.runtimeLogTitle(item),
                this.runtimeLogDescription(item),
            ].join('||');
            if (seen.has(key)) continue;
            seen.add(key);
            result.push(item);
        }
        return result;
    }

    public get autoExitTargets(): any[] {
        return this.tradePlan?.exits || [];
    }

    public get autoExitWatch(): any {
        return this.tradePlan?.auto_exit || this.runtimeStatus?.exit_watch || {};
    }

    public get autoExitSummary(): string {
        const watch = this.autoExitWatch || {};
        if (watch?.action) {
            return `${watch.action} · ${watch.reason || ''}`.trim();
        }
        return '자동 청산 대기 중';
    }

    public get reserveCycles(): number {
        return Number(this.budgetStatus?.reserve_cycle_count || 0);
    }

    public workerActionHint(item: any = null): string {
        if (item) {
            const signal = String(item.signal || 'HOLD').toUpperCase();
            if (item.executed) return `${signal} 주문 실행`;
            if (signal.startsWith('HOLD')) return '정상 감시 중 / 조건 대기';
            if (signal === 'ERROR') return '점검 오류';
            return `${signal} 보류`;
        }
        const action = String(this.workerStatus?.action || this.workerStatus?.last_action || '대기');
        const updated = String(this.workerStatus?.updated_at || this.workerStatus?.last_run_at || '');
        return updated ? `${action} · ${updated}` : action;
    }

    private sanitizeInvestorText(text: any): string {
        return String(text || '')
            .replace(/\s*\((?:qty|price|order_type|ord_dvsn)=[^)]+\)/gi, '')
            .replace(/(?:^|\s)(qty|price|order_type|ord_dvsn)=[^,\s)]+/gi, '')
            .replace(/\s{2,}/g, ' ')
            .trim();
    }

    public symbolDisplayName(symbol: string, fallback: string = ''): string {
        const code = String(symbol || '').trim();
        if (code === '') return fallback || '-';
        if (code === String(this.symbol || '').trim() && this.selectedName) return this.selectedName;
        const pools = [
            this.activePositions || [],
            this.candidates || [],
            this.symbolResults || [],
            this.leaderboard || [],
            this.workerWaitingItems || [],
        ];
        for (const pool of pools) {
            const found = (pool || []).find((item: any) => String(item?.symbol || item?.code || '').trim() === code);
            if (found?.name) return String(found.name);
        }
        return fallback || code;
    }

    public investorDecisionLabel(): string {
        const action = String(this.signalAction || 'HOLD').toUpperCase();
        if (action.startsWith('BUY2')) return '2차 진입 검토';
        if (action.startsWith('BUY')) return '매수 검토';
        if (action.includes('STOP')) return '손절 대응 필요';
        if (action.startsWith('SELL')) return '매도 검토';
        if (this.hasPosition) return '보유 관리 중';
        return '관망 구간';
    }

    public investorDecisionSummary(): string {
        const action = String(this.signalAction || 'HOLD').toUpperCase();
        const reason = this.sanitizeInvestorText(this.signalReason);
        const name = this.selectedName || this.symbolDisplayName(this.symbol, this.symbol);
        const current = Number(this.chartSignal?.current_price || 0);
        const buy1 = Number(this.chartSignal?.buy1_trigger || 0);
        const buy2 = Number(this.chartSignal?.buy2_trigger || 0);
        const target = this.primaryExitTarget();
        if (action.startsWith('BUY2')) return `현재 ${name}는 ₩${this.formatNumber(current)}이고, 2차 진입 기준은 ₩${this.formatNumber(buy2 || 0)}다. ${reason}`;
        if (action.startsWith('BUY')) return `현재 ${name}는 ₩${this.formatNumber(current)}이고, 1차 진입 기준은 ₩${this.formatNumber(buy1 || 0)}다. ${reason}`;
        if (action.startsWith('SELL')) return `현재 ${name}는 ₩${this.formatNumber(current)}이고, 우선 보는 청산 기준은 ₩${this.formatNumber(target?.target_price || current)}다. ${reason}`;
        if (this.hasPosition) return `현재 보유 종목은 유지 중이며 현재가는 ₩${this.formatNumber(current)}다. ${reason}`;
        return `지금은 서두르지 않고 대기하는 구간이다. ${reason}`;
    }

    public investorRiskSummary(): string {
        const risk = String(this.runtimeStatus?.risk_status || 'SAFE').toUpperCase();
        const haltReason = String(this.runtimeStatus?.halt_reason || '').trim();
        if (risk.includes('HALT') || haltReason !== '') {
            return haltReason || '현재는 신규 진입보다 위험 관리가 우선이다.';
        }
        if (risk.includes('WARN') || risk.includes('DEGRADE')) {
            return '시세 품질이나 장중 변동성이 불안정해 보수적으로 해석하는 구간이다.';
        }
        if (this.hasPosition) {
            return '현재 포지션은 유지 가능 범위로 보이며, 익절/손절 라인만 계속 확인하면 된다.';
        }
        return '신규 진입을 막는 큰 위험 신호는 없지만, 트리거가 올 때까지 기다리는 상태다.';
    }

    public investorNextStep(): string {
        const action = String(this.signalAction || 'HOLD').toUpperCase();
        const buy1 = Number(this.chartSignal?.buy1_trigger || 0);
        const buy2 = Number(this.chartSignal?.buy2_trigger || 0);
        const current = Number(this.chartSignal?.current_price || 0);
        const qty = Number(this.chartSignal?.order_qty || 0);
        const target = this.primaryExitTarget();
        if (action.startsWith('BUY2')) return `현재 ₩${this.formatNumber(current)} → 2차 진입선 ₩${this.formatNumber(buy2)}까지 확인하고${qty > 0 ? ` 예상 ${qty}주 규모로` : ''} 진입 여부만 결정하면 된다.`;
        if (action.startsWith('BUY')) return `현재 ₩${this.formatNumber(current)} → 1차 진입선 ₩${this.formatNumber(buy1)}까지 내려오는지 확인하고${qty > 0 ? ` 예상 ${qty}주 규모로` : ''} 진입 여부만 결정하면 된다.`;
        if (action.includes('STOP')) return '손절 기준 가격을 우선 확인하고, 자동청산 설정이 맞는지 점검하는 편이 낫다.';
        if (action.startsWith('SELL')) return `현재 ₩${this.formatNumber(current)} 기준으로${target ? ` 우선 청산선 ₩${this.formatNumber(target.target_price)}를 보고` : ''} 분할/전량 정리만 판단하면 된다.`;
        if (this.hasPosition) return '당장은 새 종목보다 현재 보유 종목의 손익과 청산 조건을 우선 보는 편이 낫다.';
        return '지금은 무리해서 쫓아가지 말고, 자동매매 알림이 바뀌는지만 보면 된다.';
    }

    private primaryExitTarget(): any {
        const targets = Array.isArray(this.autoExitTargets) ? this.autoExitTargets : [];
        return targets.find((item: any) => Number(item?.target_price || 0) > 0) || null;
    }

    public investorDecisionPriceText(): string {
        const action = String(this.signalAction || 'HOLD').toUpperCase();
        const qty = Number(this.chartSignal?.order_qty || 0);
        const current = Number(this.chartSignal?.current_price || 0);
        const buy1 = Number(this.chartSignal?.buy1_trigger || 0);
        const buy2 = Number(this.chartSignal?.buy2_trigger || 0);
        const positionQty = Number(this.tradePlan?.position?.qty || this.chartSignal?.position_qty || 0);

        if (action.startsWith('BUY2') && buy2 > 0) {
            const estimate = qty > 0 ? buy2 * qty : 0;
            return `2차 진입 기준 ₩${this.formatNumber(buy2)}${qty > 0 ? ` · 예상 ${qty}주 · 약 ₩${this.formatNumber(estimate)}` : ''}`;
        }
        if (action.startsWith('BUY') && buy1 > 0) {
            const estimate = qty > 0 ? buy1 * qty : 0;
            return `1차 진입 기준 ₩${this.formatNumber(buy1)}${qty > 0 ? ` · 예상 ${qty}주 · 약 ₩${this.formatNumber(estimate)}` : ''}`;
        }
        if (action.startsWith('SELL')) {
            const target = this.autoExitTargets.find((item: any) => Number(item?.target_price || 0) > 0);
            if (target) {
                return `${target.label} 기준 ₩${this.formatNumber(target.target_price)}${positionQty > 0 ? ` · ${positionQty}주 기준` : ''}`;
            }
        }
        if (this.hasPosition && current > 0) {
            const avg = Number(this.tradePlan?.position?.avg_price || this.chartSignal?.avg_price || 0);
            return `현재가 ₩${this.formatNumber(current)} · 평단 ₩${this.formatNumber(avg)} · 보유 ${positionQty}주`;
        }
        if (buy1 > 0) {
            return `다음 매수 감시가 ₩${this.formatNumber(buy1)}`;
        }
        return '아직 확정된 매매 가격은 없습니다.';
    }

    public strategyLabel(strategyId: string): string {
        const normalized = String(strategyId || '').trim();
        if (normalized === '') return '';
        const item = (this.strategyOptions || []).find((row: any) => String(row?.id || '') === normalized);
        return item?.name || normalized;
    }

    public activePositionFreshness(item: any): string {
        const updated = String(item?.updated_at || '').trim();
        if (updated === '') return '갱신 시각 없음';
        return `${updated} 기준`;
    }

    public runtimeLogLevelLabel(item: any): string {
        const level = String(item?.level || 'info').toLowerCase();
        if (level === 'error') return '오류';
        if (level === 'warning') return '주의';
        return '알림';
    }

    public runtimeLogLevelClass(item: any): string {
        const level = String(item?.level || 'info').toLowerCase();
        if (level === 'error') return 'bg-red-500/15 text-red-300 border border-red-400/20';
        if (level === 'warning') return 'bg-amber-500/15 text-amber-300 border border-amber-400/20';
        return 'bg-indigo-500/15 text-indigo-300 border border-indigo-400/20';
    }

    public runtimeLogCardClass(item: any): string {
        const level = String(item?.level || 'info').toLowerCase();
        if (level === 'error') return 'border-red-400/15 bg-red-500/5';
        if (level === 'warning') return 'border-amber-400/15 bg-amber-500/5';
        return 'border-white/10 bg-black/20';
    }

    public runtimeLogTitle(item: any): string {
        const message = String(item?.message || '').trim();
        const symbol = this.symbolDisplayName(String(item?.symbol || '').trim(), '선택 종목');
        if (message.includes('자동순환 시작')) return '자동매매 점검을 시작했습니다';
        if (message.includes('자동순환 점검')) return `${symbol || '선택 종목'} 점검 중`;
        if (message.includes('자동순환 결과')) return `${symbol || '선택 종목'} 이번 점검 결론`;
        if (message.includes('실행 판단')) return `${symbol || '선택 종목'} 지금 판단은 이렇습니다`;
        if (message.includes('후보 제외(변동성 부족)')) return '오늘은 움직임이 약해 후보에서 빠졌습니다';
        if (message.includes('후보 제외(시드 초과)')) return '남은 시드로는 지금 진입하기 어렵습니다';
        if (message.includes('후보 제외(실주문 전략 제한)')) return '현재 자동매매 대상 전략이 아닙니다';
        if (message.includes('후보 제외')) return '이번 추천에서는 제외됐습니다';
        if (message.includes('신규 진입 차단')) return '지금은 신규 진입을 쉬는 편이 낫습니다';
        if (message.includes('구매 상한 낮음')) return '매수 가능한 가격대가 많이 좁아졌습니다';
        if (message.includes('주문 실패')) return `${symbol || '선택 종목'} 주문에 실패했습니다`;
        if (message.includes('라이브 시그널 계산 실패')) return `${symbol || '선택 종목'} 시그널 계산에 실패했습니다`;
        return message || '운영 로그';
    }

    public runtimeLogDescription(item: any): string {
        const meta = item?.meta || {};
        const message = String(item?.message || '').trim();
        const currentPrice = Number(meta.current_price || 0);
        const buy1Trigger = Number(meta.buy1_trigger || 0);
        const buy2Trigger = Number(meta.buy2_trigger || 0);
        const orderQty = Number(meta.order_qty || 0);
        if (message.includes('자동순환 결과: HOLD / 보류')) {
            return this.sanitizeInvestorText(meta.message || '지금은 바로 매수하지 않고 기다리는 쪽이 더 낫다는 뜻이다.');
        }
        if (message.includes('실행 판단: HOLD')) {
            if (currentPrice > 0 && buy1Trigger > 0) {
                return `현재가 ₩${this.formatNumber(currentPrice)} 기준으로 1차 진입선 ₩${this.formatNumber(buy1Trigger)}${buy2Trigger > 0 ? `, 2차 진입선 ₩${this.formatNumber(buy2Trigger)}` : ''}를 기다리는 중이다. ${this.sanitizeInvestorText(meta.reason || '')}`;
            }
            return this.sanitizeInvestorText(meta.reason || '아직은 트리거가 완성되지 않아 관망하는 구간이다.');
        }
        if (message.includes('실행 판단: BUY') || message.includes('자동순환 결과: BUY')) {
            return `현재가 ₩${this.formatNumber(currentPrice)}에서 ${buy2Trigger > 0 && String(meta.action || '').includes('BUY2') ? `2차 진입선 ₩${this.formatNumber(buy2Trigger)}` : `1차 진입선 ₩${this.formatNumber(buy1Trigger || currentPrice)}`} 기준으로${orderQty > 0 ? ` 약 ${this.formatNumber(orderQty)}주 진입을 보는 중이다.` : ' 진입을 보는 중이다.'}`;
        }
        if (message.includes('자동순환 점검')) {
            return this.sanitizeInvestorText(meta.decision_reason || '보유 상태와 신규 진입 가능성을 함께 점검하는 단계다.');
        }
        if (message.includes('후보 제외(변동성 부족)')) {
            return '하루 움직임이 약해 단타 수익 구간이 좁다고 판단했다.';
        }
        if (message.includes('후보 제외(시드 초과)')) {
            return '남은 자금으로 1주 진입이 어렵기 때문에 일단 후보군에서 뺐다.';
        }
        if (message.includes('구매 상한 낮음')) {
            return '현금 여력이 줄어 고가 종목보다 저가 종목 위주로만 볼 수 있는 상태다.';
        }
        return this.sanitizeInvestorText(meta.reason || meta.message || meta.decision_reason || message || '');
    }

    public runtimeLogChips(item: any): string[] {
        const meta = item?.meta || {};
        const chips: string[] = [];
        const action = String(meta.action || '').trim();
        const risk = String(meta.risk_status || '').trim();
        const strategyId = String(item?.strategy_id || '').trim();
        const source = String(meta.source || '').trim();
        if (action !== '') chips.push(`현재 판단 ${action}`);
        if (risk !== '') chips.push(`위험 ${risk}`);
        if (strategyId !== '') chips.push(`전략 ${this.strategyLabel(strategyId)}`);
        if (source === 'active_position') chips.push('보유 종목 우선');
        if (source === 'leaderboard') chips.push('추천 후보');
        return chips;
    }

    public runtimeLogMetaText(item: any): string {
        const meta = item?.meta || {};
        const rows: string[] = [];
        const currentPrice = Number(meta.current_price || 0);
        const buy1Trigger = Number(meta.buy1_trigger || 0);
        const buy2Trigger = Number(meta.buy2_trigger || 0);
        const allocatedSeed = Number(meta.allocated_seed || 0);
        const remainBefore = Number(meta.remaining_seed_before || 0);
        const remainAfter = Number(meta.remaining_seed_after || 0);
        const orderValue = Number(meta.order_value || 0);
        const orderQty = Number(meta.order_qty || 0);
        const positionQty = Number(meta.position_qty || 0);
        if (currentPrice > 0) rows.push(`현재가 ₩${this.formatNumber(currentPrice)}`);
        if (buy1Trigger > 0) rows.push(`1차 진입가 ₩${this.formatNumber(buy1Trigger)}`);
        if (buy2Trigger > 0) rows.push(`2차 진입가 ₩${this.formatNumber(buy2Trigger)}`);
        if (allocatedSeed > 0) rows.push(`배정시드 ₩${this.formatNumber(allocatedSeed)}`);
        if (remainBefore > 0) rows.push(`실행 전 잔여 ₩${this.formatNumber(remainBefore)}`);
        if (remainAfter > 0 || remainAfter === 0) rows.push(`실행 후 잔여 ₩${this.formatNumber(remainAfter)}`);
        if (orderQty > 0) rows.push(`예상 수량 ${this.formatNumber(orderQty)}주`);
        if (positionQty > 0) rows.push(`보유 수량 ${this.formatNumber(positionQty)}주`);
        if (orderValue > 0) rows.push(`예상 주문금액 ₩${this.formatNumber(orderValue)}`);
        return rows.join(' · ');
    }

    public signalDisplayLabel(item: any): string {
        const signal = String(item?.signal || 'HOLD').toUpperCase();
        if (!item?.executed && signal.startsWith('HOLD')) return '조건대기';
        if (signal === 'ERROR') return '오류';
        return signal;
    }

    public autoCycleItemSummary(item: any): string {
        if (!item) return '-';
        const symbol = item.symbol || '-';
        const signal = String(item.signal || item.action || item.status || 'HOLD').toUpperCase();
        const executed = !!item.executed;
        if (executed) return `${symbol} · ${signal} 주문 실행`;
        if (signal.startsWith('HOLD')) return `${symbol} · 정상 감시 중 / 조건 대기`;
        if (signal === 'ERROR') return `${symbol} · 점검 오류`;
        return `${symbol} · ${signal} 보류`;
    }

    public autoCycleItemDetail(item: any): string {
        if (!item) return '';
        const parts = [
            item.signal_reason,
            item.decision_reason,
            item.detail,
            item.reason,
            item.message,
        ].map((text: any) => String(text || '').trim()).filter((text: string) => text !== '');
        return parts[0] || '';
    }

    public leaderboardDecisionText(item: any): string {
        const text = String(item?.decision_reason || item?.reason || '').trim();
        if (text !== '') return text;
        const name = String(item?.name || item?.symbol || '선택 종목');
        const strategy = String(item?.strategy_name || item?.strategy_id || '전략');
        const price = Number(item?.last_price || 0);
        const range = Number(item?.avg_day_range_pct || 0);
        const score = Number(item?.score || 0);
        return `${name}은 ${strategy} 기준 상위 후보다. 현재가 ₩${this.formatNumber(price)} · 평균 일중 변동폭 ${this.formatNumber(range, '1.0-2')}% · 점수 ${this.formatNumber(score, '1.0-1')}점.`;
    }

    public leaderboardNextActionText(item: any): string {
        const text = String(item?.next_action || item?.action || '').trim();
        if (text !== '') return text;
        const price = Number(item?.last_price || 0);
        const strategy = String(item?.strategy_id || '').trim();
        if (strategy === 'vrev') {
            return `현재가 ₩${this.formatNumber(price)} 기준으로 눌림이 나올 때 분할 진입 후보로 감시한다.`;
        }
        return `현재가 ₩${this.formatNumber(price)} 기준으로 전략 조건이 다시 맞는지 감시한다.`;
    }

    public get totalAssetSourceText(): string {
        const source = String(this.budgetStatus?.total_asset_source || '').trim();
        if (source === 'present_total_asset') return '대시보드와 같은 증권사 총자산 기준';
        if (source === 'present_balance.total_asset_krw') return '대시보드와 같은 증권사 총자산 기준';
        if (source.startsWith('summary_total_asset:')) return '증권사 잔고 요약 기준';
        if (source === 'direct(krw+domestic_eval+usd_cash+usd_eval)') return '원화 출금가능액 + 국내평가 + 해외현금 + 해외평가 기준';
        if (source === 'domestic_balance.summary_total_asset_krw') return '증권사 잔고 요약 기준';
        if (source === 'fallback_total_asset_krw') return '총자산 직접 합산 기준';
        return '';
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
        if (normalized.includes('WARN') || normalized.includes('DEGRADE')) return 'bg-amber-500/20 text-amber-300 border border-amber-400/20';
        if (normalized.includes('STOP') || normalized.includes('BLOCK')) return 'bg-red-500/20 text-red-300 border border-red-400/20';
        return 'bg-white/5 text-slate-300 border border-white/10';
    }

    public usSignalBadgeClass(): string {
        return this.signalBadgeClass(this.signalAction);
    }

    public profitClass(value: number): string {
        if (Number(value || 0) > 0) return 'text-emerald-400';
        if (Number(value || 0) < 0) return 'text-red-400';
        return 'text-slate-400';
    }

    public formatNumber(value: any, digits: any = 0): string {
        const number = Number(value || 0);
        if (!Number.isFinite(number)) return '0';
        let minDigits = 0;
        let maxDigits = 0;
        if (typeof digits === 'string') {
            const match = digits.match(/\d+\.(\d+)-(\d+)/);
            if (match) {
                minDigits = Number(match[1] || 0);
                maxDigits = Number(match[2] || 0);
            }
        } else {
            minDigits = Number(digits || 0);
            maxDigits = Number(digits || 0);
        }
        return number.toLocaleString('ko-KR', {
            minimumFractionDigits: minDigits,
            maximumFractionDigits: maxDigits,
        });
    }

    public formatUsd(value: any): string {
        const number = Number(value || 0);
        if (!Number.isFinite(number)) return '$0.00';
        return `$${number.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }

    public isSeedExceeded(item: any): boolean {
        const allocated = Number(item?.allocated_seed || item?.buy_budget || 0);
        const cap = Number(this.recommendationPerSymbolSeed || this.recommendationPriceCap || 0);
        return allocated > 0 && cap > 0 && allocated > cap;
    }

    public async switchMarketMode(mode: string) {
        if (mode === 'US') {
            this.goTo('/daytrade/us');
            return;
        }
        this.marketMode = 'KS';
        await this.service.render();
    }

    public async toggleSearch() {
        this.showSearch = !this.showSearch;
        if (!this.showSearch) {
            this.symbolQuery = '';
            this.symbolResults = [];
        }
        await this.service.render();
    }

    public async onStrategyChange() {
        await this.loadLiveStatus(true);
    }

    public async applySeed() {
        try {
            const { code, data } = await this.api('sync_seed', { seed: this.seed });
            if (code !== 200) {
                this.errorMessage = data?.message || '시드 저장 실패';
                await this.service.render();
                return;
            }
            this.successMessage = '시드를 저장했습니다.';
            this.seed = Number(data?.requested_seed || this.seed || 0);
            this.recommendationRequestedSeed = this.seed;
            this.applyBudgetStatus(data.budget_status || {}, data.max_affordable_per_share || 0);
            this.workerStatus = data.worker_status || this.workerStatus;
            await this.loadLiveStatus(true);
            await this.refreshRecommendationIfMissing(false);
        } catch (e: any) {
            this.errorMessage = e?.message || '시드 저장 중 오류가 발생했습니다.';
        }
        await this.service.render();
    }

    public async runRecommend(force: boolean = false) {
        this.recommending = true;
        this.errorMessage = '';
        await this.service.render();
        try {
            const { code, data } = await this.api('recommend', {
                seed: this.seed,
                strategy: this.strategyCode,
                force: force ? 'true' : 'false',
            });
            if (code !== 200) {
                this.errorMessage = data?.message || '추천 갱신 실패';
            } else {
                this.applyBudgetStatus(data.budget_status || this.budgetStatus, data.max_affordable_per_share || 0);
                this.applyRecommendation(data.result || null);
                this.successMessage = force ? '추천을 다시 계산했습니다.' : '추천을 불러왔습니다.';
            }
        } catch (e: any) {
            this.errorMessage = e?.message || '추천 처리 중 오류가 발생했습니다.';
        }
        this.recommending = false;
        await this.service.render();
    }

    public async refreshRecommendationIfMissing(force: boolean = false) {
        if (this.recommendationRefreshing) return;
        if (!force && this.leaderboard.length > 0) return;
        this.recommendationRefreshing = true;
        await this.service.render();
        try {
            await this.runRecommend(force);
        } finally {
            this.recommendationRefreshing = false;
            await this.service.render();
        }
    }

    public async trainSymbol() {
        this.training = true;
        this.errorMessage = '';
        await this.service.render();
        try {
            const { code, data } = await this.api('train_symbol', {
                symbol: this.symbol,
                market: 'KS',
                strategy: this.strategyCode,
                seed: this.seed,
            });
            if (code !== 200) {
                this.errorMessage = data?.message || '학습 실패';
            } else {
                this.successMessage = data?.result?.message || `${this.symbol} 학습을 완료했습니다.`;
                await this.refreshRecommendationIfMissing(true);
                await this.loadLiveStatus(true);
            }
        } catch (e: any) {
            this.errorMessage = e?.message || '학습 중 오류가 발생했습니다.';
        }
        this.training = false;
        await this.service.render();
    }

    public async searchSymbols() {
        this.searching = true;
        await this.service.render();
        try {
            const { code, data } = await this.api('search_symbols', { query: this.symbolQuery });
            this.symbolResults = code === 200 ? (data.results || []) : [];
        } catch (e) {
            this.symbolResults = [];
        }
        this.searching = false;
        await this.service.render();
    }

    public async selectSymbol(item: any) {
        const symbol = String(item?.symbol || item?.code || '').trim();
        if (symbol === '') return;
        this.symbol = symbol;
        this.selectedName = String(item?.name || this.selectedName || '');
        this.showSearch = false;
        this.symbolQuery = '';
        this.symbolResults = [];
        await this.loadLiveStatus(true);
    }

    public async loadLiveStatus(forceRefresh: boolean = false) {
        this.liveRefreshing = true;
        await this.service.render();
        try {
            const { code, data } = await this.api('live_status', {
                symbol: this.symbol,
                market: 'KS',
                strategy: this.strategyCode,
                seed: this.seed,
                force_refresh: forceRefresh ? 'true' : 'false',
            });
            if (code !== 200) {
                this.errorMessage = data?.message || '실시간 상태 조회 실패';
            } else {
                const status = data.status || {};
                this.chartSignal = status.signal || {};
                this.runtimeStatus = status.runtime || {};
                this.featureSnapshot = status.feature_snapshot || {};
                this.backtestSummary = status.backtest || this.backtestSummary;
                this.chartTriggers = {
                    anchor: this.chartSignal.anchor_price || 0,
                    buy1: this.chartSignal.buy1_trigger || 0,
                    buy2: this.chartSignal.buy2_trigger || 0,
                    current: this.chartSignal.current_price || 0,
                };
                this.tradePlan = data.plan || {};
                this.activePositions = data.active_positions || [];
                this.budgetStatus = data.budget_status || this.budgetStatus;
                this.kisStatus = data.kis_status || this.kisStatus;
                this.autoEnabled = data.auto_enabled === true;
                this.workerStatus = data.worker_status || this.workerStatus;
                const selectedPosition = this.activePositions.find((item: any) => String(item?.symbol || '') === String(this.symbol || ''));
                if (selectedPosition) {
                    this.syncSelectedPositionCard(selectedPosition);
                }
                this.applyBudgetStatus(this.budgetStatus, data.max_affordable_per_share || this.recommendationPriceCap || 0);
                if (data.recommendation) {
                    this.applyRecommendation(data.recommendation);
                }
                const state = status.state || {};
                this.manualSellEnabled = state.manual_sell_enabled === true;
                this.manualSellTargetPrice = Number(state.manual_sell_target_price || 0);
                this.stopLossEnabled = state.stop_loss_enabled === true;
                this.stopLossPrice = Number(state.stop_loss_price || 0);
            }
        } catch (e: any) {
            this.errorMessage = e?.message || '실시간 상태 조회 중 오류가 발생했습니다.';
        }
        this.liveRefreshing = false;
        await this.service.render();
    }

    public async refreshLiveStatus() {
        await this.loadLiveStatus(true);
    }

    public async executeSignal() {
        try {
            const { code, data } = await this.api('execute_live', {
                symbol: this.symbol,
                market: 'KS',
                strategy: this.strategyCode,
                seed: this.seed,
            });
            if (code !== 200) {
                this.errorMessage = data?.message || '실행 실패';
            } else {
                this.executionResult = data.result || null;
                this.successMessage = data.result?.message || '실행 요청을 전송했습니다.';
                await this.loadLiveStatus(true);
                if (this.showDailyLog) {
                    await this.loadDailyLog();
                }
            }
        } catch (e: any) {
            this.errorMessage = e?.message || '실행 중 오류가 발생했습니다.';
        }
        await this.service.render();
    }

    public async toggleDailyLog() {
        this.showDailyLog = !this.showDailyLog;
        if (this.showDailyLog) {
            await this.loadDailyLog();
        }
        await this.service.render();
    }

    public async onLogDateChange() {
        if (this.showDailyLog) {
            await this.loadDailyLog();
        }
    }

    public async loadDailyLog() {
        this.dailyLogLoading = true;
        await this.service.render();
        try {
            const { code, data } = await this.api('daily_log', { date: this.logDate });
            if (code !== 200) {
                this.errorMessage = data?.message || '거래 일지 조회 실패';
            } else {
                this.dailyLog = data.summary || null;
            }
        } catch (e: any) {
            this.errorMessage = e?.message || '거래 일지 조회 중 오류가 발생했습니다.';
        }
        this.dailyLogLoading = false;
        await this.service.render();
    }

    public async togglePeriodView() {
        this.showPeriodView = !this.showPeriodView;
        if (this.showPeriodView && !this.periodSummary) {
            await this.loadPeriodSummary();
        }
        await this.service.render();
    }

    public async loadPeriodSummary() {
        this.periodLoading = true;
        await this.service.render();
        try {
            const { code, data } = await this.api('period_summary', {
                date_from: this.logDateFrom,
                date_to: this.logDateTo,
            });
            if (code !== 200) {
                this.errorMessage = data?.message || '기간 집계 조회 실패';
            } else {
                this.periodSummary = data.result || null;
            }
        } catch (e: any) {
            this.errorMessage = e?.message || '기간 집계 조회 중 오류가 발생했습니다.';
        }
        this.periodLoading = false;
        await this.service.render();
    }

    public async toggleAutoEnabled() {
        if (this.autoEnabled !== true) {
            const confirmed = await this.confirmAutoEnable();
            if (!confirmed) {
                return;
            }
        }
        this.togglingAuto = true;
        await this.service.render();
        try {
            const { code, data } = await this.api('toggle_auto_enabled', {
                enabled: this.autoEnabled ? 'false' : 'true',
            });
            if (code !== 200) {
                this.errorMessage = data?.message || '자동매매 설정 변경 실패';
            } else {
                this.autoEnabled = data.auto_enabled === true;
                this.workerStatus = data.worker_status || this.workerStatus;
                this.successMessage = this.autoEnabled
                    ? '자동매매를 시작했습니다.'
                    : '자동매매와 자동매도를 중지했습니다.';
            }
        } catch (e: any) {
            this.errorMessage = e?.message || '자동매매 설정 변경 중 오류가 발생했습니다.';
        }
        this.togglingAuto = false;
        await this.service.render();
    }

    public async runAutoCycle() {
        this.autoCycling = true;
        this.errorMessage = '';
        await this.service.render();
        try {
            const { code, data } = await this.api('run_auto_cycle', {
                seed: this.seed,
            });
            if (code !== 200) {
                this.errorMessage = data?.message || '자동순환 점검 실패';
            } else {
                this.autoCycleResult = data.result || null;
                this.successMessage = this.autoCycleResult?.message || '자동순환 점검을 실행했습니다.';
                await this.loadLiveStatus(true);
                if (this.showDailyLog) {
                    await this.loadDailyLog();
                }
            }
        } catch (e: any) {
            this.errorMessage = e?.message || '자동순환 점검 중 오류가 발생했습니다.';
        }
        this.autoCycling = false;
        await this.service.render();
    }

    public async saveTradeSettings() {
        try {
            const { code, data } = await this.api('update_trade_settings', {
                symbol: this.symbol,
                market: 'KS',
                strategy: this.strategyCode,
                seed: this.seed,
                manual_sell_enabled: this.manualSellEnabled ? 'true' : 'false',
                manual_sell_target_price: this.manualSellTargetPrice || '',
                stop_loss_enabled: this.stopLossEnabled ? 'true' : 'false',
                stop_loss_price: this.stopLossPrice || '',
            });
            if (code !== 200) {
                this.errorMessage = data?.message || '매매 설정 저장 실패';
            } else {
                this.successMessage = '매매 설정을 저장했습니다.';
                await this.loadLiveStatus(true);
            }
        } catch (e: any) {
            this.errorMessage = e?.message || '매매 설정 저장 중 오류가 발생했습니다.';
        }
        await this.service.render();
    }

    public async manualSellPosition() {
        this.manualSelling = true;
        await this.service.render();
        try {
            const { code, data } = await this.api('manual_sell', {
                symbol: this.symbol,
                market: 'KS',
                strategy: this.strategyCode,
                seed: this.seed,
            });
            if (code !== 200) {
                this.errorMessage = data?.message || '수동 매도 실패';
            } else {
                this.successMessage = data.result?.message || '수동 매도 요청을 전송했습니다.';
                await this.loadLiveStatus(true);
                if (this.showDailyLog) {
                    await this.loadDailyLog();
                }
            }
        } catch (e: any) {
            this.errorMessage = e?.message || '수동 매도 중 오류가 발생했습니다.';
        }
        this.manualSelling = false;
        await this.service.render();
    }

    public async clearManualSellTarget() {
        this.manualSellTargetPrice = 0;
        this.manualSellEnabled = false;
        await this.saveTradeSettings();
    }

    public async clearStopLossTarget() {
        this.stopLossPrice = 0;
        this.stopLossEnabled = false;
        await this.saveTradeSettings();
    }

    public async onTradeSettingBlur() {
        await this.saveTradeSettings();
    }

    public onTradeSettingFocus() {
        this.searchFocusAt = Date.now();
    }

    public async usBootstrap() { this.goTo('/daytrade/us'); }
    public async usLoadLiveStatus() { this.goTo('/daytrade/us'); }
    public async usLoadDailyLog() { this.goTo('/daytrade/us'); }
    public async usRunAutoCycle() { this.goTo('/daytrade/us'); }
    public async usSearchSymbols() { this.goTo('/daytrade/us'); }
    public async usSelectSymbol(item: any) { this.goTo('/daytrade/us'); }
    public async usExecuteLive() { this.goTo('/daytrade/us'); }
    public async usToggleAuto() { this.goTo('/daytrade/us'); }
    public async usVerifyRuntime() { this.goTo('/daytrade/us'); }
}
