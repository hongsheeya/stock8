import { OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';
import { i18n } from '@wiz/libs/portal/trading/i18n';
import { kstDateString } from '../utils/kst';

export class Component implements OnInit {
    public loading: boolean = false;
    public running: boolean = false;
    public t = (key: string) => i18n.t(key);

    // Form
    public symbol: string = '';
    public customSymbol: string = '';
    public symbolValid: boolean | null = null;
    public symbolInfo: any = null;
    public symbolValidating: boolean = false;
    public startDate: string = '';
    public endDate: string = '';
    public investment: number = 10000;
    public divisionCount: number = 40;
    public targetProfit: number = 10;

    // Commission & Tax
    public buyCommissionRate: number = 0.25;
    public sellCommissionRate: number = 0.25;
    public taxRate: number = 0;

    // Extension option
    public allowExtension: boolean = false;

    // My Strategy
    public useMyStrategy: boolean = false;
    public myStrategyLoaded: boolean = false;
    public myStrategy: any = {};
    private customParamsBeforeMyStrategy: any = null;

    // Results
    public hasResult: boolean = false;
    public summary: any = {};
    public trades: any[] = [];
    public cycles: any[] = [];
    public errorMessage: string = '';

    // Watchlist for symbol picker
    public watchlist: any[] = [];

    // Trade filter
    public tradeFilter: string = 'ALL';

    // Strategy Comparison
    public showComparison: boolean = false;
    public comparing: boolean = false;
    public hasComparison: boolean = false;
    public comparisonResult: any = null;
    public partialSellStages: any[] = [];

    // Crash Buy (comparison)
    public crashBuyEnabled: boolean = false;
    public crashBuyDropPct: number = 5;
    public crashBuyMaDropPct: number = 10;
    public crashBuyRatio: number = 10;
    public crashBuyMaxPerCycle: number = 3;

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

    private partialStrategySummary(stages: any[] = []): string {
        return this.normalizePartialSellStages(stages)
            .map((stage: any) => `${stage.roundLabel} ${stage.triggerLabel}→${stage.sellLabel}`)
            .join(', ');
    }

    public async ngOnInit() {
        await this.service.init(this);
        await this.service.auth.allow("/access");

        // Default dates: 1 year
        const now = new Date();
        const yearAgo = new Date(now);
        yearAgo.setFullYear(yearAgo.getFullYear() - 1);
        this.startDate = kstDateString(yearAgo);
        this.endDate = kstDateString(now);

        await this.loadWatchlist();
    }

    public async loadWatchlist() {
        this.errorMessage = '';
        try {
            const { code, data } = await wiz.call("load_watchlist");
            if (code === 200) {
                this.watchlist = data.watchlist || [];
                this.buyCommissionRate = data.buy_commission_rate ?? 0.25;
                this.sellCommissionRate = data.sell_commission_rate ?? 0.25;
                this.taxRate = data.tax_rate ?? 0;
                this.divisionCount = data.division_count ?? 40;
                this.targetProfit = data.target_profit ?? 10;

                // 내 전략 파라미터 저장
                this.myStrategy = {
                    division_count: data.division_count ?? 40,
                    target_profit: data.target_profit ?? 10,
                    buy_commission_rate: data.buy_commission_rate ?? 0.25,
                    sell_commission_rate: data.sell_commission_rate ?? 0.25,
                    tax_rate: data.tax_rate ?? 0,
                    sell_strategy: data.sell_strategy || 'full',
                    partial_sell_stages: data.partial_sell_stages || [],
                    crash_buy_enabled: data.crash_buy_enabled ?? false,
                    crash_buy_drop_pct: data.crash_buy_drop_pct ?? 5,
                    crash_buy_ma_drop_pct: data.crash_buy_ma_drop_pct ?? 10,
                    crash_buy_ratio: data.crash_buy_ratio ?? 10,
                    crash_buy_max_per_cycle: data.crash_buy_max_per_cycle ?? 3,
                };
                this.partialSellStages = this.normalizePartialSellStages(data.partial_sell_stages);
                this.myStrategyLoaded = true;

                // 워치리스트가 있으면 첫 번째 종목 기본 선택
                if (this.watchlist.length > 0 && !this.symbol) {
                    this.symbol = this.watchlist[0].symbol;
                }
            } else {
                this.errorMessage = data?.message || '워치리스트를 불러오지 못했습니다.';
            }
        } catch (e: any) {
            console.error('load_watchlist failed:', e);
            this.errorMessage = '워치리스트를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.';
        }
        await this.service.render();
    }

    private applyMyStrategyParams() {
        if (!this.myStrategy) return;
        this.divisionCount = this.myStrategy.division_count ?? this.divisionCount;
        this.targetProfit = this.myStrategy.target_profit ?? this.targetProfit;
        this.buyCommissionRate = this.myStrategy.buy_commission_rate ?? this.buyCommissionRate;
        this.sellCommissionRate = this.myStrategy.sell_commission_rate ?? this.sellCommissionRate;
        this.taxRate = this.myStrategy.tax_rate ?? this.taxRate;
        this.crashBuyEnabled = this.myStrategy.crash_buy_enabled ?? this.crashBuyEnabled;
        this.crashBuyDropPct = this.myStrategy.crash_buy_drop_pct ?? this.crashBuyDropPct;
        this.crashBuyMaDropPct = this.myStrategy.crash_buy_ma_drop_pct ?? this.crashBuyMaDropPct;
        this.crashBuyRatio = this.myStrategy.crash_buy_ratio ?? this.crashBuyRatio;
        this.crashBuyMaxPerCycle = this.myStrategy.crash_buy_max_per_cycle ?? this.crashBuyMaxPerCycle;
    }

    public async toggleMyStrategy() {
        this.useMyStrategy = !this.useMyStrategy;
        if (this.useMyStrategy) {
            this.customParamsBeforeMyStrategy = {
                divisionCount: this.divisionCount,
                targetProfit: this.targetProfit,
                buyCommissionRate: this.buyCommissionRate,
                sellCommissionRate: this.sellCommissionRate,
                taxRate: this.taxRate,
                crashBuyEnabled: this.crashBuyEnabled,
                crashBuyDropPct: this.crashBuyDropPct,
                crashBuyMaDropPct: this.crashBuyMaDropPct,
                crashBuyRatio: this.crashBuyRatio,
                crashBuyMaxPerCycle: this.crashBuyMaxPerCycle,
            };
            this.applyMyStrategyParams();
        } else if (this.customParamsBeforeMyStrategy) {
            this.divisionCount = this.customParamsBeforeMyStrategy.divisionCount;
            this.targetProfit = this.customParamsBeforeMyStrategy.targetProfit;
            this.buyCommissionRate = this.customParamsBeforeMyStrategy.buyCommissionRate;
            this.sellCommissionRate = this.customParamsBeforeMyStrategy.sellCommissionRate;
            this.taxRate = this.customParamsBeforeMyStrategy.taxRate;
            this.crashBuyEnabled = this.customParamsBeforeMyStrategy.crashBuyEnabled;
            this.crashBuyDropPct = this.customParamsBeforeMyStrategy.crashBuyDropPct;
            this.crashBuyMaDropPct = this.customParamsBeforeMyStrategy.crashBuyMaDropPct;
            this.crashBuyRatio = this.customParamsBeforeMyStrategy.crashBuyRatio;
            this.crashBuyMaxPerCycle = this.customParamsBeforeMyStrategy.crashBuyMaxPerCycle;
        }
        await this.service.render();
    }

    public async toggleAllowExtension() {
        this.allowExtension = !this.allowExtension;
        await this.service.render();
    }

    public async onSymbolChange(val: string) {
        this.symbol = val;
        if (val !== '__custom__') {
            this.customSymbol = '';
            this.symbolValid = null;
            this.symbolInfo = null;
        }
        await this.service.render();
    }

    public async validateCustomSymbol() {
        const sym = this.customSymbol?.trim().toUpperCase();
        if (!sym) return;
        this.symbolValidating = true;
        this.symbolValid = null;
        this.symbolInfo = null;
        await this.service.render();

        const { code, data } = await wiz.call("validate_symbol", { symbol: sym });
        this.symbolValidating = false;
        if (code === 200) {
            this.symbolValid = data.valid;
            this.symbolInfo = data;
        } else {
            this.symbolValid = false;
            this.symbolInfo = { message: data?.message || 'Validation failed' };
        }
        await this.service.render();
    }

    private getSimulationSymbol(): string {
        if (this.symbol === '__custom__') {
            return (this.customSymbol || '').trim().toUpperCase();
        }
        return (this.symbol || '').trim().toUpperCase();
    }

    public async runSimulation() {
        if (this.running) return;
        this.running = true;
        this.hasResult = false;
        this.hasComparison = false;
        this.comparisonResult = null;
        this.errorMessage = '';
        this.loading = true;
        await this.service.render();

        try {
            const simSymbol = this.getSimulationSymbol();
            if (!simSymbol) {
                this.errorMessage = 'Please select or enter a symbol';
                this.running = false;
                this.loading = false;
                await this.service.render();
                return;
            }
            const params: any = {
                symbol: simSymbol,
                start_date: this.startDate,
                end_date: this.endDate,
                investment: this.investment,
                division_count: this.divisionCount,
                target_profit: this.targetProfit,
                buy_commission_rate: this.buyCommissionRate,
                sell_commission_rate: this.sellCommissionRate,
                tax_rate: this.taxRate,
                allow_extension: this.allowExtension,
                use_my_strategy: this.useMyStrategy,
            };

            const { code, data } = await wiz.call("run_simulation", params);

            if (code === 200) {
                this.summary = data.summary || {};
                this.trades = data.trades || [];
                this.cycles = data.cycles || [];
                this.hasResult = true;
            } else {
                this.errorMessage = data?.message || 'Simulation failed';
            }
        } catch (e: any) {
            this.errorMessage = e?.message || 'An error occurred';
            console.error("Simulation error:", e);
        }

        this.running = false;
        this.loading = false;
        await this.service.render();
    }

    public async runComparison() {
        if (this.comparing) return;
        this.comparing = true;
        this.hasComparison = false;
        this.errorMessage = '';
        await this.service.render();

        try {
            const simSymbol = this.getSimulationSymbol();
            if (!simSymbol) {
                this.errorMessage = 'Please select or enter a symbol';
                this.comparing = false;
                await this.service.render();
                return;
            }

            const { code, data } = await wiz.call("run_comparison", {
                symbol: simSymbol,
                start_date: this.startDate,
                end_date: this.endDate,
                investment: this.investment,
                division_count: this.divisionCount,
                target_profit: this.targetProfit,
                buy_commission_rate: this.buyCommissionRate,
                sell_commission_rate: this.sellCommissionRate,
                tax_rate: this.taxRate,
                allow_extension: this.allowExtension,
                crash_buy_enabled: this.crashBuyEnabled,
                crash_buy_drop_pct: this.crashBuyDropPct,
                crash_buy_ma_drop_pct: this.crashBuyMaDropPct,
                crash_buy_ratio: this.crashBuyRatio,
                crash_buy_max_per_cycle: this.crashBuyMaxPerCycle,
            });

            if (code === 200) {
                this.comparisonResult = data;
                this.hasComparison = true;
            } else {
                this.errorMessage = data?.message || 'Comparison failed';
            }
        } catch (e: any) {
            this.errorMessage = e?.message || 'Comparison error';
            console.error("Comparison error:", e);
        }

        this.comparing = false;
        await this.service.render();
    }

    public async toggleComparison() {
        this.showComparison = !this.showComparison;
        await this.service.render();
    }

    public get filteredTrades(): any[] {
        if (this.tradeFilter === 'ALL') return this.trades;
        return this.trades.filter(t => t.action === this.tradeFilter);
    }

    public async setTradeFilter(filter: string) {
        this.tradeFilter = filter;
        await this.service.render();
    }

    public profitClass(rate: number): string {
        if (rate > 0) return 'text-emerald-400';
        if (rate < 0) return 'text-red-400';
        return 'text-slate-400';
    }

    public formatUSD(value: number): string {
        if (value == null || isNaN(value)) return '0.00';
        return value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    public diffClass(a: number, b: number): string {
        if (a > b) return 'text-emerald-400';
        if (a < b) return 'text-red-400';
        return 'text-slate-400';
    }

    public strategyLabel(): string {
        if (!this.myStrategy) return '';
        const parts: string[] = [];
        if (this.myStrategy.sell_strategy === 'partial') {
            parts.push(`${this.t('set.strategy_partial')}: ${this.partialStrategySummary(this.myStrategy.partial_sell_stages)}`);
        } else {
            parts.push(this.t('sim.full_sell_result'));
        }
        if (this.myStrategy.crash_buy_enabled) {
            parts.push(`${this.t('set.crash_buy')}: -${this.myStrategy.crash_buy_drop_pct}%`);
        }
        return parts.join(' / ');
    }
}
