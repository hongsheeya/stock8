/// <reference path="../../types/wiz-modules.d.ts" />

import { OnDestroy, OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';

// WIZ renames the component class at build time; keep lookups at module level.
const MODE_LABEL: any = { off: '꺼짐', shadow: '모의 운용', live: '실거래' };
const EVENT_LABEL: any = {
    COIN_SHADOW_BUY: '모의 매수', COIN_SHADOW_SELL: '모의 매도', COIN_BUY: '매수', COIN_SELL: '매도',
    COIN_BUY_SKIPPED: '매수 보류', COIN_BUY_ERROR: '매수 실패', COIN_SELL_ERROR: '매도 실패',
    COIN_ORDER_CANCELLED: '주문 취소', COIN_EXTERNAL_SELL: '직접 매도 감지', COIN_HALT: '진입 중단', COIN_RESUME: '진입 재개', COIN_SKIP_BELOW_STOP: '진입 건너뜀',
};
const COMPARE_LABEL: any = {
    match: '일치', pending: '확인 중', exit_differs: '청산 시각 다름', replay_only: '모의에서 놓침', shadow_only: '모의에만 있음',
};
const COIN_NAME: any = { 'KRW-BTC': '비트코인', 'KRW-ETH': '이더리움', 'KRW-XRP': '리플', 'KRW-SOL': '솔라나', 'KRW-DOGE': '도지코인' };

export class Component implements OnInit, OnDestroy {
    public loading: boolean = true;
    public data: any = null;
    public errorMessage: string = '';
    public notice: string = '';
    public busy: string = '';
    public refreshing: boolean = false;
    private timer: any = null;

    public form: any = { seed_krw: 1000000, max_order_krw: 0, markets: {} };
    public keyForm: any = { access_key: '', secret_key: '' };
    public alertForm: any = { webhook: '', hc_url: '', notify_shadow: true };
    public liveConfirm: string = '';
    public showLiveConfirm: boolean = false;
    public showResearch: boolean = false;

    constructor(public service: Service) { }

    public async ngOnInit() {
        await this.service.init(this);
        await this.service.auth.allow('/access');
        await this.load(true);
        this.loading = false;
        await this.service.render();
        this.timer = window.setInterval(() => void this.load(false), 10000);
    }

    public ngOnDestroy() {
        if (this.timer) window.clearInterval(this.timer);
        this.timer = null;
    }

    private async api(name: string, params: any = {}): Promise<{ code: number; data: any }> {
        return await (wiz.call(name, params) as Promise<{ code: number; data: any }>);
    }

    public async load(syncForm: boolean) {
        if (this.refreshing) return;
        this.refreshing = true;
        try {
            const { code, data } = await this.api('status');
            if (code === 200) {
                this.data = data;
                if (syncForm) this.syncForm();
            } else if (!this.data) {
                this.errorMessage = data?.message || '코인 화면을 불러오지 못했습니다.';
            }
        } catch (e) {
            if (!this.data) this.errorMessage = '코인 화면을 불러오지 못했습니다.';
        }
        this.refreshing = false;
        await this.service.render();
    }

    private syncForm() {
        const p = this.data?.policy || {};
        const chosen: any = {};
        for (const m of this.data?.all_markets || []) chosen[m] = (p.markets || []).includes(m);
        this.form = { seed_krw: p.seed_krw || 1000000, max_order_krw: p.max_order_krw || 0, markets: chosen };
        this.alertForm = { webhook: '', hc_url: '', notify_shadow: this.data?.alerts?.notify_shadow !== false };
    }

    private async run(name: string, params: any, label: string, success: string) {
        if (this.busy) return null;
        this.busy = label;
        this.errorMessage = '';
        this.notice = '';
        await this.service.render();
        let result: any = null;
        try {
            const { code, data } = await this.api(name, params);
            if (code === 200) {
                this.notice = success;
                result = data || {};
            } else {
                this.errorMessage = data?.message || '요청을 처리하지 못했습니다.';
            }
        } catch (e) {
            this.errorMessage = '요청을 처리하지 못했습니다.';
        }
        this.busy = '';
        await this.load(true);
        return result;
    }

    // ---- actions
    public async saveKeys() {
        const r = await this.run('save_keys', { ...this.keyForm }, 'keys', '업비트 키를 암호화해서 저장했습니다. 연결 테스트를 해주세요.');
        if (r) {
            this.keyForm = { access_key: '', secret_key: '' };
            if (r.mode_reset) this.notice = '키가 바뀌어 실거래를 껐습니다. 연결 테스트 후 다시 승인해주세요.';
        }
    }

    public async deleteKeys() {
        const ok = await this.service.modal.show({
            title: '업비트 키 삭제', message: '저장된 업비트 키를 지웁니다. 실거래 중이면 꺼집니다.',
            action: '삭제', cancel: '취소', status: 'warning', actionBtn: 'warning',
        });
        if (ok === true) await this.run('delete_keys', {}, 'keys', '업비트 키를 삭제했습니다.');
    }

    public async testConnection() {
        await this.run('test_connection', {}, 'test', '연결 성공: 잔고를 읽었습니다.');
    }

    public async saveSettings() {
        const markets = Object.keys(this.form.markets).filter((m) => this.form.markets[m]);
        await this.run('save_settings', {
            seed_krw: this.form.seed_krw, max_order_krw: this.form.max_order_krw || 0, markets: markets.join(','),
        }, 'settings', '운용 설정을 저장했습니다.');
    }

    public async setMode(mode: string) {
        if (mode === this.mode) return;
        if (mode === 'live') {
            this.showLiveConfirm = true;
            this.liveConfirm = '';
            await this.service.render();
            return;
        }
        if (this.mode === 'live' && this.liveOpenPositions.length) {
            const ok = await this.service.modal.show({
                title: '실거래 끄기',
                message: `실거래로 보유 중인 ${this.liveOpenPositions.join(', ')}의 자동 손절 관리가 멈춥니다. 보유 코인은 그대로 남습니다.`,
                action: '그래도 끄기', cancel: '취소', status: 'warning', actionBtn: 'warning',
            });
            if (ok !== true) return;
        }
        await this.run('set_mode', { mode }, 'mode', `모드를 '${MODE_LABEL[mode]}'(으)로 바꿨습니다.`);
    }

    public async confirmLive() {
        const r = await this.run('set_mode', { mode: 'live', confirm: this.liveConfirm }, 'mode', '실거래를 시작했습니다. 다음 4시간봉 마감부터 주문합니다.');
        if (r) this.showLiveConfirm = false;
    }

    public async saveAlerts() {
        await this.run('save_alerts', { ...this.alertForm }, 'alerts', '알림 설정을 저장했습니다. 테스트를 보내 확인해 보세요.');
    }

    public async testAlerts() {
        await this.run('test_alerts', {}, 'alert-test', '테스트 알림을 보냈습니다. 디스코드를 확인하세요.');
    }

    public async clearAlerts() {
        const ok = await this.service.modal.show({
            title: '알림 설정 삭제', message: '디스코드 웹훅과 PC 꺼짐 감시 주소를 지웁니다. healthchecks.io 쪽 체크는 직접 지워야 경고가 멈춥니다.',
            action: '삭제', cancel: '취소', status: 'warning', actionBtn: 'warning',
        });
        if (ok === true) await this.run('save_alerts', { clear: 'webhook,hc', notify_shadow: this.alertForm.notify_shadow }, 'alerts', '알림 설정을 지웠습니다.');
    }

    public async resume() {
        await this.run('resume', {}, 'resume', '신규 진입을 다시 허용했습니다.');
    }

    // ---- view helpers
    public get mode(): string { return this.data?.policy?.mode || 'off'; }
    public get modeLabel(): string { return MODE_LABEL[this.mode] || this.mode; }
    public get engine(): any { return this.data?.engine || {}; }
    public get sleeves(): any[] { return this.engine?.sleeves || []; }
    public get activeLedger(): any { return (this.data?.ledgers || {})[this.mode] || null; }
    public get liveOpenPositions(): string[] { return this.data?.ledgers?.live?.open_positions || []; }
    public get keysConfigured(): boolean { return !!this.data?.keys?.configured; }
    public get workerStatus(): string {
        const w = this.data?.worker || {};
        if (!this.data?.available) return '';
        if (w.hard_locked) return '이 서버는 코인 실행이 잠겨 있습니다';
        if (w.status === 'locked_elsewhere') return '다른 실투자 프로세스가 이미 코인을 실행 중입니다';
        if (w.status === 'error') return `실행 오류: ${w.error || ''}`;
        if (this.mode !== 'off' && w.alive === false) return '코인 작업이 멈춰 있습니다 (서버 재시작 필요)';
        return '';
    }

    public get progress(): any { return this.data?.shadow_progress || null; }
    public get feedLabel(): string {
        const f = this.engine?.feed || '';
        if (f === 'websocket') return '실시간 체결 (웹소켓)';
        if (f === 'websocket+rest') return '웹소켓 + 3초 조회 보완';
        if (f === 'rest') return '3초 조회 (웹소켓 재연결 중)';
        return '보유 코인 없음 · 대기';
    }
    public gatePct(g: any): number {
        const v = Number(g?.value || 0), t = Number(g?.target || 1);
        return Math.max(0, Math.min(100, (v / t) * 100));
    }
    public compareLabel(s: string): string { return COMPARE_LABEL[s] || s; }
    public slipPct(): number {
        // full bar = within the gate; over the gate shows full in the warning tone
        const v = this.progress?.slippage_median_pct;
        if (v === null || v === undefined) return 0;
        return 100;
    }
    public missedLabel(): string { return (this.progress?.missed_bars || []).slice(-3).map((t: number) => this.kst(t)).join(', '); }
    public kstDate(sec: any): string {
        const n = Number(sec || 0);
        if (!n) return '-';
        return new Date(n * 1000).toLocaleDateString('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric' });
    }


    // ---- past performance chart
    public showHistory: boolean = false;
    public history: any = null;
    public hoverIdx: number = -1;
    public chart: any = { w: 760, h: 300, r: 70, b: 24, yTicks: [], xTicks: [], pathA: '', pathB: '', px: [], pyA: [], pyB: [], endA: {}, endB: {} };
    public bars: any = { zero: 110, items: [] };

    public async toggleHistory() {
        this.showHistory = !this.showHistory;
        if (this.showHistory && !this.history) {
            try {
                const { code, data } = await this.api('history');
                if (code === 200) {
                    this.history = data.history;
                    this.buildHistory();
                }
            } catch (e) { /* the card shows the loading line */ }
        }
        await this.service.render();
    }

    private buildHistory() {
        const d = this.history?.daily || [];
        const W = 760, H = 300, L = 48, R = 70, T = 12, B = 24;
        const vals = d.flatMap((r: any) => [r[1], r[2]]).filter((v: number) => v > 0);
        const lo = Math.log(Math.min(...vals) * 0.95), hi = Math.log(Math.max(...vals) * 1.05);
        const y = (v: number) => T + (1 - (Math.log(Math.max(v, 1e-6)) - lo) / (hi - lo)) * (H - T - B);
        const x = (i: number) => L + (i / Math.max(1, d.length - 1)) * (W - L - R);
        const px: number[] = [], pyA: number[] = [], pyB: number[] = [];
        let pathA = '', pathB = '';
        d.forEach((r: any, i: number) => {
            const xi = x(i), ya = y(r[1]), yb = y(r[2]);
            px.push(xi); pyA.push(ya); pyB.push(yb);
            pathA += (i ? 'L' : 'M') + xi.toFixed(1) + ' ' + ya.toFixed(1);
            pathB += (i ? 'L' : 'M') + xi.toFixed(1) + ' ' + yb.toFixed(1);
        });
        const yTicks = [0.5, 1, 2, 4, 8, 16].filter((m) => Math.log(m) >= lo && Math.log(m) <= hi)
            .map((m) => ({ y: y(m), label: (m >= 1 ? '+' : '') + Math.round((m - 1) * 100) + '%' }));
        const xTicks: any[] = [];
        d.forEach((r: any, i: number) => {
            if (i && r[0].slice(0, 4) !== d[i - 1][0].slice(0, 4)) xTicks.push({ x: x(i), label: r[0].slice(0, 4) });
        });
        const last = d[d.length - 1] || [0, 1, 1];
        let endA = { y: y(last[1]), label: this.fmtIndex(last[1]) }, endB = { y: y(last[2]), label: this.fmtIndex(last[2]) };
        if (Math.abs(endA.y - endB.y) < 14) endA = { ...endA, y: endA.y + (endA.y >= endB.y ? 7 : -7) };
        this.chart = { w: W, h: H, r: R, b: B, yTicks, xTicks, pathA, pathB, px, pyA, pyB, endA, endB };

        const years = this.history?.years || [];
        const top = 18, bottom = 196;
        const pos = Math.max(...years.flatMap((v: any) => [v.strategy, v.buy_hold, 0]));
        const neg = Math.min(...years.flatMap((v: any) => [v.strategy, v.buy_hold, 0]));
        const scale = (bottom - top) / Math.max(1, pos - neg);
        const zero = top + pos * scale;
        const slot = (712) / Math.max(1, years.length);
        const bar = (v: number) => ({ v, y: v >= 0 ? zero - v * scale : zero, h: Math.max(1, Math.abs(v) * scale) });
        this.bars = { zero, items: years.map((v: any, i: number) => ({ year: v.year, partial: v.partial, x: 40 + i * slot + (slot - 54) / 2, a: bar(v.strategy), b: bar(v.buy_hold) })) };
    }

    public onHistMove(evt: MouseEvent) {
        const el = evt.currentTarget as HTMLElement;
        const rect = el.getBoundingClientRect();
        const xv = ((evt.clientX - rect.left) / rect.width) * this.chart.w;
        const px = this.chart.px || [];
        if (!px.length) return;
        let lo = 0, hi = px.length - 1;
        while (lo < hi) {
            const mid = (lo + hi) >> 1;
            if (px[mid] < xv) lo = mid + 1; else hi = mid;
        }
        this.hoverIdx = lo;
    }

    public tipLeft(): number {
        const pct = (this.chart.px[this.hoverIdx] || 0) / this.chart.w * 100;
        return Math.max(14, Math.min(86, pct));
    }

    public fmtIndex(v: any): string {
        return (Number(v || 0) * 100).toLocaleString('ko-KR', { maximumFractionDigits: 0 });
    }

    public signedPct(v: any): string {
        const n = Number(v || 0);
        return (n > 0 ? '+' : '') + n.toLocaleString('ko-KR', { maximumFractionDigits: 1 }) + '%';
    }

    public coinName(m: string): string { return COIN_NAME[m] || m; }
    public eventLabel(t: string): string { return EVENT_LABEL[t] || t; }
    public eventTone(t: string): string {
        if (/_BUY$/.test(t)) return 'is-buy';
        if (/_SELL$/.test(t) || t === 'COIN_EXTERNAL_SELL') return 'is-sell';
        if (/ERROR|HALT|CANCELLED/.test(t)) return 'is-danger';
        return '';
    }
    public trackByMarket(_i: number, row: any) { return row?.market; }

    public tone(v: any): string {
        const n = Number(v || 0);
        return n > 0 ? 'dx-up' : n < 0 ? 'dx-down' : 'dx-flat';
    }

    public krw(v: any): string {
        const n = Number(v);
        if (!isFinite(n)) return '-';
        return '₩' + Math.round(n).toLocaleString('ko-KR');
    }

    public signedKrw(v: any): string {
        const n = Math.round(Number(v || 0));
        return (n > 0 ? '+' : n < 0 ? '-' : '') + '₩' + Math.abs(n).toLocaleString('ko-KR');
    }

    public price(v: any): string {
        const n = Number(v);
        if (!isFinite(n) || n <= 0) return '-';
        const digits = n >= 1000 ? 0 : n >= 10 ? 2 : 4;
        return n.toLocaleString('ko-KR', { minimumFractionDigits: 0, maximumFractionDigits: digits });
    }

    public kst(sec: any): string {
        const n = Number(sec || 0);
        if (!n) return '-';
        return new Date(n * 1000).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    }

    public equityChange(): number {
        const led = this.engine?.equity ? this.engine : this.activeLedger;
        const seed = Number(led?.seed_krw || 0);
        return seed ? Number(led?.equity || 0) - seed : 0;
    }

    public stateLabel(row: any): string {
        if (row.pending) return '주문 확인 중';
        if (row.long) return '보유';
        if (!row.active) return '제외 (청산 대기)';
        return '대기';
    }
}
