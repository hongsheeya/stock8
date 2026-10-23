"""10-23: A, robustness. Same pre-registered rules, 0.10%/side.
- fair benchmark: 50/50 QLD+SSO buy-and-hold (same start)
- 1x version (QQQ/SPY instead of QLD/SSO)
- calendar-year returns of the chosen rule vs benchmarks
- signal delay sensitivity (trade 1 extra day late)
- whipsaw count"""
import importlib.util
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("s", os.path.join(HERE, "us_abc_study.py"))
s = importlib.util.module_from_spec(spec); spec.loader.exec_module(s)
COST = 0.10
qqq, spy, qld, sso = s.daily("QQQ"), s.daily("SPY"), s.daily("QLD"), s.daily("SSO")
start = max(qld.index[0], sso.index[0]) + pd.Timedelta(days=400)
RULES = {
    "SMA200": lambda c: c > c.rolling(200).mean(),
    "MOM12m": lambda c: c / c.shift(252) - 1 > 0,
    "MOM6m": lambda c: c / c.shift(126) - 1 > 0,
}


def port(rule, etfs, delay=0):
    eqs = []
    for idx, etf in zip((qqq, spy), etfs):
        sig = rule(idx["Close"]).shift(delay).fillna(False)
        e, _ = s.sleeve_equity(sig, etf, COST)
        e = e[e.index >= start]; eqs.append(e / e.iloc[0])
    return (eqs[0] + eqs[1]) / 2


def bh(etfs):
    eqs = []
    for etf in etfs:
        c = etf["Close"]; c = c[c.index >= start]; eqs.append(c / c.iloc[0])
    return (eqs[0] + eqs[1]) / 2


def line(label, eq):
    (tc, tm), (sc, sm), (fc, fm) = s.split_stats(eq)
    print(f"  {label:28s} 학습 연{tc:+6.1f}% 낙폭{tm:+6.1f}% | 시험 연{sc:+6.1f}% 낙폭{sm:+6.1f}% | 전체 연{fc:+6.1f}% 낙폭{fm:+6.1f}%")


print(f"기간 {start.date()} ~ {qld.index[-1].date()}")
print("== 공정 비교: 같은 50/50 묶음 ==")
line("보유 QLD+SSO", bh((qld, sso)))
line("보유 QQQ+SPY", bh((qqq, spy)))
for name, rule in RULES.items():
    line(f"2배 {name}", port(rule, (qld, sso)))
    line(f"1배 {name}", port(rule, (qqq, spy)))
    line(f"2배 {name} 하루 늦게", port(rule, (qld, sso), delay=1))

print("\n== 연도별 (2배 MOM6m / 2배 SMA200 / 보유 QLD+SSO / 보유 QQQ+SPY) ==")
series = {"MOM6m": port(RULES["MOM6m"], (qld, sso)), "SMA200": port(RULES["SMA200"], (qld, sso)),
          "보유2배": bh((qld, sso)), "보유1배": bh((qqq, spy))}
years = sorted(set(series["MOM6m"].index.year))
for y in years:
    vals = []
    for k, eq in series.items():
        part = eq[eq.index.year == y]
        prev = eq[eq.index.year < y]
        base = prev.iloc[-1] if len(prev) else part.iloc[0]
        vals.append(f"{k} {(part.iloc[-1] / base - 1) * 100:+6.1f}%")
    print(f"  {y}: " + " | ".join(vals))

print("\n== 신호 바뀐 횟수 (QQQ 기준, 연평균) ==")
for name, rule in RULES.items():
    sig = rule(qqq["Close"]); sig = sig[sig.index >= start]
    flips = int((sig != sig.shift()).sum()) - 1
    yrs = (sig.index[-1] - sig.index[0]).days / 365.25
    print(f"  {name}: {flips / yrs:.1f}회/년")
