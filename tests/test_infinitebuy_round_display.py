"""11-29: the 회차 the pages show is FireGate's fractional T, not floor(T).

LIVE SOXL: FireGate T 15.9, trading_cycle t_value 15.9 / current_round 15.
The dashboard, the /infinite-buy chips and the history list showed "15/20",
and the /infinite-buy 회차(T) column fell back to current_round because the
buy decision carries no t_value. Orders already used t_value; only the
display and the API fields change here.
"""
import ast
import datetime
import importlib.util
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "app"


class _TimeStub:
    @staticmethod
    def now():
        return datetime.datetime(2026, 11, 29, 10, 0, 0)

    @staticmethod
    def isoformat(with_offset=False):
        return "2026-11-29T10:00:00+09:00" if with_offset else "2026-11-29T10:00:00"


class _Table:
    def __init__(self, rows):
        self._rows = rows

    def rows(self, **filters):
        out = []
        for row in self._rows:
            if all(row.get(key) == value for key, value in filters.items()
                   if key not in ("orderby", "order", "dump")):
                out.append(dict(row))
        return out

    def get(self, **filters):
        rows = self.rows(**filters)
        return rows[0] if rows else None

    def update(self, *_args, **_kwargs):
        raise AssertionError("the portfolio view must not write")


class _Engine:
    def calculate_buy_decision(self, cycle, prev_close):
        # Like engine._firegate_v4_buy_decision: no t_value key.
        return {"should_buy": True, "buy_amount": 148.7, "reason": "FireGate v4 LOC 매수 계획",
                "buy_orders": [{"label": "LOC ★-11.8%", "loc_price": 66.54, "order_qty": 2}]}

    def _firegate_v4_sell_orders(self, cycle):
        return [{"label": "LOC ★-11.80%", "order_type": "LOC", "price": 66.55, "order_qty": 37}]


class _Trading:
    def __init__(self, cycles):
        self.engine = _Engine()
        self._tables = {
            "etf_watchlist": _Table([{"id": "w1", "symbol": "SOXL", "exchange": "AMEX", "is_active": True,
                                      "total_investment": 15000, "division_count": 20}]),
            "trading_cycle": _Table(cycles),
        }

    def db(self, name):
        return self._tables[name]

    def get_config(self, _key, default=""):
        return default


class _WizStub:
    def __init__(self):
        self.trading = None

    def model(self, name):
        if name == "portal/trading/kst":
            return _TimeStub
        if name == "struct":
            return self
        raise AssertionError(f"unexpected wiz.model({name})")


def _load_infinitebuy_api():
    stub = _WizStub()
    spec = importlib.util.spec_from_file_location("infinitebuy_api_round_display", APP / "page.infinitebuy" / "api.py")
    module = importlib.util.module_from_spec(spec)
    module.wiz = stub
    spec.loader.exec_module(module)
    return module, stub


def _soxl_cycle(**changes):
    cycle = {"id": "dvijhi", "symbol": "SOXL", "cycle_number": 2, "status": "ACTIVE", "current_round": 15,
             "t_value": 15.9, "division_count": 20, "target_profit": 20.0, "total_investment": 15000.0,
             "total_spent": 11242.05, "total_qty": 149, "avg_price": 75.45, "current_price": 35.85,
             "current_eval": 5341.65, "profit_rate": -52.6, "remaining_investment": 743.51,
             "updated": "2026-11-29 00:31:55"}
    cycle.update(changes)
    return cycle


class InfiniteBuyRoundColumnTests(unittest.TestCase):
    def setUp(self):
        self.api, self.stub = _load_infinitebuy_api()

    def payload_item(self, cycle):
        self.stub.trading = _Trading([cycle])
        self.api._STRUCT_CACHE.update(obj=None, error=None, error_at=0.0)
        items = self.api._portfolio_payload(refresh=False)["items"]
        self.assertEqual(len(items), 1)
        return items[0]

    def test_cycle_t_value_prefers_firegate_t(self):
        self.assertEqual(self.api._cycle_t_value({"t_value": 15.9, "current_round": 15}), 15.9)
        self.assertEqual(self.api._cycle_t_value({"t_value": "17.67", "current_round": 17}), 17.67)

    def test_cycle_without_firegate_t_keeps_the_integer_round(self):
        # PAPER: the column default 0.0 is no T.
        self.assertEqual(self.api._cycle_t_value({"t_value": 0.0, "current_round": 5}), 5.0)
        self.assertEqual(self.api._cycle_t_value({"current_round": 3}), 3.0)
        self.assertEqual(self.api._cycle_t_value(self.api._virtual_cycle({"symbol": "SOXL"})), 0.0)

    def test_round_column_shows_firegate_t_not_current_round(self):
        item = self.payload_item(_soxl_cycle())
        self.assertEqual(item["t_value"], 15.9)
        self.assertTrue(item["t_is_firegate"])
        self.assertFalse(item["firegate_exhausted"])
        self.assertEqual(item["current_round"], 15)  # unchanged field

    def test_round_column_for_a_paper_cycle(self):
        item = self.payload_item(_soxl_cycle(t_value=0.0, current_round=4))
        self.assertEqual(item["t_value"], 4.0)
        self.assertFalse(item["t_is_firegate"])

    def test_exhausted_cycle_is_flagged(self):
        # FireGate's exhausted rule (T > splits - 1): reservations follow its
        # reverse guide, not the local v4 lines in the row.
        self.assertTrue(self.payload_item(_soxl_cycle(t_value=19.62, current_round=19))["firegate_exhausted"])
        self.assertFalse(self.api._firegate_exhausted_hint({"t_value": 19.0, "division_count": 20}))
        self.assertFalse(self.api._firegate_exhausted_hint({"t_value": 0.0, "current_round": 20, "division_count": 20}))

    def test_paused_cycle_round_uses_t_too(self):
        item = self.payload_item(_soxl_cycle(status="PAUSED"))
        self.assertEqual(item["t_value"], 15.9)


def _dict_keys_in_function(path, function_name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            for inner in ast.walk(node):
                if isinstance(inner, ast.Dict):
                    keys = {k.value for k in inner.keys if isinstance(k, ast.Constant)}
                    if "current_round" in keys:
                        found.append(keys)
    return found


class ApiFieldTests(unittest.TestCase):
    def test_history_cycle_list_selects_t_value(self):
        tree = ast.parse((APP / "page.history" / "api.py").read_text(encoding="utf-8"))
        columns = next(ast.literal_eval(node.value) for node in tree.body
                       if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "_CYCLE_COLUMNS")
        self.assertIn("t_value", columns)

    def test_dashboard_detail_and_preview_send_t_value(self):
        path = APP / "page.dashboard" / "api.py"
        for function_name in ("cycle_detail", "trade_preview"):
            dicts = _dict_keys_in_function(path, function_name)
            self.assertTrue(dicts, function_name)
            for keys in dicts:
                self.assertIn("t_value", keys, function_name)


class TemplateTests(unittest.TestCase):
    """No page renders the integer current_round as the 회차 any more."""

    INTEGER_ROUND = re.compile(r"\{\{[^}]*current_round[^}]*\}\}")

    def test_round_labels_use_the_t_helper(self):
        for page in ("page.dashboard", "page.infinitebuy", "page.history"):
            text = (APP / page / "view.pug").read_text(encoding="utf-8")
            self.assertEqual(self.INTEGER_ROUND.findall(text), [], page)
            self.assertIn("cycleRoundLabel(", text, page)
            ts = (APP / page / "view.ts").read_text(encoding="utf-8")
            self.assertIn("@wiz/libs/portal/trading/cycle-round", ts, page)

    def test_dashboard_preview_no_longer_adds_one_to_current_round(self):
        text = (APP / "page.dashboard" / "view.pug").read_text(encoding="utf-8")
        self.assertNotIn("current_round + 1", text)
        self.assertIn("previewRoundValue(p)", text)

    def test_helper_falls_back_only_without_a_firegate_t(self):
        helper = (ROOT / "src" / "portal" / "trading" / "libs" / "cycle-round.ts").read_text(encoding="utf-8")
        self.assertIn("t > 0 ? t : null", helper)
        self.assertIn("t > division - 1", helper)


if __name__ == "__main__":
    unittest.main()
