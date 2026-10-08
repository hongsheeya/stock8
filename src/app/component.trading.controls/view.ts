import { Input, OnInit, OnDestroy } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';

export class Component implements OnInit, OnDestroy {
    @Input() public positions: any[] = [];
    @Input() public daytradeOnly = false;
    @Input() public market: 'KS' | 'US' | '' = '';
    @Input() public showLocks = false;
    @Input() public locksOnly = false;
    public state: any = null;
    public get showDaytrade(): boolean {
        return this.state?.daytrade_allowed === true && window.localStorage.getItem('admin_preview_user_mode') !== 'true';
    }
    public busy = false;
    public get locWorkerSummary(): string {
        if (!this.state?.infinite_buy) return '자동 예약 OFF';
        if (this.state?.dispatcher_failed) return '예약 워커 시작 실패 — 서버 점검 필요';
        const worker = this.state?.workers?.loc;
        if (!worker) return '예약 워커 미등록 — ON 설정과 실행 상태가 다릅니다';
        const labels: any = {checking: '점검 중', waiting: '대기', off: 'OFF', error: '오류', starting: '시작 중'};
        return `예약 워커 ${labels[worker.status] || worker.status || '확인 중'} · ${worker.message || ''} · 최근 점검 ${worker.last_check || '없음'}${worker.error ? ' · ' + worker.error : ''}`;
    }
    public error = '';
    public symbol = '';
    public pending: any = null;
    public acknowledged = false;
    public brokerPositions: any[] = [];
    public holdingsMessage = '';
    public holdingsBusy = false;
    public holdingSearch = '';
    public workerSummary(job: string): string {
        if (this.state?.dispatcher_failed) return '실행기 오류 · 자동매매 가동 확인 불가';
        const worker = this.state?.workers?.[job];
        if (!worker) return '실행 확인 필요';
        if (worker.last_check && Date.now() - new Date(worker.last_check).getTime() > 120000) {
            return '점검 지연 · 마지막 완료 ' + String(worker.last_check).slice(11, 19);
        }
        const names: any = {checking: '점검 중', waiting: '다음 점검 대기', off: '중지', error: '오류 · 점검 필요', starting: '시작 중', account_changed: '계좌 변경으로 중지'};
        const stamp = worker.last_check ? String(worker.last_check).slice(11, 19) : '완료 기록 없음';
        return `${names[worker.status] || '상태 확인 필요'} · 마지막 완료 ${stamp}`;
    }
    public symbolName(symbol: string): string {
        const rows = [...this.brokerPositions, ...(this.positions || [])];
        for (const row of rows) {
            const code = String(row.symbol || row.code || '').trim().toUpperCase();
            const name = String(row.name || row.stock_name || row.prdt_name || row.ovrs_item_name || '').trim();
            if (code === symbol && name && name.toUpperCase() !== symbol) return name;
        }
        return '종목명 확인 필요';
    }
    public get visibleSymbols(): string[] {
        const query = this.holdingSearch.trim().toLocaleLowerCase();
        return this.symbols.filter(symbol => !query || `${symbol} ${this.symbolName(symbol)}`.toLocaleLowerCase().includes(query));
    }
    private timer: any;
    constructor(public service: Service) {}
    public async ngOnInit() {
        await this.service.init(this);
        await this.refresh();
        if (this.showLocks && this.state?.mode === 'LIVE') void this.loadHoldings();
        this.timer = setInterval(() => { if (!this.busy && !this.pending) void this.refresh(); }, 30000);
    }
    public ngOnDestroy() { if (this.timer) clearInterval(this.timer); }
    public async refresh() {
        this.error = '';
        try {
            const res = await wiz.call('status', {}, {timeout: 8000});
            if (res.code !== 200) throw new Error(res.data?.message || '자동매매 권한 조회 실패. 다시 확인해주세요.');
            this.state = res.data;
        } catch (e: any) {
            this.state = null;
            this.error = e?.message || '자동매매 권한 조회 지연. 다시 확인해주세요.';
        }
        await this.service.render();
    }
    public get symbols(): string[] {
        return Array.from(new Set([
            ...[...(this.positions || []), ...this.brokerPositions]
                .filter(p => Number(p.position_qty ?? p.qty ?? p.quantity ?? 0) > 0)
                .filter(p => {
                    const code = String(p.symbol || p.code || '').trim().toUpperCase();
                    const domestic = ['KS', 'KQ', 'KRX', 'NXT'].includes(String(p.market || '').toUpperCase()) || /^[0-9][A-Z0-9]{5}$/.test(code);
                    return code !== 'SOXL' && (!this.market || (this.market === 'KS' ? domestic : !domestic));
                })
                .map(p => String(p.symbol || p.code || '').trim().toUpperCase())
        ].filter(Boolean)));
    }
    public locked(symbol: string): boolean {
        return (this.state?.symbols?.[symbol] ?? this.state?.default_locked) !== false;
    }
    public async loadHoldings() {
        if (this.holdingsBusy) return;
        this.holdingsBusy = true;
        try {
            const res = await wiz.call('holdings', {}, {timeout: 12000});
            if (res.code !== 200) throw new Error('보유 종목을 확인하지 못했습니다.');
            this.brokerPositions = res.data?.holdings || [];
            this.holdingsMessage = res.data?.message || '';
        } catch (_) { this.holdingsMessage = '보유 조회 지연. 기존 잠금은 유지되며 빈 잔고로 판단하지 않습니다.'; }
        finally { this.holdingsBusy = false; await this.service.render(); }
    }
    public async toggle(lane: string) {
        if (!this.state || this.busy) return;
        const data = {lane, enabled: !this.state[lane]};
        if (data.enabled) await this.warn(data);
        else await this.save(data);
    }
    public async lock(symbol: string, locked: boolean) {
        symbol = symbol.trim().toUpperCase();
        if (!symbol || this.busy || !this.state) return;
        if (!locked) await this.warn({symbol, locked});
        else await this.save({symbol, locked});
    }
    public async warn(data: any) {
        this.pending = data;
        this.acknowledged = false;
        await this.service.render();
    }
    public async confirm() {
        if (!this.pending || !this.acknowledged || this.busy) return;
        await this.save({...this.pending, confirmation: this.state.warning_version});
    }
    public async cancel() { this.pending = null; await this.service.render(); }
    private async save(data: any) {
        this.busy = true;
        this.error = '';
        await this.service.render();
        try {
            const res = await wiz.call('save', data, {timeout: 10000});
            if (res.code !== 200) throw new Error(res.data?.message || '저장 결과를 확인하지 못했습니다. 다시 조회하세요.');
            this.state = res.data; this.pending = null; this.symbol = '';
        } catch (_) {
            this.state = null;
            this.pending = null;
            this.error = '저장 결과 확인 실패. 적용 여부를 다시 조회한 뒤 조작해주세요.';
        } finally {
            this.busy = false;
            await this.service.render();
        }
    }
}
