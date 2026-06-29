import { Component, OnInit, ChangeDetectorRef, enableProdMode } from '@angular/core';
import { Router } from '@angular/router';
import { Service } from '@wiz/libs/portal/season/service';
import { TranslateService } from '@ngx-translate/core';

@Component({
    selector: 'app-root',
    templateUrl: './app.component.html',
    styleUrls: ['./app.component.scss']
})
export class AppComponent implements OnInit {
    private assetVersion: string = '';
    private versionGuardTimer: any = null;

    constructor(
        public service: Service,
        public router: Router,
        public ref: ChangeDetectorRef,
        public translate: TranslateService
    ) {
        window['MonacoEnvironment'] = {
            getWorkerUrl: function (moduleId: string, label: string) {
                return `/lib/vs/base/worker/workerMain.js`;
            }
        };
    }

    public async ngOnInit() {
        enableProdMode();
        await this.service.init(this);
        this.installAssetVersionGuard();
    }

    private currentAssetVersion(): string {
        try {
            const scripts = Array.from(document.querySelectorAll('script[data-version]')) as HTMLScriptElement[];
            const mainScript = scripts.find(script => String(script.getAttribute('src') || '').includes('main.js')) || scripts[0];
            return String(mainScript?.getAttribute('data-version') || '').trim();
        } catch (e) {
            return '';
        }
    }

    private latestAssetVersion(html: string): string {
        const match = String(html || '').match(/data-version="([^"]+)"/);
        return match ? String(match[1] || '').trim() : '';
    }

    private installAssetVersionGuard() {
        try {
            if (typeof window === 'undefined' || typeof fetch === 'undefined') return;
            this.assetVersion = this.currentAssetVersion();
            if (!this.assetVersion) return;

            const checkLatest = async () => {
                try {
                    const response = await fetch(`/?asset_version_check=${Date.now()}`, {
                        cache: 'no-store',
                        credentials: 'same-origin',
                    });
                    const latest = this.latestAssetVersion(await response.text());
                    if (latest && latest !== this.assetVersion) {
                        window.location.reload();
                    }
                } catch (e) {
                    // Version checks must never interrupt normal app usage.
                }
            };

            window.setTimeout(checkLatest, 5000);
            this.versionGuardTimer = window.setInterval(checkLatest, 60000);
        } catch (e) {
            if (this.versionGuardTimer) {
                window.clearInterval(this.versionGuardTimer);
                this.versionGuardTimer = null;
            }
        }
    }
}
