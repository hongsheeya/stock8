"""Shadow-run progress for the coin rule (10-24): is the live loop doing what
the frozen rule says, and how far along is the pre-registered plan?

- coverage: every 4h close since the shadow run began should have a decision
  (a sleeping PC or a stalled worker shows up as missed bars)
- signal match: the shadow entries/exits against an offline replay of the
  same candles (coin_strategy.replay); entries match on the signal bar, exits
  within EXIT_TOLERANCE_SEC (the live stop watch reacts to ticks, the replay
  to hourly candles). A replay entry the live loop skipped because the bid was
  already at the stop (SPEC 5b) counts as a match.
- slippage: shadow fill prices against the model's (entry at the next 4h
  bar's open, stop exit at min(open, stop)); SPEC gate: median <= 0.15% per side
- gates: 8 weeks, 15 entries, >= 90% signal match, slippage (SPEC / G1 plan)

Pure functions; struct.coin_shadow_progress feeds files and keeps the ledger,
so results survive after the 80-day candle window rolls past them.
"""
import calendar
import datetime

BAR_SEC = 4 * 3600
WARMUP_SEC = 52 * 86400          # SMA50 of daily closes + 55 4h bars + ATR14
EXIT_TOLERANCE_SEC = 2 * 3600
GATE_WEEKS = 8
GATE_ENTRIES = 15
GATE_MATCH = 90.0
GATE_SLIPPAGE = 0.15
MIN_SAMPLES = 5
KST = datetime.timedelta(hours=9)


def kst_epoch(text):
    """trade_log 'created' (KST, naive) -> epoch seconds."""
    stamp = datetime.datetime.fromisoformat(str(text)[:19]) - KST
    return calendar.timegm(stamp.timetuple())


def first_bar_end(sec):
    return (int(sec) // BAR_SEC + 1) * BAR_SEC


def _key(ev):
    return (ev["market"], int(ev.get("bar_end") or first_bar_end(ev["time"]) - BAR_SEC))


def shadow_trades(events):
    """events: [{"time", "market", "side" BUY/SELL/SKIP, "bar_end", "price"}]
    -> ({(market, entry_bar_end): {"exit", "entry_px", "exit_px"}}, {skipped keys})."""
    open_by_market, out, skipped = {}, {}, set()
    for ev in sorted(events, key=lambda e: e["time"]):
        if ev["side"] == "BUY":
            key = _key(ev)
            open_by_market[ev["market"]] = key
            out[key] = {"exit": None, "entry_px": float(ev.get("price") or 0), "exit_px": 0.0}
        elif ev["side"] == "SELL" and ev["market"] in open_by_market:
            out[open_by_market.pop(ev["market"])].update(exit=int(ev["time"]), exit_px=float(ev.get("price") or 0))
        elif ev["side"] == "SKIP":
            skipped.add(_key(ev))
    return out, skipped


def replay_trades(strategy, candles_by_market, start, end):
    """{(market, signal_bar_end): {"exit" (None while open), "entry_px", "exit_px"}}."""
    out = {}
    for market, candles in candles_by_market.items():
        if not candles or int(candles[0]["t"]) + WARMUP_SEC > start:
            continue  # not enough history to judge this window
        for entry_t, epx, exit_t, xpx, why in strategy.replay(candles, start, end):
            out[(market, int(entry_t))] = {"exit": None if why == "end" else int(exit_t), "entry_px": float(epx),
                                           "exit_px": 0.0 if why == "end" else float(xpx)}
    return out


def _slip(model, actual, side):
    """Cost of the real fill against the model, % (positive = worse)."""
    if model <= 0 or actual <= 0:
        return None
    return round(((actual / model - 1) if side == "BUY" else (1 - actual / model)) * 100, 4)


def _median(values):
    v = sorted(values)
    if not v:
        return None
    mid = len(v) // 2
    return round(v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2, 4)


def _compare(key, r, sh, skipped, last_e):
    r_has, s_has = bool(r), bool(sh)
    r_exit, s_exit = r.get("exit"), sh.get("exit")
    if r_has and s_has:
        if r_exit is None and s_exit is None:
            status = "match"  # same entry, both still holding
        elif r_exit is None or s_exit is None:
            # one side exited near the window's end: wait for the next close
            done = r_exit if s_exit is None else s_exit
            status = "pending" if done >= last_e - EXIT_TOLERANCE_SEC else "exit_differs"
        else:
            status = "match" if abs(r_exit - s_exit) <= EXIT_TOLERANCE_SEC else "exit_differs"
    elif r_has and key in skipped:
        status = "match"  # SPEC 5b: price already at the stop, skipped live
    else:
        status = "replay_only" if r_has else "shadow_only"
    slips = []
    if r_has and s_has:
        slips.append(_slip(r.get("entry_px", 0), sh.get("entry_px", 0), "BUY"))
        if r_exit is not None and s_exit is not None:
            slips.append(_slip(r.get("exit_px", 0), sh.get("exit_px", 0), "SELL"))
    return {"market": key[0], "bar_end": key[1], "status": status, "replay_exit": r_exit, "shadow_exit": s_exit,
            "skipped": key in skipped and not s_has, "slippage": [x for x in slips if x is not None]}


def check(strategy, state, events, candles_by_market, ledger, now):
    """Returns (summary, ledger). ledger: {"started_at", "decided": [bar_end],
    "compared": {"MARKET|bar_end": {...}}, "window": [start, end]}."""
    ledger = dict(ledger or {})
    started = int(ledger.get("started_at") or state.get("created_at") or now)
    ledger["started_at"] = started
    first_e = first_bar_end(started)
    last_e = int(now) // BAR_SEC * BAR_SEC

    decided = set(int(x) for x in ledger.get("decided", []))
    decided |= {int(d["bar_end"]) for d in state.get("decisions") or [] if int(d.get("bar_end") or 0) >= first_e}
    ledger["decided"] = sorted(decided)
    expected = list(range(first_e, last_e + 1, BAR_SEC)) if last_e >= first_e else []
    missed = [e for e in expected if e not in decided]

    # compare closed history only: window ends at the last 4h close
    candle_start = min((int(c[0]["t"]) for c in candles_by_market.values() if c), default=now)
    start = max(first_e - BAR_SEC, candle_start + WARMUP_SEC)
    compared = dict(ledger.get("compared") or {})
    if last_e > start:
        replay = replay_trades(strategy, candles_by_market, start, last_e)
        shadow_all, skipped = shadow_trades(events)
        shadow = {k: v for k, v in shadow_all.items() if start <= k[1] <= last_e}
        for key in set(replay) | set(shadow):
            compared[f"{key[0]}|{key[1]}"] = _compare(key, replay.get(key) or {}, shadow.get(key) or {}, skipped, last_e)
        ledger["window"] = [start, last_e]
    ledger["compared"] = compared

    rows = sorted(compared.values(), key=lambda r: r["bar_end"])
    settled = [r for r in rows if r["status"] != "pending"]
    matched = sum(1 for r in settled if r["status"] == "match")
    match_pct = round(matched / len(settled) * 100, 1) if settled else None
    entries = sum(1 for ev in events if ev["side"] == "BUY" and ev["time"] >= started)
    slips = [x for r in rows for x in (r.get("slippage") or [])]
    slip_median = _median(slips)
    weeks = max(0.0, (now - started) / (7 * 86400))
    summary = {
        "started_at": started,
        "weeks": round(weeks, 1),
        "entries": entries,
        "expected_bars": len(expected),
        "decided_bars": len(expected) - len(missed),
        "missed_bars": missed[-12:],
        "missed_count": len(missed),
        "coverage_pct": round((len(expected) - len(missed)) / len(expected) * 100, 1) if expected else None,
        "compared": rows[-20:],
        "compared_count": len(settled),
        "matched": matched,
        "match_pct": match_pct,
        "slippage_median_pct": slip_median,
        "slippage_samples": len(slips),
        "window": ledger.get("window"),
        "gates": {
            "weeks": {"value": round(weeks, 1), "target": GATE_WEEKS, "ok": weeks >= GATE_WEEKS},
            "entries": {"value": entries, "target": GATE_ENTRIES, "ok": entries >= GATE_ENTRIES},
            "match": {"value": match_pct, "target": GATE_MATCH,
                      "ok": match_pct is not None and match_pct >= GATE_MATCH and len(settled) >= MIN_SAMPLES},
            "slippage": {"value": slip_median, "target": GATE_SLIPPAGE,
                         "ok": slip_median is not None and slip_median <= GATE_SLIPPAGE and len(slips) >= MIN_SAMPLES},
        },
        "checked_at": int(now),
    }
    summary["ready"] = all(g["ok"] for g in summary["gates"].values())
    return summary, ledger


class CoinShadowCheck:
    check = staticmethod(check)
    kst_epoch = staticmethod(kst_epoch)
    shadow_trades = staticmethod(shadow_trades)
    replay_trades = staticmethod(replay_trades)
    GATE_WEEKS = GATE_WEEKS
    GATE_ENTRIES = GATE_ENTRIES
    GATE_MATCH = GATE_MATCH
    GATE_SLIPPAGE = GATE_SLIPPAGE


Model = CoinShadowCheck
