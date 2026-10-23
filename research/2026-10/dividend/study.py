"""Dividend event study for a Korean-resident investor (KIS account).

Builds every ex-dividend event from UNADJUSTED (split-adjusted only) Yahoo daily bars, evaluates
capture / run-up / post-ex / combined strategies under several cost+tax scenarios, the ex-date drop
ratio, buy-and-hold baselines and a one-slot capital-recycling simulation.

Outputs (./results):
  events_long.csv.gz   one row per (event, strategy) with returns under every scenario
  summary.csv          stats per (strategy, group, period, scenario)
  drop_ratio.csv       ex-date drop / dividend by group and period; drop_ratio_ticker.csv per ticker
  buyhold.csv          CAGR / MDD with net dividends reinvested, per ticker and period
  slot_sim.csv         one-account capital recycling per (strategy, group, scenario), 2015-2026
"""
import math
import os

import numpy as np
import pandas as pd

from fetch import KR_ETFS, KR_STOCKS, US_CC_ETFS, US_DIV_ETFS, US_STOCKS, path_for

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
os.makedirs(RES, exist_ok=True)

# ----------------------------------------------------------------------------------------------
# Universe, tax and cost model
# ----------------------------------------------------------------------------------------------
GROUP = {}
for s in US_STOCKS:
    GROUP[s] = "US_STOCK"
for s in US_DIV_ETFS:
    GROUP[s] = "US_DIV_ETF"
for s in US_CC_ETFS:
    GROUP[s] = "US_CC_ETF"
for s in KR_STOCKS:
    GROUP[s] = "KR_STOCK"
for s in KR_ETFS:
    GROUP[s] = "KR_ETF"
MKT = {s: ("KR" if s.endswith(".KS") else "US") for s in GROUP}
PROXY = {"US": "SPY", "KR": "069500.KS"}

# Net dividend factor after withholding.
#   US source dividends: 15% (Korea-US treaty); no extra Korean withholding because 15% >= 14%.
#   BTI (UK ADR): UK levies no withholding, so the Korean broker withholds 15.4%.
#   ENB (Canada): treaty 15% assumed (25% if treaty relief is not applied - see caveats).
#   Korean dividends / ETF distributions: 15.4% (14% + 1.4% local).
DIV_NET = {s: (0.846 if MKT[s] == "KR" else 0.85) for s in GROUP}
DIV_NET["BTI"] = 0.846
KR_SELL_TAX = {s: 0.0020 for s in KR_STOCKS}  # 2026 rate (KOSPI 0.05% + rural special 0.15%); ETFs exempt
KR_GAIN_TAX = {"458730.KS": 0.154}  # KR-listed ETF on US stocks: sale gain taxed as dividend income (loss not deductible)
US_CGT = 0.22  # overseas-stock capital gains tax incl. local tax, only in the *_CGT scenario

SCENARIOS = ["RAW", "DIVTAX", "OPT", "BASE", "BASE_FX", "OPT_CGT"]
SCEN_DESC = {
    "RAW": "no tax, no cost (gross dividend) - pure market behaviour",
    "DIVTAX": "dividend withholding only (US 15%, KR 15.4%), zero trading cost",
    "OPT": "DIVTAX + US comm 0.07%/side, spread 0.05%/side, SEC 0.0028% on sells; KR comm 0.015%/side, spread 0.05%/side, KR stock sell tax 0.20%",
    "BASE": "as OPT but US comm 0.25%/side",
    "BASE_FX": "BASE + KRW->USD->KRW conversion 0.25% each way (US only)",
    "OPT_CGT": "OPT + 22% overseas CGT applied symmetrically to the US price leg net of costs (investor already above the 2.5M KRW deduction)",
}


def cost_params(scen, mkt):
    if scen in ("RAW", "DIVTAX"):
        return 0.0, 0.0, 0.0, 0.0
    if mkt == "US":
        comm = 0.0007 if scen in ("OPT", "OPT_CGT") else 0.0025
        fx = 0.0025 if scen == "BASE_FX" else 0.0
        return comm, 0.0005, 0.000028, fx
    return 0.00015, 0.0005, 0.0, 0.0


PERIODS = {
    "2005-2014": ("2005-01-01", "2014-12-31"),  # US only (KR Yahoo data before 2015 is unreliable)
    "2015-2019": ("2015-01-01", "2019-12-31"),
    "2020-2022": ("2020-01-01", "2022-12-31"),
    "2023-2026": ("2023-01-01", "2026-12-31"),
    "2015-2026": ("2015-01-01", "2026-12-31"),
}
MANUAL_BREAKS = {"MO": ["2007-04-02", "2008-03-31"]}  # Kraft / PMI spin-offs not flagged by Yahoo

# strategy -> (entry offset vs ex index, exit offset, exit kind). Entry is always at that day's close.
STRATS = {
    "C_open": (-1, 0, "open"), "C_close": (-1, 0, "close"), "C_+3": (-1, 3, "close"),
    "C_+5": (-1, 5, "close"), "C_+10": (-1, 10, "close"), "C_+20": (-1, 20, "close"),
    "R_5": (-6, -1, "close"), "R_10": (-11, -1, "close"), "R_20": (-21, -1, "close"),
    "P_3": (0, 3, "close"), "P_5": (0, 5, "close"), "P_10": (0, 10, "close"), "P_20": (0, 20, "close"),
}
for n in (5, 10, 20):
    STRATS[f"X{n}_open"] = (-1 - n, 0, "open")
    STRATS[f"X{n}_close"] = (-1 - n, 0, "close")
    for k in (5, 10, 20):
        STRATS[f"X{n}_+{k}"] = (-1 - n, k, "close")
REC = {"C_rec10": 10, "C_rec20": 20}  # buy cum close, sell first close >= buy price within K days, else day K


# ----------------------------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------------------------
def load(sym):
    df = pd.read_csv(path_for(sym), index_col=0, parse_dates=True)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df[df.index >= "2004-06-01"]
    C = df["Close"].to_numpy(float)
    O = df["Open"].to_numpy(float)
    V = df["Volume"].fillna(0).to_numpy(float)
    D = df["Dividends"].fillna(0).to_numpy(float)
    S = df["Stock Splits"].fillna(0).to_numpy(float)
    valid = np.isfinite(C) & np.isfinite(O) & (C > 0) & (O > 0) & (V > 0)
    Cf = pd.Series(np.where(valid | (np.isfinite(C) & (C > 0)), C, np.nan)).ffill().bfill().to_numpy()
    Of = np.where(np.isfinite(O) & (O > 0), O, Cf)
    brk = np.zeros(len(df), bool)
    for i, s in enumerate(S):  # spin-offs show up as non-integer "splits"
        if s > 0:
            r = s if s >= 1 else 1 / s
            if abs(r - round(r)) > 1e-6:
                brk[i] = True
    gaps = np.r_[0, np.diff(df.index.values).astype("timedelta64[D]").astype(int)]
    brk |= gaps > 12  # trading halts
    ret = np.r_[0.0, (Cf[1:] + D[1:]) / Cf[:-1] - 1]
    brk |= np.abs(ret) > 0.40
    for d in MANUAL_BREAKS.get(sym, []):
        brk |= df.index == pd.Timestamp(d)
    return {"dates": df.index, "C": Cf, "O": Of, "D": D, "CD": np.cumsum(D), "valid": valid,
            "CB": np.cumsum(brk), "ret": ret}


def align_proxy(stock, proxy):
    """Proxy close/open/cum-dividends/valid on the stock's dates (NaN where proxy has no bar)."""
    idx = stock["dates"]
    pdates = proxy["dates"]
    s = lambda a: pd.Series(a, index=pdates)
    C = s(np.where(proxy["valid"], proxy["C"], np.nan)).reindex(idx).to_numpy()
    O = s(np.where(proxy["valid"], proxy["O"], np.nan)).reindex(idx).to_numpy()
    CD = s(proxy["CD"]).reindex(idx, method="ffill").to_numpy()
    return C, O, np.nan_to_num(CD)


def beta_of(stock, pC, pCD, start="2015-01-01"):
    d = stock["dates"]
    m = (d >= pd.Timestamp(start)) & stock["valid"] & np.r_[False, stock["valid"][:-1]]
    pr = np.r_[np.nan, (pC[1:] + np.diff(pCD)) / pC[:-1] - 1]
    sr = stock["ret"]
    ok = m & np.isfinite(pr) & (np.abs(sr) < 0.2) & (np.abs(pr) < 0.2)
    if ok.sum() < 200:
        return 1.0
    x, y = pr[ok], sr[ok]
    return float(np.cov(x, y)[0, 1] / np.var(x, ddof=1))


# ----------------------------------------------------------------------------------------------
# Event returns
# ----------------------------------------------------------------------------------------------
def scenario_returns(sym, P0, P1, G):
    """Per-event net return under each scenario. P0 buy price, P1 sell price, G gross dividends received."""
    mkt = MKT[sym]
    out = {}
    price = P1 - P0
    for sc in SCENARIOS:
        if sc == "RAW":
            out[sc] = float((price + G) / P0)
            continue
        comm, spread, sec, fx = cost_params(sc, mkt)
        cost = P0 * (comm + spread + fx) + P1 * (comm + spread + sec + fx)
        if sc not in ("RAW", "DIVTAX"):
            cost = cost + P1 * KR_SELL_TAX.get(sym, 0.0)
        divnet = G * DIV_NET[sym]
        pl = price - cost
        if sym in KR_GAIN_TAX:
            pl = np.where(pl > 0, pl * (1 - KR_GAIN_TAX[sym]), pl)
        if sc == "OPT_CGT" and mkt == "US":
            pl = pl * (1 - US_CGT)
        out[sc] = float((pl + divnet) / P0)
    return out


def build_events():
    proxies = {k: load(v) for k, v in PROXY.items()}
    rows, drops, betas = [], [], {}
    for sym in GROUP:
        st = load(sym)
        pC, pO, pCD = align_proxy(st, proxies[MKT[sym]])
        b = beta_of(st, pC, pCD)
        betas[sym] = b
        C, O, D, CD, valid, CB, dates = st["C"], st["O"], st["D"], st["CD"], st["valid"], st["CB"], st["dates"]
        n = len(C)
        ex_idx = np.flatnonzero(D > 0)
        start = pd.Timestamp("2005-01-01" if MKT[sym] == "US" else "2015-01-01")
        for e in ex_idx:
            if dates[e] < start or e < 1 or not (valid[e] and valid[e - 1]):
                continue
            if CB[e] != CB[e - 1]:
                continue
            exd = dates[e]
            yld = D[e] / C[e - 1]
            if yld > 0.15:  # implausible single distribution (data error)
                continue
            # --- ex-date drop ratio (raw and beta-adjusted with the proxy) ---
            rm_on = (pO[e] + (pCD[e] - pCD[e - 1])) / pC[e - 1] - 1 if np.isfinite(pO[e]) and np.isfinite(pC[e - 1]) else np.nan
            rm_day = (pC[e] + (pCD[e] - pCD[e - 1])) / pC[e - 1] - 1 if np.isfinite(pC[e]) and np.isfinite(pC[e - 1]) else np.nan
            drops.append({"sym": sym, "group": GROUP[sym], "ex_date": exd, "div": D[e], "cum_close": C[e - 1],
                          "ex_open": O[e], "ex_close": C[e], "yield": yld,
                          "drop_open": C[e - 1] - O[e], "drop_close": C[e - 1] - C[e],
                          "drop_open_adj": C[e - 1] * (1 + b * rm_on) - O[e],
                          "drop_close_adj": C[e - 1] * (1 + b * rm_day) - C[e]})
            # --- fixed-window strategies ---
            for name, (a, z, kind) in STRATS.items():
                t0, t1 = e + a, e + z
                if t0 < 0 or t1 >= n or not (valid[t0] and valid[t1]) or CB[t1] != CB[t0]:
                    continue
                P0 = C[t0]
                P1 = O[t1] if kind == "open" else C[t1]
                G = CD[t1] - CD[t0]
                M1 = pO[t1] if kind == "open" else pC[t1]
                Rm = (M1 + (pCD[t1] - pCD[t0])) / pC[t0] - 1 if np.isfinite(M1) and np.isfinite(pC[t0]) else np.nan
                r = scenario_returns(sym, P0, P1, G)
                rows.append({"sym": sym, "group": GROUP[sym], "ex_date": exd, "strategy": name,
                             "entry_date": dates[t0], "exit_date": dates[t1], "exit_kind": kind, "hd": t1 - t0,
                             "yield": yld, "beta": b, "Rm": Rm, **r})
            # --- recovery exit ---
            for name, K in REC.items():
                t0 = e - 1
                if e + K >= n:
                    continue
                t1 = None
                for t in range(e, e + K + 1):
                    if valid[t] and C[t] >= C[t0]:
                        t1 = t
                        break
                if t1 is None:
                    t1 = e + K
                    while t1 > e and not valid[t1]:
                        t1 -= 1
                if not valid[t1] or CB[t1] != CB[t0]:
                    continue
                P0, P1 = C[t0], C[t1]
                G = CD[t1] - CD[t0]
                Rm = (pC[t1] + (pCD[t1] - pCD[t0])) / pC[t0] - 1 if np.isfinite(pC[t1]) and np.isfinite(pC[t0]) else np.nan
                r = scenario_returns(sym, P0, P1, G)
                rows.append({"sym": sym, "group": GROUP[sym], "ex_date": exd, "strategy": name,
                             "entry_date": dates[t0], "exit_date": dates[t1], "exit_kind": "close", "hd": t1 - t0,
                             "yield": yld, "beta": b, "Rm": Rm, **r})
    ev = pd.DataFrame(rows)
    dr = pd.DataFrame(drops)
    return ev, dr, betas


# ----------------------------------------------------------------------------------------------
# Statistics
# ----------------------------------------------------------------------------------------------
def cluster_t(r, keys):
    r = np.asarray(r, float)
    n = len(r)
    if n < 3:
        return np.nan
    m = r.mean()
    s = pd.Series(r - m).groupby(np.asarray(keys)).sum().to_numpy()
    G = len(s)
    if G < 3:
        return np.nan
    var = (G / (G - 1)) * np.sum(s ** 2) / n ** 2
    return m / math.sqrt(var) if var > 0 else np.nan


def week_key(dates):
    iso = pd.DatetimeIndex(dates).isocalendar()
    return (iso["year"].astype(int) * 100 + iso["week"].astype(int)).to_numpy()


def describe(sub, col):
    r = sub[col].to_numpy(float)
    n = len(r)
    if n == 0:
        return None
    keys = week_key(sub["ex_date"])
    sd = r.std(ddof=1) if n > 1 else np.nan
    srt = np.sort(r)
    ex5 = srt[:-5].mean() if n > 10 else np.nan
    ar = r - sub["beta"].to_numpy(float) * sub["Rm"].to_numpy(float)
    okar = np.isfinite(ar)
    return {
        "n": n, "mean%": 100 * r.mean(), "median%": 100 * np.median(r), "win%": 100 * (r > 0).mean(),
        "t": r.mean() / (sd / math.sqrt(n)) if n > 1 and sd > 0 else np.nan,
        "t_clu": cluster_t(r, keys), "hd": sub["hd"].mean(),
        "per_day%": 100 * r.mean() / sub["hd"].mean(),
        "mean_ex_top5%": 100 * ex5 if np.isfinite(ex5) else np.nan,
        "AR%": 100 * ar[okar].mean() if okar.any() else np.nan,
        "AR_t_clu": cluster_t(ar[okar], keys[okar]) if okar.sum() > 2 else np.nan,
    }


def group_sets(ev):
    sets = {g: ev["group"] == g for g in ["US_STOCK", "US_DIV_ETF", "US_CC_ETF", "KR_STOCK", "KR_ETF"]}
    sets["US_ALL"] = ev["group"].isin(["US_STOCK", "US_DIV_ETF", "US_CC_ETF"])
    dec = pd.DatetimeIndex(ev["ex_date"]).month == 12
    sets["KR_STOCK_DEC"] = (ev["group"] == "KR_STOCK") & dec
    sets["KR_STOCK_NONDEC"] = (ev["group"] == "KR_STOCK") & ~dec
    return sets


def summarize(ev):
    out = []
    sets = group_sets(ev)
    exd = pd.DatetimeIndex(ev["ex_date"])
    for pname, (a, b) in PERIODS.items():
        pm = (exd >= pd.Timestamp(a)) & (exd <= pd.Timestamp(b))
        for gname, gm in sets.items():
            if pname == "2005-2014" and gname.startswith("KR"):
                continue
            base = ev[pm & gm]
            for strat, sub in base.groupby("strategy"):
                for sc in SCENARIOS:
                    if sc in ("BASE_FX", "OPT_CGT") and gname.startswith("KR"):
                        continue
                    d = describe(sub, sc)
                    if d:
                        out.append({"period": pname, "group": gname, "strategy": strat, "scenario": sc, **d})
    s = pd.DataFrame(out)
    s["fragile"] = (np.sign(s["mean%"]) != np.sign(s["mean_ex_top5%"])) & s["mean_ex_top5%"].notna()
    return s


def drop_summary(dr):
    out = []
    exd = pd.DatetimeIndex(dr["ex_date"])
    sets = {g: dr["group"] == g for g in ["US_STOCK", "US_DIV_ETF", "US_CC_ETF", "KR_STOCK", "KR_ETF"]}
    sets["US_ALL"] = dr["group"].str.startswith("US")
    for pname, (a, b) in PERIODS.items():
        pm = (exd >= pd.Timestamp(a)) & (exd <= pd.Timestamp(b))
        for gname, gm in sets.items():
            if pname == "2005-2014" and gname.startswith("KR"):
                continue
            sub = dr[pm & gm]
            if len(sub) < 3:
                continue
            row = {"period": pname, "group": gname, "n": len(sub), "yield_med%": 100 * sub["yield"].median()}
            keys = week_key(sub["ex_date"])
            for col in ["drop_open", "drop_close", "drop_open_adj", "drop_close_adj"]:
                a_ = (sub[col] / sub["cum_close"]).to_numpy(float)
                b_ = sub["yield"].to_numpy(float)
                ok = np.isfinite(a_)
                a_, b_, k_ = a_[ok], b_[ok], keys[ok]
                ratio = a_.sum() / b_.sum()
                u = a_ - ratio * b_
                s = pd.Series(u).groupby(k_).sum().to_numpy()
                G = len(s)
                se = math.sqrt((G / (G - 1)) * np.sum(s ** 2)) / b_.sum()
                per = a_ / b_
                lo, hi = np.percentile(per, [5, 95])
                row[f"{col}_pooled"] = ratio
                row[f"{col}_se"] = se
                row[f"{col}_median"] = np.median(per)
                row[f"{col}_wmean"] = np.clip(per, lo, hi).mean()
            out.append(row)
    return pd.DataFrame(out)


def drop_by_ticker(dr):
    out = []
    sub = dr[pd.DatetimeIndex(dr["ex_date"]) >= pd.Timestamp("2015-01-01")]
    for sym, g in sub.groupby("sym"):
        a = (g["drop_open_adj"] / g["cum_close"]).to_numpy(float)
        c = (g["drop_close_adj"] / g["cum_close"]).to_numpy(float)
        y = g["yield"].to_numpy(float)
        ok = np.isfinite(a) & np.isfinite(c)
        out.append({"sym": sym, "group": g["group"].iloc[0], "n": int(ok.sum()), "yield_med%": 100 * np.median(y),
                    "drop_open_adj_pooled": a[ok].sum() / y[ok].sum(), "drop_close_adj_pooled": c[ok].sum() / y[ok].sum(),
                    "drop_open_raw_pooled": ((g["drop_open"] / g["cum_close"]).sum()) / y.sum()})
    return pd.DataFrame(out)


# ----------------------------------------------------------------------------------------------
# Buy and hold with net dividends reinvested
# ----------------------------------------------------------------------------------------------
def buyhold():
    out = []
    syms = list(GROUP) + ["SPY", "069500.KS"]
    for sym in syms:
        st = load(sym)
        net = DIV_NET.get(sym, 0.85 if not sym.endswith(".KS") else 0.846)
        C, D, dates, valid = st["C"], st["D"], st["dates"], st["valid"]
        for pname, (a, b) in PERIODS.items():
            if pname == "2005-2014" and sym.endswith(".KS"):
                continue
            m = (dates >= pd.Timestamp(a)) & (dates <= pd.Timestamp(b))
            idx = np.flatnonzero(m)
            if len(idx) < 60:
                continue
            i0 = idx[0]
            while i0 < idx[-1] and not valid[i0]:
                i0 += 1
            i1 = idx[-1]
            while i1 > i0 and not valid[i1]:
                i1 -= 1
            seg = np.arange(i0, i1 + 1)
            gr = (C[seg][1:] + net * D[seg][1:]) / C[seg][:-1]
            tr = np.r_[1.0, np.cumprod(gr)]
            years = (dates[i1] - dates[i0]).days / 365.25
            cagr = tr[-1] ** (1 / years) - 1 if years > 0.5 else np.nan
            mdd = (tr / np.maximum.accumulate(tr) - 1).min()
            pr = C[i1] / C[i0]
            out.append({"sym": sym, "group": GROUP.get(sym, "BENCH"), "period": pname,
                        "start": dates[i0].date(), "end": dates[i1].date(), "years": round(years, 2),
                        "CAGR_netdiv%": 100 * cagr, "price_CAGR%": 100 * (pr ** (1 / years) - 1) if years > 0.5 else np.nan,
                        "MDD%": 100 * mdd, "full_period": abs((dates[i0] - pd.Timestamp(a)).days) < 10})
    return pd.DataFrame(out)


# ----------------------------------------------------------------------------------------------
# One-account capital recycling (one position at a time, greedy, highest announced yield first)
# ----------------------------------------------------------------------------------------------
def slot_sim(ev, groups, strategies, scenarios, start="2015-01-01", end="2026-10-21"):
    out = []
    sets = group_sets(ev)
    span = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    base = ev[pd.DatetimeIndex(ev["entry_date"]) >= pd.Timestamp(start)]
    for g in groups:
        bg = base[sets[g].loc[base.index]]
        for strat in strategies:
            sub = bg[bg["strategy"] == strat].sort_values(["entry_date", "yield"], ascending=[True, False])
            if sub.empty:
                continue
            taken = []
            last_exit, last_kind = None, None
            for i, r in zip(sub.index, sub[["entry_date", "exit_date", "exit_kind"]].itertuples(index=False)):
                ed = r.entry_date
                if last_exit is None or ed > last_exit or (ed == last_exit and last_kind == "open"):
                    taken.append(i)
                    last_exit, last_kind = r.exit_date, r.exit_kind
            tk = sub.loc[taken]
            yrs = pd.DatetimeIndex(tk["entry_date"]).year
            for sc in scenarios:
                if sc in ("BASE_FX", "OPT_CGT") and g.startswith("KR"):
                    continue
                r = tk[sc].to_numpy(float)
                eq = np.prod(1 + r)
                yearly = pd.Series(1 + r).groupby(yrs).prod() - 1
                out.append({"group": g, "strategy": strat, "scenario": sc, "trades": len(r),
                            "trades_per_year": len(r) / span, "mean_trade%": 100 * r.mean(),
                            "win%": 100 * (r > 0).mean(), "days_invested_share%": 100 * tk["hd"].sum() / (252 * span),
                            "CAGR%": 100 * (eq ** (1 / span) - 1), "worst_year%": 100 * yearly.min(),
                            "best_year%": 100 * yearly.max(), "pos_years": int((yearly > 0).sum()), "years": len(yearly)})
    return pd.DataFrame(out)


if __name__ == "__main__":
    ev, dr, betas = build_events()
    ev.to_csv(os.path.join(RES, "events_long.csv.gz"), index=False, compression="gzip")
    dr.to_csv(os.path.join(RES, "drops.csv"), index=False)
    pd.Series(betas, name="beta").to_csv(os.path.join(RES, "betas.csv"))
    summ = summarize(ev)
    summ.to_csv(os.path.join(RES, "summary.csv"), index=False)
    ds = drop_summary(dr)
    ds.to_csv(os.path.join(RES, "drop_ratio.csv"), index=False)
    drop_by_ticker(dr).to_csv(os.path.join(RES, "drop_ratio_ticker.csv"), index=False)
    bh = buyhold()
    bh.to_csv(os.path.join(RES, "buyhold.csv"), index=False)
    strategies = sorted(ev["strategy"].unique())
    ss = slot_sim(ev, ["US_STOCK", "US_DIV_ETF", "US_CC_ETF", "US_ALL", "KR_STOCK", "KR_ETF"], strategies,
                  ["RAW", "DIVTAX", "OPT", "BASE", "BASE_FX", "OPT_CGT"])
    ss.to_csv(os.path.join(RES, "slot_sim.csv"), index=False)
    print("events:", ev.groupby(["group", "strategy"]).size().unstack(0).loc[["C_open", "C_+20", "R_20"]])
    print("done")
