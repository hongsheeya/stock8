"""Frozen coin rule "breakout 4h_N55_atr4" (10-24; was atr2 from 10-21).

Long-only, one position per market, all-in per sleeve:
- 4h bars on UTC boundaries (00/04/08/12/16/20 UTC = 09/13/17/21/01/05 KST),
  built from Upbit 60m candles (same trades as the research's 5m bars).
- Entry at a 4h close when close > highest high of the previous 55 bars and
  close > SMA50 of completed UTC-day closes (Upbit's 09:00 KST day).
- Exit only by a chandelier stop: highest high since the signal bar minus
  4 x ATR14 (Wilder, alpha 1/14), fixed for a whole bar, ratcheting up.
History: atr2 passed G1 (2019-10..2025-10 CAGR +20.0%, MDD -14.6%). The
10-24 variants study (research/2026-10/coin/variants, 0.10%/side + half a
tick, 25% sleeves) found the x2 stop too tight (average hold 1.2 days):
atr4 2019-10..2026-10 CAGR +41.9% (MDD -21.3%) vs +16.1%, untouched
2018-01..2019-10 holdout +41.7% (MDD -18.6%) vs +11.2%, smooth from x2 to
x5, better on 14 of 16 other coins. atr4 was flagged after the holdout was
seen, so the user restarted the shadow run with it (10-24) as the forward
test. Parameters must not be tuned further.

Pure functions only (no WIZ), so the replay and unit tests can import it.
"""
import math

BAR_SEC = 4 * 3600
DAY_SEC = 24 * 3600
DONCHIAN_N = 55
ATR_N = 14
ATR_K = 4.0
DAILY_MA = 50
# 10-31 W1 volatility sizing (research/2026-10/coin/more, pre-registered):
# entry size = min(1, 60% / the coin's 30-day daily-return volatility,
# annualized with 365 days), fixed for the trade. Signals are unchanged.
VOL_SIZE_TARGET = 0.60
VOL_SIZE_DAYS = 30


def build_bars(candles, bar_sec=BAR_SEC):
    """candles: [{"t": epoch_sec_start, "o","h","l","c"}] oldest first (any
    sub-bar size dividing bar_sec). Returns bars with start/end epoch; a bucket
    without candles produces no bar (indicators count existing bars only)."""
    bars = []
    cur = None
    for row in candles:
        key = int(row["t"]) // bar_sec * bar_sec
        if cur is None or cur["start"] != key:
            if cur is not None:
                bars.append(cur)
            cur = {"start": key, "end": key + bar_sec, "o": float(row["o"]), "h": float(row["h"]),
                   "l": float(row["l"]), "c": float(row["c"])}
        else:
            cur["h"] = max(cur["h"], float(row["h"]))
            cur["l"] = min(cur["l"], float(row["l"]))
            cur["c"] = float(row["c"])
    if cur is not None:
        bars.append(cur)
    return bars


def closed_bars(bars, now_sec):
    return [b for b in bars if b["end"] <= now_sec]


def daily_closes(candles, now_sec):
    """[(day_start, close)] for UTC days that have ended by now_sec."""
    out = []
    for bar in build_bars(candles, DAY_SEC):
        if bar["end"] <= now_sec:
            out.append((bar["start"], bar["c"]))
    return out


def vol_weight(daily, target=VOL_SIZE_TARGET, days=VOL_SIZE_DAYS):
    """daily: [(day_start, close)] of completed days -> (weight, annual vol or None)."""
    closes = [float(c) for _t, c in daily[-(days + 1):]]
    if len(closes) < days + 1:
        return 1.0, None
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    mean = sum(rets) / len(rets)
    vol = (sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5 * 365 ** 0.5
    if vol <= 0:
        return 1.0, vol
    return min(1.0, target / vol), vol


def atr_series(bars, n=ATR_N):
    """Wilder ATR as pandas ewm(alpha=1/n, adjust=False, min_periods=n):
    seeded with the first true range; None until n bars exist."""
    out = []
    value = None
    prev_close = None
    for i, b in enumerate(bars):
        tr = b["h"] - b["l"]
        if prev_close is not None:
            tr = max(tr, abs(b["h"] - prev_close), abs(b["l"] - prev_close))
        value = tr if value is None else value + (tr - value) / n
        out.append(value if i + 1 >= n else None)
        prev_close = b["c"]
    return out


def sma_daily_at(daily, bar_end, n=DAILY_MA):
    """Mean of the last n daily closes whose day ended at or before bar_end."""
    usable = [close for start, close in daily if start + DAY_SEC <= bar_end]
    if len(usable) < n:
        return None
    window = usable[-n:]
    return sum(window) / n


def indicators(bars, daily, j):
    """Values for closed bar j (index into bars)."""
    atr = atr_series(bars[: j + 1])[j] if j >= 0 else None
    hh = max(b["h"] for b in bars[j - DONCHIAN_N:j]) if j >= DONCHIAN_N else None
    sma = sma_daily_at(daily, bars[j]["end"]) if j >= 0 else None
    return {"bar_end": bars[j]["end"], "close": bars[j]["c"], "high": bars[j]["h"], "atr": atr,
            "donchian_high": hh, "sma50d": sma,
            "ready": atr is not None and hh is not None and sma is not None}


def decide(position, ind):
    """One decision at a 4h close. position: {"long": bool, "hh", "stop"}.
    Returns (action, new_position, reason). action in HOLD/ENTER/RATCHET/WAIT."""
    position = dict(position or {})
    if position.get("long"):
        if ind.get("atr") is None:
            return "HOLD", position, "ATR 없음 — 손절가 유지"
        hh = max(float(position.get("hh") or 0), ind["high"])
        stop = max(float(position.get("stop") or 0), hh - ATR_K * ind["atr"])
        changed = stop > float(position.get("stop") or 0) + 1e-12
        position.update(hh=hh, stop=stop)
        return ("RATCHET" if changed else "HOLD"), position, f"손절가 {stop:,.4f}"
    if not ind.get("ready"):
        return "WAIT", position, "지표 준비 중 (일봉 50개·4시간봉 56개 필요)"
    if ind["close"] <= ind["donchian_high"]:
        return "WAIT", position, f"55봉 고점 {ind['donchian_high']:,.4f} 미돌파"
    if ind["close"] <= ind["sma50d"]:
        return "WAIT", position, f"일봉 50일선 {ind['sma50d']:,.4f} 아래"
    stop = ind["high"] - ATR_K * ind["atr"]
    position.update(long=True, hh=ind["high"], stop=stop, signal_bar_end=ind["bar_end"])
    return "ENTER", position, f"55봉 고점 돌파 · 50일선 위 · 손절가 {stop:,.4f}"


def stop_hit(position, price):
    return bool(position.get("long")) and price > 0 and price <= float(position.get("stop") or 0)


def replay(candles_fine, start_sec, end_sec, fee_side=0.001):
    """Offline replay used for parity checks: decisions at each 4h close from
    candles (60m or 5m), stops checked on the fine candles inside the holding
    bar (fill at min(open, stop)), entries at the next bar's first open.
    Returns trades [(entry_t, entry_px, exit_t, exit_px, why)]."""
    bars = build_bars(candles_fine)
    daily_all = build_bars(candles_fine, DAY_SEC)
    daily = [(b["start"], b["c"]) for b in daily_all]
    atr = atr_series(bars)
    by_bar = {}
    for row in candles_fine:
        by_bar.setdefault(int(row["t"]) // BAR_SEC * BAR_SEC, []).append(row)
    trades = []
    pos = {}
    entry = None
    for j, bar in enumerate(bars):
        if bar["end"] < start_sec or bar["start"] >= end_sec:
            continue
        if pos.get("long"):
            for row in by_bar.get(bar["start"], []):
                if int(row["t"]) >= end_sec:
                    break
                if float(row["l"]) <= pos["stop"]:
                    trades.append((entry[0], entry[1], int(row["t"]), min(float(row["o"]), pos["stop"]), "stop"))
                    pos = {}
                    break
            if pos.get("long") and atr[j] is not None:
                pos["hh"] = max(pos["hh"], bar["h"])
                pos["stop"] = max(pos["stop"], pos["hh"] - ATR_K * atr[j])
        if not pos.get("long") and j + 1 < len(bars) and bars[j + 1]["start"] < end_sec:
            hh = max(b["h"] for b in bars[j - DONCHIAN_N:j]) if j >= DONCHIAN_N else None
            sma = sma_daily_at([d for d in daily if d[0] + DAY_SEC <= bar["end"]], bar["end"])
            if hh is None or atr[j] is None or sma is None:
                continue
            if bar["c"] > hh and bar["c"] > sma:
                first = by_bar.get(bars[j + 1]["start"], [])
                if not first or int(first[0]["t"]) < start_sec:
                    continue
                entry = (int(first[0]["t"]), float(first[0]["o"]))
                pos = {"long": True, "hh": bar["h"], "stop": bar["h"] - ATR_K * atr[j]}
    if pos.get("long") and entry:
        last = [r for r in candles_fine if int(r["t"]) < end_sec][-1]
        trades.append((entry[0], entry[1], int(last["t"]), float(last["c"]), "end"))
    return trades


def trade_return(entry_px, exit_px, fee_side=0.001):
    return (exit_px * (1 - fee_side)) / (entry_px * (1 + fee_side)) - 1


def floor_volume(volume, decimals=8):
    q = 10 ** decimals
    return math.floor(float(volume) * q) / q


class CoinStrategy:
    BAR_SEC = BAR_SEC
    ATR_K = ATR_K
    build_bars = staticmethod(build_bars)
    closed_bars = staticmethod(closed_bars)
    daily_closes = staticmethod(daily_closes)
    atr_series = staticmethod(atr_series)
    sma_daily_at = staticmethod(sma_daily_at)
    indicators = staticmethod(indicators)
    decide = staticmethod(decide)
    stop_hit = staticmethod(stop_hit)
    replay = staticmethod(replay)
    trade_return = staticmethod(trade_return)
    floor_volume = staticmethod(floor_volume)
    vol_weight = staticmethod(vol_weight)
    VOL_SIZE_TARGET = VOL_SIZE_TARGET


Model = CoinStrategy
