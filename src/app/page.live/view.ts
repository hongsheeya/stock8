import { OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';

export class Component implements OnInit {
    public status: any = {};
    public error = '';
    constructor(public service: Service) {}
    public async ngOnInit() {
        await this.service.init(this);
        await this.service.auth.allow('/access');
        const account = await wiz.call('account_context');
        if (account.code === 200) {
            location.replace(account.data.live_url);
            return;
        }
        try {
            const result = await wiz.call('status');
            if (result.code === 200) this.status = result.data;
            else this.error = '실투자 설정 상태를 확인하지 못했습니다.';
        } catch (_) { this.error = '상태 조회에 실패했습니다.'; }
        await this.service.render();
    }
}
