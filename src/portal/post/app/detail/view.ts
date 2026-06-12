import { OnInit, OnDestroy } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';
import { Router, NavigationEnd } from '@angular/router';

export class Component implements OnInit, OnDestroy {
    public id: string = '';
    public tab: string = 'view';
    public data: any = null;
    public saving: boolean = false;

    public tabs: any[] = [
        { key: 'view', label: '내용 보기', icon: '📄' },
        { key: 'edit', label: '수정', icon: '✏️' },
        { key: 'settings', label: '설정', icon: '⚙️' },
    ];

    private basePath: string = '/posts';
    private routerSub: any;

    constructor(public service: Service, private router: Router) {
        this.id = WizRoute.segment.id;
        this.tab = WizRoute.segment.tab || 'view';
    }

    public async ngOnInit() {
        await this.service.init(this);

        // 탭 전환 감지: NavigationEnd 구독
        this.routerSub = this.router.events.subscribe(async (event) => {
            if (event instanceof NavigationEnd) {
                const newId = WizRoute.segment.id;
                const newTab = WizRoute.segment.tab || 'view';

                if (newId && newId !== this.id) {
                    this.id = newId;
                    this.tab = newTab;
                    await this.load();
                } else if (newTab !== this.tab) {
                    this.tab = newTab;
                    await this.service.render();
                }
            }
        });

        // tab 없이 접근 시 기본 탭으로 리다이렉트
        if (!WizRoute.segment.tab) {
            this.service.href(`${this.basePath}/${this.id}/view`);
            return;
        }

        await this.load();
    }

    public ngOnDestroy() {
        if (this.routerSub) this.routerSub.unsubscribe();
    }

    public isNewPost() {
        return this.id === 'new';
    }

    public async load() {
        if (this.isNewPost()) {
            this.data = { title: '', content: '', category: '', status: 'draft' };
            this.tab = 'edit';
            await this.service.render();
            return;
        }

        this.data = null;
        await this.service.render();

        const { code, data } = await wiz.call("get", { id: this.id });
        if (code !== 200) {
            this.service.href(this.basePath);
            return;
        }
        this.data = data;
        await this.service.render();
    }

    public async save() {
        if (!this.data.title) {
            await this.service.modal.error("제목을 입력해주세요.");
            return;
        }

        this.saving = true;
        await this.service.render();

        let payload = JSON.stringify(this.data);
        const { code, data } = await wiz.call("save", { data: payload });

        await this.service.sleep(800);
        this.saving = false;

        if (code === 200) {
            await this.service.modal.success("저장되었습니다.");
            if (this.isNewPost() && data.id) {
                this.id = data.id;
                this.service.href(`${this.basePath}/${this.id}/view`);
            }
        } else {
            await this.service.modal.error(data || "저장에 실패했습니다.");
        }

        await this.service.render();
    }

    public async remove() {
        let res = await this.service.modal.show({
            title: "게시물 삭제",
            message: "정말 이 게시물을 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.",
            action: "삭제",
            actionBtn: "error",
            status: "error"
        });
        if (!res) return;

        const { code } = await wiz.call("delete", { id: this.id });
        if (code === 200) {
            this.service.href(this.basePath);
        }
    }
}
