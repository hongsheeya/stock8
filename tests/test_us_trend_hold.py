"""US daily trend hold (10-23, PAPER only): frozen 6-month momentum rule, own ledger.
10-31: E3 volatility targeting sizes the held sleeve."""
import calendar
import datetime
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

MODEL = Path(__file__).resolve().parents[1] / "src" / "portal" / "trading" / "model"
spec = importlib.util.spec_from_file_location("us_trend_hold", MODEL / "us_trend_hold.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
E = mod.UsTrendHold

# Tuesday 2026-10-20 10:00 ET (EDT = UTC-4)
T0 = calendar.timegm(datetime.datetime(2026, 10, 20, 14, 0).timetuple())


def closes(trend_up, n=200, end="2026-10-20"):
    """n sessions ending the day before `end`, plus a partial bar on `end`."""
    day = datetime.date.fromisoformat(end)
    rows = []
    d = day
    for i in range(n):
        d -= datetime.timedelta(days=1)
        while d.weekday() >= 5:
            d -= datetime.timedelta(days=1)
        price = 100 + (n - i) * (0.1 if trend_up else -0.1)
        rows.append((d.isoformat(), price))
    rows.append((end, 1.0))  # today's partial bar must be ignored
    return sorted(rows)


def choppy(daily_move, n=60, end="2026-10-20"):
    """An ETF alternating +/- daily_move: annualized vol ~ daily_move * sqrt(252)."""
    day = datetime.date.fromisoformat(end)
    rows, d, price = [], day, 100.0
    dates = []
    for _ in range(n):
        d -= datetime.timedelta(days=1)
        while d.weekday() >= 5:
            d -= datetime.timedelta(days=1)
        dates.append(d)
    for i, d in enumerate(sorted(dates)):
        price *= (1 + daily_move) if i % 2 else (1 - daily_move)
        rows.append((d.isoformat(), price))
    rows.append((end, 1.0))
    return rows


class FakeBroker:
    def __init__(self, prices=None):
        self.prices = prices or {"QLD": 100.0, "SSO": 50.0}
        self.holdings = {}
        self.orders = []
        self.fills = {}
        self.fill_now = True
        self.cancelled = []

    def get_current_price(self, symbol, exchange="NAS"):
        return {"price": self.prices[symbol]}

    def get_balance(self, exchange=None):
        return {"holdings": [{"symbol": s, "qty": q, "avg_price": a} for s, (q, a) in self.holdings.items() if q]}

    def _order(self, side, symbol, qty, price):
        no = f"{len(self.orders) + 1:010d}"
        self.orders.append((side, symbol, qty, price))
        if self.fill_now:
            px = self.prices[symbol]
            q, a = self.holdings.get(symbol, (0, 0.0))
            if side == "BUY":
                self.holdings[symbol] = (q + qty, (q * a + qty * px) / (q + qty))
            else:
                self.holdings[symbol] = (q - qty, a)
            self.fills[no] = (qty, px)
        return {"order_no": no}

    def buy_order(self, symbol, qty, price=0, order_type="LOC", exchange="NASD"):
        assert order_type == "MARKET" and exchange == "AMEX" and price > self.prices[symbol]
        return self._order("BUY", symbol, qty, price)

    def sell_order(self, symbol, qty, price=0, order_type="MARKET", exchange="NASD"):
        assert order_type == "MARKET" and exchange == "AMEX" and price < self.prices[symbol]
        return self._order("SELL", symbol, qty, price)

    def get_overseas_order_history(self, start_date=None, end_date=None, symbol=""):
        return {"orders": [{"order_no": no, "filled_qty": q, "filled_price": p} for no, (q, p) in self.fills.items()]}

    def cancel_overseas_order(self, order_no, symbol, qty, exchange="NASD"):
        self.cancelled.append((order_no, symbol, qty))


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class TrendHoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.broker = FakeBroker()
        self.clock = Clock(T0)
        self.up = {"QQQ": True, "SPY": True}
        self.etf_move = {}  # ETF -> daily +/- move; default: calm (full weight)
        self.fail = set()
        self.logs = []

    def tearDown(self):
        self.tmp.cleanup()

    def _closes(self, symbol):
        if symbol in self.fail:
            raise RuntimeError("no data")
        session = mod.et_now(self.clock.t).date().isoformat()
        if symbol in self.etf_move:
            return choppy(self.etf_move[symbol], end=session)
        return closes(self.up.get(symbol, True), end=session)

    def engine(self, enabled=True, seed=20000, holiday=""):
        return E(self.broker, self.tmp.name, {"enabled": enabled, "seed_usd": seed}, self._closes,
                 log=lambda *a, **k: self.logs.append(a[0]), now=self.clock, holiday_fn=lambda day: holiday)

    def test_momentum_and_completed_closes(self):
        self.assertEqual(E.momentum([1.0] * 126), (None, None))
        on, pct = E.momentum([100.0] + [1.0] * 125 + [110.0])
        self.assertTrue(on)
        self.assertAlmostEqual(pct, 10.0)
        self.assertEqual(E.completed([("2026-10-19", 2.0), ("2026-10-20", 3.0)], "2026-10-20"), [2.0])

    def test_realized_vol_and_target_weight(self):
        self.assertIsNone(E.realized_vol([100.0] * 20))
        rows = [c for _d, c in choppy(0.03)][:-1]
        vol = E.realized_vol(rows)
        self.assertAlmostEqual(vol, 0.03 * 252 ** 0.5, delta=0.02)
        self.assertEqual(E.target_weight(False, vol), 0.0)
        self.assertEqual(E.target_weight(True, 0.20), 1.0)
        self.assertAlmostEqual(E.target_weight(True, 0.70), 0.5)

    def test_high_volatility_enters_at_the_target_weight(self):
        self.etf_move = {"QLD": 0.04}  # ~63% vol -> ~55% weight
        engine = self.engine()
        engine.step()
        qld = [o for o in self.broker.orders if o[1] == "QLD"][0]
        want = E.STATUS["sleeves"][0]["signal"]["target_w"]
        self.assertLess(want, 0.6)
        self.assertEqual(qld[2], int(10000 * want // (100 * 1.01)))
        self.assertEqual([o[2] for o in self.broker.orders if o[1] == "SSO"], [196])  # calm SSO: full
        self.clock.t += 61
        engine.step()
        self.assertAlmostEqual(engine.state["sleeves"]["QLD"]["target_w"], want)

    def test_held_sleeve_is_trimmed_only_on_a_20pt_change(self):
        engine = self.engine()
        engine.step()
        self.clock.t += 61
        engine.step()
        self.assertEqual(engine.state["sleeves"]["QLD"]["qty"], 98)
        engine.state["sleeves"]["QLD"].pop("target_w")  # a ledger from before E3
        # next session: vol ~32% -> target ~100%: no order
        self.etf_move = {"QLD": 0.02}
        self.clock.t += 24 * 3600
        engine.step()
        self.assertEqual(len(self.broker.orders), 2)
        self.assertIn("변경 없음", engine.state["sleeves"]["QLD"]["last_reason"])
        # following session: vol ~63% -> ~55%: sell down to it, keep the rest
        self.etf_move = {"QLD": 0.04}
        self.clock.t += 24 * 3600
        engine.step()
        side, sym, qty, _ = self.broker.orders[-1]
        self.assertEqual((side, sym), ("SELL", "QLD"))
        self.clock.t += 61
        engine.step()
        qld = engine.state["sleeves"]["QLD"]
        self.assertEqual(qld["qty"], 98 - qty)
        self.assertGreater(qld["qty"], 40)
        self.assertLess(qld["target_w"], 0.6)
        # momentum off: sell the rest
        self.up["QQQ"] = False
        self.clock.t += 24 * 3600
        engine.step()
        self.assertEqual(self.broker.orders[-1][:3], ("SELL", "QLD", 98 - qty))

    def test_policy_is_clamped(self):
        self.assertEqual(E.normalize_policy({"seed_usd": 5})["seed_usd"], E.SEED_MIN)
        self.assertFalse(E.normalize_policy({})["enabled"])

    def test_buy_both_sleeves_then_book_fills(self):
        engine = self.engine()
        engine.step()
        self.assertEqual([o[:3] for o in self.broker.orders], [("BUY", "QLD", 98), ("BUY", "SSO", 196)])
        engine.step()  # under a minute: still pending, no second order
        self.assertEqual(len(self.broker.orders), 2)
        self.clock.t += 61
        engine.step()
        qld = engine.state["sleeves"]["QLD"]
        self.assertEqual(qld["qty"], 98)
        self.assertAlmostEqual(qld["cash"], 10000 - 98 * 100 * (1 + mod.FEE_SIDE))
        self.assertEqual(qld["last_session"], "2026-10-20")
        self.assertIn("USTH_FILL", self.logs)
        # same session: no more trading
        self.clock.t += 600
        engine.step()
        self.assertEqual(len(self.broker.orders), 2)
        snap = E.STATUS
        self.assertEqual({s["etf"]: s["qty"] for s in snap["sleeves"]}, {"QLD": 98, "SSO": 196})

    def test_next_session_off_signal_sells_own_qty_only(self):
        engine = self.engine()
        engine.step()
        self.clock.t += 61
        engine.step()
        # someone else also holds 10 QLD in the account
        q, a = self.broker.holdings["QLD"]
        self.broker.holdings["QLD"] = (q + 10, a)
        self.up["QQQ"] = False
        self.broker.prices["QLD"] = 110.0
        self.clock.t += 24 * 3600
        engine.step()
        self.assertEqual(self.broker.orders[-1][:3], ("SELL", "QLD", 98))
        self.clock.t += 61
        engine.step()
        qld = engine.state["sleeves"]["QLD"]
        self.assertEqual(qld["qty"], 0)
        self.assertEqual(qld["trades"], 1)
        self.assertGreater(qld["realized_usd"], 900)
        self.assertEqual(self.broker.holdings["QLD"][0], 10)
        self.assertEqual(engine.state["sleeves"]["SSO"]["qty"], 196)  # SPY still up: unchanged

    def test_no_orders_outside_window_weekend_holiday_or_disabled(self):
        self.clock.t = T0 - 3600  # 09:00 ET
        self.engine().step()
        self.clock.t = T0 + 6 * 3600  # 16:00 ET
        self.engine().step()
        self.clock.t = T0 + 4 * 24 * 3600  # Saturday
        self.engine().step()
        self.clock.t = T0
        self.engine(holiday="Thanksgiving").step()
        self.engine(enabled=False).step()
        self.assertEqual(self.broker.orders, [])

    def test_data_failure_keeps_state_and_retries(self):
        self.fail.add("QQQ")
        engine = self.engine()
        engine.step()
        self.assertEqual([o[1] for o in self.broker.orders], ["SSO"])
        self.assertEqual(engine.state["sleeves"]["QLD"]["last_session"], "")
        self.fail.clear()
        self.clock.t += 61
        engine.step()
        self.assertEqual([o[1] for o in self.broker.orders], ["SSO", "QLD"])

    def test_unfilled_buy_is_cancelled_and_retried(self):
        self.broker.fill_now = False
        engine = self.engine()
        engine.step()
        self.clock.t += 61
        engine.step()
        self.assertTrue(engine.state["sleeves"]["QLD"]["pending"])
        self.clock.t += mod.PENDING_GIVE_UP_SEC
        engine.step()
        self.assertEqual(len(self.broker.cancelled), 2)
        self.assertEqual(engine.state["sleeves"]["QLD"]["qty"], 0)
        self.assertEqual(engine.state["sleeves"]["QLD"]["cash"], 10000)
        # retried within the same session window
        self.assertEqual(len(self.broker.orders), 4)

    def test_ledger_survives_restart(self):
        engine = self.engine()
        engine.step()
        self.clock.t += 61
        engine.step()
        again = self.engine()
        self.assertEqual(again.state["sleeves"]["SSO"]["qty"], 196)
        with open(os.path.join(self.tmp.name, "state.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["seed_usd"], 20000)



class TrendHoldIsolationTests(unittest.TestCase):
    def test_day_trade_lane_treats_trend_hold_etfs_as_reserved(self):
        from test_daytrade_engine_regressions import _engine_with_state
        engine, _ = _engine_with_state({}, [])
        engine.struct.db = lambda name: type("Rows", (), {"rows": lambda self, **kw: []})()
        engine.struct.us_trend_hold_reserved_symbols = lambda: {"QLD", "SSO"}
        self.assertTrue(engine._is_infinite_buy_symbol("QLD", "US"))
        self.assertTrue(engine._is_infinite_buy_symbol("SSO", "US"))
        self.assertFalse(engine._is_infinite_buy_symbol("USD", "US"))

    def test_page_is_admin_only_and_paper_gated(self):
        root = Path(__file__).resolve().parents[1] / "src"
        app = json.loads((root / "app" / "page.ustrend" / "app.json").read_text(encoding="utf-8"))
        self.assertEqual(app["controller"], "coin")  # admin-only controller
        api = (root / "app" / "page.ustrend" / "api.py").read_text(encoding="utf-8")
        for name in ("def save_settings", "def set_enabled"):
            body = api.split(name, 1)[1].split("\ndef ", 1)[0]
            self.assertIn("_require_paper()", body)


if __name__ == "__main__":
    unittest.main()
