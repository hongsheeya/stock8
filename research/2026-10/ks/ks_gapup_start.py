exec(open("ks_gapup_combo.py", encoding="utf-8").read().split("base, _ = simulate()")[0])
for start in ("09:05", "09:10", "09:15", "09:20", "09:25"):
    combo, gu = simulate(gu_bull_start=start)
    report(f"갭상승일 레버리지 {start}~ (갭상승일분)", gu)
for stop in (1.5, 2.0, 3.5):
    combo, gu = simulate(gu_bull_start="09:15", gu_stop=stop)
    report(f"09:15 손절 -{stop}% (갭상승일분)", gu)
# half split
h = len(days) // 2
combo, gu = simulate(gu_bull_start="09:15")
for name, part in (("앞 6개월", days[:h]), ("뒤 6개월", days[h:])):
    print(name, "갭상승일분 %+.1f%%" % (sum(sum(gu.get(d, [])) for d in part) * 0.33))
