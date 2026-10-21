// Per-page title, description and breadcrumb trail (10-21, pre-launch).
// The SPA serves one index.html, so app.component applies these on every
// navigation: <title>, meta description, robots and canonical.

export interface PageMeta {
    title: string;
    description?: string;
    trail?: { label: string; path: string }[];
    index?: boolean;  // only public pages may be indexed by search engines
}

export const SITE_NAME = '∞stock';
export const SITE_DESCRIPTION = '한국투자증권 API로 무한매수와 국내·미국 단타를 자동으로 실행하고 기록하는 투자 자동화 도구입니다. 모의투자로 먼저 검증하세요.';

const HOME = { label: '홈', path: '/dashboard' };

const PAGES: { pattern: RegExp; meta: PageMeta }[] = [
    { pattern: /^\/access\/?$/, meta: { title: '로그인 · 회원가입', description: SITE_DESCRIPTION, index: true } },
    { pattern: /^\/dashboard\/?$/, meta: { title: '대시보드', trail: [] } },
    { pattern: /^\/infinite-buy\/?$/, meta: { title: '무한매수', trail: [HOME] } },
    { pattern: /^\/dividend\/?$/, meta: { title: '배당', trail: [HOME] } },
    { pattern: /^\/daytrade\/us\/?$/, meta: { title: '미국 단타', trail: [HOME, { label: '단타', path: '/daytrade' }] } },
    { pattern: /^\/daytrade\/?$/, meta: { title: '단타', trail: [HOME] } },
    { pattern: /^\/history\/?$/, meta: { title: '거래 이력', trail: [HOME] } },
    { pattern: /^\/coin\/?$/, meta: { title: '코인 자동매매', trail: [HOME] } },
    { pattern: /^\/simulation\/?$/, meta: { title: '시뮬레이션', trail: [HOME] } },
    { pattern: /^\/settings\/live\/?$/, meta: { title: '실투자 설정', trail: [HOME, { label: '설정', path: '/settings' }] } },
    { pattern: /^\/settings\/?$/, meta: { title: '설정', trail: [HOME] } },
    { pattern: /^\/live\/?$/, meta: { title: '실투자 관리', trail: [HOME] } },
    { pattern: /^\/members\/?$/, meta: { title: '회원 관리', trail: [HOME] } },
    { pattern: /^\/mypage\/?$/, meta: { title: '내 정보', trail: [HOME] } },
    { pattern: /^\/posts\/[^/]+/, meta: { title: '게시글', trail: [HOME, { label: '게시판', path: '/posts' }] } },
    { pattern: /^\/posts\/?$/, meta: { title: '게시판', trail: [HOME] } },
    { pattern: /^\/not-found\/?$/, meta: { title: '페이지를 찾을 수 없습니다' } },
];

export function pageMeta(path: string): PageMeta {
    const clean = String(path || '/').split(/[?#]/)[0] || '/';
    for (const page of PAGES) {
        if (page.pattern.test(clean)) return page.meta;
    }
    return { title: '' };
}

export function documentTitle(meta: PageMeta): string {
    return meta?.title ? `${meta.title} | ${SITE_NAME}` : SITE_NAME;
}

function upsertMeta(attr: 'name' | 'property', key: string, content: string) {
    let el = document.head.querySelector(`meta[${attr}="${key}"]`) as HTMLMetaElement | null;
    if (!el) {
        el = document.createElement('meta');
        el.setAttribute(attr, key);
        document.head.appendChild(el);
    }
    el.setAttribute('content', content);
}

export function applyPageMeta(path: string) {
    try {
        const meta = pageMeta(path);
        const title = documentTitle(meta);
        document.title = title;
        upsertMeta('name', 'description', meta.description || SITE_DESCRIPTION);
        upsertMeta('name', 'robots', meta.index ? 'index, follow' : 'noindex, nofollow');
        upsertMeta('property', 'og:title', title);
        let canonical = document.head.querySelector('link[rel="canonical"]') as HTMLLinkElement | null;
        if (!canonical) {
            canonical = document.createElement('link');
            canonical.setAttribute('rel', 'canonical');
            document.head.appendChild(canonical);
        }
        canonical.setAttribute('href', window.location.origin + String(path || '/').split(/[?#]/)[0]);
    } catch (e) {
        // Metadata must never break navigation.
    }
}
