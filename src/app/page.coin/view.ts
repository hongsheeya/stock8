/// <reference path="../../types/wiz-modules.d.ts" />

import { OnDestroy, OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';

// WIZ renames the component class at build time; keep lookups at module level.
const MODE_LABEL: any = { off: '꺼짐', shadow: '모의 운용', live: '실거래' };
const EVENT_LABEL: any = {
    COIN_SHADOW_BUY: '모의 매수', COIN_SHADOW_SELL: '모의 매도', COIN_BUY: '매수', COIN_SELL: '매도',
    COIN_BUY_SKIPPED: '매수 보류', COIN_BUY_ERROR: '매수 실패', COIN_SELL_ERROR: '매도 실패',
    COIN_ORDER_CANCELLED: '주문 취소', COIN_EXTERNAL_SELL: '직접 매도 감지', COIN_HALT: '진입 중단', COIN_RESUME: '진입 재개',
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
