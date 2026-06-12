import builtins
import copy
import datetime
import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
	sys.path.insert(0, str(SRC))


class _TimeStub:
	@staticmethod
	def now():
		return datetime.datetime(2026, 5, 28, 17, 38, 0)


class _WizStub:
	@staticmethod
	def model(name):
		if name == "portal/trading/kst":
			return _TimeStub
		raise AssertionError(f"unexpected wiz.model({name})")


builtins.wiz = _WizStub()
engine_path = SRC / "portal" / "trading" / "model" / "struct" / "engine.py"
engine_spec = importlib.util.spec_from_file_location("infinitebuy_engine_under_test", engine_path)
engine_module = importlib.util.module_from_spec(engine_spec)
engine_spec.loader.exec_module(engine_module)


class _FakeDB:
	def __init__(self, rows=None):
		self._rows = [copy.deepcopy(row) for row in (rows or [])]

	def rows(self, **where):
		result = []
		for row in self._rows:
			matched = True
			for key, value in where.items():
				if key in ("orderby", "order", "page", "dump"):
					continue
				if row.get(key) != value:
					matched = False
					break
			if matched:
				result.append(copy.deepcopy(row))
		return result

	def get(self, **where):
		rows = self.rows(**where)
		return rows[0] if rows else None

	def update(self, data, id=None, **where):
		for row in self._rows:
			if id is not None and row.get("id") != id:
				continue
			matched = True
			for key, value in where.items():
				if row.get(key) != value:
					matched = False
					break
			if matched:
				row.update(copy.deepcopy(data))


class _StructStub:
	def __init__(self, watchlist_rows, cycle_rows, configs=None):
		self._db = {
			"etf_watchlist": _FakeDB(watchlist_rows),
			"trading_cycle": _FakeDB(cycle_rows),
		}
		self.configs = dict(configs or {})

	def db(self, name):
		return self._db[name]

	def get_config(self, key, default=""):
		return self.configs.get(key, default)


class _KisApiStub:
	def __init__(self, buying_power_info, reservation_orders=None):
		self.buying_power_info = copy.deepcopy(buying_power_info)
		self.reservation_orders = copy.deepcopy(reservation_orders or [])
		self.buy_calls = []

	def get_current_price(self, symbol, exchange="NAS"):
		return {
			"symbol": symbol,
			"price": 150.0,
			"prev_close": 149.0,
			"order_exchange": "NASD",
		}

	def get_buying_power_info(self, symbol="TQQQ", price=0, exchange="NASD"):
		payload = copy.deepcopy(self.buying_power_info)
		payload.setdefault("symbol", symbol)
		payload.setdefault("price", price)
		payload.setdefault("exchange", exchange)
		return payload

	def get_overseas_reservation_orders(self, start_date=None, end_date=None, exchanges=None):
		return copy.deepcopy(self.reservation_orders)

	def buy_reservation_order(self, symbol, qty, price=0, order_type="LOC", exchange="NASD"):
		order = {
			"order_no": f"RSV-{len(self.buy_calls) + 1}",
			"symbol": symbol,
			"qty": qty,
			"price": price,
			"order_type": order_type,
			"exchange": exchange,
		}
		self.buy_calls.append(copy.deepcopy(order))
		return order


class InfiniteBuyLocScheduleRegressionTests(unittest.TestCase):
	def _engine(self, buying_power_info, reservation_orders=None, watchlist_rows=None, cycle_rows=None, configs=None):
		watchlist_rows = watchlist_rows or []
		cycle_rows = cycle_rows or []
		struct = _StructStub(watchlist_rows, cycle_rows, configs=configs)
		engine = engine_module.Engine(struct)
		kis_api = _KisApiStub(buying_power_info, reservation_orders=reservation_orders)
		engine._load_kis_api = lambda: kis_api
		engine.update_cycle_price = lambda cycle_id, price: None
		engine.calculate_buy_decision = lambda cycle, prev_close: {
			"should_buy": True,
			"order_type": "LOC",
			"order_qty": 1,
			"loc_price": 150.0,
			"reason": "테스트 LOC",
		}
		logs = []
		engine._log_event = lambda symbol, cycle_id, event_type, action="", message="": logs.append({
			"symbol": symbol,
			"cycle_id": cycle_id,
			"event_type": event_type,
			"action": action,
			"message": message,
		})
		return engine, kis_api, logs

	def test_schedule_loc_buys_marks_existing_reservation_and_budget_exhaustion_as_skip(self):
		engine, kis_api, logs = self._engine(
			buying_power_info={
				"executable_amount": 0,
				"executable_qty": 0,
				"broker_amount": 0,
				"broker_qty": 0,
				"estimated_amount": 155.59,
				"estimated_qty": 1,
				"auto_exchange_ready": True,
				"auto_exchange_usd": 0,
				"krw_auto_exchange_estimate_usd": 155.59,
			},
			reservation_orders=[
				{
					"side": "BUY",
					"symbol": "TQQQ",
					"exchange": "NASD",
					"qty": 1,
					"filled_qty": 0,
					"price": 153.12,
					"order_no": "0031033779",
					"cancel_yn": "N",
					"status_name": "접수",
					"trade_status_name": "정상",
					"reject_reason": "",
				}
			],
			watchlist_rows=[
				{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True},
				{"id": "w2", "symbol": "SOXL", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{"id": "c1", "symbol": "TQQQ", "status": "ACTIVE"},
				{"id": "c2", "symbol": "SOXL", "status": "ACTIVE"},
			],
		)

		result = engine.schedule_loc_buys()

		self.assertEqual(result["status"], "completed")
		self.assertEqual(result["scheduled_count"], 0)
		self.assertEqual(result["already_scheduled_count"], 1)
		self.assertEqual(result["skipped_count"], 1)
		self.assertEqual(result["error_count"], 0)
		self.assertEqual(kis_api.buy_calls, [])
		self.assertIn("0031033779", result["already_scheduled"][0]["order_no"])
		self.assertIn("reserved_today=$153.12", result["skipped"][0]["reason"])
		self.assertTrue(any(log["event_type"] == "LOC_BUY_ALREADY_SCHEDULED" for log in logs))
		self.assertTrue(any(log["event_type"] == "LOC_BUY_SKIPPED" for log in logs))

	def test_schedule_loc_buys_uses_estimated_amount_for_auto_exchange_attempt(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={
				"executable_amount": 0,
				"executable_qty": 0,
				"broker_amount": 0,
				"broker_qty": 0,
				"estimated_amount": 200.0,
				"estimated_qty": 1,
				"auto_exchange_ready": False,
				"auto_exchange_usd": 0,
				"krw_auto_exchange_estimate_usd": 200.0,
			},
			watchlist_rows=[
				{"id": "w1", "symbol": "SOXL", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{"id": "c1", "symbol": "SOXL", "status": "ACTIVE"},
			],
			configs={"us_auto_exchange_order_attempt_enabled": "true"},
		)

		result = engine.schedule_loc_buys()

		self.assertEqual(result["status"], "completed")
		self.assertEqual(result["scheduled_count"], 1)
		self.assertEqual(result["error_count"], 0)
		self.assertEqual(len(kis_api.buy_calls), 1)
		self.assertEqual(kis_api.buy_calls[0]["symbol"], "SOXL")


if __name__ == "__main__":
	unittest.main()
