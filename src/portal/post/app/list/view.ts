import { OnInit } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';

export class Component implements OnInit {
    public loading: boolean = false;
    public list: any[] = [];
    public categories: string[] = [];
    public selectedCategory: string = "";

    public search: any = {
        text: "",
        page: 1,
        dump: 20
    };

    public pagination: any = {
        end: -1,
        start: -1,
        current: 0
    };

    public keyuptime: any = 0;

    constructor(public service: Service) { }

    public async ngOnInit() {
        await this.service.init(this);
        await this.loadCategories();
        await this.load();
    }

    public async loadCategories() {
        const { code, data } = await wiz.call("categories");
        if (code === 200) {
            this.categories = data;
        }
    }

    public async selectCategory(cat: string) {
        this.selectedCategory = this.selectedCategory === cat ? "" : cat;
        await this.load();
    }

    public searchAction() {
        this.keyuptime = new Date().getTime();
        let ref = this.keyuptime;
        setTimeout(async () => {
            if (ref !== this.keyuptime) return;
            await this.load();
        }, 300);
    }

    public async load(page: number = 1) {
        if (this.loading) return;
        this.loading = true;
        this.pagination.current = page;
        this.search.page = page;
        this.list = [];
        await this.service.render();

        const { code, data } = await wiz.call("search", {
            ...this.search,
            category: this.selectedCategory
        });

        if (code === 200) {
            this.list = data.rows || [];

            let total = data.total || 0;
            let dump = this.search.dump;
            this.pagination.start = 1;
            this.pagination.end = Math.ceil(total / dump);
        }

        this.loading = false;
        await this.service.render();
    }

    public statusClass(status: string) {
        switch (status) {
            case 'published': return 'bg-green-50 text-green-700 border border-green-200';
            case 'draft': return 'bg-yellow-50 text-yellow-700 border border-yellow-200';
            case 'archived': return 'bg-gray-50 text-gray-600 border border-gray-200';
            default: return 'bg-gray-50 text-gray-600 border border-gray-200';
        }
    }
}
