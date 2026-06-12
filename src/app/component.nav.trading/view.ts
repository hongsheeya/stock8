import { HostListener, OnInit } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { Service } from '@wiz/libs/portal/season/service';
import { i18n } from '@wiz/libs/portal/trading/i18n';

export class Component implements OnInit {
    public now: Date = new Date();
    private clockInterval: any;
    private routerSub: Subscription;
    public userMenuOpen: boolean = false;
    public currentPath: string = location.pathname;
    public adminPreviewUserMode: boolean = false;
    public themeMode: 'dark' | 'light' = 'dark';

    constructor(public service: Service, private router: Router) { }

    public t = (key: string) => i18n.t(key);
    public get lang() { return i18n.lang; }

    public async ngOnInit() {
        this.loadThemePreference();
        await this.service.init(this);
        this.refreshAdminPreviewMode();

        this.currentPath = this.router.url || location.pathname;
        this.routerSub = this.router.events.subscribe((event) => {
            if (event instanceof NavigationEnd) {
                this.currentPath = event.urlAfterRedirects || event.url || location.pathname;
                this.service.render();
            }
        });

        this.clockInterval = setInterval(() => {
            this.now = new Date();
        }, 1000);
    }

    ngOnDestroy() {
        if (this.clockInterval) clearInterval(this.clockInterval);
        if (this.routerSub) this.routerSub.unsubscribe();
    }

    public async toggleLang() {
        i18n.toggleLang();
        await this.service.render();
    }

    private loadThemePreference() {
        try {
            const saved = window.localStorage.getItem('dashboard-theme-mode');
            this.themeMode = saved === 'light' ? 'light' : 'dark';
        } catch (e) {
            this.themeMode = 'dark';
        }
    }

    public get isLightTheme(): boolean {
        return this.themeMode === 'light';
    }

    public get themeModeLabel(): string {
        return this.isLightTheme ? '화이트' : '다크';
    }

    public async toggleThemeMode() {
        this.themeMode = this.isLightTheme ? 'dark' : 'light';
        try {
            window.localStorage.setItem('dashboard-theme-mode', this.themeMode);
            window.dispatchEvent(new CustomEvent('dashboard-theme-changed', { detail: { mode: this.themeMode } }));
        } catch (e) {
        }
        await this.service.render();
    }

    public toggleUserMenu() {
        this.userMenuOpen = !this.userMenuOpen;
    }

    private refreshAdminPreviewMode() {
        try {
            this.adminPreviewUserMode = window.localStorage.getItem('admin_preview_user_mode') === 'true';
        } catch (e) {
            this.adminPreviewUserMode = false;
        }
    }

    public get isRealAdmin(): boolean {
        const session: any = this.service?.auth?.session || {};
        const role = String(session.role || session.user?.role || session.profile?.role || session.data?.role || '').toLowerCase();
        const email = String(session.email || session.user?.email || session.profile?.email || session.data?.email || '').trim().toLowerCase();
        return role === 'admin' || email === 'gigukbyun@gmail.com';
    }

    public get effectiveAdminMode(): boolean {
        return this.isRealAdmin && !this.adminPreviewUserMode;
    }

    public get adminPreviewButtonLabel(): string {
        return this.adminPreviewUserMode ? '사용자 모드' : '관리자 모드';
    }

    public get adminPreviewButtonTitle(): string {
        return this.adminPreviewUserMode ? '관리자 화면으로 전환' : '사용자 화면으로 전환';
    }

    public async toggleAdminPreviewMode() {
        if (!this.isRealAdmin) return;
        this.adminPreviewUserMode = !this.adminPreviewUserMode;
        try {
            window.localStorage.setItem('admin_preview_user_mode', this.adminPreviewUserMode ? 'true' : 'false');
            window.dispatchEvent(new CustomEvent('admin-preview-changed'));
        } catch (e) {
        }
        await this.service.render();
    }

    @HostListener('document:click')
    public onDocumentClick() {
        if (this.userMenuOpen) {
            this.userMenuOpen = false;
        }
    }

    @HostListener('window:admin-preview-changed')
    public async onAdminPreviewChanged() {
        this.refreshAdminPreviewMode();
        await this.service.render();
    }

    @HostListener('window:dashboard-theme-changed', ['$event'])
    public async onThemeChanged(event: any) {
        const mode = event?.detail?.mode;
        if (mode === 'light' || mode === 'dark') {
            this.themeMode = mode;
        } else {
            this.loadThemePreference();
        }
        await this.service.render();
    }

    public closeUserMenu() {
        this.userMenuOpen = false;
    }

    public async handleLogout() {
        try {
            await this.service.auth.logout('/access');
        } catch (e) {
            console.error("로그아웃 실패", e);
        }
    }

    public async goToSettings() {
        this.closeUserMenu();
        this.service.href('/settings');
    }

    public isActive(link: string) {
        const path = this.currentPath || location.pathname;
        if (link === '/daytrade') {
            return path === '/daytrade';
        }
        if (link === '/daytrade/us') {
            return path.indexOf('/daytrade/us') === 0;
        }
        return path.indexOf(link) === 0;
    }

    public navClass(link: string) {
        if (this.isActive(link)) {
            return "bn-nav-link is-active";
        }
        return "bn-nav-link";
    }

    public settingsButtonClass() {
        if (this.userMenuOpen) {
            return "bn-icon-button is-active";
        }
        return "bn-icon-button";
    }

    public avatarButtonClass() {
        if (this.userMenuOpen) {
            return "bn-avatar-button is-active";
        }
        return "bn-avatar-button";
    }

    private timeParts(timeZone: string) {
        const parts = new Intl.DateTimeFormat('en-GB', {
            timeZone,
            weekday: 'short',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
        }).formatToParts(new Date());
        const read = (type: string) => parts.find((item: any) => item.type === type)?.value || '';
        return {
            weekday: read('weekday'),
            hour: Number(read('hour') || 0),
            minute: Number(read('minute') || 0),
        };
    }

    private isKoreanMarketOpen(): boolean {
        const info = this.timeParts('Asia/Seoul');
        if (info.weekday === 'Sat' || info.weekday === 'Sun') return false;
        const mins = info.hour * 60 + info.minute;
        return mins >= 540 && mins < 930;
    }

    private isUsMarketOpen(): boolean {
        const info = this.timeParts('America/New_York');
        if (info.weekday === 'Sat' || info.weekday === 'Sun') return false;
        const mins = info.hour * 60 + info.minute;
        return mins >= 570 && mins < 960;
    }

    public isMarketOpen(): boolean {
        const path = this.currentPath || location.pathname;
        if (path.indexOf('/daytrade/us') === 0) {
            return this.isUsMarketOpen();
        }
        if (path.indexOf('/daytrade') === 0) {
            return this.isKoreanMarketOpen();
        }
        return this.isKoreanMarketOpen() || this.isUsMarketOpen();
    }
}
