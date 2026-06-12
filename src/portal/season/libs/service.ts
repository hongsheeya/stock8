import { Injectable } from '@angular/core';
import { ChangeDetectorRef } from '@angular/core';

import Auth from './src/auth';
import Event from './src/event';
import Lang from './src/lang';
import Modal from './src/modal';
import Status from './src/status';

import Crypto from './util/crypto';
import File from './util/file';
import Request from './util/request';
import Formatter from './util/formatter';

@Injectable({ providedIn: 'root' })
export class Service {
    public app: ChangeDetectorRef;
    private apps: any[] = [];
    public inited: boolean = false;
    private initPromise: Promise<void> | null = null;

    public auth: Auth;
    public modal: Modal;
    public event: Event;
    public lang: Lang;
    public status: Status;

    public crypto: Crypto;
    public file: File;
    public request: Request;
    public formatter: Formatter;

    constructor() { }

    private registerApp(app: any) {
        if (!app) return;
        if (!this.apps.includes(app)) {
            this.apps.push(app);
        }
        if (!this.app) {
            this.app = app;
            return;
        }
        if (!this.app.router && app.router) {
            this.app = app;
        }
    }

    public async init(app: any) {
        if (app) {
            this.registerApp(app);
        }

        if (this.inited === false) {
            if (this.initPromise === null) {
                this.initPromise = (async () => {
                    this.crypto = new Crypto();
                    this.file = new File();
                    this.request = new Request();
                    this.formatter = new Formatter();

                    this.auth = new Auth(this);
                    this.modal = new Modal(this);
                    this.status = new Status(this);
                    this.event = new Event(this);

                    if (this.app.translate) {
                        this.lang = new Lang(this);
                        let lang: string = (navigator.language || navigator.userLanguage).substring(0, 2).toLowerCase();
                        if (!['ko', 'en'].includes(lang)) lang = 'ko';
                        this.lang.set(lang);
                    }

                    await this.auth.init();
                    this.inited = true;
                })().finally(() => {
                    this.initPromise = null;
                });
            }

            await this.initPromise;
        }

        await this.auth.update();
        await this.render();
        return this;
    }

    public async sleep(time: number = 0) {
        let timeout = () => new Promise((resolve) => {
            setTimeout(resolve, time);
        });
        await timeout();
    }

    public async render(time: number = 0) {
        if (!this.app && this.apps.length === 0) {
            return;
        }

        let timeout = () => new Promise((resolve) => {
            setTimeout(resolve, time);
        });

        if (time > 0) {
            await timeout();
        }

        const targets = this.apps.length > 0 ? this.apps : [this.app];
        const alive: any[] = [];

        try {
            for (const target of targets) {
                if (!target) continue;
                try {
                    if (typeof target.detectChanges === 'function') {
                        target.detectChanges();
                        alive.push(target);
                    } else if (target.ref && typeof target.ref.detectChanges === 'function') {
                        target.ref.detectChanges();
                        alive.push(target);
                    }
                } catch (e) {
                    console.warn('[Service.render] Skip stale app:', e);
                }
            }
        } catch (e) {
            console.warn('[Service.render] Error calling detectChanges:', e);
        }

        this.apps = alive;
        if ((!this.app || !alive.includes(this.app)) && alive.length > 0) {
            this.app = alive[0];
        }
    }

    public href(url: any) {
        if (this.app && this.app.router && typeof this.app.router.navigateByUrl === 'function') {
            this.app.router.navigateByUrl(url);
            return;
        }

        for (const target of this.apps) {
            if (target && target.router && typeof target.router.navigateByUrl === 'function') {
                target.router.navigateByUrl(url);
                return;
            }
        }

        location.href = url;
    }

    public random(stringLength: number = 16) {
        const fchars = 'abcdefghiklmnopqrstuvwxyz';
        const chars = '0123456789abcdefghiklmnopqrstuvwxyz';
        let randomstring = '';
        for (let i = 0; i < stringLength; i++) {
            let rnum = null;
            if (i === 0) {
                rnum = Math.floor(Math.random() * fchars.length);
                randomstring += fchars.substring(rnum, rnum + 1);
            } else {
                rnum = Math.floor(Math.random() * chars.length);
                randomstring += chars.substring(rnum, rnum + 1);
            }
        }
        return randomstring;
    }
}

export default Service;