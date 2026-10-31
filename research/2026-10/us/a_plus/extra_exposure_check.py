"""Post-hoc check (not pre-registered): is E3's gain timing or just lower
average exposure? Compare with A held at E3's average risk weight."""
import numpy as np
import pandas as pd
import study as s

ws, curves_e3 = [], []
for idx, etf in s.PAIRS:
    W = s.sleeve_a(idx, etf, vol=(0.35, 0.20))
    w = W[etf][W.index >= s.START]
    ws.append(w[w > 0].mean())
avg = float(np.mean(ws))
print(f"E3 average weight while A is on: {avg:.3f}")
for frac in (avg, 0.75, 0.85):
    curves = []
    for idx, etf in s.PAIRS:
        W = s.sleeve_a(idx, etf) * frac
        curves.append(s.run(W, 0.001))
    eq = (curves[0] + curves[1]) / 2
    full, first, second = s.stats(eq), s.stats(eq, s.START, s.SPLIT), s.stats(eq, s.SPLIT, s.END)
    print(f"A x{frac:.2f}: CAGR {full[0]:+.1f} MDD {full[1]:+.1f} MAR {full[2]:.2f} | halves {first[2]:.2f} / {second[2]:.2f} | 2022 {s.year_ret(eq, 2022):+.1f}")
e3 = s.strategy("E3", 0.001, target=0.35, band=0.20)
print("E3 rolling 3y CAGR minus A x avg, share of windows E3 better:")
curves = [s.run(s.sleeve_a(i, e) * avg, 0.001) for i, e in s.PAIRS]
ax = (curves[0] + curves[1]) / 2
e3, ax = e3[e3.index >= s.START], ax[ax.index >= s.START]
r3 = (e3 / e3.shift(756)) - (ax / ax.shift(756))
print(f"  {float((r3.dropna() > 0).mean()) * 100:.0f}% of 3-year windows")
