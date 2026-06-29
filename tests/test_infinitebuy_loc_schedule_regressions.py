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

	def insert(self, data):
		row = copy.deepcopy(data)
		if not row.get("id"):
			row["id"] = f"row-{len(self._rows) + 1}"
		self._rows.append(row)
		return row["id"]


class _LegacyTradeDB(_FakeDB):
	def insert(self, data):
		if "broker_order_no" in data:
			raise Exception("table cycle_trade has no column named broker_order_no")
		if "source" in data:
			raise Exception("table cycle_trade has no column named source")
		return super().insert(data)


class _StructStub:
	def __init__(self, watchlist_rows, cycle_rows, configs=None):
		self._db = {
			"etf_watchlist": _FakeDB(watchlist_rows),
			"trading_cycle": _FakeDB(cycle_rows),
			"cycle_trade": _FakeDB([]),
			"trade_log": _FakeDB([]),
		}
		self.configs = dict(configs or {})

	def db(self, name):
		return self._db[name]

	def get_config(self, key, default=""):
		return self.configs.get(key, default)


class _KisApiStub:
	def __init__(self, buying_power_info, reservation_orders=None, order_history=None, holdings=None):
		self.buying_power_info = copy.deepcopy(buying_power_info)
		self.reservation_orders = copy.deepcopy(reservation_orders or [])
		self.order_history = copy.deepcopy(order_history or [])
		self.holdings = copy.deepcopy(holdings or [])
		self.buy_calls = []
		self.sell_calls = []
		self.sell_reservation_calls = []
		self.cancel_reservation_calls = []
		self.order_history_calls = []
		self.reservation_order_calls = []

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
		self.reservation_order_calls.append({
			"start_date": start_date,
			"end_date": end_date,
			"exchanges": list(exchanges or []),
		})
		return copy.deepcopy(self.reservation_orders)

	def get_overseas_order_history(self, start_date=None, end_date=None, symbol="", exchanges=None):
		self.order_history_calls.append({
			"start_date": start_date,
			"end_date": end_date,
			"symbol": symbol,
			"exchanges": list(exchanges or []),
		})
		if symbol:
			return [copy.deepcopy(row) for row in self.order_history if str(row.get("symbol", "")).upper() == str(symbol).upper()]
		return copy.deepcopy(self.order_history)

	def get_balance(self):
		return {"holdings": copy.deepcopy(self.holdings)}

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

	def sell_order(self, symbol, qty, price=0, order_type="LOC", exchange="NASD"):
		order = {
			"order_no": f"SELL-{len(self.sell_calls) + 1}",
			"symbol": symbol,
			"qty": qty,
			"price": price,
			"order_type": order_type,
			"exchange": exchange,
		}
		self.sell_calls.append(copy.deepcopy(order))
		return order

	def sell_reservation_order(self, symbol, qty, price=0, order_type="LOC", exchange="NASD"):
		order = {
			"order_no": f"RSV-SELL-{len(self.sell_reservation_calls) + 1}",
			"symbol": symbol,
			"qty": qty,
			"price": price,
			"order_type": order_type,
			"exchange": exchange,
		}
		self.sell_reservation_calls.append(copy.deepcopy(order))
		return order

	def cancel_overseas_reservation_order(self, reservation_order_no, symbol="", qty=0, exchange="NASD", side="", receipt_date=""):
		order = {
			"reserve_order_no": reservation_order_no,
			"symbol": symbol,
			"qty": qty,
			"exchange": exchange,
			"side": side,
			"receipt_date": receipt_date,
		}
		self.cancel_reservation_calls.append(copy.deepcopy(order))
		for reservation in self.reservation_orders:
			if str(reservation.get("order_no", reservation.get("reserve_order_no", ""))) == str(reservation_order_no):
				reservation["cancel_yn"] = "Y"
				reservation["status_name"] = "취소"
				reservation["trade_status_name"] = "취소"
		return order


class InfiniteBuyLocScheduleRegressionTests(unittest.TestCase):
	def test_engine_exposes_default_kis_api_loader(self):
		struct = _StructStub([], [])
		kis_api = object()
		struct.kis_api = kis_api
		engine = engine_module.Engine(struct)

		self.assertTrue(hasattr(engine, "_load_kis_api"))
		self.assertIs(engine._load_kis_api(), kis_api)

	def test_trade_insert_falls_back_while_legacy_schema_is_migrating(self):
		struct = _StructStub([], [])
		engine = engine_module.Engine(struct)
		trade_db = _LegacyTradeDB([])

		trade_id = engine._insert_trade_record(trade_db, {
			"symbol": "TQQQ",
			"action": "BUY",
			"filled_qty": 6,
			"filled_price": 86.84,
			"broker_order_no": "EXT-TQQQ-6",
			"source": "KIS",
		})

		self.assertTrue(trade_id)
		rows = trade_db.rows(symbol="TQQQ")
		self.assertEqual(len(rows), 1)
		self.assertNotIn("broker_order_no", rows[0])
		self.assertNotIn("source", rows[0])

	def _engine(self, buying_power_info, reservation_orders=None, order_history=None, watchlist_rows=None, cycle_rows=None, configs=None, holdings=None):
		watchlist_rows = watchlist_rows or []
		cycle_rows = cycle_rows or []
		struct = _StructStub(watchlist_rows, cycle_rows, configs=configs)
		engine = engine_module.Engine(struct)
		kis_api = _KisApiStub(buying_power_info, reservation_orders=reservation_orders, order_history=order_history, holdings=holdings)
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

	def test_schedule_loc_buys_uses_firegate_authoritative_state_instead_of_local_cycle(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={
				"executable_amount": 100000,
				"executable_qty": 1000,
				"broker_amount": 100000,
				"broker_qty": 1000,
			},
			reservation_orders=[],
			watchlist_rows=[
				{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{
					"id": "c1",
					"symbol": "TQQQ",
					"status": "ACTIVE",
					"current_round": 5,
					"t_value": 5,
					"division_count": 20,
					"target_profit": 15.0,
					"total_investment": 10000.0,
					"total_spent": 1000.0,
					"total_qty": 10,
					"avg_price": 100.0,
					"remaining_investment": 9000.0,
					"total_commission": 0.0,
				},
			],
			configs={"firegate_authoritative_reservations_only": "true"},
		)
		engine.calculate_buy_decision = engine_module.Engine.calculate_buy_decision.__get__(engine, engine.__class__)
		engine._load_firegate_authoritative_states = lambda symbol_filter="": {
			"states": {
				"TQQQ": {
					"symbol": "TQQQ",
					"current_round": 1,
					"t_value": 1,
					"division_count": 20,
					"target_profit": 15.0,
					"total_investment": 10000.0,
					"total_buy": 1000.0,
					"total_sell": 0.0,
					"buying_unit": 800.0,
					"total_spent": 400.0,
					"total_qty": 2,
					"avg_price": 200.0,
					"remaining_investment": 9000.0,
					"_firegate_authoritative": True,
				}
			},
			"error": "",
		}

		result = engine.schedule_loc_buys(symbol_filter="TQQQ")

		self.assertEqual(result["status"], "completed")
		self.assertTrue(result["firegate_authoritative"])
		self.assertGreaterEqual(len(kis_api.buy_calls), 2)
		self.assertAlmostEqual(kis_api.buy_calls[0]["price"], 200.0)
		self.assertEqual(kis_api.buy_calls[0]["qty"], 1)
		self.assertAlmostEqual(kis_api.buy_calls[1]["price"], 226.99)

	def test_schedule_loc_buys_blocks_local_fallback_when_firegate_state_is_missing(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={
				"executable_amount": 100000,
				"executable_qty": 1000,
			},
			reservation_orders=[],
			watchlist_rows=[
				{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{"id": "c1", "symbol": "TQQQ", "status": "ACTIVE"},
			],
			configs={"firegate_authoritative_reservations_only": "true"},
		)
		engine._load_firegate_authoritative_states = lambda symbol_filter="": {"states": {}, "error": ""}

		result = engine.schedule_loc_buys(symbol_filter="TQQQ")

		self.assertEqual(result["status"], "error")
		self.assertEqual(result["scheduled_count"], 0)
		self.assertEqual(kis_api.buy_calls, [])
		self.assertIn("로컬 DB 기준 예약을 차단", result["errors"][0]["reason"])

	def test_reservation_query_failure_does_not_look_like_missing_orders(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={
				"executable_amount": 100000,
				"executable_qty": 1000,
			},
			watchlist_rows=[
				{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{"id": "c1", "symbol": "TQQQ", "status": "ACTIVE"},
			],
		)

		def fail_reservation_query(*_args, **_kwargs):
			raise Exception("reservation query timeout")

		kis_api.get_overseas_reservation_orders = fail_reservation_query

		result = engine.schedule_loc_buys(symbol_filter="TQQQ")

		self.assertEqual(result["status"], "error")
		self.assertTrue(result["reservation_query_failed"])
		self.assertEqual(result["expected_count"], 0)
		self.assertEqual(result["missing_count"], 0)
		self.assertEqual(result["force_rebuild_count"], 0)
		self.assertEqual(kis_api.buy_calls, [])

	def test_cancelled_kis_reservation_code_is_not_treated_as_active(self):
		engine, _kis_api, _logs = self._engine(buying_power_info={})

		self.assertFalse(engine._reservation_order_is_active({
			"cancel_yn": "02",
			"status_name": "완료",
			"trade_status_name": "취소",
			"reject_reason": "",
		}))
		self.assertFalse(engine._reservation_order_is_active({
			"cancel_yn": "N",
			"status_name": "완료",
			"trade_status_name": "취소",
			"reject_reason": "",
		}))

	def test_already_cancelled_broker_response_does_not_block_rebuild(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={},
			reservation_orders=[
				{
					"side": "BUY",
					"symbol": "TQQQ",
					"exchange": "NASD",
					"qty": 3,
					"filled_qty": 0,
					"price": 78.59,
					"order_no": "TQQQ-OLD",
					"cancel_yn": "N",
					"status_name": "접수",
					"trade_status_name": "정상",
					"reject_reason": "",
				}
			],
		)

		def already_cancelled(*_args, **_kwargs):
			raise Exception("이미 취소처리된 신청내역입니다.")

		kis_api.cancel_overseas_reservation_order = already_cancelled

		result = engine.cancel_active_loc_reservations(symbols=["TQQQ"])

		self.assertEqual(result["status"], "completed")
		self.assertEqual(result["cancelled_count"], 0)
		self.assertEqual(result["skipped_count"], 1)
		self.assertEqual(result["error_count"], 0)
		self.assertTrue(result["skipped"][0]["inactive"])
		self.assertIn("이미 취소처리", result["skipped"][0]["reason"])

	def test_schedule_loc_sells_uses_firegate_authoritative_state_instead_of_local_cycle(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={},
			reservation_orders=[],
			watchlist_rows=[
				{"id": "w1", "symbol": "SOXL", "exchange": "AMEX", "is_active": True},
			],
			cycle_rows=[
				{
					"id": "c1",
					"symbol": "SOXL",
					"status": "ACTIVE",
					"total_qty": 99,
					"avg_price": 10.0,
					"total_spent": 990.0,
					"target_profit": 20.0,
					"total_commission": 0.0,
					"current_round": 1,
					"t_value": 1,
					"division_count": 20,
				},
			],
			configs={"firegate_authoritative_reservations_only": "true"},
		)
		engine.calculate_buy_decision = engine_module.Engine.calculate_buy_decision.__get__(engine, engine.__class__)
		engine._load_firegate_authoritative_states = lambda symbol_filter="": {
			"states": {
				"SOXL": {
					"symbol": "SOXL",
					"total_qty": 10,
					"avg_price": 200.0,
					"total_spent": 2000.0,
					"total_buy": 2200.0,
					"total_sell": 200.0,
					"target_profit": 20.0,
					"current_round": 3,
					"t_value": 3,
					"division_count": 20,
					"total_investment": 15000.0,
					"remaining_investment": 13000.0,
					"_firegate_authoritative": True,
				}
			},
			"error": "",
		}

		result = engine.schedule_loc_sells(symbol_filter="SOXL")

		self.assertEqual(result["status"], "completed")
		self.assertTrue(result["firegate_authoritative"])
		self.assertEqual([(call["price"], call["qty"]) for call in kis_api.sell_reservation_calls], [
			(228.0, 2),
			(240.0, 8),
		])

	def test_firegate_authoritative_buy_matches_firegate_web_v4_remaining_turn_formula(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={
				"executable_amount": 100000,
				"executable_qty": 1000,
				"broker_amount": 100000,
				"broker_qty": 1000,
			},
			reservation_orders=[],
			watchlist_rows=[
				{"id": "w1", "symbol": "SOXL", "exchange": "AMEX", "is_active": True},
			],
			cycle_rows=[
				{"id": "c1", "symbol": "SOXL", "status": "ACTIVE"},
			],
			configs={"firegate_authoritative_reservations_only": "true"},
		)
		engine.calculate_buy_decision = engine_module.Engine.calculate_buy_decision.__get__(engine, engine.__class__)
		engine._load_firegate_authoritative_states = lambda symbol_filter="": {
			"states": {
				"SOXL": {
					"symbol": "SOXL",
					"current_round": 3,
					"t_value": 3.5,
					"division_count": 20,
					"target_profit": 20.0,
					"total_investment": 15000.0,
					"buying_unit": 750.0,
					"buyingUnit": 750.0,
					"total_buy": 2989.23,
					"total_sell": 741.54,
					"total_spent": 2294.05,
					"total_qty": 10,
					"avg_price": 229.4046,
					"remaining_investment": 12000.0,
					"_firegate_authoritative": True,
				}
			},
			"error": "",
		}

		result = engine.schedule_loc_buys(symbol_filter="SOXL")

		self.assertEqual(result["status"], "completed")
		self.assertEqual(kis_api.buy_calls[0]["price"], 229.4)
		self.assertEqual(kis_api.buy_calls[0]["qty"], 2)
		self.assertEqual(kis_api.buy_calls[1]["price"], 259.22)
		self.assertEqual(kis_api.buy_calls[1]["qty"], 1)
		self.assertEqual([call["price"] for call in kis_api.buy_calls[2:]], [
			193.22,
			154.57,
			128.81,
			110.41,
			96.61,
			85.87,
			77.29,
		])

	def test_firegate_authoritative_sell_matches_firegate_web_v4_prices(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={},
			reservation_orders=[],
			watchlist_rows=[
				{"id": "w1", "symbol": "SOXL", "exchange": "AMEX", "is_active": True},
			],
			cycle_rows=[
				{"id": "c1", "symbol": "SOXL", "status": "ACTIVE"},
			],
			configs={"firegate_authoritative_reservations_only": "true"},
		)
		engine._load_firegate_authoritative_states = lambda symbol_filter="": {
			"states": {
				"SOXL": {
					"symbol": "SOXL",
					"total_qty": 10,
					"avg_price": 229.4046,
					"total_spent": 2294.046,
					"target_profit": 20.0,
					"current_round": 3,
					"t_value": 3.5,
					"division_count": 20,
					"_firegate_authoritative": True,
				}
			},
			"error": "",
		}

		result = engine.schedule_loc_sells(symbol_filter="SOXL")

		self.assertEqual(result["status"], "completed")
		self.assertEqual([(call["price"], call["qty"]) for call in kis_api.sell_reservation_calls], [
			(259.23, 2),
			(275.29, 8),
		])

	def test_schedule_loc_sells_corrects_soxl_stale_nasd_exchange_to_amex(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={},
			reservation_orders=[],
			watchlist_rows=[
				{"id": "w1", "symbol": "SOXL", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{
					"id": "c1",
					"symbol": "SOXL",
					"status": "ACTIVE",
					"total_qty": 10,
					"avg_price": 200.0,
					"total_spent": 2000.0,
					"target_profit": 20.0,
					"total_commission": 0.0,
					"current_round": 3,
					"t_value": 3,
					"division_count": 20,
				},
			],
			configs={"firegate_authoritative_reservations_only": "true"},
		)
		engine._load_firegate_authoritative_states = lambda symbol_filter="": {
			"states": {
				"SOXL": {
					"symbol": "SOXL",
					"total_qty": 10,
					"avg_price": 200.0,
					"total_spent": 2000.0,
					"target_profit": 20.0,
					"current_round": 3,
					"t_value": 3,
					"division_count": 20,
					"_firegate_authoritative": True,
				}
			},
			"error": "",
		}

		result = engine.schedule_loc_sells(symbol_filter="SOXL")

		self.assertEqual(result["status"], "completed")
		self.assertEqual({call["exchange"] for call in kis_api.sell_reservation_calls}, {"AMEX"})

	def test_schedule_loc_buys_firegate_default_reserves_first_line_as_limit(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={
				"executable_amount": 100000,
				"executable_qty": 1000,
			},
			reservation_orders=[],
			watchlist_rows=[
				{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{
					"id": "c1",
					"symbol": "TQQQ",
					"status": "ACTIVE",
					"current_round": 0,
					"division_count": 20,
					"target_profit": 10.0,
					"total_investment": 5000.0,
					"total_spent": 0.0,
					"total_qty": 0,
					"avg_price": 0.0,
					"remaining_investment": 5000.0,
					"total_commission": 0.0,
				},
			],
			configs={"buy_method": "firegate"},
		)
		engine.calculate_buy_decision = engine_module.Engine.calculate_buy_decision.__get__(engine, engine.__class__)
		kis_api.get_current_price = lambda symbol, exchange="NAS": {
			"symbol": symbol,
			"price": 100.0,
			"prev_close": 100.0,
			"order_exchange": "NASD",
		}

		result = engine.schedule_loc_buys(symbol_filter="TQQQ")

		self.assertEqual(result["status"], "completed")
		self.assertGreater(len(kis_api.buy_calls), 1)
		self.assertEqual(kis_api.buy_calls[0]["order_type"], "LIMIT")
		self.assertEqual(kis_api.buy_calls[0]["price"], 112.0)
		self.assertTrue(all(call["order_type"] == "LOC" for call in kis_api.buy_calls[1:]))

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
					"price": 150.0,
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

		self.assertEqual(result["status"], "partial_pending")
		self.assertEqual(result["scheduled_count"], 0)
		self.assertEqual(result["already_scheduled_count"], 1)
		self.assertEqual(result["skipped_count"], 1)
		self.assertEqual(result["error_count"], 0)
		self.assertEqual(result["expected_count"], 2)
		self.assertEqual(result["satisfied_count"], 1)
		self.assertEqual(result["missing_count"], 1)
		self.assertEqual(kis_api.buy_calls, [])
		self.assertIn("0031033779", result["already_scheduled"][0]["order_no"])
		self.assertIn("reserved_today=$150.00", result["skipped"][0]["reason"])
		self.assertTrue(any(log["event_type"] == "LOC_BUY_ALREADY_SCHEDULED" for log in logs))
		self.assertTrue(any(log["event_type"] == "LOC_BUY_SKIPPED" for log in logs))

	def test_schedule_loc_buys_submits_only_missing_firegate_ladder_lines(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={
				"executable_amount": 2000,
				"executable_qty": 10,
				"broker_amount": 2000,
				"broker_qty": 10,
			},
			reservation_orders=[
				{
					"side": "BUY",
					"symbol": "SOXL",
					"exchange": "NASD",
					"qty": 2,
					"filled_qty": 0,
					"price": 226.76,
					"order_no": "SOXL-AVG",
					"cancel_yn": "N",
					"status_name": "접수",
					"trade_status_name": "정상",
					"reject_reason": "",
				}
			],
			watchlist_rows=[
				{"id": "w1", "symbol": "SOXL", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{"id": "c1", "symbol": "SOXL", "status": "ACTIVE"},
			],
		)
		engine.calculate_buy_decision = lambda cycle, prev_close: {
			"should_buy": True,
			"order_type": "LOC",
			"reason": "FireGate v4 ladder",
			"buy_orders": [
				{"label": "LOC 평단", "loc_price": 226.76, "order_qty": 2},
				{"label": "LOC ★18.0%", "loc_price": 267.57, "order_qty": 1},
			],
		}

		result = engine.schedule_loc_buys(symbol_filter="SOXL")

		self.assertEqual(result["status"], "completed")
		self.assertTrue(result["complete"])
		self.assertEqual(result["expected_count"], 2)
		self.assertEqual(result["satisfied_count"], 2)
		self.assertEqual(result["missing_count"], 0)
		self.assertEqual(result["already_scheduled_count"], 1)
		self.assertEqual(result["scheduled_count"], 1)
		self.assertEqual(len(kis_api.buy_calls), 1)
		self.assertEqual(kis_api.buy_calls[0]["symbol"], "SOXL")
		self.assertAlmostEqual(kis_api.buy_calls[0]["price"], 267.57)

	def test_schedule_loc_buys_verify_mode_flags_missing_line_for_rebuild_without_ordering(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={
				"executable_amount": 2000,
				"executable_qty": 10,
				"broker_amount": 2000,
				"broker_qty": 10,
			},
			reservation_orders=[
				{
					"side": "BUY",
					"symbol": "SOXL",
					"exchange": "NASD",
					"qty": 2,
					"filled_qty": 0,
					"price": 226.76,
					"order_no": "SOXL-AVG",
					"cancel_yn": "N",
					"status_name": "접수",
					"trade_status_name": "정상",
					"reject_reason": "",
				}
			],
			watchlist_rows=[
				{"id": "w1", "symbol": "SOXL", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{"id": "c1", "symbol": "SOXL", "status": "ACTIVE"},
			],
		)
		engine.calculate_buy_decision = lambda cycle, prev_close: {
			"should_buy": True,
			"order_type": "LOC",
			"reason": "FireGate v4 ladder",
			"buy_orders": [
				{"label": "LOC 평단", "loc_price": 226.76, "order_qty": 2},
				{"label": "LOC ★18.0%", "loc_price": 267.57, "order_qty": 1},
			],
		}

		result = engine.schedule_loc_buys(symbol_filter="SOXL", allow_new_orders=False)

		self.assertEqual(result["status"], "partial_pending")
		self.assertEqual(result["expected_count"], 2)
		self.assertEqual(result["satisfied_count"], 1)
		self.assertEqual(result["scheduled_count"], 0)
		self.assertEqual(result["skipped_count"], 1)
		self.assertEqual(result["missing_count"], 1)
		self.assertEqual(result["force_rebuild_count"], 1)
		self.assertEqual(kis_api.buy_calls, [])
		self.assertTrue(result["skipped"][0]["force_rebuild"])

	def test_schedule_loc_buys_marks_under_reserved_line_for_immediate_rebuild(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={
				"executable_amount": 2000,
				"executable_qty": 10,
				"broker_amount": 2000,
				"broker_qty": 10,
			},
			reservation_orders=[
				{
					"side": "BUY",
					"symbol": "SOXL",
					"exchange": "NASD",
					"qty": 1,
					"filled_qty": 0,
					"price": 226.76,
					"order_no": "SOXL-UNDER",
					"cancel_yn": "N",
					"status_name": "접수",
					"trade_status_name": "정상",
					"reject_reason": "",
				}
			],
			watchlist_rows=[
				{"id": "w1", "symbol": "SOXL", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{"id": "c1", "symbol": "SOXL", "status": "ACTIVE"},
			],
		)
		engine.calculate_buy_decision = lambda cycle, prev_close: {
			"should_buy": True,
			"order_type": "LOC",
			"reason": "FireGate v4 ladder",
			"buy_orders": [
				{"label": "LOC 평단", "loc_price": 226.76, "order_qty": 2},
				{"label": "LOC ★18.0%", "loc_price": 267.57, "order_qty": 1},
			],
		}

		result = engine.schedule_loc_buys(symbol_filter="SOXL")

		self.assertEqual(result["status"], "partial_pending")
		self.assertEqual(result["force_rebuild_count"], 1)
		self.assertEqual(result["scheduled_count"], 0)
		self.assertEqual(kis_api.buy_calls, [])
		self.assertTrue(result["skipped"][0]["force_rebuild"])
		self.assertIn("expected_qty=2, active_qty=1", result["skipped"][0]["reason"])

	def test_schedule_loc_buys_matches_broker_exchange_alias(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={
				"executable_amount": 2000,
				"executable_qty": 10,
			},
			reservation_orders=[
				{
					"side": "BUY",
					"symbol": "TQQQ",
					"exchange": "NAS",
					"qty": 1,
					"filled_qty": 0,
					"price": 150.0,
					"order_no": "ALIAS-NAS",
					"cancel_yn": "N",
					"status_name": "접수",
					"trade_status_name": "정상",
					"reject_reason": "",
				}
			],
			watchlist_rows=[
				{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{"id": "c1", "symbol": "TQQQ", "status": "ACTIVE"},
			],
		)

		result = engine.schedule_loc_buys(symbol_filter="TQQQ")

		self.assertEqual(result["status"], "completed")
		self.assertEqual(result["already_scheduled_count"], 1)
		self.assertEqual(result["missing_count"], 0)
		self.assertEqual(kis_api.buy_calls, [])

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

	def test_schedule_loc_sells_does_not_duplicate_existing_sell_reservation(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={},
			reservation_orders=[
				{
					"side": "SELL",
					"symbol": "SOXL",
					"exchange": "NASD",
					"qty": 3,
					"filled_qty": 0,
					"price": 120.0,
					"order_no": "SOXL-SELL",
					"cancel_yn": "N",
					"status_name": "접수",
					"trade_status_name": "정상",
					"reject_reason": "",
				},
			],
			watchlist_rows=[
				{"id": "w1", "symbol": "SOXL", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{
					"id": "c1",
					"symbol": "SOXL",
					"status": "ACTIVE",
					"total_qty": 3,
					"avg_price": 100.0,
					"total_spent": 300.0,
					"target_profit": 5.0,
					"current_round": 1,
					"division_count": 20,
				},
			],
		)
		engine.calculate_sell_decision = lambda cycle, current_price: {
			"should_sell": True,
			"sell_type": engine_module.STRATEGY_FULL_SELL,
			"sell_qty": 3,
			"profit_rate": 50.0,
			"reason": "목표 수익률 도달",
		}

		result = engine.schedule_loc_sells(symbol_filter="SOXL")

		self.assertEqual(result["status"], "completed")
		self.assertEqual(result["expected_count"], 1)
		self.assertEqual(result["satisfied_count"], 1)
		self.assertEqual(result["already_scheduled_count"], 1)
		self.assertEqual(result["scheduled_count"], 0)
		self.assertEqual(kis_api.sell_calls, [])
		self.assertEqual(kis_api.sell_reservation_calls, [])

	def test_schedule_loc_sells_ignores_cancelled_sell_reservation_and_recovers(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={},
			reservation_orders=[
				{
					"side": "SELL",
					"symbol": "SOXL",
					"exchange": "NASD",
					"qty": 4,
					"filled_qty": 0,
					"price": 120.0,
					"order_no": "CANCELLED-SELL",
					"cancel_yn": "N",
					"status_name": "전송",
					"trade_status_name": "주문전송",
					"reject_reason": "DFD 주문종료 취소",
				},
			],
			watchlist_rows=[
				{"id": "w1", "symbol": "SOXL", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{
					"id": "c1",
					"symbol": "SOXL",
					"status": "ACTIVE",
					"total_qty": 4,
					"avg_price": 100.0,
					"total_spent": 400.0,
					"target_profit": 20.0,
					"current_round": 1,
					"division_count": 20,
				},
			],
		)

		result = engine.schedule_loc_sells(symbol_filter="SOXL")

		self.assertEqual(result["status"], "completed")
		self.assertEqual(result["already_scheduled_count"], 0)
		self.assertEqual(result["scheduled_count"], 2)
		self.assertEqual(result["expected_count"], 2)
		self.assertEqual(kis_api.sell_reservation_calls[0]["symbol"], "SOXL")
		self.assertEqual(kis_api.sell_reservation_calls[0]["qty"], 1)
		self.assertEqual(kis_api.sell_reservation_calls[0]["order_type"], "LOC")
		self.assertEqual(kis_api.sell_reservation_calls[0]["price"], 118.0)
		self.assertEqual(kis_api.sell_reservation_calls[1]["qty"], 3)
		self.assertEqual(kis_api.sell_reservation_calls[1]["order_type"], "LIMIT")
		self.assertEqual(kis_api.sell_reservation_calls[1]["price"], 120.0)

	def test_schedule_loc_sells_verify_mode_flags_missing_lines_for_rebuild_without_ordering(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={},
			reservation_orders=[],
			watchlist_rows=[
				{"id": "w1", "symbol": "SOXL", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{
					"id": "c1",
					"symbol": "SOXL",
					"status": "ACTIVE",
					"total_qty": 4,
					"avg_price": 100.0,
					"total_spent": 400.0,
					"target_profit": 20.0,
					"current_round": 1,
					"division_count": 20,
				},
			],
		)

		result = engine.schedule_loc_sells(symbol_filter="SOXL", allow_new_orders=False)

		self.assertEqual(result["status"], "partial_pending")
		self.assertEqual(result["scheduled_count"], 0)
		self.assertEqual(result["skipped_count"], 2)
		self.assertEqual(result["missing_count"], 2)
		self.assertEqual(result["force_rebuild_count"], 2)
		self.assertEqual(kis_api.sell_calls, [])
		self.assertEqual(kis_api.sell_reservation_calls, [])
		self.assertTrue(all(row["force_rebuild"] for row in result["skipped"]))

	def test_schedule_loc_sells_uses_firegate_floor_target_without_sell_fee(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={},
			reservation_orders=[],
			watchlist_rows=[
				{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{
					"id": "c1",
					"symbol": "TQQQ",
					"status": "ACTIVE",
					"total_qty": 8,
					"avg_price": 79.7375,
					"total_spent": 637.9,
					"target_profit": 15.0,
					"total_commission": 1.59,
					"current_round": 1,
					"division_count": 20,
				},
			],
			configs={
				"sell_strategy": "firegate",
				"sell_commission_rate": "0.25",
			},
		)

		result = engine.schedule_loc_sells(symbol_filter="TQQQ")

		self.assertEqual(result["status"], "completed")
		self.assertEqual(result["scheduled_count"], 2)
		self.assertEqual(len(kis_api.sell_reservation_calls), 2)
		self.assertEqual(kis_api.sell_reservation_calls[0]["qty"], 2)
		self.assertEqual(kis_api.sell_reservation_calls[0]["order_type"], "LOC")
		self.assertEqual(kis_api.sell_reservation_calls[0]["price"], 90.5)
		self.assertEqual(kis_api.sell_reservation_calls[1]["qty"], 6)
		self.assertEqual(kis_api.sell_reservation_calls[1]["order_type"], "LIMIT")
		self.assertEqual(kis_api.sell_reservation_calls[1]["price"], 91.7)

	def test_schedule_loc_sells_loc_method_keeps_firegate_split_quantities_with_loc_order_type(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={},
			reservation_orders=[],
			watchlist_rows=[
				{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{
					"id": "c1",
					"symbol": "TQQQ",
					"status": "ACTIVE",
					"total_qty": 14,
					"avg_price": 79.6087,
					"total_spent": 1114.52,
					"target_profit": 15.0,
					"total_commission": 0.0,
					"current_round": 5,
					"t_value": 5,
					"division_count": 20,
				},
			],
			configs={
				"sell_method": "loc",
				"sell_strategy": "firegate",
			},
		)

		result = engine.schedule_loc_sells(symbol_filter="TQQQ")

		self.assertEqual(result["status"], "completed")
		self.assertEqual(result["scheduled_count"], 2)
		self.assertEqual(len(kis_api.sell_reservation_calls), 2)
		self.assertEqual(kis_api.sell_reservation_calls[0]["symbol"], "TQQQ")
		self.assertEqual(kis_api.sell_reservation_calls[0]["qty"], 3)
		self.assertEqual(kis_api.sell_reservation_calls[0]["order_type"], "LOC")
		self.assertEqual(kis_api.sell_reservation_calls[0]["price"], 85.58)
		self.assertEqual(kis_api.sell_reservation_calls[1]["qty"], 11)
		self.assertEqual(kis_api.sell_reservation_calls[1]["order_type"], "LOC")
		self.assertEqual(kis_api.sell_reservation_calls[1]["price"], 91.55)

	def test_schedule_loc_sells_loc_method_matches_current_tqqq_firegate_lines(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={},
			reservation_orders=[],
			watchlist_rows=[
				{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{
					"id": "c1",
					"symbol": "TQQQ",
					"status": "ACTIVE",
					"total_qty": 33,
					"avg_price": 76.64,
					"total_spent": 2529.12,
					"target_profit": 15.0,
					"total_commission": 0.0,
					"current_round": 8,
					"t_value": 8.5,
					"division_count": 20,
				},
			],
			configs={
				"sell_method": "loc",
				"sell_strategy": "firegate",
			},
		)

		result = engine.schedule_loc_sells(symbol_filter="TQQQ")

		self.assertEqual(result["status"], "completed")
		self.assertEqual(result["scheduled_count"], 2)
		self.assertEqual([(c["price"], c["qty"], c["order_type"]) for c in kis_api.sell_reservation_calls], [
			(78.36, 8, "LOC"),
			(88.14, 25, "LOC"),
		])

	def test_schedule_loc_sells_firegate_default_matches_firegate_split_lines(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={},
			reservation_orders=[],
			watchlist_rows=[
				{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{
					"id": "c1",
					"symbol": "TQQQ",
					"status": "ACTIVE",
					"total_qty": 18,
					"avg_price": 79.61,
					"total_spent": 1432.98,
					"target_profit": 15.0,
					"total_commission": 0.0,
					"current_round": 5,
					"t_value": 5,
					"division_count": 20,
				},
			],
			configs={
				"sell_method": "firegate",
				"sell_strategy": "firegate",
			},
		)

		result = engine.schedule_loc_sells(symbol_filter="TQQQ")

		self.assertEqual(result["status"], "completed")
		self.assertEqual(result["scheduled_count"], 2)
		self.assertEqual(kis_api.sell_reservation_calls[0]["qty"], 4)
		self.assertEqual(kis_api.sell_reservation_calls[0]["order_type"], "LOC")
		self.assertEqual(kis_api.sell_reservation_calls[0]["price"], 85.58)
		self.assertEqual(kis_api.sell_reservation_calls[1]["qty"], 14)
		self.assertEqual(kis_api.sell_reservation_calls[1]["order_type"], "LIMIT")
		self.assertEqual(kis_api.sell_reservation_calls[1]["price"], 91.55)

	def test_schedule_loc_sells_marks_over_reserved_line_for_immediate_rebuild(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={},
			reservation_orders=[
				{
					"side": "SELL",
					"symbol": "TQQQ",
					"exchange": "NASD",
					"qty": 8,
					"filled_qty": 0,
					"price": 85.58,
					"order_no": "DUP-LOC",
					"cancel_yn": "N",
					"status_name": "접수",
					"trade_status_name": "정상",
					"reject_reason": "",
				},
				{
					"side": "SELL",
					"symbol": "TQQQ",
					"exchange": "NASD",
					"qty": 14,
					"filled_qty": 0,
					"price": 91.55,
					"order_no": "OK-LIMIT",
					"cancel_yn": "N",
					"status_name": "접수",
					"trade_status_name": "정상",
					"reject_reason": "",
				},
			],
			watchlist_rows=[
				{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{
					"id": "c1",
					"symbol": "TQQQ",
					"status": "ACTIVE",
					"total_qty": 18,
					"avg_price": 79.61,
					"total_spent": 1432.98,
					"target_profit": 15.0,
					"total_commission": 0.0,
					"current_round": 5,
					"t_value": 5,
					"division_count": 20,
				},
			],
			configs={
				"sell_method": "firegate",
				"sell_strategy": "firegate",
			},
		)

		result = engine.schedule_loc_sells(symbol_filter="TQQQ")

		self.assertEqual(result["status"], "partial_pending")
		self.assertEqual(result["force_rebuild_count"], 1)
		self.assertEqual(result["scheduled_count"], 0)
		self.assertEqual(kis_api.sell_reservation_calls, [])
		self.assertTrue(result["skipped"][0]["force_rebuild"])

	def test_schedule_loc_sells_marks_under_reserved_line_for_immediate_rebuild(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={},
			reservation_orders=[
				{
					"side": "SELL",
					"symbol": "TQQQ",
					"exchange": "NASD",
					"qty": 8,
					"filled_qty": 0,
					"price": 88.14,
					"order_type": "LOC",
					"order_no": "WRONG-LOC",
					"cancel_yn": "N",
					"status_name": "접수",
					"trade_status_name": "정상",
					"reject_reason": "",
				},
			],
			watchlist_rows=[
				{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{
					"id": "c1",
					"symbol": "TQQQ",
					"status": "ACTIVE",
					"total_qty": 33,
					"avg_price": 76.64,
					"total_spent": 2529.12,
					"target_profit": 15.0,
					"total_commission": 0.0,
					"current_round": 6,
					"t_value": 6,
					"division_count": 20,
				},
			],
			configs={
				"sell_method": "firegate",
				"sell_strategy": "firegate",
			},
		)

		result = engine.schedule_loc_sells(symbol_filter="TQQQ")

		self.assertEqual(result["status"], "partial_pending")
		self.assertEqual(result["force_rebuild_count"], 1)
		self.assertEqual(result["scheduled_count"], 0)
		self.assertEqual(kis_api.sell_reservation_calls, [])
		self.assertTrue(result["skipped"][0]["force_rebuild"])
		self.assertEqual(result["skipped"][0]["expected_qty"], 25)
		self.assertEqual(result["skipped"][0]["active_qty"], 8)
		self.assertEqual(result["skipped"][0]["expected_order_type"], "LIMIT")
		self.assertEqual(result["skipped"][0]["active_order_type"], "LOC")

	def test_rebuild_loc_reservations_cancels_wrong_existing_order_then_reschedules(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={
				"executable_amount": 100000,
				"executable_qty": 1000,
			},
			reservation_orders=[
				{
					"side": "SELL",
					"symbol": "TQQQ",
					"exchange": "NASD",
					"qty": 14,
					"filled_qty": 0,
					"price": 91.55,
					"order_no": "WRONG-SELL",
					"cancel_yn": "N",
					"status_name": "접수",
					"trade_status_name": "정상",
					"reject_reason": "",
				},
			],
			watchlist_rows=[
				{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{
					"id": "c1",
					"symbol": "TQQQ",
					"status": "ACTIVE",
					"total_qty": 14,
					"avg_price": 79.6087,
					"total_spent": 1114.52,
					"target_profit": 15.0,
					"total_commission": 0.0,
					"current_round": 5,
					"t_value": 5,
					"division_count": 20,
					"total_investment": 10000,
					"remaining_investment": 8885.48,
				},
			],
			configs={
				"sell_method": "loc",
				"sell_strategy": "firegate",
			},
		)

		result = engine.rebuild_loc_reservations(["TQQQ"])

		self.assertEqual(result["cancel"]["cancelled_count"], 1)
		self.assertEqual(kis_api.cancel_reservation_calls[0]["reserve_order_no"], "WRONG-SELL")
		self.assertTrue(any(call["symbol"] == "TQQQ" and call["price"] == 85.58 for call in kis_api.sell_reservation_calls))

	def test_cancel_active_reservations_queries_previous_receipt_date_after_midnight(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={},
			reservation_orders=[
				{
					"side": "BUY",
					"symbol": "TQQQ",
					"exchange": "NASD",
					"qty": 4,
					"filled_qty": 0,
					"price": 85.57,
					"order_no": "OVERNIGHT-BUY",
					"receipt_date": "20260624",
					"cancel_yn": "N",
					"status_name": "접수",
					"trade_status_name": "정상",
					"reject_reason": "",
				},
			],
		)
		engine._now = lambda: datetime.datetime(2026, 6, 25, 1, 30, 0)

		result = engine.cancel_active_loc_reservations(symbols=["TQQQ"])

		self.assertEqual(result["status"], "completed")
		self.assertEqual(kis_api.reservation_order_calls[-1]["start_date"], "20260624")
		self.assertEqual(kis_api.cancel_reservation_calls[0]["reserve_order_no"], "OVERNIGHT-BUY")
		self.assertEqual(kis_api.cancel_reservation_calls[0]["receipt_date"], "20260624")

	def test_schedule_loc_sells_reserves_target_price_before_current_profit_hits(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={},
			reservation_orders=[],
			watchlist_rows=[
				{"id": "w1", "symbol": "SOXL", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{
					"id": "c1",
					"symbol": "SOXL",
					"status": "ACTIVE",
					"total_qty": 3,
					"avg_price": 100.0,
					"total_spent": 300.0,
					"target_profit": 10.0,
					"total_commission": 0.0,
					"division_count": 20,
					"current_round": 1,
				},
			],
		)
		kis_api.get_current_price = lambda symbol, exchange="NAS": {
			"symbol": symbol,
			"price": 101.0,
			"prev_close": 100.0,
			"order_exchange": "NASD",
		}

		result = engine.schedule_loc_sells(symbol_filter="SOXL")

		self.assertEqual(result["status"], "completed")
		self.assertEqual(result["expected_count"], 1)
		self.assertEqual(result["scheduled_count"], 1)
		self.assertEqual(result["missing_count"], 0)
		self.assertEqual(len(kis_api.sell_reservation_calls), 1)
		self.assertEqual(kis_api.sell_calls, [])
		self.assertEqual(kis_api.sell_reservation_calls[0]["symbol"], "SOXL")
		self.assertEqual(kis_api.sell_reservation_calls[0]["qty"], 3)
		self.assertEqual(kis_api.sell_reservation_calls[0]["order_type"], "LIMIT")
		self.assertEqual(kis_api.sell_reservation_calls[0]["price"], 120.0)
		self.assertGreater(kis_api.sell_reservation_calls[0]["price"], 101.0)

	def test_external_cycle_sync_creates_cycle_for_watchlist_buy_fill(self):
		engine, _kis_api, _logs = self._engine(
			buying_power_info={},
			order_history=[
				{
					"symbol": "SOXL",
					"status": "FILLED",
					"action": "BUY",
					"filled_qty": 3,
					"filled_price": 226.76,
					"order_price": 226.76,
					"order_date": "20260622",
					"order_time": "220100",
					"order_no": "EXT-BUY-1",
					"broker": "KIS",
				}
			],
			watchlist_rows=[
				{
					"id": "w1",
					"symbol": "SOXL",
					"exchange": "NASD",
					"is_active": True,
					"total_investment": 15000,
					"division_count": 20,
					"target_profit": 10,
				},
			],
			cycle_rows=[],
		)

		result = engine.sync_external_cycle_trades(lookback_days=7, symbol_filter="SOXL")
		cycle = engine._cycle_db().get(symbol="SOXL", status=engine_module.STATUS_ACTIVE)
		trades = engine._trade_db().rows(symbol="SOXL", action=engine_module.ACTION_BUY)

		self.assertEqual(result["status"], "completed")
		self.assertTrue(result["verified"])
		self.assertEqual(result["synced_count"], 1)
		self.assertEqual(result["unresolved_count"], 0)
		self.assertIsNotNone(cycle)
		self.assertEqual(cycle["total_qty"], 3)
		self.assertEqual(cycle["current_round"], 1)
		self.assertEqual(len(trades), 1)
		self.assertEqual(trades[0]["broker_order_no"], "EXT-BUY-1")

	def test_external_cycle_sync_activates_inactive_watchlist_when_broker_buy_fill_exists(self):
		engine, _kis_api, logs = self._engine(
			buying_power_info={},
			order_history=[
				{
					"symbol": "TQQQ",
					"status": "FILLED",
					"action": "BUY",
					"filled_qty": 6,
					"filled_price": 86.84,
					"order_price": 86.84,
					"order_date": "20260622",
					"order_time": "230100",
					"order_no": "EXT-TQQQ-6",
					"broker": "KIS",
				}
			],
			watchlist_rows=[
				{
					"id": "w1",
					"symbol": "TQQQ",
					"exchange": "NASD",
					"is_active": False,
					"total_investment": 10000,
					"division_count": 20,
					"target_profit": 10,
				},
			],
			cycle_rows=[],
		)

		result = engine.sync_external_cycle_trades(lookback_days=7, symbol_filter="TQQQ")
		cycle = engine._cycle_db().get(symbol="TQQQ", status=engine_module.STATUS_ACTIVE)
		watchlist = engine._watchlist_db().get(symbol="TQQQ")
		trades = engine._trade_db().rows(symbol="TQQQ", action=engine_module.ACTION_BUY)

		self.assertEqual(result["status"], "completed")
		self.assertTrue(result["verified"])
		self.assertEqual(result["synced_count"], 1)
		self.assertEqual(result["eligible_order_count"], 1)
		self.assertEqual(result["raw_order_count"], 1)
		self.assertTrue(watchlist["is_active"])
		self.assertIsNotNone(cycle)
		self.assertEqual(cycle["total_qty"], 6)
		self.assertEqual(len(trades), 1)
		self.assertEqual(trades[0]["broker_order_no"], "EXT-TQQQ-6")
		self.assertTrue(any(log["event_type"] == "WATCHLIST_AUTO_ACTIVATE" for log in logs))

	def test_external_cycle_sync_creates_default_tqqq_watchlist_when_buy_fill_exists(self):
		engine, _kis_api, logs = self._engine(
			buying_power_info={},
			order_history=[
				{
					"symbol": "TQQQ",
					"status": "FILLED",
					"action": "BUY",
					"filled_qty": 6,
					"filled_price": 86.84,
					"order_price": 86.84,
					"order_date": "20260622",
					"order_time": "230100",
					"order_no": "EXT-TQQQ-6",
					"broker": "KIS",
				}
			],
			watchlist_rows=[],
			cycle_rows=[],
		)

		result = engine.sync_external_cycle_trades(lookback_days=7, symbol_filter="TQQQ")
		watchlist = engine._watchlist_db().get(symbol="TQQQ")
		cycle = engine._cycle_db().get(symbol="TQQQ", status=engine_module.STATUS_ACTIVE)
		trades = engine._trade_db().rows(symbol="TQQQ", action=engine_module.ACTION_BUY)

		self.assertEqual(result["status"], "completed")
		self.assertTrue(result["verified"])
		self.assertEqual(result["synced_count"], 1)
		self.assertEqual(result["target_symbols"], ["TQQQ"])
		self.assertIsNotNone(watchlist)
		self.assertTrue(watchlist["is_active"])
		self.assertEqual(watchlist["total_investment"], 10000.0)
		self.assertIsNotNone(cycle)
		self.assertEqual(cycle["total_qty"], 6)
		self.assertEqual(len(trades), 1)
		self.assertEqual(trades[0]["broker_order_no"], "EXT-TQQQ-6")
		self.assertTrue(any(log["event_type"] == "WATCHLIST_AUTO_CREATE" for log in logs))

	def test_external_cycle_sync_queries_each_target_symbol(self):
		engine, kis_api, _logs = self._engine(
			buying_power_info={},
			order_history=[
				{
					"symbol": "TQQQ",
					"status": "FILLED",
					"action": "BUY",
					"filled_qty": 6,
					"filled_price": 82.58,
					"order_price": 91.69,
					"order_date": "20260622",
					"order_time": "222005",
					"order_no": "EXT-TQQQ-20260622",
					"broker": "KIS",
				}
			],
			watchlist_rows=[
				{"id": "w1", "symbol": "SOXL", "exchange": "NASD", "is_active": True},
				{"id": "w2", "symbol": "TQQQ", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[
				{
					"id": "c1",
					"symbol": "TQQQ",
					"status": "ACTIVE",
					"current_round": 3,
					"division_count": 20,
					"target_profit": 15,
					"total_investment": 10000,
					"total_spent": 637.9,
					"total_qty": 8,
					"avg_price": 79.7375,
					"remaining_investment": 9362.1,
					"total_commission": 1.59,
				},
			],
		)

		result = engine.sync_external_cycle_trades(lookback_days=7)

		self.assertEqual(result["status"], "completed")
		self.assertEqual(result["synced_count"], 1)
		self.assertEqual(engine._cycle_db().get(id="c1")["total_qty"], 6)
		self.assertIn("TQQQ", {call["symbol"] for call in kis_api.order_history_calls})
		self.assertIn("SOXL", {call["symbol"] for call in kis_api.order_history_calls})

	def test_external_cycle_sync_imports_verified_broker_fills_without_local_qty_cap(self):
		base_cycle = {
			"id": "c1",
			"symbol": "TQQQ",
			"status": "ACTIVE",
			"current_round": 3,
			"division_count": 20,
			"target_profit": 15,
			"total_investment": 10000,
			"total_spent": 637.9,
			"total_qty": 8,
			"avg_price": 79.7375,
			"remaining_investment": 9362.1,
			"total_commission": 1.59,
		}
		order_history = [
			{"symbol": "TQQQ", "status": "FILLED", "action": "BUY", "filled_qty": 2, "filled_price": 82.58, "order_price": 91.69, "order_date": "20260619", "order_time": "222005", "order_no": "OLD-DUP-2", "broker": "KIS"},
			{"symbol": "TQQQ", "status": "FILLED", "action": "BUY", "filled_qty": 1, "filled_price": 82.58, "order_price": 93.62, "order_date": "20260619", "order_time": "222005", "order_no": "OLD-DUP-1", "broker": "KIS"},
			{"symbol": "TQQQ", "status": "FILLED", "action": "BUY", "filled_qty": 2, "filled_price": 82.58, "order_price": 91.69, "order_date": "20260622", "order_time": "222005", "order_no": "NEW-A-2", "broker": "KIS"},
			{"symbol": "TQQQ", "status": "FILLED", "action": "BUY", "filled_qty": 1, "filled_price": 82.58, "order_price": 93.62, "order_date": "20260622", "order_time": "222005", "order_no": "NEW-A-1", "broker": "KIS"},
			{"symbol": "TQQQ", "status": "FILLED", "action": "BUY", "filled_qty": 2, "filled_price": 82.58, "order_price": 91.69, "order_date": "20260622", "order_time": "222020", "order_no": "NEW-B-2", "broker": "KIS"},
			{"symbol": "TQQQ", "status": "FILLED", "action": "BUY", "filled_qty": 1, "filled_price": 82.58, "order_price": 93.62, "order_date": "20260622", "order_time": "222020", "order_no": "NEW-B-1", "broker": "KIS"},
		]
		engine, _kis_api, _logs = self._engine(
			buying_power_info={},
			order_history=order_history,
			holdings=[{"symbol": "TQQQ", "qty": 14}],
			watchlist_rows=[
				{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True},
			],
			cycle_rows=[base_cycle],
		)

		result = engine.sync_external_cycle_trades(lookback_days=7, symbol_filter="TQQQ")
		trades = engine._trade_db().rows(symbol="TQQQ", action=engine_module.ACTION_BUY)
		order_nos = {row["broker_order_no"] for row in trades}

		self.assertEqual(result["status"], "partial_pending")
		self.assertFalse(result["verified"])
		self.assertEqual(result["synced_count"], 6)
		self.assertEqual(result["balance_aligned_count"], 1)
		self.assertEqual(engine._cycle_db().get(id="c1")["total_qty"], 14)
		self.assertEqual(order_nos, {"OLD-DUP-1", "OLD-DUP-2", "NEW-A-1", "NEW-A-2", "NEW-B-1", "NEW-B-2"})
		self.assertEqual(result["holding_mismatch_count"], 0)
		self.assertEqual(result["unresolved"][0]["broker_qty"], 14)
		self.assertEqual(result["unresolved"][0]["local_cycle_qty"], 9)

	def test_external_cycle_sync_refuses_unstable_three_pass_history(self):
		order = {
			"symbol": "TQQQ",
			"status": "FILLED",
			"action": "BUY",
			"filled_qty": 6,
			"filled_price": 86.84,
			"order_price": 86.84,
			"order_date": "20260528",
			"order_time": "230100",
			"order_no": "EXT-TQQQ-6",
			"broker": "KIS",
		}
		engine, kis_api, _logs = self._engine(
			buying_power_info={},
			order_history=[],
			watchlist_rows=[{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True}],
			cycle_rows=[],
		)
		call_count = {"value": 0}

		def unstable_history(start_date=None, end_date=None, symbol="", exchanges=None):
			call_count["value"] += 1
			if call_count["value"] <= 2:
				return [copy.deepcopy(order)]
			if call_count["value"] <= 4:
				return []
			return [copy.deepcopy(order)]

		kis_api.get_overseas_order_history = unstable_history

		result = engine.sync_external_cycle_trades(lookback_days=1, symbol_filter="TQQQ")

		self.assertEqual(result["status"], "error")
		self.assertFalse(result["verified"])
		self.assertEqual(result["synced_count"], 0)
		self.assertEqual(engine._trade_db().rows(symbol="TQQQ"), [])
		self.assertEqual(result["history_verification"]["reason"], "history_unstable")

	def test_external_cycle_sync_corrects_same_order_no_qty_mismatch(self):
		base_cycle = {
			"id": "c1",
			"symbol": "TQQQ",
			"status": "ACTIVE",
			"current_round": 1,
			"division_count": 20,
			"target_profit": 15,
			"total_investment": 10000,
			"total_spent": 400.0,
			"total_qty": 5,
			"avg_price": 80.0,
			"remaining_investment": 9600.0,
			"total_commission": 1.0,
		}
		order = {
			"symbol": "TQQQ",
			"status": "FILLED",
			"action": "BUY",
			"filled_qty": 6,
			"filled_price": 82.0,
			"order_price": 82.0,
			"order_date": "20260528",
			"order_time": "230100",
			"order_no": "EXT-TQQQ-6",
			"broker": "KIS",
		}
		engine, _kis_api, _logs = self._engine(
			buying_power_info={},
			order_history=[order],
			holdings=[{"symbol": "TQQQ", "qty": 6}],
			watchlist_rows=[{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True}],
			cycle_rows=[base_cycle],
		)
		engine._trade_db().insert({
			"id": "t1",
			"cycle_id": "c1",
			"symbol": "TQQQ",
			"round": 1,
			"trade_date": "2026-05-28",
			"action": engine_module.ACTION_BUY,
			"order_type": "EXTERNAL",
			"order_price": 80.0,
			"order_qty": 5,
			"filled_price": 80.0,
			"filled_qty": 5,
			"filled_amount": 400.0,
			"commission": 1.0,
			"status": engine_module.ORDER_FILLED,
			"broker_order_no": "EXT-TQQQ-6",
			"source": "KIS",
			"memo": "old wrong row",
			"created": datetime.datetime(2026, 5, 28, 23, 2, 0),
		})

		result = engine.sync_external_cycle_trades(lookback_days=1, symbol_filter="TQQQ")
		trade = engine._trade_db().get(id="t1")
		cycle = engine._cycle_db().get(id="c1")

		self.assertEqual(result["status"], "completed")
		self.assertTrue(result["verified"])
		self.assertEqual(result["corrected_count"], 1)
		self.assertEqual(trade["filled_qty"], 6)
		self.assertEqual(trade["filled_price"], 82.0)
		self.assertEqual(cycle["total_qty"], 6)
		self.assertEqual(result["holding_mismatch_count"], 0)

	def test_external_cycle_sync_links_matching_local_trade_without_order_no(self):
		base_cycle = {
			"id": "c1",
			"symbol": "TQQQ",
			"status": "ACTIVE",
			"current_round": 1,
			"division_count": 20,
			"target_profit": 15,
			"total_investment": 10000,
			"total_spent": 492.0,
			"total_qty": 6,
			"avg_price": 82.0,
			"remaining_investment": 9508.0,
			"total_commission": 0.0,
		}
		order = {
			"symbol": "TQQQ",
			"status": "FILLED",
			"action": "BUY",
			"filled_qty": 6,
			"filled_price": 82.0,
			"order_price": 82.0,
			"order_date": "20260528",
			"order_time": "230100",
			"order_no": "EXT-TQQQ-LINK",
			"broker": "KIS",
		}
		engine, _kis_api, _logs = self._engine(
			buying_power_info={},
			order_history=[order],
			holdings=[{"symbol": "TQQQ", "qty": 6}],
			watchlist_rows=[{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True}],
			cycle_rows=[base_cycle],
		)
		engine._trade_db().insert({
			"id": "t1",
			"cycle_id": "c1",
			"symbol": "TQQQ",
			"round": 1,
			"trade_date": "2026-05-28",
			"action": engine_module.ACTION_BUY,
			"order_type": "LOC",
			"order_price": 82.0,
			"order_qty": 6,
			"filled_price": 82.0,
			"filled_qty": 6,
			"filled_amount": 492.0,
			"commission": 0.0,
			"status": engine_module.ORDER_FILLED,
			"broker_order_no": "",
			"source": "",
			"memo": "site fill without broker order id",
			"created": datetime.datetime(2026, 5, 28, 17, 40, 0),
		})

		result = engine.sync_external_cycle_trades(lookback_days=1, symbol_filter="TQQQ")
		trade = engine._trade_db().get(id="t1")
		cycle = engine._cycle_db().get(id="c1")

		self.assertEqual(result["status"], "completed")
		self.assertTrue(result["verified"])
		self.assertEqual(result["corrected_count"], 1)
		self.assertEqual(result["synced_count"], 1)
		self.assertEqual(trade["broker_order_no"], "EXT-TQQQ-LINK")
		self.assertEqual(trade["source"], "KIS")
		self.assertEqual(cycle["total_qty"], 6)
		self.assertEqual(len(engine._trade_db().rows(symbol="TQQQ")), 1)

	def test_external_cycle_sync_converts_verified_fill_to_real_row_when_cycle_qty_already_matches_broker(self):
		base_cycle = {
			"id": "c1",
			"symbol": "TQQQ",
			"status": "ACTIVE",
			"current_round": 1,
			"division_count": 20,
			"target_profit": 15,
			"total_investment": 10000,
			"total_spent": 492.0,
			"total_qty": 6,
			"avg_price": 82.0,
			"remaining_investment": 9508.0,
			"total_commission": 0.0,
		}
		order = {
			"symbol": "TQQQ",
			"status": "FILLED",
			"action": "BUY",
			"filled_qty": 6,
			"filled_price": 82.0,
			"order_price": 82.0,
			"order_date": "20260528",
			"order_time": "230100",
			"order_no": "EXT-TQQQ-AUDIT",
			"broker": "KIS",
		}
		engine, _kis_api, _logs = self._engine(
			buying_power_info={},
			order_history=[order],
			holdings=[{"symbol": "TQQQ", "qty": 6}],
			watchlist_rows=[{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True}],
			cycle_rows=[base_cycle],
		)

		result = engine.sync_external_cycle_trades(lookback_days=1, symbol_filter="TQQQ")
		cycle = engine._cycle_db().get(id="c1")
		trades = engine._trade_db().rows(symbol="TQQQ", action=engine_module.ACTION_BUY)
		recalc = engine._recalculate_cycle_from_trades("c1")

		self.assertEqual(result["status"], "completed")
		self.assertTrue(result["verified"])
		self.assertEqual(result["audited_count"], 0)
		self.assertEqual(result["synced_count"], 1)
		self.assertEqual(cycle["total_qty"], 6)
		self.assertEqual(len(trades), 1)
		self.assertEqual(trades[0]["order_type"], "EXTERNAL")
		self.assertEqual(trades[0]["broker_order_no"], "EXT-TQQQ-AUDIT")
		self.assertEqual(recalc["total_qty"], 6)

	def test_external_cycle_sync_reports_broker_holding_qty_gap_without_fake_trade(self):
		base_cycle = {
			"id": "c1",
			"symbol": "TQQQ",
			"status": "ACTIVE",
			"current_round": 15,
			"division_count": 20,
			"target_profit": 15,
			"total_investment": 10000,
			"total_spent": 2416.33,
			"total_qty": 31,
			"avg_price": 77.9461,
			"remaining_investment": 7583.67,
			"total_commission": 1.0,
		}
		engine, _kis_api, _logs = self._engine(
			buying_power_info={},
			order_history=[],
			holdings=[{"symbol": "TQQQ", "qty": 33, "avg_price": 78.0, "current_price": 79.0}],
			watchlist_rows=[{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True}],
			cycle_rows=[base_cycle],
		)

		result = engine.sync_external_cycle_trades(lookback_days=7, symbol_filter="TQQQ")
		cycle = engine._cycle_db().get(id="c1")
		trades = engine._trade_db().rows(symbol="TQQQ", action=engine_module.ACTION_BUY)

		self.assertEqual(result["status"], "partial_pending")
		self.assertFalse(result["verified"])
		self.assertEqual(result["reconciled_count"], 0)
		self.assertEqual(result["balance_aligned_count"], 1)
		self.assertEqual(result["holding_mismatch_count"], 0)
		self.assertEqual(cycle["total_qty"], 33)
		self.assertEqual(trades, [])
		self.assertEqual(result["unresolved"][0]["reason"], "broker_history_missing_buy_fill")

	def test_external_cycle_sync_ignores_stale_reconcile_rows_and_does_not_create_new_fake_trade(self):
		base_cycle = {
			"id": "c1",
			"symbol": "TQQQ",
			"status": "ACTIVE",
			"current_round": 10,
			"division_count": 20,
			"target_profit": 15,
			"total_investment": 10000,
			"total_spent": 1716.0,
			"total_qty": 22,
			"avg_price": 78.0,
			"remaining_investment": 8284.0,
			"total_commission": 1.0,
		}
		engine, _kis_api, _logs = self._engine(
			buying_power_info={},
			order_history=[],
			holdings=[{"symbol": "TQQQ", "qty": 41, "avg_price": 78.5, "current_price": 80.0}],
			watchlist_rows=[{"id": "w1", "symbol": "TQQQ", "exchange": "NASD", "is_active": True}],
			cycle_rows=[base_cycle],
		)
		engine._trade_db().insert({
			"id": "old-reconcile",
			"cycle_id": "old-cycle",
			"symbol": "TQQQ",
			"round": 1,
			"trade_date": "2026-05-28",
			"action": engine_module.ACTION_BUY,
			"order_type": "RECON",
			"order_price": 78.0,
			"order_qty": 19,
			"filled_price": 78.0,
			"filled_qty": 19,
			"filled_amount": 1482.0,
			"commission": 0.0,
			"status": engine_module.ORDER_FILLED,
			"broker_order_no": "RECONCILE-TQQQ-20260528-41",
			"source": "BROKER",
			"memo": "stale reconcile row from a previous cycle",
			"created": datetime.datetime(2026, 5, 28, 17, 40, 0),
		})
		engine._now = lambda: datetime.datetime(2026, 5, 28, 17, 38, 0)

		result = engine.sync_external_cycle_trades(lookback_days=7, symbol_filter="TQQQ")
		cycle = engine._cycle_db().get(id="c1")
		trades = engine._trade_db().rows(cycle_id="c1", action=engine_module.ACTION_BUY)

		self.assertEqual(result["status"], "partial_pending")
		self.assertFalse(result["verified"])
		self.assertEqual(result["reconciled_count"], 0)
		self.assertEqual(result["balance_aligned_count"], 1)
		self.assertEqual(cycle["total_qty"], 41)
		self.assertEqual(trades, [])
		self.assertEqual(result["unresolved"][0]["reason"], "broker_history_missing_buy_fill")

	def test_external_cycle_sync_does_not_verify_unmatched_sell_fill(self):
		engine, _kis_api, _logs = self._engine(
			buying_power_info={},
			order_history=[
				{
					"symbol": "SOXL",
					"status": "FILLED",
					"action": "SELL",
					"filled_qty": 3,
					"filled_price": 250.0,
					"order_date": "20260622",
					"order_time": "230100",
					"order_no": "EXT-SELL-1",
					"broker": "KIS",
				}
			],
			watchlist_rows=[
				{
					"id": "w1",
					"symbol": "SOXL",
					"exchange": "NASD",
					"is_active": True,
					"total_investment": 15000,
					"division_count": 20,
					"target_profit": 10,
				},
			],
			cycle_rows=[],
		)

		result = engine.sync_external_cycle_trades(lookback_days=7, symbol_filter="SOXL")

		self.assertEqual(result["status"], "partial_pending")
		self.assertFalse(result["verified"])
		self.assertEqual(result["synced_count"], 0)
		self.assertEqual(result["unresolved_count"], 1)
		self.assertEqual(result["unresolved"][0]["reason"], "active_cycle_missing")


if __name__ == "__main__":
	unittest.main()
