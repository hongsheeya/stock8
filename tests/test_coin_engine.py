"""Coin automation (10-22): frozen breakout rule, shadow/live ledgers, order safety."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

MODEL = Path(__file__).resolve().parents[1] / "src" / "portal" / "trading" / "model"


def _module(name):
    spec = importlib.util.spec_from_file_location(f"coin_{name}", MODEL / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


strategy_mod = _module("coin_strategy")
engine_mod = _module("coin_engine")
S = strategy_mod.CoinStrategy
H = 3600
E0 = 1792540800  # 2026-10-21 00:00 UTC, a 4h boundary


class ApiError(Exception):
    def __init__(self, message, status=0, name=""):
        super().__init__(message)
        self.status = status
        self.name = name


def hourly(start, hours, price_fn):
    rows = []
    for i in range(hours):
        p = price_fn(i)
        rows.append({"t": start + i * H, "o": p, "h": p * 1.002, "l": p * 0.998, "c": p, "v": 1.0})
    return rows


class FakeApi:
    def __init__(self, candles, price):
        self.candles = candles
        self.price = price
        self.buys, self.sells, self.orders = [], [], {}
        self.krw = 10_000_000.0
        self.coin = 0.0
        self.fail_next_buy = None
        self.order_queries = 0

    def minute_candles(self, market, unit=60, count=200, to=None):
        rows = [r for r in self.candles if r["t"] <= self.clock()]
        if to:
            import calendar, time
            limit = calendar.timegm(time.strptime(to, "%Y-%m-%dT%H:%M:%SZ"))
            rows = [r for r in rows if r["t"] < limit]
        return [dict(r) for r in rows[-count:]]

    def orderbook(self, markets):
        return {m: {"bid": self.price * 0.9995, "ask": self.price * 1.0005} for m in markets}

    def ticker(self, markets):
        return {m: {"trade_price": self.price} for m in markets}

    def balances(self):
        return {"KRW": {"balance": self.krw, "locked": 0.0}, "BTC": {"balance": self.coin, "locked": 0.0}}

    def buy_market_krw(self, market, amount, identifier=""):
        self.buys.append((market, amount, identifier))
        if self.fail_next_buy is not None:
            exc, self.fail_next_buy = self.fail_next_buy, None
            if exc.status == 0:  # timeout: the order DID reach the exchange
                self._fill_bid(identifier, amount)
            raise exc
        return self._fill_bid(identifier, amount)

    def _fill_bid(self, identifier, amount):
        volume = round(amount / self.price, 8)
        fee = amount * 0.0005
        self.krw -= amount + fee
        self.coin += volume
        order = {"uuid": f"u-{identifier}", "state": "cancel", "executed_volume": str(volume), "paid_fee": str(fee),
                 "trades": [{"price": str(self.price), "volume": str(volume), "funds": str(amount)}]}
        self.orders[identifier] = order
        return {"uuid": order["uuid"]}

    def sell_market(self, market, volume, identifier="", ref_price=0.0):
        self.sells.append((market, volume, identifier))
        funds = volume * self.price
        fee = funds * 0.0005
        self.coin -= volume
        self.krw += funds - fee
        order = {"uuid": f"u-{identifier}", "state": "done", "executed_volume": str(volume), "paid_fee": str(fee),
                 "trades": [{"price": str(self.price), "volume": str(volume), "funds": str(funds)}]}
        self.orders[identifier] = order
        return {"uuid": order["uuid"]}

    def get_order(self, order_uuid="", identifier=""):
        self.order_queries += 1
        for ident, order in self.orders.items():
            if order["uuid"] == order_uuid or ident == identifier:
                return order
        raise ApiError("order_not_found", 404, "order_not_found")


def breakout_series():
    """75 quiet days at 100, then a strong rally in the last 4h bar of day 75."""
    start = E0 - 76 * 24 * H

    def price(i):
        t = start + i * H
        if t >= E0 - 4 * H:
            return 130.0
        return 100.0 + (i % 7) * 0.1

    return start, hourly(start, 76 * 24 + 12, price)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class CoinEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        _, self.rows = breakout_series()
        self.clock = Clock(E0 + 15)
        self.api = FakeApi(self.rows, 130.0)
        self.api.clock = self.clock
        self.logs = []

    def engine(self, mode="shadow", **policy):
        pol = {"mode": mode, "seed_krw": 1_000_000, "markets": ["KRW-BTC"], **policy}
        return engine_mod.CoinEngine(self.api, os.path.join(self.tmp.name, "state"), os.path.join(self.tmp.name, "candles"),
                                     pol, S, log=lambda *a, **k: self.logs.append(a), now=self.clock, sleep=lambda s: None,
                                     error_cls=ApiError)

    def events(self):
        return [entry[0] for entry in self.logs]

    def test_off_mode_cannot_build_an_engine(self):
        with self.assertRaises(ValueError):
            self.engine("off")

    def test_shadow_breakout_enters_then_stops_out(self):
        eng = self.engine("shadow")
        eng.step()
        sleeve = eng.state["sleeves"]["KRW-BTC"]
        self.assertTrue(sleeve["long"], sleeve["last_reason"])
        self.assertEqual(self.events(), ["COIN_SHADOW_BUY"])
        self.assertEqual(self.api.buys, [])  # shadow never orders
        stop = sleeve["stop"]
        self.assertLess(stop, 130.0)
        self.api.price = stop * 0.99
        self.clock.t += 600
        eng.step()
        self.assertFalse(eng.state["sleeves"]["KRW-BTC"]["long"])
        self.assertEqual(self.events(), ["COIN_SHADOW_BUY", "COIN_SHADOW_SELL"])
        self.assertEqual(eng.state["sleeves"]["KRW-BTC"]["trades"], 1)
        # the ledger survives a restart
        again = self.engine("shadow")
        self.assertEqual(again.state["sleeves"]["KRW-BTC"]["trades"], 1)

    def test_entry_is_skipped_when_the_bid_is_already_at_the_stop(self):
        for mode in ("shadow", "live"):
            with self.subTest(mode=mode):
                self.setUp()
                self.api.price = 1.0  # far below any stop of the 130 breakout
                eng = self.engine(mode)
                eng.step()
                sleeve = eng.state["sleeves"]["KRW-BTC"]
                self.assertFalse(sleeve["long"])
                self.assertIn("손절가", sleeve["last_reason"])
                self.assertEqual(self.events(), ["COIN_SKIP_BELOW_STOP"])
                self.assertEqual(self.api.buys, [])

    def test_entry_window_closes_after_15_minutes(self):
        self.clock.t = E0 + 16 * 60
        eng = self.engine("shadow")
        eng.step()
        self.assertFalse(eng.state["sleeves"]["KRW-BTC"]["long"])
        self.assertIn("놓침", eng.state["sleeves"]["KRW-BTC"]["last_reason"])

    def test_live_buy_records_the_fill_and_stop_sells_the_ledger_volume(self):
        eng = self.engine("live")
        eng.step()
        sleeve = eng.state["sleeves"]["KRW-BTC"]
        self.assertEqual(len(self.api.buys), 1)
        market, amount, ident = self.api.buys[0]
        self.assertEqual(ident, f"s8c-BTC-{E0}-b")
        self.assertLessEqual(amount * 1.0005, 1_000_000)
        self.assertTrue(sleeve["long"])
        self.assertIsNone(sleeve["pending"])
        self.assertAlmostEqual(sleeve["volume"], round(amount / 130.0, 8))
        self.assertIn("COIN_BUY", self.events())
        held = sleeve["volume"]
        self.api.price = sleeve["stop"] * 0.995
        self.clock.t += 120
        eng.step()
        self.assertEqual(len(self.api.sells), 1)
        self.assertAlmostEqual(self.api.sells[0][1], held)  # only the automation's own volume
        self.assertFalse(eng.state["sleeves"]["KRW-BTC"]["long"])
        self.assertIn("COIN_SELL", self.events())

    def test_unknown_outcome_is_resolved_by_identifier_without_a_second_order(self):
        self.api.fail_next_buy = ApiError("timeout", 0, "")
        eng = self.engine("live")
        eng.step()
        self.assertEqual(len(self.api.buys), 1)
        self.assertTrue(eng.state["sleeves"]["KRW-BTC"]["long"])  # found by identifier
        self.clock.t += 30
        eng.step()
        self.assertEqual(len(self.api.buys), 1)

    def test_rejected_buy_is_not_retried_in_the_same_bar(self):
        self.api.fail_next_buy = ApiError("insufficient funds", 400, "insufficient_funds_bid")
        eng = self.engine("live")
        eng.step()
        self.clock.t += 30
        eng.step()
        self.assertEqual(len(self.api.buys), 1)
        self.assertFalse(eng.state["sleeves"]["KRW-BTC"]["long"])
        self.assertIn("COIN_BUY_ERROR", self.events())

    def test_kill_switch_halts_new_entries(self):
        eng = self.engine("shadow")
        eng.step()
        eng.state["peak_equity"] = 2_000_000
        self.api.price = 129.0
        self.clock.t += 60
        eng.step()
        self.assertTrue(eng.state["halted"])
        self.assertIn("COIN_HALT", self.events())

    def test_external_sell_is_reconciled(self):
        eng = self.engine("live")
        eng.step()
        self.api.coin = 0.0  # sold in the Upbit app
        self.clock.t += 120
        eng.step()
        self.assertFalse(eng.state["sleeves"]["KRW-BTC"]["long"])
        self.assertIn("COIN_EXTERNAL_SELL", self.events())

    def test_policy_normalisation(self):
        p = engine_mod.normalize_policy({"mode": "LIVE", "seed_krw": "1e9", "markets": ["KRW-BTC", "KRW-FAKE"]})
        self.assertEqual(p["mode"], "live")
        self.assertEqual(p["seed_krw"], engine_mod.SEED_MAX)
        self.assertEqual(p["markets"], ["KRW-BTC"])
        self.assertEqual(engine_mod.normalize_policy({"mode": "bogus"})["mode"], "off")
        self.assertEqual(engine_mod.normalize_policy(None)["markets"], list(engine_mod.DEFAULT_MARKETS))


class StrategyTests(unittest.TestCase):
    def test_breakout_needs_both_filters(self):
        _, rows = breakout_series()
        closed = [r for r in rows if r["t"] + H <= E0]
        bars = S.build_bars(closed)
        daily = S.daily_closes(closed, E0)
        ind = S.indicators(bars, daily, len(bars) - 1)
        self.assertTrue(ind["ready"])
        action, pos, _ = S.decide({"long": False}, ind)
        self.assertEqual(action, "ENTER")
        self.assertAlmostEqual(pos["stop"], ind["high"] - 2.0 * ind["atr"])
        quiet = S.indicators(bars[:-1], daily, len(bars) - 2)
        self.assertEqual(S.decide({"long": False}, quiet)[0], "WAIT")

    def test_stop_only_ratchets_up(self):
        pos = {"long": True, "hh": 130.0, "stop": 120.0}
        _, pos2, _ = S.decide(pos, {"high": 125.0, "atr": 10.0})
        self.assertEqual(pos2["stop"], 120.0)
        _, pos3, _ = S.decide(pos2, {"high": 150.0, "atr": 5.0})
        self.assertEqual(pos3["stop"], 140.0)

    def test_bars_follow_utc_4h_buckets(self):
        rows = hourly(E0 - 2 * H, 6, lambda i: 100.0 + i)
        bars = S.build_bars(rows)
        self.assertEqual([b["start"] for b in bars], [E0 - 4 * H, E0])
        self.assertEqual(bars[0]["c"], 101.0)
        self.assertEqual(bars[1]["o"], 102.0)


if __name__ == "__main__":
    unittest.main()
