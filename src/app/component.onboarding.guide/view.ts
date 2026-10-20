import { OnDestroy, OnInit } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { Service } from '@wiz/libs/portal/season/service';

declare const wiz: any;

// Module-level data: WIZ rewrites the component class line, so no static members.
const QUESTS: any[] = [
    {
        id: 'account', title: '계정 만들기', goal: '회원가입',
        how: ['회원가입을 마치면 이 단계는 완료돼요.'],
        tip: '', link: '/dashboard',
    },
    {
        id: 'api', title: '증권사 API 키 등록', goal: '앱키·시크릿·계좌번호 입력',
        how: [
            '한국투자증권 KIS Developers(apiportal.koreainvestment.com)에 로그인합니다.',
            'API 신청 메뉴에서 앱키(App Key)와 시크릿(App Secret)을 발급받습니다. 연습용이라면 모의투자용으로 발급받으세요.',
            '설정 → 증권사 API에 앱키, 시크릿, 계좌번호(8자리-2자리)를 입력하고 저장합니다.',
        ],
        tip: 'API 키는 내 계정에만 저장되며 다른 사용자에게 보이지 않습니다.', link: '/settings',
    },
    {
        id: 'connection', title: '연결 테스트', goal: '잔고·시세 조회 확인',
        how: [
            '설정 → 증권사 API에서 연결 테스트를 누릅니다.',
            '잔고, 시세, 주문가능금액 조회가 성공하면 완료됩니다.',
        ],
        tip: '연결 테스트만으로는 주문이 나가지 않습니다.', link: '/settings',
    },
    {
        id: 'firegate', title: 'FireGate 연결', goal: 'FireGate 계정 연동',
        how: [
            '무한매수 메뉴로 이동합니다.',
            'Google 계정 연결을 눌러 FireGate에 로그인합니다.',
            '연결 후 동기화 버튼으로 포트폴리오를 불러옵니다.',
        ],
        tip: '주문은 FireGate의 계획표를 그대로 따릅니다.', link: '/infinite-buy',
    },
    {
        id: 'cycle', title: '무한매수 사이클 만들기', goal: '첫 사이클 시작',
        how: [
            'FireGate에서 종목(예: SOXL)과 시드를 정해 포트폴리오를 만듭니다.',
            '무한매수 메뉴에서 동기화하면 진행 중 사이클이 생성됩니다.',
        ],
        tip: '처음에는 감당 가능한 작은 금액으로 시작하는 것을 권장합니다.', link: '/infinite-buy',
    },
    {
        id: 'auto', title: '자동매매 켜기', goal: '무한매수 자동매매 ON',
        how: [
            '대시보드 상단의 무한매수 스위치를 ON으로 변경합니다.',
            '위험 안내를 확인합니다.',
            '이후 평일 10:00부터 LOC 예약 주문이 자동으로 접수됩니다.',
        ],
        tip: '실투자는 실제 자금으로 주문됩니다. 처음이라면 모의투자로 먼저 연습하세요.', link: '/dashboard',
    },
    {
        id: 'explore', title: '화면 살펴보기', goal: '대시보드와 거래이력 확인',
        how: [
            '대시보드: 총자산, 손익, 주문가능금액과 LOC 예약 상태를 확인합니다.',
            '거래이력: 성과, 체결 내역, 사이클, 주문 로그 탭을 확인합니다.',
        ],
        tip: '두 화면을 한 번씩 열면 완료됩니다.', link: '/history',
    },
];

export class Component implements OnInit, OnDestroy {
    public open = false;
    public loaded = false;
    public expanded = '';
    public steps: any = {};
    public visited: any = {};
    public dismissed = false;
    public quests = QUESTS;
    private routerSub: Subscription;
    private timer: any;

    constructor(public service: Service, private router: Router) { }

    public get doneCount(): number {
        return this.quests.filter(q => this.steps[q.id]).length;
    }

    public get percent(): number {
        return Math.round(this.doneCount / this.quests.length * 100);
    }

    public get current(): any {
        return this.quests.find(q => !this.steps[q.id]) || null;
    }

    public get allDone(): boolean {
        return this.loaded && !this.current;
    }

    public state(q: any): string {
        if (this.steps[q.id]) return 'done';
        return this.current && this.current.id === q.id ? 'current' : 'locked';
    }

    public isOpen(q: any): boolean {
        return this.expanded ? this.expanded === q.id : this.state(q) === 'current';
    }

    public async ngOnInit() {
        await this.service.init(this);
        await this.refresh(true);
        this.routerSub = this.router.events.subscribe(event => {
            if (event instanceof NavigationEnd) this.onRoute(event.urlAfterRedirects || event.url);
        });
        this.onRoute(location.pathname);
        this.timer = setInterval(() => this.refresh(false), 60000);
    }

    public ngOnDestroy() {
        if (this.routerSub) this.routerSub.unsubscribe();
        if (this.timer) clearInterval(this.timer);
    }

    public async refresh(first = false) {
        try {
            const res = await wiz.call('progress', {}, { timeout: 8000 });
            if (res.code === 200) {
                this.steps = res.data.steps || {};
                this.visited = res.data.visited || {};
                this.dismissed = !!res.data.dismissed;
                this.loaded = true;
                let shown = false;
                try { shown = sessionStorage.getItem('stock8GuideShown') === '1'; } catch (e) { }
                if (first && !this.dismissed && !this.allDone && !shown) {
                    this.open = true;
                    try { sessionStorage.setItem('stock8GuideShown', '1'); } catch (e) { }
                }
            }
        } catch (e) { }
        await this.service.render();
    }

    private async onRoute(path: string) {
        const key = String(path || '').startsWith('/dashboard') ? 'dashboard' : (String(path || '').startsWith('/history') ? 'history' : '');
        if (!key || this.visited[key] || !this.loaded) return;
        try {
            const res = await wiz.call('mark', { key }, { timeout: 8000 });
            if (res.code === 200) {
                this.visited = res.data.visited || this.visited;
                await this.refresh(false);
            }
        } catch (e) { }
    }

    public async toggle() {
        this.open = !this.open;
        this.expanded = '';
        if (this.open) await this.refresh(false);
        await this.service.render();
    }

    public async select(q: any) {
        this.expanded = this.expanded === q.id ? '' : q.id;
        await this.service.render();
    }

    public async go(q: any) {
        await this.router.navigateByUrl(q.link);
    }

    public async hideForGood() {
        try { await wiz.call('dismiss', { value: 'true' }, { timeout: 8000 }); } catch (e) { }
        this.dismissed = true;
        this.open = false;
        await this.service.render();
    }

    public async showAgain() {
        try { await wiz.call('dismiss', { value: 'false' }, { timeout: 8000 }); } catch (e) { }
        this.dismissed = false;
        await this.service.render();
    }
}
