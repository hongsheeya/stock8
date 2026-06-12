import builtins
import datetime
import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class _TimeStub:
    @staticmethod
    def now():
        return datetime.datetime(2026, 5, 27, 9, 30, 0)

    @staticmethod
    def to_kst(value):
        text = str(value or "").strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.datetime.strptime(text, fmt)
            except Exception:
                pass
        return datetime.datetime(2026, 5, 27, 9, 30, 0)


class _WizStub:
    @staticmethod
    def model(name):
        if name == "portal/trading/kst":
            return _TimeStub
        raise AssertionError(f"unexpected wiz.model({name})")


builtins.wiz = _WizStub()
api_path = SRC / "app" / "page.infinitebuy" / "api.py"
api_spec = importlib.util.spec_from_file_location("infinitebuy_api_under_test", api_path)
api = importlib.util.module_from_spec(api_spec)
api_spec.loader.exec_module(api)


class _FakeDb:
    def __init__(self, rows=None):
        self.rows_data = [dict(row) for row in (rows or [])]
        self._next_id = len(self.rows_data) + 1

    def get(self, **conds):
        for row in self.rows_data:
            matched = True
            for key, value in conds.items():
                if row.get(key) != value:
                    matched = False
                    break
            if matched:
                return dict(row)
        return None

    def rows(self, **kwargs):
        filtered = list(self.rows_data)
        orderby = kwargs.pop("orderby", None)
        order = str(kwargs.pop("order", "ASC") or "ASC").upper()
        dump = kwargs.pop("dump", None)
        kwargs.pop("page", None)
        for key, value in kwargs.items():
            filtered = [row for row in filtered if row.get(key) == value]
        if orderby:
            filtered = sorted(filtered, key=lambda row: row.get(orderby) or 0, reverse=(order == "DESC"))
        if dump is not None:
            filtered = filtered[: int(dump)]
        return [dict(row) for row in filtered]

    def insert(self, data):
        row = dict(data)
        row.setdefault("id", f"row-{self._next_id}")
        self._next_id += 1
        self.rows_data.append(row)
        return row["id"]

    def update(self, data, id=None):
        for index, row in enumerate(self.rows_data):
            if row.get("id") == id:
                updated = dict(row)
                updated.update(dict(data))
                self.rows_data[index] = updated
                return
        raise AssertionError(f"missing row id={id}")


class _TradingStub:
    def __init__(self):
        self.watchlist_db = _FakeDb()
        self.cycle_db = _FakeDb()

    def db(self, name):
        if name == "etf_watchlist":
            return self.watchlist_db
        if name == "trading_cycle":
            return self.cycle_db
        raise AssertionError(f"unexpected db({name})")


class _BridgeStub:
    def __init__(self, portfolios):
        self._portfolios = list(portfolios)

    def list_portfolios(self):
        return list(self._portfolios)


class InfiniteBuyFireGatePullTests(unittest.TestCase):
    def test_firegate_portfolio_to_cycle_creates_completed_cycle_for_stopped_portfolio(self):
        trading = _TradingStub()

        result = api._firegate_portfolio_to_cycle(trading, {
            "id": "fg-2",
            "ticker": "SOXL",
            "isRunning": False,
            "seed": 15000,
            "divisionDate": 20,
            "targetProfit": 20,
            "holdingQty": 0,
            "avgPrice": 0,
            "totalBuy": 1000,
            "totalSell": 1234.56,
            "tValue": 0,
            "sellPrice": 24.5,
            "startDate": "2026-05-01",
            "endDate": "2026-05-20",
        })

        self.assertEqual(result, "created")
        created = trading.cycle_db.rows_data[0]
        self.assertEqual(created["status"], "COMPLETED")
        self.assertEqual(created["symbol"], "SOXL")
        self.assertEqual(created["current_eval"], 1234.56)
        self.assertEqual(created["remaining_investment"], 0.0)
        self.assertIsNotNone(created["completed_at"])

    def test_pull_firegate_to_local_counts_all_symbol_portfolios_and_creates_cycles(self):
        trading = _TradingStub()
        bridge = _BridgeStub([
            {
                "id": "fg-1",
                "ticker": "TQQQ",
                "source": "infinitystock",
                "sourceCycleId": "cycle-tqqq",
                "portfolioGroup": "InfinityStock Auto",
                "category": "infinite_buy",
                "isRunning": True,
                "seed": 10000,
                "divisionDate": 20,
                "targetProfit": 15,
                "holdingQty": 5,
                "avgPrice": 100,
                "totalBuy": 500,
                "totalSell": 0,
                "tValue": 1.5,
                "sellPrice": 112,
            },
            {
                "id": "fg-2",
                "ticker": "SOXL",
                "source": "infinitystock",
                "sourceCycleId": "cycle-soxl",
                "portfolioGroup": "InfinityStock Auto",
                "category": "infinite_buy",
                "isRunning": False,
                "seed": 15000,
                "divisionDate": 20,
                "targetProfit": 20,
                "holdingQty": 0,
                "avgPrice": 0,
                "totalBuy": 1000,
                "totalSell": 1200,
                "tValue": 0,
                "sellPrice": 24.5,
                "endDate": "2026-05-20",
            },
        ])

        result = api._pull_firegate_to_local(bridge, trading)

        self.assertEqual(result["firegate_portfolios"], 2)
        self.assertEqual(result["watchlist_created"], 2)
        self.assertEqual(result["cycles_created"], 2)
        statuses = {row["symbol"]: row["status"] for row in trading.cycle_db.rows_data}
        self.assertEqual(statuses["TQQQ"], "ACTIVE")
        self.assertEqual(statuses["SOXL"], "COMPLETED")

    def test_pull_firegate_to_local_skips_manual_portfolios(self):
        trading = _TradingStub()
        bridge = _BridgeStub([{
            "id": "manual-1",
            "ticker": "TQQQ",
            "nickname": "Manual TQQQ",
            "isRunning": True,
            "seed": 999999,
        }])

        result = api._pull_firegate_to_local(bridge, trading)

        self.assertEqual(result["firegate_portfolios"], 0)
        self.assertEqual(result["watchlist_created"], 0)
        self.assertEqual(result["cycles_created"], 0)


if __name__ == "__main__":
    unittest.main()
