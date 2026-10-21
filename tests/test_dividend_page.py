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

    def seed_cache(self, symbol, market, events, price):
        cache_dir = os.path.join(self.tmp.name, "data", "live", "dividend", "cache")
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

    def test_login_required(self):
        self.uid = ""
        env = self.load()
        self.assertEqual(self.call(env, "overview").code, 401)


if __name__ == "__main__":
    unittest.main()
