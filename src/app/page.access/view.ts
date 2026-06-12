import { OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';

export class Component implements OnInit {
    constructor(public service: Service) { }

    public view: string = 'login';
    public loading: boolean = false;
    public errorMsg: string = '';
    public successMsg: string = '';

    public loginData: any = {
        email: '',
        password: ''
    };

    public signupData: any = {
        name: '',
        mobile: '',
        email: '',
        password: '',
        passwordConfirm: ''
    };

    public findIdData: any = {
        name: '',
        mobile: ''
    };

    public resetPasswordData: any = {
        email: '',
        name: '',
        mobile: '',
        newPassword: '',
        newPasswordConfirm: ''
    };

    public async ngOnInit() {
        await this.service.init(this);
        let check = await this.service.auth.check();
        if (check) return location.href = "/dashboard";
        await this.service.render();
    }

    public async switchView(v: string) {
        this.view = v;
        this.errorMsg = '';
        this.successMsg = '';
        await this.service.render();
    }

    public async login() {
        this.errorMsg = '';
        this.successMsg = '';
        if (!this.loginData.email) {
            this.errorMsg = '이메일을 입력해주세요.';
            await this.service.render();
            return;
        }
        if (!this.loginData.password) {
            this.errorMsg = '비밀번호를 입력해주세요.';
            await this.service.render();
            return;
        }
        this.loginData.email = (this.loginData.email || '').trim().toLowerCase();

        this.loading = true;
        await this.service.render();

        let { code, data } = await wiz.call("login", this.loginData);

        if (code == 200) {
            location.href = "/dashboard";
        } else {
            this.errorMsg = data.message || '로그인에 실패했습니다.';
            this.loading = false;
            await this.service.render();
        }
    }

    public async signup() {
        this.errorMsg = '';
        this.successMsg = '';
        if (!this.signupData.name) {
            this.errorMsg = '이름을 입력해주세요.';
            await this.service.render();
            return;
        }
        if (!this.signupData.email) {
            this.errorMsg = '이메일을 입력해주세요.';
            await this.service.render();
            return;
        }
        if (!this.signupData.password) {
            this.errorMsg = '비밀번호를 입력해주세요.';
            await this.service.render();
            return;
        }
        this.signupData.email = (this.signupData.email || '').trim().toLowerCase();
        if (this.signupData.password.length < 8) {
            this.errorMsg = '비밀번호는 8자 이상이어야 합니다.';
            await this.service.render();
            return;
        }
        if (this.signupData.password !== this.signupData.passwordConfirm) {
            this.errorMsg = '비밀번호가 일치하지 않습니다.';
            await this.service.render();
            return;
        }

        this.loading = true;
        await this.service.render();

        let { code, data } = await wiz.call("signup", {
            name: this.signupData.name,
            mobile: this.signupData.mobile,
            email: this.signupData.email,
            password: this.signupData.password
        });

        if (code == 200) {
            location.href = "/dashboard";
        } else {
            this.errorMsg = data.message || '회원가입에 실패했습니다.';
            this.loading = false;
            await this.service.render();
        }
    }

    public async findId() {
        this.errorMsg = '';
        this.successMsg = '';
        if (!this.findIdData.name || !this.findIdData.mobile) {
            this.errorMsg = '이름과 휴대폰 번호를 입력해주세요.';
            await this.service.render();
            return;
        }

        this.loading = true;
        await this.service.render();

        let { code, data } = await wiz.call('find_id', this.findIdData);
        this.loading = false;
        if (code === 200) {
            this.successMsg = `가입된 아이디: ${data.masked_email || data.email}`;
        } else {
            this.errorMsg = data.message || '아이디 찾기에 실패했습니다.';
        }
        await this.service.render();
    }

    public async resetPassword() {
        this.errorMsg = '';
        this.successMsg = '';
        if (!this.resetPasswordData.email || !this.resetPasswordData.name || !this.resetPasswordData.mobile || !this.resetPasswordData.newPassword) {
            this.errorMsg = '모든 필드를 입력해주세요.';
            await this.service.render();
            return;
        }
        if (this.resetPasswordData.newPassword.length < 8) {
            this.errorMsg = '비밀번호는 8자 이상이어야 합니다.';
            await this.service.render();
            return;
        }
        if (this.resetPasswordData.newPassword !== this.resetPasswordData.newPasswordConfirm) {
            this.errorMsg = '비밀번호가 일치하지 않습니다.';
            await this.service.render();
            return;
        }

        this.loading = true;
        await this.service.render();

        let { code, data } = await wiz.call('reset_password', {
            email: (this.resetPasswordData.email || '').trim().toLowerCase(),
            name: this.resetPasswordData.name,
            mobile: this.resetPasswordData.mobile,
            new_password: this.resetPasswordData.newPassword,
        });

        this.loading = false;
        if (code === 200) {
            this.successMsg = data.message || '비밀번호를 재설정했습니다.';
            this.view = 'login';
            this.loginData.email = (this.resetPasswordData.email || '').trim().toLowerCase();
            this.resetPasswordData = { email: '', name: '', mobile: '', newPassword: '', newPasswordConfirm: '' };
        } else {
            this.errorMsg = data.message || '비밀번호 재설정에 실패했습니다.';
        }
        await this.service.render();
    }
}
