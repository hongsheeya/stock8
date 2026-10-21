import { OnInit } from '@angular/core';
import { Router, NavigationEnd } from '@angular/router';
import { Service } from '@wiz/libs/portal/season/service';
import { pageMeta } from '@wiz/libs/portal/trading/page-meta';

export class Component implements OnInit {
    public themeMode: 'dark' | 'light' = 'light';
    private themeListener: any = null;
    private routeSub: any = null;
    // Breadcrumb: the trail above the current page (hidden on the dashboard).
    public crumbs: { label: string; path: string }[] = [];
    public crumbCurrent: string = '';

    constructor(public service: Service, public router: Router) { }

    private updateCrumbs(url: string) {
        const meta = pageMeta(url);
        this.crumbs = meta.trail || [];
        this.crumbCurrent = meta.title || '';
    }

    public async ngOnInit() {
        this.updateCrumbs(this.router.url || window.location.pathname);
        this.routeSub = this.router.events.subscribe((event: any) => {
            if (event instanceof NavigationEnd) {
                this.updateCrumbs(event.urlAfterRedirects || event.url);
                this.service.render();
            }
        });
        this.loadThemePreference();
        this.themeListener = (event: any) => {
            const mode = event?.detail?.mode;
            if (mode === 'light' || mode === 'dark') {
                this.themeMode = mode;
            } else {
                this.loadThemePreference();
            }
            this.service.render();
        };
        try {
            window.addEventListener('dashboard-theme-changed', this.themeListener);
        } catch (e) {
        }
        await this.service.init(this);
        await this.service.render();
    }

    public ngOnDestroy() {
        if (this.routeSub) {
            this.routeSub.unsubscribe();
            this.routeSub = null;
        }
        if (this.themeListener) {
            try {
                window.removeEventListener('dashboard-theme-changed', this.themeListener);
            } catch (e) {
            }
            this.themeListener = null;
        }
    }

    private loadThemePreference() {
        try {
            const saved = window.localStorage.getItem('dashboard-theme-mode');
            this.themeMode = saved === 'dark' ? 'dark' : 'light';
        } catch (e) {
            this.themeMode = 'light';
        }
    }
}
