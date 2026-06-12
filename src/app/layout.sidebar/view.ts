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
        this.service.status.toggle('navbar', false);
    }

    public isActive(link: string) {
        return location.pathname.indexOf(link) === 0
    }
}