/// <reference path="../../types/wiz-modules.d.ts" />

import { OnDestroy, OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';

// WIZ renames the component class at build time; keep lookups at module level.
const EVENT_LABEL: any = { USTH_ORDER: '주문', USTH_FILL: '체결', USTH_ERROR: '오류', USTH_DATA: '데이터' };

export class Component implements OnInit, OnDestroy {
    public loading: boolean = true;
    public data: any = null;
    public errorMessage: string = '';
    public notice: string = '';
    public busy: string = '';
    public refreshing: boolean = false;
    public showResearch: boolean = false;
    public form: any = { seed_usd: 20000 };
    private timer: any = null;

    constructor(public service: Service) { }

    public async ngOnInit() {
        await this.service.init(this);
        await this.service.auth.allow('/access');
        await this.load(true);
        this.loading = false;
        await this.service.render();
        this.timer = window.setInterval(() => void this.load(false), 15000);
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
                if (syncForm) this.form = { seed_usd: data?.policy?.seed_usd || 20000 };
            } else if (!this.data) {
                this.errorMessage = data?.message || '화면을 불러오지 못했습니다.';
            }
        } catch (e) {
            if (!this.data) this.errorMessage = '화면을 불러오지 못했습니다.';
        }
        this.refreshing = false;
        await this.service.render();
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

    public async setEnabled(on: boolean) {
        if (on === this.enabled) return;
        if (!on && this.held.length) {
            const ok = await this.service.modal.show({
                title: '미장 추세 보유 끄기',
                message: `보유 중인 ${this.held.join(', ')}는 팔지 않고 그대로 둡니다. 다시 켜면 이어서 관리합니다.`,
                action: '끄기', cancel: '취소', status: 'warning', actionBtn: 'warning',
            });
            if (ok !== true) return;
        }
        await this.run('set_enabled', { enabled: on }, 'enabled', on ? '켰습니다. 미국 장 09:35부터 판단합니다.' : '껐습니다.');
    }

    public async saveSettings() {
        await this.run('save_settings', { seed_usd: this.form.seed_usd }, 'settings', '시드를 저장했습니다.');
    }

    // ---- view helpers
    public get enabled(): boolean { return !!this.data?.policy?.enabled; }
    public get engine(): any { return this.data?.engine || {}; }
    public get sleeves(): any[] { return this.engine?.sleeves || []; }
    public get held(): string[] { return this.sleeves.filter((s: any) => s.qty > 0).map((s: any) => s.etf); }
    public get heldLabel(): string { return this.held.length ? this.held.join(' · ') : '현금'; }
    public get workerStatus(): string {
        const w = this.data?.worker || {};
        if (!this.data?.available) return '';
        if (w.status === 'error') return `실행 오류: ${w.error || ''}`;
        if (this.enabled && w.alive === false) return '작업이 멈춰 있습니다 (서버 재시작 필요)';
        return '';
    }

    public eventLabel(e: any): string {
        const base = EVENT_LABEL[e.event_type] || e.event_type;
        if (e.event_type === 'USTH_ORDER' || e.event_type === 'USTH_FILL') return `${e.action === 'BUY' ? '매수' : '매도'} ${base}`;
        return base;
    }

    public eventTone(e: any): string {
        if (e.event_type === 'USTH_ERROR' || e.event_type === 'USTH_DATA') return 'is-danger';
        return e.action === 'BUY' ? 'is-buy' : e.action === 'SELL' ? 'is-sell' : '';
    }

    public tone(v: any): string {
        const n = Number(v || 0);
        return n > 0 ? 'dx-up' : n < 0 ? 'dx-down' : 'dx-flat';
    }

    public usd(v: any): string {
        const n = Number(v);
        if (!isFinite(n) || n <= 0) return '-';
        return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    public signedUsd(v: any): string {
        const n = Number(v || 0);
        const s = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        return (n > 0 ? '+$' : n < 0 ? '-$' : '$') + s;
    }

    public pct(v: any): string {
        if (v === null || v === undefined || v === '') return '-';
        const n = Number(v);
        if (!isFinite(n)) return '-';
        return (n > 0 ? '+' : '') + n.toFixed(2) + '%';
    }

    public kst(sec: any): string {
        const n = Number(sec || 0);
        if (!n) return '-';
        return new Date(n * 1000).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    }

    public equityChange(): number {
        const seed = Number(this.engine?.seed_usd || 0);
        const eq = Number(this.engine?.equity || 0);
        return seed && eq ? eq - seed : 0;
    }
}
