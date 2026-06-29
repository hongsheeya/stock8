import { OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';
import { i18n } from '@wiz/libs/portal/trading/i18n';

export class Component implements OnInit {
    // Tab: 'daytrade' | 'cycles' | 'logs'
    public tab: string = 'daytrade';
    public t = (key: string) => i18n.t(key);

    // Cycles
    public cycles: any[] = [];
    public cyclePage: number = 1;
    public cycleTotalPages: number = 1;
    public cycleFilter: string = '';  // ALL, ACTIVE, COMPLETED, HOLDING
    public cycleSymbolFilter: string = '';
    public symbols: string[] = [];

    // Cycle Detail
    public selectedCycle: any = null;
    public cycleTrades: any[] = [];

    // Daytrade
    public daytradeTrades: any[] = [];
    public daytradeSummary: any = {};
    public daytradePage: number = 1;
    public daytradeTotalPages: number = 1;
    public daytradeTotal: number = 0;
    public daytradeHasMore: boolean = false;
    public daytradeLoadingMore: boolean = false;
    public daytradeOlderSummary: any = {};
    public daytradeMarketFilter: string = '';
    public daytradeActionFilter: string = '';
    public daytradeSymbolFilter: string = '';
    public daytradeSearchText: string = '';

    // Trade Logs
    public logs: any[] = [];
    public logPage: number = 1;
    public logTotalPages: number = 1;
    public logTotal: number = 0;
    public logHasMore: boolean = false;
    public logLoadingMore: boolean = false;
    public logOlderSummary: any = {};
    public logSymbolFilter: string = '';
    public logActionFilter: string = '';  // BUY, SELL
    public logSearchText: string = '';
    public expandedLogIdx: Set<number> = new Set();

    public loading: boolean = false;
    public loadError: string = '';

    constructor(public service: Service) { }

    public async ngOnInit() {
        await this.service.init(this);
        await this.service.auth.allow("/access");
        await this.loadSymbols();
        await this.loadDaytradeTrades();
        await this.service.render();
    }

    public async switchTab(t: string) {
        this.tab = t;
        this.selectedCycle = null;
        if (t === 'daytrade') await this.loadDaytradeTrades();
        else if (t === 'cycles') await this.loadCycles();
        else if (t === 'logs') await this.loadLogs();
        await this.service.render();
    }

    // ─── Symbols ───
    private async loadSymbols() {
        this.loadError = '';
        try {
            const res = await wiz.call("symbols");
            if (res.code === 200) {
                this.symbols = Array.isArray(res.data) ? res.data : (res.data?.symbols || []);
            }
            else this.loadError = res.data?.message || '종목 목록을 불러오지 못했습니다.';
        } catch (e: any) {
            console.error('symbols load failed:', e);
            this.loadError = '종목 목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.';
        }
        await this.service.render();
    }

    // ─── Cycles ───
    public async loadCycles() {
        this.loading = true;
        await this.service.render();
        const res = await wiz.call("cycles", {
            page: this.cyclePage,
            status: this.cycleFilter,
            symbol: this.cycleSymbolFilter,
            sync: this.cyclePage === 1 ? 'true' : 'false',
        });
        if (res.code === 200) {
            this.cycles = res.data.rows || [];
            this.cycleTotalPages = res.data.total_pages || 1;
        }
        this.loading = false;
        await this.service.render();
    }

    public async filterCycles(status: string) {
        this.cycleFilter = status;
        this.cyclePage = 1;
        await this.loadCycles();
    }

    public async filterCycleSymbol(sym: string) {
        this.cycleSymbolFilter = sym;
        this.cyclePage = 1;
        await this.loadCycles();
    }

    public async goCyclePage(p: number) {
        if (p < 1 || p > this.cycleTotalPages) return;
        this.cyclePage = p;
        await this.loadCycles();
    }

    // ─── Cycle Detail ───
    public async viewCycleDetail(cycle: any) {
        this.loading = true;
        await this.service.render();
        const res = await wiz.call("cycle_detail", { cycle_id: cycle.id, sync: 'true' });
        if (res.code === 200) {
            this.selectedCycle = res.data.cycle;
            this.cycleTrades = res.data.trades || [];
        }
        this.loading = false;
        await this.service.render();
    }

    public async closeCycleDetail() {
        this.selectedCycle = null;
        await this.service.render();
    }

    // ─── Daytrade ───
    public async loadDaytradeTrades(append: boolean = false) {
        if (append) this.daytradeLoadingMore = true;
        else this.loading = true;
        await this.service.render();
        const res = await wiz.call("daytrade_trades", {
            page: this.daytradePage,
            market: this.daytradeMarketFilter,
            action: this.daytradeActionFilter,
            symbol: this.daytradeSymbolFilter,
            search: this.daytradeSearchText,
            sync_broker: this.daytradePage === 1 && !append ? 'true' : 'false',
            include_old: this.daytradePage > 3 ? 'true' : 'false',
        });
        if (res.code === 200) {
            const rows = res.data.rows || [];
            this.daytradeTrades = append ? this.daytradeTrades.concat(rows) : rows;
            this.daytradeSummary = res.data.summary || {};
            this.daytradeTotalPages = res.data.total_pages || 1;
            this.daytradeTotal = res.data.total || this.daytradeTrades.length;
            this.daytradeHasMore = res.data.has_more === true;
            this.daytradeOlderSummary = res.data.older_summary || {};
        }
        if (append) this.daytradeLoadingMore = false;
        else this.loading = false;
        await this.service.render();
    }

    public async filterDaytradeMarket(market: string) {
        this.daytradeMarketFilter = market;
        this.daytradePage = 1;
        await this.loadDaytradeTrades();
    }

    public async filterDaytradeAction(action: string) {
        this.daytradeActionFilter = action;
        this.daytradePage = 1;
        await this.loadDaytradeTrades();
    }

    public async filterDaytradeSymbol(symbol: string) {
        this.daytradeSymbolFilter = symbol;
        this.daytradePage = 1;
        await this.loadDaytradeTrades();
    }

    public async searchDaytradeTrades() {
        this.daytradePage = 1;
        await this.loadDaytradeTrades();
    }

    public async goDaytradePage(p: number) {
        if (p < 1 || p > this.daytradeTotalPages) return;
        this.daytradePage = p;
        await this.loadDaytradeTrades();
    }

    public async loadMoreDaytradeTrades() {
        if (!this.daytradeHasMore || this.daytradeLoadingMore) return;
        this.daytradePage += 1;
        await this.loadDaytradeTrades(true);
    }

    // ─── Delete Cycle ───
    public async deleteCycle(cycle: any) {
        const res = await this.service.modal.show({
            title: this.t('cycle.delete_title'),
            message: `${cycle.symbol} #${cycle.id?.substring(0, 8)} - ${this.t('cycle.delete_confirm')}`,
            action: this.t('cycle.delete_btn'),
            actionBtn: 'bg-red-500/80 hover:bg-red-500',
        });
        if (!res) return;
        this.loading = true;
        await this.service.render();
        const { code, data } = await wiz.call("delete_cycle", { cycle_id: cycle.id });
        this.loading = false;
        if (code === 200) {
            await this.loadCycles();
        } else {
            await this.service.modal.show({
                title: 'Error',
                message: data?.message || 'Failed to delete cycle',
                action: '확인',
            });
            await this.service.render();
        }
    }

    // ─── Trade Logs ───
    public async loadLogs(append: boolean = false) {
        if (append) this.logLoadingMore = true;
        else this.loading = true;
        await this.service.render();
        const res = await wiz.call("trade_logs", {
            page: this.logPage,
            symbol: this.logSymbolFilter,
            action: this.logActionFilter,
            search: this.logSearchText,
            sync_broker: this.logPage === 1 && !append ? 'true' : 'false',
            include_old: this.logPage > 3 ? 'true' : 'false',
        });
        if (res.code === 200) {
            const rows = res.data.rows || [];
            this.logs = append ? this.logs.concat(rows) : rows;
            this.logTotalPages = res.data.total_pages || 1;
            this.logTotal = res.data.total || this.logs.length;
            this.logHasMore = res.data.has_more === true;
            this.logOlderSummary = res.data.older_summary || {};
        }
        this.expandedLogIdx.clear();
        if (append) this.logLoadingMore = false;
        else this.loading = false;
        await this.service.render();
    }

    public async filterLogSymbol(sym: string) {
        this.logSymbolFilter = sym;
        this.logPage = 1;
        await this.loadLogs();
    }

    public async filterLogAction(action: string) {
        this.logActionFilter = action;
        this.logPage = 1;
        await this.loadLogs();
    }

    public async searchLogs() {
        this.logPage = 1;
        await this.loadLogs();
    }

    public async goLogPage(p: number) {
        if (p < 1 || p > this.logTotalPages) return;
        this.logPage = p;
        await this.loadLogs();
    }

    public async loadMoreLogs() {
        if (!this.logHasMore || this.logLoadingMore) return;
        this.logPage += 1;
        await this.loadLogs(true);
    }

    public async toggleLogExpand(i: number) {
        if (this.expandedLogIdx.has(i)) this.expandedLogIdx.delete(i);
        else this.expandedLogIdx.add(i);
        await this.service.render();
    }

    // ─── Utils ───
    public formatUSD(val: any): string {
        const n = parseFloat(val) || 0;
        return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    public formatKRW(val: any): string {
        const n = Math.round(parseFloat(val) || 0);
        return '₩' + n.toLocaleString('ko-KR');
    }

    public formatMarketMoney(val: any, market: string = 'KS'): string {
        return (market || '').toUpperCase() === 'US' ? this.formatUSD(val) : this.formatKRW(val);
    }

    public hasRealizedValue(val: any): boolean {
        if (val === null || val === undefined || val === '') return false;
        return !Number.isNaN(Number(val));
    }

    public profitClass(rate: any): string {
        const r = parseFloat(rate) || 0;
        if (r > 0) return 'bn-up';
        if (r < 0) return 'bn-down';
        return 'bn-muted-text';
    }

    public statusBadge(status: string): string {
        const s = (status || '').toUpperCase();
        switch (s) {
            case 'ACTIVE': return 'bn-chip state-active';
            case 'HOLDING': return 'bn-chip state-holding';
            case 'COMPLETED': return 'bn-chip state-completed';
            case 'IDLE': return 'bn-chip state-idle';
            default: return 'bn-chip state-idle';
        }
    }

    public actionBadge(action: string): string {
        const a = (action || '').toUpperCase();
        if (a.startsWith('BUY')) return 'bn-chip action-buy';
        if (a.startsWith('SELL')) return 'bn-chip action-sell';
        if (a === 'SKIP') return 'bn-chip action-muted';
        return 'bn-chip action-muted';
    }

    public marketBadge(market: string): string {
        const m = (market || '').toUpperCase();
        if (m === 'US') return 'bn-chip market-us';
        return 'bn-chip market-ks';
    }

    public actionLabel(action: string, detail: string = ''): string {
        const d = (detail || action || '').toUpperCase();
        if (d === 'BUY1') return '1차 매수';
        if (d === 'BUY2') return '2차 매수';
        if (d.includes('RESERVED')) return '예약매수';
        if (d.includes('PARTIAL')) return '부분매도';
        if (d.includes('BUY')) return '매수';
        if (d.includes('SELL')) return '매도';
        return d || '-';
    }

    public eventBadge(eventType: string): string {
        const e = (eventType || '').toLowerCase();
        if (e.includes('buy')) return 'bn-chip action-buy';
        if (e.includes('sell')) return 'bn-chip action-sell';
        if (e.includes('error')) return 'bn-chip action-error';
        if (e.includes('cycle')) return 'bn-chip state-active';
        return 'bn-chip action-muted';
    }

    public cycleProgress(cycle: any): number {
        const current = parseInt(cycle.current_round) || 0;
        const total = parseInt(cycle.division_count) || 40;
        return Math.round((current / total) * 100);
    }

    public pageArray(total: number): number[] {
        return Array.from({ length: total }, (_, i) => i + 1);
    }

    public tabClass(t: string): string {
        if (this.tab === t) {
            return "bn-tab is-active";
        }
        return "bn-tab";
    }
}
