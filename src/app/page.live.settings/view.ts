import { OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';
export class Component implements OnInit {
    public state: any = {};
    public confirmation = '';
    public message = '';
    public busy = false;
    constructor(public service: Service) {}
    public async ngOnInit() {
        await this.service.init(this);
        await this.service.auth.allow('/access');
        try {
            const res = await wiz.call('status');
            if (res.code === 200) this.state = res.data;
            else this.message = res.message || '설정 조회 실패';
        } catch (_) { this.message = '설정 상태를 확인하지 못했습니다. 주문 허용 상태로 간주하지 않습니다.'; }
        await this.service.render();
    }
    public async save(enabled: boolean) {
        this.busy = true;
        try {
            const res = await wiz.call('save', {enabled: String(enabled), confirmation: this.confirmation});
            if (res.code === 200) {
                this.state = res.data;
                this.confirmation = '';
                this.message = enabled ? '실투자 주문 허용 설정을 저장했습니다.' : '실투자 주문을 차단했습니다.';
            } else this.message = res.message || res.data?.message || '설정을 저장하지 못했습니다.';
        } catch (_) { this.message = '저장 실패. 현재 상태를 다시 확인하세요.'; }
        this.busy = false;
        await this.service.render();
    }
}

