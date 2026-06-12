import { OnInit } from '@angular/core';
import { HostListener } from '@angular/core';
import { Service } from '@wiz/libs/portal/season/service';

export class Component implements OnInit {
    constructor(public service: Service) { }

    public async ngOnInit() {
        await this.service.init(this);
    }

    @HostListener('document:click')
    public clickout() {
        this.service.status.toggle('navbar', true);
    }

    public isActive(link: string) {
        return location.pathname.indexOf(link) === 0
    }

    public activeClass(link: string) {
        if (this.isActive(link)) {
            return "group flex gap-x-2 items-center rounded-md bg-gray-100 px-2 py-1.5 text-[13px] font-medium text-indigo-600";
        }
        return "group flex gap-x-2 items-center rounded-md px-2 py-1.5 text-[13px] font-medium text-gray-600 hover:bg-gray-50 hover:text-indigo-600";
    }
}