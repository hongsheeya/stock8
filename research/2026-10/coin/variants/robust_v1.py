"""EXPLORATORY (post-hoc, after the pre-registered verdict kept V0): is V1's
gain from a wider stop structural or luck?
- neighbourhood: k in {2, 2.5, 3, 4, 5, 6} on both periods, base and 2x cost
- breadth: k=2 vs k=4 on large caps outside the 4 coins (each coin alone,
  2019-10-21..2026-10-24), counted, not selected
No result here can promote a rule by itself; see RESULT.md."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("vstudy", os.path.join(HERE, "study.py"))
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)

KS = (2.0, 2.5, 3.0, 4.0, 5.0, 6.0)
OTHERS = ["KRW-ADA", "KRW-DOGE", "KRW-BCH", "KRW-XLM", "KRW-TRX", "KRW-ETC", "KRW-LINK", "KRW-DOT",
          "KRW-AVAX", "KRW-ATOM", "KRW-HBAR", "KRW-SUI", "KRW-NEAR", "KRW-SAND", "KRW-QTUM", "KRW-BSV"]


def with_k(k):
    V.VARIANTS["K"] = lambda c, a, b: V.replay_4h(c, a, b, k=k)
    V.LABEL["K"] = f"ATR×{k:g}"
    return "K"


def main():
    print("== 손절 폭 이웃값 (연수익 / 낙폭 / MAR) ==")
    for k in KS:
        name = with_k(k)
        a = V.run(name, V.MARKETS, V.SELECT)
        a2 = V.run(name, V.MARKETS, V.SELECT, fee=0.002)
        h = V.run(name, V.MARKETS[:3], V.HOLDOUT)
        print(f"ATR×{k:<3g} 선정 연{a['cagr']:+6.1f}% 낙폭{a['mdd']:+6.1f}% MAR{a['mar']:5.2f} | 비용2배 연{a2['cagr']:+6.1f}% "
              f"| 시험 연{h['cagr']:+6.1f}% 낙폭{h['mdd']:+6.1f}% MAR{h['mar']:5.2f} | 거래 {a['trades']}/{h['trades']} 평균보유 {a['hold']:.1f}일", flush=True)

    print("\n== 다른 대형 코인 하나씩 (2019-10-21~2026-10-24, 상장 전 현금): ATR×2 vs ATR×4 ==")
    better = 0
    rows = []
    for m in OTHERS:
        if not V.candles(m):
            continue
        r2 = V.run(with_k(2.0), [m], V.SELECT)
        r4 = V.run(with_k(4.0), [m], V.SELECT)
        better += r4["cagr"] > r2["cagr"]
        rows.append((m, r2, r4))
        print(f"  {m.split('-')[1]:5s} ×2 연{r2['cagr']:+6.1f}% 낙폭{r2['mdd']:+6.1f}% | ×4 연{r4['cagr']:+6.1f}% 낙폭{r4['mdd']:+6.1f}%", flush=True)
    print(f"ATR×4가 연수익이 높은 코인: {better}/{len(rows)}")
    print(f"ATR×4가 낙폭도 -35% 이내: {sum(r4['mdd'] >= -35 for _m, _r2, r4 in rows)}/{len(rows)} (×2: {sum(r2['mdd'] >= -35 for _m, r2, _r4 in rows)}/{len(rows)})")


if __name__ == "__main__":
    main()
