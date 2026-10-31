"""Post-hoc (not pre-registered): is W1 better only because it invests less?
Compare with V1 at W1's average entry weight (fixed for every trade)."""
import study as s

for period, name in ((s.SELECT, "select"), (s.HOLDOUT, "holdout")):
    a, b = s.U.epoch(period[0]), s.U.epoch(period[1])
    ws = []
    for m in s.markets_for(period):
        for et, *_r in s.v1_trades(m, a, b):
            v = s.vol30(m, et)
            ws.append(1.0 if not v else min(1.0, 0.60 / v))
    avg = sum(ws) / len(ws)
    curves = []
    for m in s.markets_for(period):
        tr = s.v1_trades(m, a, b)
        curves.append(s.sleeve_curve(s.candles(m), tr, a, b, s.FEE, [avg] * len(tr)))
    print(f"{name}: W1 average weight {avg:.2f} over {len(ws)} trades; V1 at fixed {avg:.2f}: {s.summarize(curves, a, b)}; "
          f"W1: {s.run('W1', period, target=0.60)}")
