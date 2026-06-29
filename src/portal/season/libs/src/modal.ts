import Service from '../service';

export default class Modal {

    public isshow: boolean = false;
    public callback: any = null;
    public hide: any = async () => { };
    public action: any = async () => { };
    public default_opts: any = {
        title: 'Are you sure?',
        message: "Do you really want to remove app? What you've done cannot be undone.",
        action: "Delete",
        actionBtn: "error",
        cancel: true,
        status: 'error'
    };
    public opts: any = {};

    constructor(private service: Service) { }

    private label(value: any, role: string) {
        if (value === false || value === null || value === undefined || value === '') return value;
        if (value === true) return role === 'cancel' ? '취소' : '확인';
        let text = String(value).trim();
        let lower = text.toLowerCase();
        if (lower === 'ok' || lower === 'okay' || lower === 'true') return '확인';
        if (lower === 'cancel' || lower === 'false') return '취소';
        return text;
    }

    private normalizeLabels() {
        this.opts.action = this.label(this.opts.action, 'action');
        this.opts.cancel = this.label(this.opts.cancel, 'cancel');
    }

    public async show(mopts: any = {}) {
        this.isshow = true;
        this.opts = JSON.parse(JSON.stringify(this.default_opts));
        for (let key in mopts)
            this.opts[key] = mopts[key];
        this.normalizeLabels();
        await this.service.render();

        let fn = () => new Promise((resolve) => {
            this.cancel = async () => {
                this.isshow = false;
                await this.service.render();
                resolve(false);
            }

            this.hide = async () => {
                this.isshow = false;
                await this.service.render();
                resolve();
            }

            this.action = async (data: any = true) => {
                this.isshow = false;
                await this.service.render();
                resolve(data);
            }
        });

        return await fn();
    }

    public async error(message: string, cancel: any = false, action: string = '확인') {
        return await this.show({
            title: "",
            message: message,
            cancel: cancel,
            actionBtn: 'error',
            action: action,
            status: 'error'
        });
    }

    public async success(message: string, cancel: any = false, action: string = '확인') {
        return await this.show({
            title: "",
            message: message,
            cancel: cancel,
            actionBtn: 'success',
            action: action,
            status: 'success'
        });
    }

    public async warning(message: string, cancel: any = false, action: string = '확인') {
        return await this.show({
            title: "",
            message: message,
            cancel: cancel,
            actionBtn: 'warning',
            action: action,
            status: 'warning'
        });
    }

    public localize(mopts: any = {}) {
        let modal = new Modal(this.service);
        for (let key in mopts)
            modal.default_opts[key] = mopts[key];
        return modal;
    }

}
