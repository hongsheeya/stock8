import { OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';

export class Component implements OnInit {
    public loading: boolean = false;
    public members: any[] = [];

    public search: any = {
        text: "",
        role: ""
    };

    public roles: string[] = ['admin', 'user'];

    public showInviteModal: boolean = false;
    public inviteData: any = { email: '', role: 'viewer' };

    constructor(public service: Service) { }

    public async ngOnInit() {
        await this.service.init(this);
        await this.service.auth.allow("/access");
        await this.load();
    }

    public async load() {
        this.loading = true;
        await this.service.render();

        const { code, data } = await wiz.call("list", this.search);
        if (code === 200) {
            this.members = data || [];
        }

        this.loading = false;
        await this.service.render();
    }

    public async filterByRole(role: string) {
        this.search.role = this.search.role === role ? "" : role;
        await this.load();
    }

    public async openInvite() {
        this.inviteData = { email: '', role: 'user' };
        this.showInviteModal = true;
        await this.service.render();
    }

    public async invite() {
        if (!this.inviteData.email) {
            await this.service.modal.error("이메일을 입력해주세요.");
            return;
        }

        const { code, data } = await wiz.call("invite", this.inviteData);
        if (code === 200) {
            await this.service.modal.success("초대가 완료되었습니다.");
            this.showInviteModal = false;
            await this.load();
        } else {
            await this.service.modal.error(data || "초대에 실패했습니다.");
        }
    }

    public async removeMember(member: any) {
        let res = await this.service.modal.show({
            title: "멤버 제거",
            message: `${member.name}님을 멤버에서 제거하시겠습니까?`,
            action: "제거",
            actionBtn: "error",
            status: "error"
        });
        if (!res) return;

        const { code } = await wiz.call("remove", { id: member.id });
        if (code === 200) {
            await this.load();
        }
    }

    public roleClass(role: string) {
        switch (role) {
            case 'admin': return 'bg-purple-100 text-purple-700';
            case 'editor': return 'bg-blue-100 text-blue-700';
            case 'viewer': return 'bg-gray-100 text-gray-600';
            default: return 'bg-gray-100 text-gray-600';
        }
    }
}
