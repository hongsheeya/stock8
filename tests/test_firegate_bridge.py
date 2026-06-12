import importlib.util
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE_PATH = ROOT / "src" / "portal" / "trading" / "model" / "struct" / "firegate_bridge.py"
spec = importlib.util.spec_from_file_location("firegate_bridge_under_test", BRIDGE_PATH)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class FireGateBridgeTests(unittest.TestCase):
    def test_model_export_exposes_bridge_api(self):
        self.assertIs(bridge.Model.FireGateBridge, bridge.FireGateBridge)
        self.assertIs(bridge.Model.FireGateAuthError, bridge.FireGateAuthError)
        self.assertIs(bridge.Model.refresh_id_token, bridge.refresh_id_token)
        self.assertIs(bridge.Model.sync_cycle_trade, bridge.sync_cycle_trade)
        self.assertIs(bridge.Model.sync_portfolios_to_local, bridge.sync_portfolios_to_local)
        self.assertIs(bridge.Model.sync_local_to_firegate, bridge.sync_local_to_firegate)
        self.assertIs(bridge.Model.sync_portfolios_bidirectional, bridge.sync_portfolios_bidirectional)
        self.assertEqual(bridge.Model.INFINITYSTOCK_SOURCE, bridge.INFINITYSTOCK_SOURCE)

    def test_firestore_document_round_trip_preserves_firegate_fields(self):
        source = {
            "ticker": "TQQQ",
            "seed": 10000.0,
            "divisionDate": 20,
            "isRunning": True,
            "tValue": 5.5,
        }
        encoded = bridge.firestore_document(source)
        decoded = bridge.decode_firestore_document({"fields": encoded["fields"], "name": "users/a/portfolios/123"})

        self.assertEqual(decoded["ticker"], "TQQQ")
        self.assertEqual(decoded["seed"], 10000.0)
        self.assertEqual(decoded["divisionDate"], 20)
        self.assertEqual(decoded["isRunning"], True)
        self.assertEqual(decoded["tValue"], 5.5)
        self.assertEqual(decoded["id"], "123")

    def test_build_v4_portfolio_maps_local_cycle_state_to_firegate_shape(self):
        portfolio = bridge.build_v4_portfolio(
            "soxl",
            15000,
            division_count=20,
            target_profit=20,
            cycle={
                "current_round": 3,
                "t_value": 3.5,
                "total_qty": 4,
                "avg_price": 71.234,
                "total_spent": 284.94,
                "status": "ACTIVE",
            },
        )

        self.assertEqual(portfolio["ticker"], "SOXL")
        self.assertEqual(portfolio["version"], "v4")
        self.assertEqual(portfolio["currency"], "USD")
        self.assertEqual(portfolio["divisionDate"], 20)
        self.assertEqual(portfolio["targetProfit"], 20)
        self.assertEqual(portfolio["holdingQty"], 4)
        self.assertEqual(portfolio["avgPrice"], 71.23)
        self.assertEqual(portfolio["tValue"], 3.5)

    def test_build_v4_portfolio_includes_infinitystock_metadata(self):
        portfolio = bridge.build_v4_portfolio(
            "SOXL",
            10000,
            nickname=bridge.infinitystock_portfolio_nickname("SOXL", {"cycle_number": 1}),
            source=bridge.INFINITYSTOCK_SOURCE,
            source_cycle_id="cycle-1",
            portfolio_group=bridge.INFINITYSTOCK_PORTFOLIO_GROUP,
            portfolio_category=bridge.INFINITYSTOCK_PORTFOLIO_CATEGORY,
        )

        self.assertEqual(portfolio["nickname"], "InfinityStock Auto | SOXL | Cycle 1")
        self.assertEqual(portfolio["source"], "infinitystock")
        self.assertEqual(portfolio["sourceCycleId"], "cycle-1")
        self.assertEqual(portfolio["portfolioGroup"], "InfinityStock Auto")
        self.assertEqual(portfolio["category"], "infinite_buy")

    def test_ensure_v4_portfolio_keeps_managed_cycle_separate_from_manual_ticker(self):
        class _MemoryBridge(bridge.FireGateBridge):
            def __init__(self):
                self.portfolios = [{
                    "id": "manual-1",
                    "ticker": "SOXL",
                    "nickname": "Manual SOXL",
                    "isRunning": True,
                    "seed": 5000,
                }]

            def list_portfolios(self):
                return [dict(row) for row in self.portfolios]

            def create_portfolio(self, portfolio, doc_id=None):
                payload = dict(portfolio)
                payload["id"] = doc_id or f"managed-{len(self.portfolios)}"
                self.portfolios.append(payload)
                return dict(payload)

            def update_portfolio(self, portfolio_id, changes):
                for row in self.portfolios:
                    if str(row.get("id")) == str(portfolio_id):
                        row.update(dict(changes))
                        return dict(changes)
                raise AssertionError(f"missing portfolio id={portfolio_id}")

        remote = _MemoryBridge()
        cycle = {"id": "cycle-1", "symbol": "SOXL", "cycle_number": 1}
        managed, created = remote.ensure_v4_portfolio(
            "SOXL",
            10000,
            division_count=20,
            target_profit=20,
            nickname=bridge.infinitystock_portfolio_nickname("SOXL", cycle),
            cycle=cycle,
            source=bridge.INFINITYSTOCK_SOURCE,
            source_cycle_id=bridge.infinitystock_source_cycle_id(cycle, "SOXL"),
            portfolio_group=bridge.INFINITYSTOCK_PORTFOLIO_GROUP,
            portfolio_category=bridge.INFINITYSTOCK_PORTFOLIO_CATEGORY,
        )
        self.assertTrue(created)
        self.assertNotEqual(managed["id"], "manual-1")
        self.assertEqual(remote.find_portfolio("SOXL")["id"], "manual-1")
        self.assertEqual(
            remote.find_portfolio(
                "SOXL",
                include_stopped=True,
                source=bridge.INFINITYSTOCK_SOURCE,
                source_cycle_id="cycle-1",
            )["id"],
            managed["id"],
        )

        updated, created_again = remote.ensure_v4_portfolio(
            "SOXL",
            12000,
            division_count=30,
            target_profit=18,
            nickname=bridge.infinitystock_portfolio_nickname("SOXL", cycle),
            cycle=cycle,
            source=bridge.INFINITYSTOCK_SOURCE,
            source_cycle_id="cycle-1",
            portfolio_group=bridge.INFINITYSTOCK_PORTFOLIO_GROUP,
            portfolio_category=bridge.INFINITYSTOCK_PORTFOLIO_CATEGORY,
        )
        self.assertFalse(created_again)
        self.assertEqual(updated["id"], managed["id"])
        self.assertEqual(remote.find_portfolio("SOXL")["seed"], 5000)
        self.assertEqual(updated["seed"], 12000)

    def test_apply_v4_buy_transaction_updates_t_value_and_average(self):
        portfolio = bridge.build_v4_portfolio("TQQQ", 10000, division_count=20, target_profit=15)
        updated = bridge.apply_v4_transaction(portfolio, {
            "type": "buy",
            "ticker": "TQQQ",
            "date": "2026. 05. 27",
            "price": 100,
            "size": 5,
            "commission": 0,
        })

        self.assertEqual(updated["holdingQty"], 5)
        self.assertEqual(updated["avgPrice"], 100)
        self.assertEqual(updated["totalBuy"], 500)
        self.assertEqual(updated["tValue"], 1.0)

    def test_crash_buy_transaction_keeps_t_value_zero(self):
        portfolio = bridge.build_v4_portfolio("SOXL", 15000, division_count=20, target_profit=20)
        updated = bridge.apply_v4_transaction(portfolio, {
            "type": "buy",
            "ticker": "SOXL",
            "date": "2026. 05. 27",
            "price": 83.33,
            "size": 1,
            "commission": 0,
            "tDelta": 0,
        })

        self.assertEqual(updated["holdingQty"], 1)
        self.assertEqual(updated["tValue"], 0)

    def test_firestore_requests_include_api_key_header_and_query(self):
        captured = {}

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"documents": []}).encode("utf-8")

        original_urlopen = bridge.urllib.request.urlopen

        def _fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            captured["timeout"] = timeout
            return _Response()

        bridge.urllib.request.urlopen = _fake_urlopen
        try:
            rows = bridge.FireGateBridge("user@example.com", "token-123").list_portfolios()
        finally:
            bridge.urllib.request.urlopen = original_urlopen

        self.assertEqual(rows, [])
        self.assertIn(f"key={bridge.FIRE_GATE_API_KEY}", captured["url"])
        self.assertEqual(captured["headers"].get("X-goog-api-key"), bridge.FIRE_GATE_API_KEY)
        self.assertEqual(captured["headers"].get("Authorization"), "Bearer token-123")

    def test_sync_portfolios_to_local_updates_watchlist_and_paused_cycle(self):
        class _FakeDb:
            def __init__(self, rows=None):
                self.rows_data = [dict(row) for row in (rows or [])]

            def get(self, **kwargs):
                for row in self.rows_data:
                    matched = True
                    for key, value in kwargs.items():
                        if row.get(key) != value:
                            matched = False
                            break
                    if matched:
                        return row
                return None

            def rows(self, **kwargs):
                data = [dict(row) for row in self.rows_data]
                symbol = kwargs.get("symbol")
                if symbol is not None:
                    data = [row for row in data if row.get("symbol") == symbol]
                orderby = kwargs.get("orderby")
                order = str(kwargs.get("order", "ASC") or "ASC").upper()
                if orderby:
                    data.sort(key=lambda row: row.get(orderby), reverse=(order == "DESC"))
                dump = kwargs.get("dump")
                if dump:
                    data = data[:int(dump)]
                return data

            def update(self, data, id=None):
                for row in self.rows_data:
                    if row.get("id") == id:
                        row.update(dict(data))
                        return
                raise AssertionError(f"missing row id={id}")

            def insert(self, data):
                payload = dict(data)
                payload.setdefault("id", str(len(self.rows_data) + 1))
                self.rows_data.append(payload)
                return payload

        class _FakeStruct:
            def __init__(self):
                self.dbs = {
                    "etf_watchlist": _FakeDb([{
                        "id": "wl-1",
                        "symbol": "TQQQ",
                        "name": "Old TQQQ",
                        "total_investment": 10000.0,
                        "division_count": 20,
                        "target_profit": 10.0,
                    }]),
                    "trading_cycle": _FakeDb([{
                        "id": "cy-1",
                        "symbol": "TQQQ",
                        "status": "ACTIVE",
                        "cycle_number": 3,
                        "current_round": 1,
                        "total_investment": 10000.0,
                        "created": 1,
                    }]),
                }

            def db(self, name):
                return self.dbs[name]

        class _FakeRemoteBridge:
            def list_portfolios(self):
                return [{
                    "id": "fg-1",
                    "ticker": "TQQQ",
                    "nickname": "TQQQ Core",
                    "source": "infinitystock",
                    "sourceCycleId": "cy-1",
                    "portfolioGroup": "InfinityStock Auto",
                    "category": "infinite_buy",
                    "seed": 15000,
                    "divisionDate": 30,
                    "targetProfit": 14,
                    "isRunning": False,
                    "holdingQty": 0,
                    "avgPrice": 0,
                    "totalBuy": 1200,
                    "totalSell": 0,
                    "tValue": 2.4,
                    "startDate": "2026-05-01",
                }]

        original = bridge._bridge_call_from_config
        bridge._bridge_call_from_config = lambda struct, fn: fn(_FakeRemoteBridge(), {"enabled": True})
        try:
            fake = _FakeStruct()
            result = bridge.sync_portfolios_to_local(fake)
        finally:
            bridge._bridge_call_from_config = original

        self.assertTrue(result["executed"])
        self.assertEqual(result["watchlist_updated"], 1)
        self.assertEqual(result["cycles_updated"], 1)
        watchlist = fake.db("etf_watchlist").get(symbol="TQQQ")
        cycle = fake.db("trading_cycle").get(id="cy-1")
        self.assertEqual(watchlist["total_investment"], 15000.0)
        self.assertEqual(watchlist["division_count"], 30)
        self.assertEqual(cycle["status"], "PAUSED")
        self.assertEqual(cycle["total_investment"], 15000.0)
        self.assertEqual(cycle["current_round"], 2)

    def test_sync_portfolios_to_local_ignores_manual_firegate_portfolios(self):
        class _FakeDb:
            def __init__(self, rows=None):
                self.rows_data = [dict(row) for row in (rows or [])]

            def get(self, **kwargs):
                for row in self.rows_data:
                    if all(row.get(key) == value for key, value in kwargs.items()):
                        return row
                return None

            def rows(self, **kwargs):
                return [dict(row) for row in self.rows_data]

            def update(self, data, id=None):
                raise AssertionError("manual FireGate portfolio must not update local rows")

            def insert(self, data):
                raise AssertionError("manual FireGate portfolio must not create local rows")

            def delete(self, id=None, **kwargs):
                raise AssertionError("manual FireGate portfolio must not delete local rows")

        class _FakeStruct:
            def __init__(self):
                self.dbs = {
                    "etf_watchlist": _FakeDb([{
                        "id": "wl-1",
                        "symbol": "TQQQ",
                        "name": "Local TQQQ",
                        "total_investment": 10000.0,
                    }]),
                    "trading_cycle": _FakeDb([{
                        "id": "cy-1",
                        "symbol": "TQQQ",
                        "status": "ACTIVE",
                        "total_investment": 10000.0,
                    }]),
                }

            def db(self, name):
                return self.dbs[name]

        class _FakeRemoteBridge:
            def list_portfolios(self):
                return [{
                    "id": "manual-1",
                    "ticker": "TQQQ",
                    "nickname": "Manual TQQQ",
                    "seed": 999999,
                    "divisionDate": 1,
                    "targetProfit": 1,
                    "isRunning": True,
                }]

        original = bridge._bridge_call_from_config
        bridge._bridge_call_from_config = lambda struct, fn: fn(_FakeRemoteBridge(), {"enabled": True})
        try:
            fake = _FakeStruct()
            result = bridge.sync_portfolios_to_local(fake)
        finally:
            bridge._bridge_call_from_config = original

        self.assertTrue(result["executed"])
        self.assertEqual(result["firegate_portfolios"], 0)
        self.assertEqual(result["watchlist_updated"], 0)
        self.assertEqual(result["cycles_updated"], 0)

    def test_sync_portfolios_to_local_removes_missing_firegate_symbol_locally(self):
        class _FakeDb:
            def __init__(self, rows=None):
                self.rows_data = [dict(row) for row in (rows or [])]

            def get(self, **kwargs):
                for row in self.rows_data:
                    matched = True
                    for key, value in kwargs.items():
                        if row.get(key) != value:
                            matched = False
                            break
                    if matched:
                        return row
                return None

            def rows(self, **kwargs):
                data = [dict(row) for row in self.rows_data]
                symbol = kwargs.get("symbol")
                if symbol is not None:
                    data = [row for row in data if row.get("symbol") == symbol]
                dump = kwargs.get("dump")
                if dump:
                    data = data[:int(dump)]
                return data

            def update(self, data, id=None):
                for row in self.rows_data:
                    if row.get("id") == id:
                        row.update(dict(data))
                        return
                raise AssertionError(f"missing row id={id}")

            def insert(self, data):
                payload = dict(data)
                payload.setdefault("id", str(len(self.rows_data) + 1))
                self.rows_data.append(payload)
                return payload

            def delete(self, id=None, **kwargs):
                self.rows_data = [row for row in self.rows_data if row.get("id") != id]

        class _FakeStruct:
            def __init__(self):
                self.dbs = {
                    "etf_watchlist": _FakeDb([{
                        "id": "wl-1",
                        "symbol": "FGT0528",
                        "memo": "FireGate portfolio 123",
                    }]),
                    "trading_cycle": _FakeDb([{
                        "id": "cy-1",
                        "symbol": "FGT0528",
                        "status": "ACTIVE",
                    }]),
                }

            def db(self, name):
                return self.dbs[name]

        class _FakeRemoteBridge:
            def list_portfolios(self):
                return []

        original = bridge._bridge_call_from_config
        bridge._bridge_call_from_config = lambda struct, fn: fn(_FakeRemoteBridge(), {"enabled": True})
        try:
            fake = _FakeStruct()
            result = bridge.sync_portfolios_to_local(fake, symbol_filter="FGT0528")
        finally:
            bridge._bridge_call_from_config = original

        self.assertTrue(result["executed"])
        self.assertEqual(result["removed_watchlists"], 1)
        self.assertEqual(result["archived_cycles"], 1)
        self.assertEqual(result["removed_symbols"], ["FGT0528"])
        self.assertIsNone(fake.db("etf_watchlist").get(symbol="FGT0528"))
        self.assertEqual(fake.db("trading_cycle").get(id="cy-1")["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
