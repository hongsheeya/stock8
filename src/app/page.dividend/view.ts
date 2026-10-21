/// <reference path="../../types/wiz-modules.d.ts" />

import { OnDestroy, OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';

// WIZ renames the component class at build time; keep lookups at module level.
const MARKET_LABEL: any = { US: '미국', KS: '코스피', KQ: '코스닥' };

export class Component implements OnInit, OnDestroy {
    public loading: boolean = true;
    public data: any = null;
    public errorMessage: string = '';
    public notice: string = '';
    public busy: boolean = false;
    public fetching: boolean = false;
    public showResearch: boolean = false;
    public watchForm: any = { market: 'US', symbol: '', name: '' };
    private timer: any = null;

    constructor(public service: Service) { }

    public async ngOnInit() {
        await this.service.init(this);
        await this.service.auth.allow('/access');
        await this.load(false);
        this.loading = false;
        await this.service.render();
        this.timer = window.setInterval(() => {
            if (this.data?.refreshing || this.data?.pending) void this.load(false);
        }, 4000);
    }

    public ngOnDestroy() {
        if (this.timer) window.clearInterval(this.timer);
        this.timer = null;
    }

    private async api(name: string, params: any = {}): Promise<{ code: number; data: any }> {
        return await (wiz.call(name, params) as Promise<{ code: number; data: any }>);
    }

    public async load(force: boolean) {
        if (this.fetching) return;
        this.fetching = true;
        try {
            const { code, data } = await this.api('overview', { force: force ? 'true' : 'false' });
            if (code === 200) {
                this.data = data;
                this.errorMessage = '';
            } else if (!this.data) {
                this.errorMessage = data?.message || '배당 화면을 불러오지 못했습니다.';
            }
        } catch (e) {
            if (!this.data) this.errorMessage = '배당 화면을 불러오지 못했습니다.';
        }
        this.fetching = false;
        await this.service.render();
    }

    public async addWatch() {
        if (this.busy) return;
        this.busy = true;
        this.notice = '';
        this.errorMessage = '';
        const { code, data } = await this.api('add_watch', { ...this.watchForm, symbol: String(this.watchForm.symbol || '').trim().toUpperCase() });
        this.busy = false;
        if (code === 200) {
            this.notice = '관심 종목에 추가했습니다. 배당 정보를 불러오는 중입니다.';
            this.watchForm = { market: this.watchForm.market, symbol: '', name: '' };
        } else {
            this.errorMessage = data?.message || '추가하지 못했습니다.';
        }
        await this.load(false);
    }

    public async removeWatch(row: any) {
        if (this.busy) return;
        this.busy = true;
        await this.api('remove_watch', { symbol: row.symbol, market: row.market });
        this.busy = false;
        await this.load(false);
    }

    // ---- view helpers
    public marketLabel(m: string): string { return MARKET_LABEL[m] || m; }
    public isUs(m: string): boolean { return m === 'US'; }

    public krw(v: any): string {
        const n = Number(v);
        if (!isFinite(n)) return '-';
        return '₩' + Math.round(n).toLocaleString('ko-KR');
    }

    public money(v: any, market: string): string {
        const n = Number(v);
        if (!isFinite(n) || n <= 0) return '-';
        if (this.isUs(market)) return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
        return '₩' + Math.round(n).toLocaleString('ko-KR');
    }

    public pct(v: any): string {
        const n = Number(v);
        return v === null || v === undefined || !isFinite(n) ? '-' : n.toFixed(2) + '%';
    }

    public shortDate(v: any): string {
        if (!v) return '-';
        const d = String(v);
        return `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}`;
    }

    public dday(v: any): string {
        if (!v || !this.data?.today) return '';
        const diff = Math.round((new Date(v).getTime() - new Date(this.data.today).getTime()) / 86400000);
        if (diff < 0) return '';
        return diff === 0 ? '오늘' : `D-${diff}`;
    }

    public monthLabel(m: string): string { return `${Number(m.slice(5, 7))}월`; }

    public barHeight(value: number): number {
        const max = Math.max(1, ...(this.data?.cashflow || []).map((b: any) => b.net_krw || 0));
        return Math.round((value || 0) / max * 100);
    }

    public statusTags(r: any): any[] {
        const tags: any[] = [];
        if (!r.has_data) tags.push({ text: this.data?.refreshing ? '불러오는 중' : '정보 없음', tone: '' });
        if (r.cut) tags.push({ text: `삭감 ${r.cut.pct}%`, tone: 'is-danger' });
        if (r.frequency_changed) tags.push({ text: `${r.frequency_changed.from}→${r.frequency_changed.to}`, tone: 'is-warn' });
        if (r.variable) tags.push({ text: '금액 변동', tone: 'is-warn' });
        if (r.missed) tags.push({ text: '지급 지연?', tone: 'is-warn' });
        if (r.has_data && r.next_ex_date) tags.push({ text: r.next_confirmed ? '일정 확정' : '예상', tone: r.next_confirmed ? 'is-ok' : '' });
        return tags;
    }

    public get finPct(): number {
        return Math.min(100, Number(this.data?.financial_income?.used_pct || 0));
    }

    public trackBySymbol(_i: number, r: any) { return `${r.market}:${r.symbol}`; }
}
