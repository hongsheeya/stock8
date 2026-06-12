import $ from "jquery";

function sanitizeJsonText(text: string): any {
    const sanitized = text
        .replace(/\bNaN\b/g, 'null')
        .replace(/\b-Infinity\b/g, 'null')
        .replace(/\bInfinity\b/g, 'null');
    return JSON.parse(sanitized);
}

export default class Request {
    constructor() { }

    public async post(url: string, data: any = {}) {
        let request = () => {
            return new Promise((resolve, reject) => {
                $.ajax({
                    url: url,
                    type: "POST",
                    data: data,
                    dataType: "text",
                    timeout: 5000,
                }).done(function (responseText: string) {
                    try {
                        resolve(sanitizeJsonText(responseText));
                    } catch (e) {
                        resolve(responseText);
                    }
                }).fail(function (jqXHR: any, textStatus: string, errorThrown: any) {
                    // 네트워크 오류 (readyState:0, status:0): 서버 미응답/타임아웃
                    if (!jqXHR || jqXHR.readyState === 0 || jqXHR.status === 0) {
                        reject(new Error(`Network error: textStatus=${textStatus || 'unknown'}, readyState=${jqXHR?.readyState}, status=${jqXHR?.status}, error=${errorThrown || ''}`));
                        return;
                    }
                    // HTTP 오류 응답: responseText가 있으면 파싱 시도
                    if (jqXHR && typeof jqXHR.responseText === "string") {
                        try {
                            resolve(sanitizeJsonText(jqXHR.responseText));
                            return;
                        } catch (e) {}
                    }
                    reject(new Error(`HTTP error: status=${jqXHR?.status}`));
                });
            });
        }

        return await request();
    }

}