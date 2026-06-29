import { OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';

declare const wiz: any;

export class Component implements OnInit {
    public loading: boolean = true;
    public bridgeBusy: boolean = false;
    public error: string = '';
    public bridgeMessage: string = '';
    public bridge: any = null;
    public fireGateUrl: string = 'https://fire-gate.app/';
    public loginWindow: Window | null = null;
    public showBridgeTools: boolean = false;
    public showFireGateFrame: boolean = true;

    private destroyed: boolean = false;
    private bridgeAutoLogin: boolean = false;
    private bridgeStatusPollTimer: any = null;
    private bridgeMessageHandler: any = null;
    private loginPollTimer: any = null;
    private firebaseLoadPromise: Promise<any> | null = null;
    private readonly fireGateFirebaseConfig: any = {
        apiKey: 'AIzaSyB1hnlSuxJwlx5Xq9O9mj7gf33Me8F4-Mw',
        authDomain: 'fire-gate-6add2.firebaseapp.com',
        projectId: 'fire-gate-6add2',
        storageBucket: 'fire-gate-6add2.appspot.com',
        messagingSenderId: '475812744726',
        appId: '1:475812744726:web:bdb74729f42bf83d85ef37',
    };

    constructor(public service: Service) { }

    public async ngOnInit() {
        this.destroyed = false;
        await this.service.init(this);
        await this.service.auth.allow("/access");
        this.bridgeAutoLogin = new URLSearchParams(window.location.search).get('firegate_bridge_login') === '1';
        this.bridgeMessageHandler = async (event: MessageEvent) => {
            if (event?.data?.type !== 'firegate_bridge_saved') return;
            await this.loadBridgeStatus(true);
            await this.bootstrapFireGateBridge('FireGate 연결 완료');
            await this.renderIfAlive();
        };
        window.addEventListener('message', this.bridgeMessageHandler);
        await this.loadBridgeStatus(false);
        this.loading = false;
        await this.renderIfAlive();
        if (this.bridgeAutoLogin) {
            setTimeout(() => this.loginFireGateBridge(), 250);
        }
    }

    public ngOnDestroy() {
        this.destroyed = true;
        if (this.bridgeStatusPollTimer) {
            clearInterval(this.bridgeStatusPollTimer);
            this.bridgeStatusPollTimer = null;
        }
        if (this.bridgeMessageHandler) {
            window.removeEventListener('message', this.bridgeMessageHandler);
            this.bridgeMessageHandler = null;
        }
        if (this.loginPollTimer) {
            clearInterval(this.loginPollTimer);
            this.loginPollTimer = null;
        }
    }

    private async renderIfAlive() {
        if (this.destroyed) return;
        await this.service.render();
    }

    private loadScript(src: string): Promise<void> {
        return new Promise((resolve, reject) => {
            const existing = document.querySelector(`script[src="${src}"]`) as HTMLScriptElement | null;
            if (existing) {
                if ((existing as any).__loaded) resolve();
                else existing.addEventListener('load', () => resolve(), { once: true });
                return;
            }
            const script = document.createElement('script');
            script.src = src;
            script.async = true;
            script.onload = () => {
                (script as any).__loaded = true;
                resolve();
            };
            script.onerror = () => reject(new Error('Firebase SDK 로딩 실패'));
            document.head.appendChild(script);
        });
    }

    private async loadFirebase(): Promise<any> {
        const win = window as any;
        if (win.firebase?.auth) return win.firebase;
        if (!this.firebaseLoadPromise) {
            this.firebaseLoadPromise = (async () => {
                await this.loadScript('https://www.gstatic.com/firebasejs/10.12.5/firebase-app-compat.js');
                await this.loadScript('https://www.gstatic.com/firebasejs/10.12.5/firebase-auth-compat.js');
                return (window as any).firebase;
            })();
        }
        return this.firebaseLoadPromise;
    }

    private fireGateAuth(firebase: any): any {
        const name = 'firegateBridge';
        let app = (firebase.apps || []).find((item: any) => item.name === name);
        if (!app) app = firebase.initializeApp(this.fireGateFirebaseConfig, name);
        const auth = firebase.auth(app);
        auth.languageCode = 'ko';
        return auth;
    }

    private firebaseAuthorizedHost(): boolean {
        const host = window.location.hostname.toLowerCase();
        return ['localhost', 'fire-gate.app', 'fire-gate-6add2.firebaseapp.com', 'fire-gate-6add2.web.app'].includes(host);
    }

    private localhostBridgeUrl(): string {
        const url = new URL(window.location.href);
        url.protocol = 'http:';
        url.hostname = 'localhost';
        if (!url.port) url.port = '3000';
        url.searchParams.set('firegate_bridge_login', '1');
        return url.toString();
    }

    private pollBridgeLoginWindow(win: Window | null) {
        if (this.bridgeStatusPollTimer) clearInterval(this.bridgeStatusPollTimer);
        let tries = 0;
        this.bridgeStatusPollTimer = setInterval(async () => {
            tries += 1;
            await this.loadBridgeStatus(true);
            if (this.bridge?.connected || this.bridge?.configured || tries > 80 || (win && win.closed)) {
                clearInterval(this.bridgeStatusPollTimer);
                this.bridgeStatusPollTimer = null;
                this.bridgeBusy = false;
                if (this.bridge?.configured) {
                    this.bridgeMessage = 'FireGate 브릿지 로그인 완료';
                }
                await this.renderIfAlive();
            }
        }, 1500);
    }

    public bridgeStatusText(): string {
        if (!this.bridge?.configured) return 'FireGate 미연결';
        if (this.bridge?.connected) return `FireGate 자동동기화 연결됨 · ${this.bridge.email_masked || ''}`;
        return `FireGate 저장됨 · ${this.bridge?.email_masked || '연결 확인 필요'}`;
    }

    public bridgeActionText(): string {
        if (!this.bridge?.configured) return 'FireGate 연결';
        if (this.bridge?.connected) return '연결 확인';
        return '재연결';
    }

    public toggleBridgeTools() {
        this.showBridgeTools = !this.showBridgeTools;
    }

    public async connectFireGateBridge() {
        if (!this.bridge?.configured || !this.bridge?.connected) {
            await this.loginFireGateBridge();
            return;
        }
        this.bridgeBusy = true;
        this.error = '';
        this.bridgeMessage = '';
        await this.renderIfAlive();
        await this.loadBridgeStatus(true);
        this.bridgeMessage = this.bridge?.connected ? 'FireGate 연결 확인 완료' : 'FireGate 재연결이 필요합니다.';
        this.bridgeBusy = false;
        await this.renderIfAlive();
    }

    private async bootstrapFireGateBridge(prefix: string = 'FireGate 연결 완료') {
        if (!this.bridge?.configured) return;
        try {
            const sync = await wiz.call('sync_fire_gate');
            if (sync?.code !== 200) throw new Error(sync?.data?.message || 'FireGate 초기 동기화 실패');
            const synced = sync?.data?.result || {};
            this.bridge = sync?.data?.fire_gate_bridge || this.bridge;
            this.bridgeMessage = `${prefix} · FireGate ${synced.firegate_portfolios || 0}, 사이클 ${synced.cycles_created || 0}/${synced.cycles_updated || 0}`;
            await this.loadBridgeStatus(true);
        } catch (e: any) {
            this.error = e?.message || 'FireGate 초기 자동동기화 실패';
        }
    }

    public async loadBridgeStatus(check: boolean = false) {
        try {
            const { code, data } = await wiz.call('fire_gate_bridge_status', { check: check ? 'true' : 'false' });
            if (code === 200) {
                this.bridge = data;
                if (data?.message) this.error = data.message;
            }
        } catch (e: any) {
            this.error = e?.message || '브릿지 상태 확인 실패';
        }
    }

    public async loginFireGateBridge() {
        this.bridgeBusy = true;
        this.error = '';
        this.bridgeMessage = '';
        await this.renderIfAlive();
        try {
            if (!this.firebaseAuthorizedHost()) {
                const win = window.open(this.localhostBridgeUrl(), 'fireGateBridgeLocalhost', 'width=1180,height=860');
                this.bridgeMessage = 'OAuth 허용 도메인 제한으로 localhost 창에서 브릿지 로그인을 진행합니다.';
                this.pollBridgeLoginWindow(win);
                await this.renderIfAlive();
                return;
            }
            const firebase = await this.loadFirebase();
            const auth = this.fireGateAuth(firebase);
            const provider = new firebase.auth.GoogleAuthProvider();
            provider.setCustomParameters({ prompt: 'select_account' });
            const result = await auth.signInWithPopup(provider);
            const user = result?.user;
            if (!user) throw new Error('Google 로그인 정보를 받지 못했습니다.');
            const idToken = await user.getIdToken(true);
            const refreshToken = user.refreshToken || '';
            const { code, data } = await wiz.call('save_fire_gate_bridge', {
                email: user.email || '',
                id_token: idToken,
                refresh_token: refreshToken,
                enabled: 'true',
            });
            if (code !== 200) throw new Error(data?.message || '브릿지 저장 실패');
            this.bridge = data;
            this.bridgeMessage = 'FireGate 브릿지 로그인 완료';
            await this.loadBridgeStatus(true);
            if (window.opener) {
                window.opener.postMessage({ type: 'firegate_bridge_saved' }, '*');
            }
            if (!this.bridgeAutoLogin) {
                await this.bootstrapFireGateBridge('FireGate 연결 완료');
            }
            if (this.bridgeAutoLogin) {
                setTimeout(() => window.close(), 600);
            }
        } catch (e: any) {
            this.error = e?.message || e?.code || '브릿지 로그인 실패';
        }
        this.bridgeBusy = false;
        await this.renderIfAlive();
    }

    public async syncFireGate() {
        this.bridgeBusy = true;
        this.error = '';
        this.bridgeMessage = '';
        await this.renderIfAlive();
        try {
            const { code, data } = await wiz.call('sync_fire_gate');
            if (code !== 200) throw new Error(data?.message || 'FireGate 동기화 실패');
            const result = data?.result || {};
            this.bridge = data?.fire_gate_bridge || this.bridge;
            this.bridgeMessage = `동기화 완료 · FireGate ${result.firegate_portfolios || 0}, 사이클 ${result.cycles_created || 0}/${result.cycles_updated || 0}`;
            await this.loadBridgeStatus(true);
        } catch (e: any) {
            this.error = e?.message || 'FireGate 동기화 실패';
        }
        this.bridgeBusy = false;
        await this.renderIfAlive();
    }

    public async pullFireGate() {
        await this.syncFireGate();
    }

    public async pushFireGate() {
        await this.syncFireGate();
    }

    public async reloadFireGate() {
        if (!this.showFireGateFrame) {
            this.showFireGateFrame = true;
            await this.renderIfAlive();
        }
        const frame = document.getElementById('fireGateIframe') as HTMLIFrameElement | null;
        if (!frame) return;
        frame.src = 'about:blank';
        setTimeout(() => {
            if (this.destroyed) return;
            frame.src = this.fireGateUrl;
        }, 50);
    }

    public loginFireGate() {
        this.loginWindow = window.open(this.fireGateUrl, 'fireGateLogin', 'width=1180,height=860');
        if (this.loginPollTimer) clearInterval(this.loginPollTimer);
        this.loginPollTimer = setInterval(() => {
            if (this.destroyed) return;
            if (!this.loginWindow || this.loginWindow.closed) {
                clearInterval(this.loginPollTimer);
                this.loginPollTimer = null;
                this.loginWindow = null;
                this.reloadFireGate();
            }
        }, 800);
    }

    public openFireGate() {
        window.open(this.fireGateUrl, '_blank', 'noopener,noreferrer');
    }
}
