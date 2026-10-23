exec(open("ks_entry_robust.py", encoding="utf-8").read().split("# note:")[0])
tr = run_filtered(max_move=2.5, min_vwap=0.3)
summary("2.5% 상한 + VWAP 0.3% 이상", tr); a, b = halves(tr); print(f"{'':34s} 앞 반년 {a:+6.1f}% / 뒤 반년 {b:+6.1f}%")
