"""배당 page API (10-22): cached reads only, per-user state, watchlist validation."""
import datetime as dt
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1] / "src"
MODEL = ROOT / "portal" / "trading" / "model"


def _module(name):
    spec = importlib.util.spec_from_file_location(f"divpage_{name}", MODEL / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DIVIDEND = _module("dividend").Dividend
DATA = _module("dividend_data")


class Status(Exception):
    def __init__(self, code, data):
        super().__init__(code)
        self.code, self.data = code, data


def _status(code=200, **data):
    raise Status(code, data)


class DividendPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = {}
        self.uid = "u1"
        self.query = {}

    def load(self):
        os.environ["TRADING_MODE"] = "LIVE"
        self.addCleanup(os.environ.pop, "TRADING_MODE")
        trading = NS(
            _user_config_key=lambda uid, key: f"user:{uid}:{key}",
            _lookup_config_value=lambda key, default="": self.config.get(key, default),
            _write_config_value=lambda key, value, desc="", secret=False: self.config.__setitem__(key, value),
        )
        models = {"struct": NS(trading=trading), "portal/trading/dividend": DIVIDEND, "portal/trading/dividend_data": DATA.DividendData,
                  "portal/trading/kst": NS(now=lambda: dt.datetime(2026, 10, 22, 9))}
        wiz = NS(model=lambda name: models[name], session=NS(get=lambda key: self.uid),
                 request=NS(query=lambda key, default=None: self.query.get(key, default)), response=NS(status=_status),
                 project=NS(fs=lambda: NS(abspath=lambda path: os.path.join(self.tmp.name, path))))
        env = {"wiz": wiz, "__name__": "dividend_api"}
        exec(compile((ROOT / "app" / "page.dividend" / "api.py").read_text(encoding="utf-8"), "api.py", "exec"), env)
        self.started = []
        env["_start_refresh"] = lambda uid, **kw: self.started.append((uid, kw))
        return env

    def call(self, env, name):
        with self.assertRaises(Status) as ctx:
            env[name]()
        return ctx.exception

    def seed_cache(self, symbol, market, events, price, mode="live"):
        cache_dir = os.path.join(self.tmp.name, "data", mode, "dividend", "cache")
        os.makedirs(cache_dir, exist_ok=True)
        data = DATA.DividendData(cache_dir, DIVIDEND, now=lambda: 0)
        with open(data._path(symbol, market), "w", encoding="utf-8") as handle:
            json.dump({"symbol": symbol, "market": market, "fetched_at": 9e12, "price": price, "events": events}, handle)

    def test_overview_reads_cache_and_starts_a_background_refresh(self):
        env = self.load()
        env["_STATE"].clear()
        env["_STATE"]["u1"] = {"holdings": [{"symbol": "KO", "market": "US", "name": "Coca-Cola", "qty": 10, "avg_price": 50.0,
                                            "current_price": 80.0}], "fx": 1400.0, "holdings_at": 0}
        self.seed_cache("KO", "US", [{"ex_date": f"2025-{m:02d}-01", "amount": 1.0} for m in (12,)] +
                        [{"ex_date": d, "amount": 1.0} for d in ("2026-03-02", "2026-06-01", "2026-08-31")], 80.0)
        res = self.call(env, "overview")
        self.assertEqual(res.code, 200)
        self.assertEqual(self.started, [("u1", {"refresh_holdings": True, "force": False})])  # stale holdings -> thread
        row = res.data["holdings"][0]
        self.assertEqual(row["annual_net_krw"], round(4 * 10 * 1400 * 0.85))
        self.assertEqual(row["yield_pct"], 5.0)
        self.assertEqual(res.data["totals"]["annual_net_krw"], row["annual_net_krw"])
        json.dumps(res.data)  # dates were serialised

    def test_state_is_per_user(self):
        env = self.load()
        env["_STATE"].clear()
        env["_STATE"]["other"] = {"holdings": [{"symbol": "T", "market": "US", "qty": 5}], "holdings_at": 9e12}
        res = self.call(env, "overview")
        self.assertEqual(res.data["holdings"], [])

    def test_watchlist_validation_and_storage(self):
        env = self.load()
        self.query = {"symbol": "schd", "market": "US"}
        res = self.call(env, "add_watch")
        self.assertEqual(res.code, 200)
        self.assertEqual(json.loads(self.config["user:u1:dividend_watchlist"]), [{"symbol": "SCHD", "market": "US", "name": ""}])
        self.assertEqual(self.started[-1][1], {"refresh_holdings": False, "only": [("SCHD", "US")]})
        for bad in ({"symbol": "33780", "market": "KS"}, {"symbol": "SCHD", "market": "JP"}, {"symbol": "drop table", "market": "US"}):
            with self.subTest(bad=bad):
                self.query = bad
                self.assertEqual(self.call(env, "add_watch").code, 400)
        self.query = {"symbol": "SCHD", "market": "US"}
        self.call(env, "remove_watch")
        self.assertEqual(json.loads(self.config["user:u1:dividend_watchlist"]), [])

    def reinvest_env(self, mode):
        os.environ["TRADING_MODE"] = mode
        env = self.load()
        os.environ["TRADING_MODE"] = mode
        env["_TRADING_MODE"] = mode
        self.orders = []
        broker = NS(
            get_current_price=lambda symbol, exchange="NAS": {"price": 34.62, "order_exchange": "AMEX"},
            get_domestic_current_price=lambda symbol: {"price": 194000},
            get_buying_power_info=lambda symbol, price, exchange: {"executable_amount": 1000.0},
            get_domestic_buying_power_info=lambda symbol, price, order_type: {"amount": 10000000},
            buy_order=lambda *a, **k: self.orders.append((a, k)) or {"order_no": "A1"},
            buy_domestic_order=lambda *a, **k: self.orders.append((a, k)) or {"order_no": "K1"},
        )
        env["wiz"].model("struct").trading.broker_api = broker
        env["wiz"].model("struct").trading.db = lambda name: NS(insert=lambda row: self.logged.append(row))
        self.logged = []
        env["_STATE"].clear()
        env["_STATE"]["u1"] = {"holdings": [{"symbol": "SCHD", "market": "US", "qty": 300, "exchange": "AMEX"}], "fx": 1400.0}
        # SCHD paid 0.267 on 2026-09-29 (ex 09-23): 300 x 0.267 x 0.85 = $68.09 -> 1 share at $34.73
        self.seed_cache("SCHD", "US", [{"ex_date": "2026-06-24", "amount": 0.26, "pay_date": "2026-06-29"},
                                        {"ex_date": "2026-09-23", "amount": 0.267, "pay_date": "2026-09-29"}], 34.62,
                        mode="live" if mode == "LIVE" else "paper")
        return env

    def test_reinvest_plan_and_single_use_order_on_paper(self):
        env = self.reinvest_env("PAPER")
        self.query = {"days": "30"}
        plan = self.call(env, "reinvest_plan").data
        self.assertTrue(plan["orders_enabled"])
        row = plan["proposals"][0]
        self.assertEqual((row["symbol"], row["qty"], row["limit_price"]), ("SCHD", 1, 34.73))
        self.assertAlmostEqual(row["dividend_net"], 68.09, places=2)
        self.query = {"token": row["token"]}
        res = self.call(env, "reinvest_order")
        self.assertEqual(res.code, 200)
        args, kwargs = self.orders[0]
        self.assertEqual(args[:2], ("SCHD", 1))
        self.assertEqual((kwargs["order_type"], kwargs["price"], kwargs["exchange"]), ("LIMIT", 34.73, "AMEX"))
        self.assertEqual(self.logged[0]["event_type"], "DIV_REINVEST_BUY")
        self.assertEqual(self.call(env, "reinvest_order").code, 400)     # the token is single use
        self.assertEqual(len(self.orders), 1)

    def test_live_server_never_orders(self):
        env = self.reinvest_env("LIVE")
        self.query = {"days": "30"}
        plan = self.call(env, "reinvest_plan").data
        self.assertFalse(plan["orders_enabled"])
        self.query = {"token": plan["proposals"][0]["token"]}
        self.assertEqual(self.call(env, "reinvest_order").code, 403)
        self.assertEqual(self.orders, [])

    def test_expired_proposal_is_refused_and_small_dividends_accumulate(self):
        env = self.reinvest_env("PAPER")
        self.query = {"days": "30"}
        plan = self.call(env, "reinvest_plan").data
        token = plan["proposals"][0]["token"]
        env["_STATE"]["u1"]["proposals"][token]["expires"] = 0
        self.query = {"token": token}
        self.assertEqual(self.call(env, "reinvest_order").code, 400)
        self.assertEqual(self.orders, [])
        env["_STATE"]["u1"]["holdings"][0]["qty"] = 100   # $22.70 < one share
        self.query = {"days": "30"}
        row = self.call(env, "reinvest_plan").data["proposals"][0]
        self.assertEqual(row["qty"], 0)
        self.assertIn("적립", " ".join(row["notes"]))
        self.assertEqual(row["token"], "")

    def test_login_required(self):
        self.uid = ""
        env = self.load()
        self.assertEqual(self.call(env, "overview").code, 401)


if __name__ == "__main__":
    unittest.main()
