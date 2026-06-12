import { OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';

export class Component implements OnInit {
    public user: any = null;
    public saving: boolean = false;

    public passwordForm: any = {
        current_password: '',
        new_password: '',
        confirm_password: ''
    };
    public changingPassword: boolean = false;

    constructor(public service: Service) { }

    public async ngOnInit() {
        await this.service.init(this);
        await this.service.auth.allow("/access");
        await this.load();
    }

    public async load() {
        const { code, data } = await wiz.call("get");
        if (code === 200) {
            this.user = data;
        }
        await this.service.render();
    }

    public async updateProfile() {
        if (!this.user.name) {
            await this.service.modal.error("이름을 입력해주세요.");
            return;
        }

        this.saving = true;
        await this.service.render();

        const { code, data } = await wiz.call("update_profile", {
            name: this.user.name,
            mobile: this.user.mobile || ''
        });

        await this.service.sleep(500);
        this.saving = false;

        if (code === 200) {
            await this.service.modal.success("프로필이 업데이트되었습니다.");
        } else {
            await this.service.modal.error(data || "업데이트에 실패했습니다.");
        }
        await this.service.render();
    }

    public async changePassword() {
        const { current_password, new_password, confirm_password } = this.passwordForm;

        if (!current_password) {
            await this.service.modal.error("현재 비밀번호를 입력해주세요.");
            return;
        }
        if (!new_password) {
            await this.service.modal.error("새 비밀번호를 입력해주세요.");
            return;
        }
        if (new_password.length < 8) {
            await this.service.modal.error("새 비밀번호는 8자 이상이어야 합니다.");
            return;
        }
        if (new_password !== confirm_password) {
            await this.service.modal.error("새 비밀번호가 일치하지 않습니다.");
            return;
        }

        this.changingPassword = true;
        await this.service.render();

        const { code, data } = await wiz.call("change_password", {
            current_password: current_password,
            new_password: new_password
        });

        await this.service.sleep(500);
        this.changingPassword = false;

        if (code === 200) {
            await this.service.modal.success("비밀번호가 변경되었습니다.");
            this.passwordForm = { current_password: '', new_password: '', confirm_password: '' };
        } else {
            await this.service.modal.error(data || "비밀번호 변경에 실패했습니다.");
        }
        await this.service.render();
    }
}
