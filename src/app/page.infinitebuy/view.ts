import { OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';

declare const wiz: any;

export class Component implements OnInit {
    public loading: boolean = true;
    public bridgeBusy: boolean = false;
    public authStage: string = '';
    public popupReady = false;
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
        // Retire stale redirect attempts: never resume a failed cross-origin flow.
        sessionStorage.removeItem('stock8.firegate.connect');
        sessionStorage.removeItem('stock8.firegate.redirect');
        if (!await this.service.auth.allow("/access")) return;
        this.bridgeAutoLogin = new URLSearchParams(window.location.search).get('firegate_bridge_login') === '1';
        this.bridgeMessageHandler = async (event: MessageEvent) => {
            if (event.origin !== window.location.origin) return;
            if (event?.data?.type !== 'firegate_bridge_saved') return;
            await this.loadBridgeStatus(true);
            await this.bootstrapFireGateBridge('FireGate 연결 완료');
            await this.renderIfAlive();
        };
        window.addEventListener('message', this.bridgeMessageHandler);
        await this.loadBridgeStatus(false);
        this.loading = false;
        await this.renderIfAlive();
        // Download Firebase after first paint so opening this page and the
        // first click on "FireGate 연결" do not pay the SDK startup serially.
        setTimeout(() => this.loadFirebase().then(async firebase => {
            let timer: any;
            try {
                await Promise.race([
                    this.fireGateAuth(firebase, 'firegatePopup').setPersistence(firebase.auth.Auth.Persistence.SESSION),
                    new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('인증 저장소 준비 시간 초과')), 15000); })
                ]);
            } finally { clearTimeout(timer); }
            if (this.destroyed) return;
            this.popupReady = true;
            await this.renderIfAlive();
        }).catch(async e => {
            if (this.destroyed) return;
            this.error = '별도 인증 창 준비 실패: ' + (e?.message || '브라우저 저장소를 확인해주세요.');
            await this.renderIfAlive();
        }), 0);
        const cleanUrl = new URL(window.location.href);
        cleanUrl.searchParams.delete('firegate_bridge_login');
        window.history.replaceState(null, '', cleanUrl.toString());
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

    private async authStep<T>(label: string, action: Promise<T>, timeoutMs: number = 15000): Promise<T> {
        this.authStage = label;
        await this.renderIfAlive();
        let timer: any;
        try {
            return await Promise.race([action, new Promise<T>((_, reject) => {
                timer = setTimeout(() => reject(new Error(label + ' 시간 초과. 인증은 완료되지 않았습니다. FireGate 인증 도메인과 브라우저 저장소 제한을 확인해야 합니다.')), timeoutMs);
            })]);
        } finally { clearTimeout(timer); }
    }

    private loadScript(src: string): Promise<void> {
        return new Promise((resolve, reject) => {
            const existing = document.querySelector(`script[src="${src}"]`) as HTMLScriptElement | null;
            if (existing) {
                if ((existing as any).__loaded) resolve();
                else {
                    const timer = setTimeout(() => { existing.remove(); reject(new Error('Firebase SDK 다운로드 시간 초과')); }, 12000);
                    existing.addEventListener('load', () => { clearTimeout(timer); resolve(); }, {once: true});
                    existing.addEventListener('error', () => { clearTimeout(timer); existing.remove(); reject(new Error('Firebase SDK 다운로드 실패')); }, {once: true});
                }
                return;
            }
            const script = document.createElement('script');
            script.src = src;
            script.async = true;
            const timer = setTimeout(() => { script.remove(); reject(new Error('Firebase SDK 다운로드 시간 초과')); }, 12000);
            script.onload = () => {
                clearTimeout(timer);
                (script as any).__loaded = true;
                resolve();
            };
            script.onerror = () => { clearTimeout(timer); script.remove(); reject(new Error('Firebase SDK 로딩 실패')); };
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
            })().catch(error => { this.firebaseLoadPromise = null; throw error; });
        }
        return this.firebaseLoadPromise;
    }

    private fireGateAuth(firebase: any, name: string = 'firegateBridge'): any {
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
            await this.loadBridgeStatus(false);
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
        return this.bridge?.configured ? '지금 동기화' : (this.popupReady ? 'Google 계정 연결' : '인증 준비 중');
    }

    public toggleBridgeTools() {
        this.showBridgeTools = !this.showBridgeTools;
    }

    public async connectFireGateBridge() {
        if (!this.bridge?.configured) {
            await this.loginWithPopup();
            return;
        }
        await this.syncFireGate();
    }

    public async loginFireGateInPage() {
        if (this.bridgeBusy) return;
        this.bridgeBusy = true;
        this.error = '';
        try {
            if (!this.firebaseAuthorizedHost()) {
                // Same-tab navigation avoids both popup blockers and loss of
                // user activation after SDK loading. No credential in the URL.
                window.location.assign(this.localhostBridgeUrl());
                return;
            }
            const firebase = await this.authStep('인증 모듈 준비', this.loadFirebase());
            const auth = this.fireGateAuth(firebase);
            await this.authStep('인증 저장소 준비', auth.setPersistence(firebase.auth.Auth.Persistence.SESSION));
            const provider = new firebase.auth.GoogleAuthProvider();
            provider.setCustomParameters({prompt: 'select_account'});
            sessionStorage.removeItem('stock8.firegate.connect');
            sessionStorage.setItem('stock8.firegate.redirect', '1');
            await this.authStep('Google 인증 화면 이동', auth.signInWithRedirect(provider));
        } catch (e: any) {
            sessionStorage.removeItem('stock8.firegate.redirect');
            this.error = 'FireGate 인증을 시작하지 못했습니다. ' + (e?.message || '');
        } finally {
            this.bridgeBusy = false;
            await this.renderIfAlive();
        }
    }

    public async loginWithPopup() {
        if (this.bridgeBusy || !this.popupReady) return;
        if (!this.firebaseAuthorizedHost()) {
            window.location.assign(this.localhostBridgeUrl());
            return;
        }
        const firebase = (window as any).firebase;
        const auth = this.fireGateAuth(firebase, 'firegatePopup');
        const provider = new firebase.auth.GoogleAuthProvider();
        provider.setCustomParameters({prompt: 'select_account'});
        this.bridgeBusy = true;
        this.error = '';
        this.authStage = '별도 창에서 Google 인증';
        // Open synchronously within the user's click; no SDK/network await first.
        try {
            const pending = auth.signInWithPopup(provider);
            await this.renderIfAlive();
            const result: any = await this.authStep('Google 인증 창 완료 대기', pending, 90000);
            if (!result?.user) throw new Error('인증 결과를 받지 못했습니다.');
            await this.saveAuthenticatedUser(result.user);
        } catch (e: any) {
            this.error = 'Google 연결을 완료하지 못했습니다. ' + (e?.code || e?.message || '') + ' 앱 내 브라우저에서 창이 열리지 않으면 일반 Chrome에서 아래 Stock8 주소를 열고 연결해주세요.';
        } finally { this.bridgeBusy = false; await this.renderIfAlive(); }
    }

    private async saveAuthenticatedUser(user: any) {
        if (this.destroyed) return;
        const idToken = await this.authStep('인증 토큰 확인', user.getIdToken(false));
        if (this.destroyed) return;
        const response: any = await this.authStep('Stock8 연결 저장', wiz.call('save_fire_gate_bridge', {
            email: user.email || '', id_token: idToken,
            refresh_token: user.refreshToken || '', enabled: 'true'
        }, {timeout: 15000}));
        if (response.code !== 200) throw new Error(response.data?.message || '연결 저장 실패');
        this.bridge = response.data;
        sessionStorage.removeItem('stock8.firegate.redirect');
        sessionStorage.removeItem('stock8.firegate.connect');
        this.bridgeMessage = '연결 완료. 지금 동기화를 눌러 FireGate 내역을 가져오세요.';
    }

    public get browserConnectUrl(): string {
        const url = new URL(window.location.href);
        if (url.hostname === '127.0.0.1') url.hostname = 'localhost';
        url.search = '';
        url.hash = '';
        return url.toString();
    }

    private async finishRedirectLogin() {
        this.bridgeBusy = true;
        sessionStorage.removeItem('stock8.firegate.redirect');
        try {
            const firebase = await this.authStep('인증 모듈 준비', this.loadFirebase());
            const auth = this.fireGateAuth(firebase);
            const result: any = await this.authStep('Google 인증 결과 확인', auth.getRedirectResult());
            if (!result?.user) throw new Error('인증 결과를 받지 못했습니다. 브라우저의 교차 사이트 저장소 제한 또는 FireGate 허용 도메인 설정을 확인해야 합니다.');
            await this.saveAuthenticatedUser(result.user);
            const url = new URL(window.location.href);
            url.searchParams.delete('firegate_bridge_login');
            window.history.replaceState(null, '', url.toString());
            this.bridgeMessage = '연결 완료. 지금 동기화를 눌러 FireGate 내역을 가져오세요.';
        } catch (e: any) {
            this.error = e?.message || 'FireGate 인증 완료 처리 실패';
        } finally {
            this.bridgeBusy = false;
            await this.renderIfAlive();
        }
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
            const { code, data } = await wiz.call('fire_gate_bridge_status', { check: check ? 'true' : 'false' }, {timeout: 10000});
            if (code === 200) {
                this.bridge = data;
                if (data?.message) this.error = data.message;
            }
        } catch (e: any) {
            this.error = e?.message || '브릿지 상태 확인 실패';
        }
    }


    public async syncFireGate() {
        if (this.bridgeBusy || !this.bridge?.configured) return;
        this.bridgeBusy = true;
        this.error = '';
        this.bridgeMessage = '';
        await this.renderIfAlive();
        try {
            const { code, data } = await wiz.call('sync_fire_gate', {}, {timeout: 20000});
            if (code !== 200) throw new Error(data?.message || 'FireGate 동기화 실패');
            const result = data?.result || {};
            if (result.executed !== true) throw new Error(result.message || 'FireGate 인증이 없어 동기화하지 못했습니다.');
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
        await this.loadBridgeStatus(false);
        await this.renderIfAlive();
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
