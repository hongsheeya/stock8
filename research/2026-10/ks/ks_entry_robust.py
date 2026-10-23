exec(open("ks_entry_extension.py", encoding="utf-8").read().split("base = simulate()")[0])
half = len(days) // 2
def halves(trades):
    a = sum(t["ret"] for t in trades if t["day"] < days[half]) * 0.33
    b = sum(t["ret"] for t in trades if t["day"] >= days[half]) * 0.33
    return a, b

def run_filtered(max_move=None, min_vwap=None, cutoff=None):
    out = []
    for t in simulate(max_move=max_move):
        if min_vwap is not None and t["vgap"] < min_vwap:
            continue
        if cutoff is not None and t["hm"] >= cutoff:
            continue
        out.append(t)
    return out
# note: post-filtering skips the trade but does not allow a later re-entry (conservative)
for label, kw in (("현재 규칙", {}), ("3% 넘게 움직였으면 건너뜀", {"max_move": 3.0}), ("2.5% 넘게 움직였으면 건너뜀", {"max_move": 2.5}),
                  ("VWAP 0.3% 미만이면 건너뜀", {"min_vwap": 0.3}), ("11:30 이후 신규 진입 없음", {"cutoff": "11:30"}),
                  ("3% 상한 + VWAP 0.3% 이상", {"max_move": 3.0, "min_vwap": 0.3})):
    tr = run_filtered(**kw)
    a, b = halves(tr)
    summary(label, tr)
    print(f"{'':34s} 앞 반년 {a:+6.1f}% / 뒤 반년 {b:+6.1f}%")
