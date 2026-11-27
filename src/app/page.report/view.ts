/// <reference path="../../types/wiz-modules.d.ts" />

import { OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';

// WIZ renames the component class at build time; keep lookups at module level.
const STATUS_ORDER = ['blocked', 'unknown', 'running', 'waiting', 'off'];
const STATUS_LABEL: any = { running: '동작', waiting: '대기', blocked: '막힘', off: '꺼짐', unknown: '확인 불가' };
const STATUS_CLASS: any = { running: 'is-ok', waiting: 'rp-wait', blocked: 'is-danger', off: '', unknown: 'is-warn' };
const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'];

export class Component implements OnInit {
    public loading: boolean = true;
    public fetching: boolean = false;
    public data: any = null;
    public errorMessage: string = '';
    public date: string = '';
    public dates: string[] = [];
    public expanded: any = {};
    public readonly statusOrder: string[] = STATUS_ORDER;

    constructor(public service: Service) { }

    public async ngOnInit() {
        await this.service.init(this);
        await this.service.auth.allow('/access');
        await this.load(false);
        this.loading = false;
        await this.service.render();
    }

    private async api(name: string, params: any = {}): Promise<{ code: number; data: any }> {
        return await (wiz.call(name, params) as Promise<{ code: number; data: any }>);
    }

    public async load(force: boolean) {
        if (this.fetching) return;
        this.fetching = true;
        await this.service.render();
        try {
            const { code, data } = await this.api('report', { date: this.date, force: force ? 'true' : 'false' });
            if (code === 200) {
                const sameDay = this.data?.date === data.date;
                this.data = data;
                this.date = data.date;
                this.dates = data.dates || [];
                this.errorMessage = '';
                if (!sameDay) this.expandProblems();
            } else {
                // A failed read never keeps an older day's numbers on screen.
                this.data = null;
                this.errorMessage = data?.message || '일일 보고를 불러오지 못했습니다.';
                if (data?.dates) this.dates = data.dates;
            }
        } catch (e) {
            this.data = null;
            this.errorMessage = '일일 보고를 불러오지 못했습니다.';
        }
        this.fetching = false;
        await this.service.render();
    }

    public async changeDate(value: string) {
        this.date = value;
        await this.load(false);
    }

    private expandProblems() {
        this.expanded = {};
        for (const lane of this.data?.lanes || []) {
            if (lane.status === 'blocked' || lane.status === 'unknown') this.expanded[lane.key] = true;
        }
    }

    public toggle(lane: any) {
        this.expanded[lane.key] = !this.expanded[lane.key];
    }

    public async openLane(lane: any) {
        this.expanded[lane.key] = true;
        await this.service.render();
        const el = document.getElementById('lane-' + lane.key.replace(':', '-'));
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // ---- view helpers
    public statusLabel(s: string): string { return STATUS_LABEL[s] || s; }
    public statusClass(s: string): string { return STATUS_CLASS[s] || ''; }
    public count(s: string): number { return Number(this.data?.counts?.[s] || 0); }
    public laneId(lane: any): string { return 'lane-' + String(lane.key).replace(':', '-'); }

    public dateLabel(d: string): string {
        if (!d) return '';
        const day = new Date(d + 'T00:00:00');
        const text = `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}(${WEEKDAYS[day.getDay()]})`;
        return d === this.data?.today ? `${text} 오늘` : text;
    }

    public countText(v: any): string {
        return v === null || v === undefined ? '—' : String(v);
    }

    public money(v: any, currency: string): string {
        if (v === null || v === undefined || v === '') return '—';
        const n = Number(v);
        if (!isFinite(n)) return '—';
        const sign = n > 0 ? '+' : n < 0 ? '-' : '';
        if (currency === 'USD') return `${sign}$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        return `${sign}₩${Math.round(Math.abs(n)).toLocaleString('ko-KR')}`;
    }

    public price(v: any, currency: string): string {
        if (v === null || v === undefined || v === '') return '—';
        const n = Number(v);
        if (!isFinite(n) || n <= 0) return '—';
        if (currency === 'USD') return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
        return '₩' + Math.round(n).toLocaleString('ko-KR');
    }

    public qty(v: any): string {
        if (v === null || v === undefined || v === '') return '—';
        const n = Number(v);
        if (!isFinite(n)) return '—';
        return Number.isInteger(n) ? n.toLocaleString('ko-KR') : n.toLocaleString('en-US', { maximumFractionDigits: 8 });
    }

    public pnlClass(v: any): string {
        const n = Number(v);
        if (v === null || v === undefined || !isFinite(n) || n === 0) return '';
        return n > 0 ? 'dx-up' : 'dx-down';
    }

    public sideClass(side: string): string {
        return side === 'BUY' ? 'is-buy' : side === 'SELL' ? 'is-sell' : '';
    }

    public problemSpan(p: any): string {
        return p.first_hhmm === p.last_hhmm ? p.first_hhmm : `${p.first_hhmm}~${p.last_hhmm}`;
    }

    public problemClass(p: any): string {
        return p.level === 'block' || p.level === 'error' ? 'is-danger' : 'is-warn';
    }

    public problemLevel(p: any): string {
        return p.level === 'block' ? '차단' : p.level === 'error' ? '오류' : '경고';
    }

    public hasDetail(lane: any): boolean {
        return !!(lane.notes?.length || lane.problems?.length || lane.fills?.length || lane.orders?.length
            || lane.positions?.length || lane.pending?.length || lane.worker?.length);
    }

    public verificationText(s: any): string {
        const v = s?.verification || {};
        if (!s?.ok) return '확인 불가';
        if (v.status === 'not_configured') return '계좌 미설정';
        if (v.status === 'missing') return '확인 불가 (장부 파일 없음)';
        if (v.status === 'error') return '확인 불가 (' + (v.message || '장부를 읽지 못함') + ')';
        if (v.status === 'foreign') return '확인 불가 (다른 사용자 소유 계좌)';
        const holds = (v.holds || []).length;
        return holds ? `매수 보류 ${holds}종목 (${v.hold_records}건)` : '매수 보류 없음';
    }

    public verificationClass(s: any): string {
        const v = s?.verification || {};
        if (!s?.ok || v.status === 'missing' || v.status === 'error' || v.status === 'foreign') return 'is-warn';
        if (v.status === 'not_configured') return '';
        return (v.holds || []).length ? 'is-danger' : 'is-ok';
    }

    public paperUnavailableText(s: any): string {
        if (!s?.ok) return '확인 불가';
        const flag = s.paper_unavailable;
        if (flag === null || flag === undefined) return '확인 불가';
        if (!flag.since) return '표시 없음';
        return `사용 불가 (${String(flag.since).slice(0, 16).replace('T', ' ')}부터)`;
    }

    public modeLabel(mode: string): string {
        return mode === 'LIVE' ? '실투자 (LIVE)' : '모의투자 (PAPER)';
    }

    public trackByKey(_i: number, lane: any) { return lane.key; }
}
