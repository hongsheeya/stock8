"""Kimchi premium filter re-test (PREREG.md). Reuses ../more/study.py
(COIN_UNIVERSE_DATA and COIN_EXT_DATA as there)."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("more_study", os.path.join(HERE, "..", "more", "study.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
U = M.U
TH = 0.05
PROBE = ["KRW-DOGE", "KRW-ADA", "KRW-SUI", "KRW-XLM", "KRW-TRX", "KRW-LINK", "KRW-AVAX", "KRW-DOT", "KRW-HBAR", "KRW-NEAR"]
A_PERIOD = ("2019-10-21", "2026-10-24")
B_PERIOD = ("2017-11-15", "2018-01-15")


def sleeve(m, period, filtered):
    a, b = U.epoch(period[0]), U.epoch(period[1])
    allowed = M.premium_filter(TH) if filtered else (lambda t: True)
    tr = M.v1_trades(m, a, b, allowed=allowed)
    weights = []
    for et, *_r in tr:
        v = M.vol30(m, et)
        weights.append(1.0 if not v else min(1.0, 0.60 / v))
    eq = M.sleeve_curve(M.candles(m), tr, a, b, M.FEE, weights)
    return eq, len(tr)


def portfolio(markets, period, filtered):
    curves, per = [], {}
    for m in markets:
        eq, n = sleeve(m, period, filtered)
        curves.append(eq)
        per[m] = ((eq[max(eq)] - 1) * 100, n)
    a, b = U.epoch(period[0]), U.epoch(period[1])
    return M.summarize(curves, a, b), per


def main():
    prem = M.premium_series()
    a, b = U.epoch(B_PERIOD[0]), U.epoch(B_PERIOD[1])
    window = [v for d, v in prem.items() if a <= d < b]
    print(f"B window premium: median {sorted(window)[len(window) // 2] * 100:+.1f}%, max {max(window) * 100:+.1f}%, "
          f">=5% on {sum(v >= TH for v in window)}/{len(window)} days")
    a, b = U.epoch(A_PERIOD[0]), U.epoch(A_PERIOD[1])
    window = [v for d, v in prem.items() if a <= d < b]
    print(f"A window premium >=5% on {sum(v >= TH for v in window) / len(window) * 100:.0f}% of days")

    base_a, per_base = portfolio(PROBE, A_PERIOD, False)
    filt_a, per_filt = portfolio(PROBE, A_PERIOD, True)
    better = sum(1 for m in PROBE if per_filt[m][0] > per_base[m][0] + 1e-9)
    worse = sum(1 for m in PROBE if per_filt[m][0] < per_base[m][0] - 1e-9)
    print(f"\nA base {base_a} | filter {filt_a}")
    for m in PROBE:
        print(f"   {m:9s} base {per_base[m][0]:+8.1f}% ({per_base[m][1]} trades)  filter {per_filt[m][0]:+8.1f}% ({per_filt[m][1]} trades)")
    print(f"   better {better}, worse {worse}")

    early = ["KRW-BTC", "KRW-ETH", "KRW-XRP"]
    base_b, pb = portfolio(early, B_PERIOD, False)
    filt_b, pf = portfolio(early, B_PERIOD, True)
    tot = lambda per: sum(v[0] for v in per.values()) / len(per)
    print(f"\nB base {base_b} total {tot(pb):+.1f}% trades {sum(v[1] for v in pb.values())} | "
          f"filter {filt_b} total {tot(pf):+.1f}% trades {sum(v[1] for v in pf.values())}")

    c = {}
    for name, period, mk in (("select", M.SELECT, M.MARKETS), ("holdout", M.HOLDOUT, M.MARKETS[:3])):
        c[name] = (portfolio(mk, period, False)[0], portfolio(mk, period, True)[0])
        print(f"C {name}: base {c[name][0]} | filter {c[name][1]}")

    gates = {
        "1 A MAR>=base x1.1": filt_a["mar"] >= base_a["mar"] * 1.10,
        f"2 A coins better {better} > worse {worse}": better > worse,
        "3 B total>=base": tot(pf) >= tot(pb),
        "4 C select & holdout MAR>=base": all(f["mar"] >= bs["mar"] for bs, f in c.values()),
    }
    print("\ngates", gates, "->", "PASS" if all(gates.values()) else "FAIL")


if __name__ == "__main__":
    main()
