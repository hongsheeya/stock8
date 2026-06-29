import { OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';

export class Component implements OnInit {
    public themeMode: 'dark' | 'light' = 'light';
    private themeListener: any = null;

    constructor(public service: Service) { }

    public async ngOnInit() {
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
