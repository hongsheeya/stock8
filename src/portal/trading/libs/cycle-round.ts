// 무한매수 사이클의 '회차' 표시 (11-29).
//
// FireGate v4의 회차는 소수 T다(T 15.9). current_round는 그 T를 내림한 정수라서
// 대시보드가 "15/20"으로 보여 줄 때 FireGate 화면과 달라 보였다. 매수·매도
// 계획(engine._firegate_v4_t_value)도 소수 T를 쓰므로 화면도 T를 보여 준다.
//
// t_value가 0이거나 비어 있으면 FireGate T가 없는 사이클이다(PAPER 등: 컬럼 기본값
// 0.0). 그때는 예전처럼 정수 회차를 보여 주고 'T'라고 부르지 않는다.

export function cycleT(cycle: any): number | null {
    const raw = cycle ? cycle.t_value : null;
    if (raw === null || raw === undefined || raw === '') return null;
    const t = Number(raw);
    return Number.isFinite(t) && t > 0 ? t : null;
}

export function formatT(t: number): string {
    return String(Math.round(t * 100) / 100);
}

function divisionOf(cycle: any): number {
    const n = Number(cycle ? cycle.division_count : 0);
    return Number.isFinite(n) && n > 0 ? n : 0;
}

// "T 15.9 / 20" — or "회차 15 / 20" (roundWord) when the cycle has no FireGate T.
export function roundLabel(cycle: any, roundWord: string = ''): string {
    const t = cycleT(cycle);
    const division = divisionOf(cycle);
    if (t !== null) return `T ${formatT(t)} / ${division}`;
    const current = Number(cycle ? cycle.current_round : 0) || 0;
    return `${roundWord ? roundWord + ' ' : ''}${current} / ${division}`;
}

export function roundProgress(cycle: any): number {
    const division = divisionOf(cycle);
    if (division <= 0) return 0;
    const t = cycleT(cycle);
    const value = t !== null ? t : (Number(cycle ? cycle.current_round : 0) || 0);
    return Math.max(0, Math.min(100, Math.round(value / division * 100)));
}

// FireGate reverse mode, as far as the screen can tell without asking FireGate:
// FireGate's exhausted rule (T > splits - 1), under which the reservations
// follow FireGate's reverse guide (firegate_bridge.is_exhausted_v4). The pages
// do not load FireGate's reverseState, so a reverse portfolio whose T has
// already dropped below that (reverse sells multiply T by 0.9) shows nothing.
export function reverseLabel(cycle: any): string {
    const t = cycleT(cycle);
    const division = divisionOf(cycle);
    if (t !== null && division > 0 && t > division - 1) return '소진 · 리버스 기준';
    return '';
}
