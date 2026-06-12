declare module '@angular/core' {
    export function Input(bindingPropertyName?: string): any;
    export function HostListener(eventName?: string, args?: string[]): any;

    export interface OnInit {
        ngOnInit(): void | Promise<void>;
    }

    export interface OnDestroy {
        ngOnDestroy(): void;
    }
}

declare module '@wiz/libs/portal/season/service' {
    export class Service {
        init(app?: any): Promise<void>;
        render(): Promise<void>;
        href(url: any): void;
        auth: {
            allow(path: string): Promise<void>;
            [key: string]: any;
        };
        modal: any;
    }
}

declare module '@wiz/libs/portal/trading/i18n' {
    export const i18n: {
        lang: 'en' | 'ko';
        t(key: string): string;
        toggleLang(): void;
        setLang(lang: 'en' | 'ko'): void;
    };
}

declare const wiz: {
    call(name: string, params?: any): Promise<{ code: number; data: any }>;
};