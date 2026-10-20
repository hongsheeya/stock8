import { OnDestroy, OnInit } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { Service } from '@wiz/libs/portal/season/service';

declare const wiz: any;

// Module-level data: WIZ rewrites the component class line, so no static members.
const QUESTS: any[] = [
    {
        id: 'account', icon: '🧭', title: '모험 시작', goal: '계정 만들기',
        how: ['회원가입을 마치면 자동으로 클리어돼요.'],
        tip: '환영해요! 첫 퀘스트는 이미 깼어요.', link: '/dashboard', reward: '모험가 등록',
    },
    {
        id: 'api', icon: '🔑', title: '열쇠 얻기', goal: '증권사 API 키 등록',
        how: [
            '한국투자증권 KIS Developers(apiportal.koreainvestment.com)에 로그인해요.',
            'API 신청에서 앱키(App Key)와 시크릿(App Secret)을 발급받아요. 연습은 모의투자용으로 받으면 돼요.',
            '설정 → 증권사 API에 앱키, 시크릿, 계좌번호(8자리-2자리)를 넣고 저장해요.',
        ],
        tip: '키는 내 계정에만 저장돼요. 다른 사용자는 볼 수 없어요.', link: '/settings', reward: '증권사 열쇠',
    },
    {
        id: 'connection', icon: '🔌', title: '전원 연결', goal: '연결 테스트 통과',
        how: [
            '설정 → 증권사 API에서 연결 테스트를 눌러요.',
            '잔고·시세·주문가능금액 조회가 성공하면 클리어예요.',
        ],
        tip: '연결만으로는 주문이 나가지 않아요. 안심하고 눌러도 돼요.', link: '/settings', reward: '계좌 연결 배지',
    },
    {
        id: 'firegate', icon: '🔥', title: 'FireGate 동맹', goal: 'FireGate 계정 연결',
        how: [
            '무한매수 메뉴로 가요.',
            'Google 계정 연결을 눌러 FireGate에 로그인해요.',
            '연결되면 동기화 버튼으로 내 포트폴리오를 불러와요.',
        ],
        tip: 'FireGate에서 정한 계획표 그대로 주문해요.', link: '/infinite-buy', reward: '전략 지도',
    },
    {
        id: 'cycle', icon: '📈', title: '첫 출정', goal: '무한매수 사이클 만들기',
        how: [
            'FireGate에서 종목(예: SOXL)과 시드를 정해 포트폴리오를 만들어요.',
            '무한매수 메뉴에서 동기화하면 진행 중 사이클이 생겨요.',
        ],
        tip: '시드는 잃어도 괜찮은 금액부터 작게 시작하세요.', link: '/infinite-buy', reward: '첫 사이클',
    },
    {
        id: 'auto', icon: '⚡', title: '자동 모드', goal: '무한매수 자동매매 켜기',
        how: [
            '대시보드 상단의 무한매수 스위치를 ON으로 바꿔요.',
            '위험 안내를 읽고 확인을 눌러요.',
            '이후 평일 10:00부터 LOC 예약이 자동으로 걸려요.',
        ],
        tip: '실투자는 실제 돈이 움직여요. 처음이라면 모의투자에서 먼저 연습하세요.', link: '/dashboard', reward: '자동 운전 면허',
    },
    {
        id: 'explore', icon: '🗺️', title: '지도 익히기', goal: '대시보드와 거래이력 둘러보기',
        how: [
            '대시보드: 총자산·손익·주문가능금액과 LOC 예약 상태를 봐요.',
            '거래이력: 성과, 체결 내역, 사이클, 주문 로그 탭을 하나씩 눌러봐요.',
        ],
        tip: '두 화면을 모두 열어보면 클리어돼요.', link: '/history', reward: '튜토리얼 클리어',
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
