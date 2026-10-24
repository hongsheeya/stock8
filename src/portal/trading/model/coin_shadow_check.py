"""Shadow-run progress for the coin rule (10-24): is the live loop doing what
the frozen rule says, and how far along is the pre-registered plan?

- coverage: every 4h close since the shadow run began should have a decision
  (a sleeping PC or a stalled worker shows up as missed bars)
- signal match: the shadow entries/exits against an offline replay of the
  same candles (coin_strategy.replay); entries match on the signal bar, exits
  within EXIT_TOLERANCE_SEC (the live stop watch reacts to ticks, the replay
  to hourly candles)
- gates: 8 weeks, 15 entries, >= 90% signal match (SPEC / G1 plan)

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
KST = datetime.timedelta(hours=9)


def kst_epoch(text):
    """trade_log 'created' (KST, naive) -> epoch seconds."""
    stamp = datetime.datetime.fromisoformat(str(text)[:19]) - KST
    return calendar.timegm(stamp.timetuple())


def first_bar_end(sec):
    return (int(sec) // BAR_SEC + 1) * BAR_SEC


def shadow_trades(events):
    """events: [{"time", "market", "side" BUY/SELL, "bar_end"}] oldest first ->
    {(market, entry_bar_end): exit_time or None}."""
    open_by_market, out = {}, {}
    for ev in sorted(events, key=lambda e: e["time"]):
        if ev["side"] == "BUY":
            key = (ev["market"], int(ev.get("bar_end") or first_bar_end(ev["time"]) - BAR_SEC))
            open_by_market[ev["market"]] = key
            out[key] = None
        elif ev["side"] == "SELL" and ev["market"] in open_by_market:
            out[open_by_market.pop(ev["market"])] = int(ev["time"])
    return out


def replay_trades(strategy, candles_by_market, start, end):
    """{(market, signal_bar_end): exit_time or None (still open at end)}."""
    out = {}
    for market, candles in candles_by_market.items():
        if not candles or int(candles[0]["t"]) + WARMUP_SEC > start:
            continue  # not enough history to judge this window
        for entry_t, _epx, exit_t, _xpx, why in strategy.replay(candles, start, end):
            out[(market, int(entry_t))] = None if why == "end" else int(exit_t)
    return out


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
        shadow = {k: v for k, v in shadow_trades(events).items() if start <= k[1] <= last_e}
        for key in set(replay) | set(shadow):
            r_has, s_has = key in replay, key in shadow
            r_exit, s_exit = replay.get(key), shadow.get(key)
            if r_has and s_has:
                if r_exit is None and s_exit is None:
                    status = "match"  # same entry, both still holding
                elif r_exit is None or s_exit is None:
                    # one side exited near the window's end: wait for the next close
                    done = r_exit if s_exit is None else s_exit
                    status = "pending" if done >= last_e - EXIT_TOLERANCE_SEC else "exit_differs"
                else:
                    status = "match" if abs(r_exit - s_exit) <= EXIT_TOLERANCE_SEC else "exit_differs"
            else:
                status = "replay_only" if r_has else "shadow_only"
            compared[f"{key[0]}|{key[1]}"] = {"market": key[0], "bar_end": key[1], "status": status,
                                             "replay_exit": r_exit, "shadow_exit": s_exit}
        ledger["window"] = [start, last_e]
    ledger["compared"] = compared

    rows = sorted(compared.values(), key=lambda r: r["bar_end"])
    settled = [r for r in rows if r["status"] != "pending"]
    matched = sum(1 for r in settled if r["status"] == "match")
    match_pct = round(matched / len(settled) * 100, 1) if settled else None
    entries = sum(1 for ev in events if ev["side"] == "BUY" and ev["time"] >= started)
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
        "window": ledger.get("window"),
        "gates": {
            "weeks": {"value": round(weeks, 1), "target": GATE_WEEKS, "ok": weeks >= GATE_WEEKS},
            "entries": {"value": entries, "target": GATE_ENTRIES, "ok": entries >= GATE_ENTRIES},
            "match": {"value": match_pct, "target": GATE_MATCH, "ok": match_pct is not None and match_pct >= GATE_MATCH and len(settled) >= 5},
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


Model = CoinShadowCheck
