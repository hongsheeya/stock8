import Service from '../service';

export default class Status {
    [key: string]: any;
    public loading: boolean = false;
    public navbar: boolean = true;

    constructor(private service: Service) { }

    public async toggle(target: string, status: any = null) {
        if (status === null) {
            this[target] = !this[target];
        } else {
            this[target] = status;
        }
        await this.service.render();
    }

    public async show(target: string) {
        this[target] = true;
        await this.service.render();
    }

    public async hide(target: string) {
        this[target] = false;
        await this.service.render();
    }
}
