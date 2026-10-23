"""Parity: stock8's coin_strategy.replay vs the research engine breakout_wf.simulate
(TEST window 2026-06-21..end, 5m candles) and the same decisions from 60m candles."""
import json, os, sys, datetime, importlib.util
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "breakout"))
import breakout_wf as B
spec = importlib.util.spec_from_file_location("cs", r"C:\dev\stock8\src\portal\trading\model\coin_strategy.py")
cs = importlib.util.module_from_spec(spec); spec.loader.exec_module(cs)

def epoch(t):
    return int(datetime.datetime.fromisoformat(t).replace(tzinfo=datetime.timezone.utc).timestamp())

coins = [B.Coin(m) for m in B.MARKETS]
first = max(cn.t[0] for cn in coins)
hour = np.timedelta64(1, "h").astype("timedelta64[ns]")
ps = (first + hour - np.timedelta64(1, "ns")).astype("datetime64[h]").astype("datetime64[ns]")
pe = min(cn.t[-1] for cn in coins) + B.FIVE_MIN
to_sec = lambda x: int(x.astype("datetime64[s]").astype("int64"))
for period, (a, b) in {"TEST": (B.SPLIT, pe), "FULL": (ps, pe)}.items():
    tot_ref = tot_new5 = tot_new60 = 0
    for cn in coins:
        ref, k_ps, k_pe = B.simulate(cn, ("4h", 55, "atr2"), a, b)
        ref_t = [(to_sec(cn.t[ek]), round(epx, 6), to_sec(cn.t[xk]), round(xpx, 6)) for ek, epx, xk, xpx, _ in ref]
        rows5 = json.load(open(os.path.join(B.CANDLES, f"{cn.m}_5m.json")))
        fine = [{"t": epoch(r["t"]), "o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"]} for r in rows5]
        new5 = [(e, round(ep, 6), x, round(xp, 6)) for e, ep, x, xp, _ in cs.replay(fine, to_sec(a), to_sec(b))]
        # 60m candles built from the 5m data: same decisions; stops then judged on 60m bars
        h60 = cs.build_bars(fine, 3600)
        h60 = [{"t": r["start"], "o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"]} for r in h60]
        new60 = cs.replay(h60, to_sec(a), to_sec(b))
        same = ref_t == new5
        entries_ref = [t[0] // 3600 for t in ref_t]
        entries_60 = [e // 3600 for e, *_ in new60]
        r_ref = np.prod([cs.trade_return(t[1], t[3]) + 1 for t in ref_t]) - 1 if ref_t else 0
        r_60 = np.prod([cs.trade_return(t[1], t[3]) + 1 for t in new60]) - 1 if new60 else 0
        tot_ref += r_ref / 5; tot_new60 += r_60 / 5
        print(f"{period} {cn.m:9s} research {len(ref_t):3d} trades | stock8 5m identical={same} | 60m trades {len(new60):3d} "
              f"entry-hours match {sum(1 for x in entries_60 if x in entries_ref)}/{len(entries_ref)} | ret research {r_ref*100:+6.2f}% 60m {r_60*100:+6.2f}%")
        if not same:
            diff = [(i, x, y) for i, (x, y) in enumerate(zip(ref_t, new5)) if x != y][:3]
            print("   first diffs:", diff, len(ref_t), len(new5))
    print(f"{period} portfolio (simple mean of compounded coin returns): research {tot_ref*100:+.2f}%  stock8-60m {tot_new60*100:+.2f}%")
