"""Read-only shadow check (10-31): runs coin_shadow_check.check on the LIVE
shadow/probe ledgers and trade_log, without writing shadow_check.json.
Run from the deploy folder (data/live/...)."""
import datetime as dt
import importlib.util
import json
import os
import sqlite3
import time

SRC = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "src", "portal", "trading", "model")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SRC, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


strategy, checker = load("coin_strategy"), load("coin_shadow_check")
owner_dir = next(os.path.join("data/live/coin", d) for d in os.listdir("data/live/coin") if d != "candles")
state = json.load(open(os.path.join(owner_dir, "state_shadow.json"), encoding="utf-8"))
probe = json.load(open(os.path.join(owner_dir, "state_probe.json"), encoding="utf-8"))
markets = set(state["sleeves"]) | set(probe["sleeves"])
candles = {m: json.load(open(f"data/live/coin/candles/{m}_60m.json", encoding="utf-8")) for m in markets}
db = sqlite3.connect("file:data/live/trading.db?mode=ro", uri=True)
sides = {"COIN_SHADOW_BUY": "BUY", "COIN_SHADOW_SELL": "SELL", "COIN_SKIP_BELOW_STOP": "SKIP"}
events = []
for et, sym, created, raw in db.execute("select event_type, symbol, created, raw_response from trade_log "
                                         "where event_type like 'COIN_SHADOW_%' or event_type like 'COIN_SKIP_%' order by created"):
    side, payload = sides.get(et), json.loads(raw or "{}")
    if not side or (side == "SKIP" and not payload.get("shadow")):
        continue
    events.append({"time": checker.kst_epoch(created), "market": sym, "side": side, "bar_end": payload.get("bar_end"),
                   "price": payload.get("price"), "probe": bool(payload.get("probe"))})
ledger = json.load(open(os.path.join(owner_dir, "shadow_check.json")))
summary, _ = checker.check(getattr(strategy, "Model", strategy), state, events, candles, ledger, time.time())
kst = dt.timezone(dt.timedelta(hours=9))
summary["missed_bars"] = [dt.datetime.fromtimestamp(x, kst).strftime("%m-%d %H:%M") for x in summary["missed_bars"]]
print(json.dumps({k: summary[k] for k in ("weeks", "entries", "coverage_pct", "missed_bars", "matched", "compared_count",
                                          "slippage_median_pct", "slippage_samples", "compared")}, ensure_ascii=False, indent=1))
