import { OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';
import { i18n } from '@wiz/libs/portal/trading/i18n';

const PAGE = 20;

export class Component implements OnInit {
    // Tab: 'performance' | 'fills' | 'cycles' | 'logs'
    public tab: string = 'cycles';
    public get showDaytrade(): boolean {
        const user: any = this.service?.auth?.session || {};
        return (String(user.role || user.user?.role || '').toLowerCase() === 'admin'
            || String(user.email || user.user?.email || '').toLowerCase() === 'gigukbyun@gmail.com')
            && window.localStorage.getItem('admin_preview_user_mode') !== 'true';
    }
    public t = (key: string) => i18n.t(key);

    public readonly periods = [
        { id: '1D', label: '오늘' }, { id: '1W', label: '7일' }, { id: '1M', label: '30일' },
        { id: '3M', label: '90일' }, { id: 'ALL', label: '전체' },
    ];
    public readonly markets = [{ id: '', label: '전체' }, { id: 'KS', label: '국장' }, { id: 'US', label: '미장' }];
    public readonly logKinds = [{ id: '', label: '주문·체결' }, { id: 'error', label: '오류' }, { id: 'all', label: '시스템 포함' }];

    // Trades (performance + fills share one payload)
    public period: string = '1M';
    public market: string = '';
    public strategy: string = '';
    public data: any = { summary: {}, strategies: [], daily: [], trips: [], fills: [], strategy_options: [] };
    public tripSearch: string = '';
    public tripLimit: number = PAGE;
    public fillSearch: string = '';
    public fillLimit: number = PAGE;
    public tradesLoaded: boolean = false;

    // Cycles
    public cycles: any[] = [];
    public cyclePage: number = 1;
    public cycleTotalPages: number = 1;
    public cycleFilter: string = '';
    public cycleSymbolFilter: string = '';
    public symbols: string[] = [];
    public selectedCycle: any = null;
    public cycleTrades: any[] = [];

    // Logs
    public logs: any[] = [];
    public logPage: number = 1;
    public logTotal: number = 0;
    public logHasMore: boolean = false;
    public logKind: string = '';
    public logSymbolFilter: string = '';
    public logSearchText: string = '';
    public expandedLog: string = '';

    public loading: boolean = false;
    public loadingMore: boolean = false;
    public loadError: string = '';
    public updatedAt: string = '';

    constructor(public service: Service) { }

    public async ngOnInit() {
        await this.service.init(this);
        await this.service.auth.allow("/access");
        if (this.showDaytrade) this.tab = 'performance';
        await Promise.all([this.loadSymbols(), this.loadTab()]);
    }

    public async switchTab(tab: string) {
        if ((tab === 'performance' || tab === 'fills') && !this.showDaytrade) return;
        this.tab = tab;
        this.selectedCycle = null;
        await this.loadTab();
    }

    private async loadTab(force: boolean = false) {
        if (this.tab === 'performance' || this.tab === 'fills') {
            if (force || !this.tradesLoaded) await this.loadTrades();
            else await this.service.render();
        } else if (this.tab === 'cycles') await this.loadCycles();
        else await this.loadLogs();
    }

    public async refresh() {
        await this.loadTab(true);
    }

    private stamp() {
        const now = new Date();
        this.updatedAt = now.toTimeString().slice(0, 8);
    }

    // ─── Trades ───
    public async loadTrades() {
        this.loading = true;
        this.loadError = '';
        await this.service.render();
        try {
            const res = await wiz.call("trades", { period: this.period, market: this.market, strategy: this.strategy });
            if (res.code === 200) {
                this.data = res.data || {};
                this.tradesLoaded = true;
                this.tripLimit = PAGE;
                this.fillLimit = PAGE;
                this.stamp();
            } else {
                this.loadError = res.data?.message || '거래이력을 불러오지 못했습니다.';
            }
        } catch (e: any) {
            console.error('trades load failed:', e);
            this.loadError = '거래이력을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.';
        }
        this.loading = false;
        await this.service.render();
    }

    public async setPeriod(period: string) {
        if (this.period === period) return;
        this.period = period;
        await this.loadTrades();
    }

    public async setMarket(market: string) {
        if (this.market === market) return;
        this.market = market;
        await this.loadTrades();
    }

    public async setStrategy(strategy: string) {
        this.strategy = this.strategy === strategy ? '' : strategy;
        await this.loadTrades();
    }

    public get summaryMarkets(): string[] {
        return ['KS', 'US'].filter((m) => this.data?.summary?.[m]);
    }

    private matches(row: any, text: string): boolean {
        const q = (text || '').trim().toLowerCase();
        if (!q) return true;
        return `${row.symbol} ${row.name} ${row.strategy_label} ${row.reason || ''}`.toLowerCase().includes(q);
    }

    public get filteredTrips(): any[] {
        return (this.data?.trips || []).filter((row: any) => this.matches(row, this.tripSearch));
    }

    public get visibleTrips(): any[] {
        return this.filteredTrips.slice(0, this.tripLimit);
    }

    public get filteredFills(): any[] {
        return (this.data?.fills || []).filter((row: any) => this.matches(row, this.fillSearch));
    }

    public get visibleFills(): any[] {
        return this.filteredFills.slice(0, this.fillLimit);
    }

    public async moreTrips() {
        this.tripLimit += PAGE;
        await this.service.render();
    }

    public async moreFills() {
        this.fillLimit += PAGE;
        await this.service.render();
    }

    // Daily bars: one scale per market (KRW and USD never share an axis).
    public dailyBars(market: string): any[] {
        const days = (this.data?.daily || []).filter((d: any) => Math.abs(Number(d[market]) || 0) > 0);
        const max = Math.max(1, ...days.map((d: any) => Math.abs(Number(d[market]) || 0)));
        return days.map((d: any) => {
            const value = Number(d[market]) || 0;
            return { date: d.date, value, height: Math.max(4, Math.round(Math.abs(value) / max * 100)), up: value >= 0 };
        });
    }

    public get dailyMarkets(): string[] {
        return ['KS', 'US'].filter((m) => (!this.market || this.market === m) && this.dailyBars(m).length > 0);
    }

    // ─── Cycles ───
    private async loadSymbols() {
        try {
            const res = await wiz.call("symbols");
            if (res.code === 200) this.symbols = Array.isArray(res.data) ? res.data : (res.data?.symbols || []);
        } catch (e: any) {
            console.error('symbols load failed:', e);
        }
        await this.service.render();
    }

    public async loadCycles() {
        this.loading = true;
        await this.service.render();
        try {
            const res = await wiz.call("cycles", { page: this.cyclePage, status: this.cycleFilter, symbol: this.cycleSymbolFilter });
            if (res.code === 200) {
                this.cycles = res.data.rows || [];
                this.cycleTotalPages = res.data.total_pages || 1;
                this.stamp();
            }
        } catch (e: any) {
            console.error('cycles load failed:', e);
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

    public async viewCycleDetail(cycle: any) {
        this.loading = true;
        await this.service.render();
        const res = await wiz.call("cycle_detail", { cycle_id: cycle.id });
        if (res.code === 200) {
            this.selectedCycle = { ...res.data.cycle, realized: cycle.realized, days: cycle.days };
            this.cycleTrades = res.data.trades || [];
        }
        this.loading = false;
        await this.service.render();
    }

    public async closeCycleDetail() {
        this.selectedCycle = null;
        await this.service.render();
    }

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
            await this.service.modal.show({ title: 'Error', message: data?.message || 'Failed to delete cycle', action: '확인' });
            await this.service.render();
        }
    }

    public cycleProgress(cycle: any): number {
        const current = parseInt(cycle.current_round) || 0;
        const total = parseInt(cycle.division_count) || 40;
        return Math.min(100, Math.round((current / total) * 100));
    }

    public cycleStatusLabel(status: string): string {
        const s = (status || '').toUpperCase();
        return ({ ACTIVE: '진행 중', HOLDING: '보유 중', COMPLETED: '완료', PAUSED: '일시정지', IDLE: '대기' } as any)[s] || s || '-';
    }

    public pageArray(total: number): number[] {
        return Array.from({ length: total }, (_, i) => i + 1);
    }

    // ─── Logs ───
    public async loadLogs(append: boolean = false) {
        if (append) this.loadingMore = true;
        else {
            this.loading = true;
            this.logPage = 1;
        }
        await this.service.render();
        try {
            const res = await wiz.call("trade_logs", {
                page: this.logPage, kind: this.logKind, symbol: this.logSymbolFilter, search: this.logSearchText,
            });
            if (res.code === 200) {
                const rows = res.data.rows || [];
                this.logs = append ? this.logs.concat(rows) : rows;
                this.logTotal = res.data.total || this.logs.length;
                this.logHasMore = res.data.has_more === true;
                this.loadError = '';
                this.stamp();
            } else {
                this.loadError = res.data?.message || '로그를 불러오지 못했습니다.';
            }
        } catch (e: any) {
            console.error('logs load failed:', e);
            this.loadError = '로그를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.';
        }
        this.loading = false;
        this.loadingMore = false;
        await this.service.render();
    }

    public async setLogKind(kind: string) {
        if (this.logKind === kind) return;
        this.logKind = kind;
        await this.loadLogs();
    }

    public async filterLogSymbol(sym: string) {
        this.logSymbolFilter = sym;
        await this.loadLogs();
    }

    public async searchLogs() {
        await this.loadLogs();
    }

    public async moreLogs() {
        if (!this.logHasMore || this.loadingMore) return;
        this.logPage += 1;
        await this.loadLogs(true);
    }

    public async toggleLog(row: any) {
        this.expandedLog = this.expandedLog === row.id ? '' : row.id;
        await this.service.render();
    }

    // ─── Format ───
    public money(value: any, market: string = 'KS', signed: boolean = false): string {
        if (value === null || value === undefined || value === '') return '-';
        const n = Number(value) || 0;
        const sign = signed && n > 0 ? '+' : (n < 0 ? '-' : '');
        const abs = Math.abs(n);
        if ((market || '').toUpperCase() === 'US') {
            return `${sign}$${abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        }
        return `${sign}₩${Math.round(abs).toLocaleString('ko-KR')}`;
    }

    public price(value: any, market: string = 'KS'): string {
        const n = Number(value) || 0;
        if (n <= 0) return '-';
        if ((market || '').toUpperCase() === 'US') return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        return '₩' + Math.round(n).toLocaleString('ko-KR');
    }

    public pct(value: any, signed: boolean = true): string {
        if (value === null || value === undefined || value === '') return '-';
        const n = Number(value) || 0;
        return `${signed && n > 0 ? '+' : ''}${n.toFixed(2)}%`;
    }

    public tone(value: any): string {
        const n = Number(value) || 0;
        if (n > 0) return 'up';
        if (n < 0) return 'down';
        return 'flat';
    }

    public hold(minutes: any): string {
        if (minutes === null || minutes === undefined) return '-';
        const m = Number(minutes) || 0;
        if (m < 60) return `${m}분`;
        if (m < 1440) return `${Math.floor(m / 60)}시간 ${m % 60 ? (m % 60) + '분' : ''}`.trim();
        const days = m / 1440;
        return `${days >= 10 ? Math.round(days) : days.toFixed(1)}일`;
    }

    public when(ts: string): string {
        const text = String(ts || '');
        if (!text) return '-';
        const today = new Date();
        const ymd = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
        return text.startsWith(ymd) ? text.slice(11, 16) : text.slice(5, 16);
    }

    public marketLabel(market: string): string {
        return (market || '').toUpperCase() === 'US' ? '미장' : '국장';
    }

    public get periodLabel(): string {
        return (this.periods.find((p) => p.id === this.period) || this.periods[2]).label;
    }

    public get strategyLabel(): string {
        const found = (this.data?.strategy_options || []).find((s: any) => s.id === this.strategy);
        return found ? found.label : '';
    }
}
