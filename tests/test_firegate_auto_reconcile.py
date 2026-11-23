"""FireGate auto reconcile (11-23). LIVE SOXL on 11-21..23: the running
FireGate portfolio 1780022179464 held 112 shares and was linked to a cycle ID
from a rebuilt DB; the broker held 165 @ 84.82. Stock8 books the missing
fills itself, closes a difference no fill explains with one adjustment entry,
and relinks the portfolio, but only when the replay ends at the broker
quantity. It never sends an order."""
import copy
import datetime
import importlib.util
import json
import pathlib
import unittest

import test_infinitebuy_loc_schedule_regressions as base

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "firegate_bridge_auto_reconcile", ROOT / "src/portal/trading/model/struct/firegate_bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

CONFIGURED = json.dumps({"enabled": True, "email": "user@example.test"})
OLD_LINK = "tsevwkrrjetkjjunnsamosnumiuskebe"
CYCLE_1 = "yudyhnjbvimrmwjinurxthdfoxrwrspu"
CYCLE_2 = "dvijhiqxrdslimffqukbunqzisxccpde"
NOW = datetime.datetime(2026, 11, 23, 6, 30)  # KST Monday, Sunday 16:30 ET

PORTFOLIO = {"id": 1780022179464, "ticker": "SOXL", "source": "infinitystock", "sourceCycleId": OLD_LINK,
             "portfolioGroup": "InfinityStock Auto", "category": "infinite_buy", "version": "v4",
             "nickname": "InfinityStock Auto | SOXL | Cycle 1", "seed": 15000, "divisionDate": 20,
             "targetProfit": 20, "isRunning": True, "holdingQty": 112, "avgPrice": 117.61,
             "totalBuy": 13166.36, "totalSell": 0, "tValue": 19.62, "reverseMode": True,
             "reverseState": "ENTERED", "reverseModeStarPrice": 0, "startDate": "2026-06-26",
             "endDate": "2026. 10. 27", "updatedAt": "2026-11-09 03:58:48"}
FIREGATE_TXS = [
    {"id": "old-1", "portfolioId": 1780022179464, "type": "buy", "date": "2026. 10. 20", "price": 98.65,
     "size": 8, "source": "infinitystock", "sourceTradeId": "old-1"},
    {"id": "old-2", "portfolioId": 1780022179464, "type": "sell", "date": "2026. 10. 27", "price": 101.08,
     "size": 10, "source": "infinitystock", "sourceTradeId": "old-2"},
]
# cycle_trade rows in the LIVE DB on 11-23 (cycle #1 and #2)
LOCAL = [
    ("ffjalykpfh", CYCLE_1, "2026-11-11", "SELL", 66.03, 20, 3.3, "0030616750", "2026-11-11 23:23:28"),
    ("skbeatbaih", CYCLE_1, "2026-11-12", "SELL", 65.53, 11, 1.8, "0030947397", "2026-11-12 00:24:25"),
    ("uwmlbiovua", CYCLE_1, "2026-11-16", "BUY", 48.76, 20, 2.44, "0030196371", "2026-11-16 03:16:25"),
    ("zpjdeudznl", CYCLE_2, "2026-11-17", "BUY", 49.07, 20, 2.45, "0030392685", "2026-11-17 01:50:31"),
    ("wjjyyevuje", CYCLE_2, "2026-11-20", "BUY", 35.88, 3, 0.27, "0031121938", "2026-11-20 01:21:00"),
    ("pqfqcfkfpc", CYCLE_2, "2026-11-20", "BUY", 33.02, 8, 0.66, "0031155056", "2026-11-20 03:16:45"),
]
LOCAL_ROWS = [{"id": rid, "cycle_id": cid, "symbol": "SOXL", "trade_date": day, "action": action,
               "order_type": "EXTERNAL", "filled_price": price, "filled_qty": qty, "commission": fee,
               "status": "FILLED", "broker_order_no": order_no, "source": "KIS",
               "strategy_type": "NORMAL" if action == "BUY" else "PARTIAL_SELL", "created": created}
              for rid, cid, day, action, price, qty, fee, order_no, created in LOCAL]
LOCAL_IDS = [row["id"] for row in LOCAL_ROWS]
# a fill from before the rebuilt DB that FireGate never got (the 33-share gap)
GAP_FILL = {"order_no": "0029000001", "symbol": "SOXL", "action": "BUY", "side": "BUY", "order_date": "20261103",
            "order_time": "053000", "filled_qty": 33, "filled_price": 70.0, "order_qty": 33, "status": "FILLED"}
CANCELLED_MOC = {"order_no": "0030757070", "symbol": "SOXL", "action": "SELL", "side": "SELL", "order_date": "20261119",
                 "order_time": "233533", "filled_qty": 0, "filled_price": 0, "order_qty": 11, "status": "CANCELLED"}
ADJUST_ID = "ADJUST-SOXL-20261123-33"


def broker_history(extra=()):
    rows = [{"order_no": order_no, "symbol": "SOXL", "action": action, "side": action,
             "order_date": day.replace("-", ""), "order_time": "050000", "filled_qty": qty, "filled_price": price,
             "order_qty": qty, "status": "FILLED"} for _rid, _cid, day, action, price, qty, _fee, order_no, _c in LOCAL]
    return rows + [CANCELLED_MOC] + list(extra)


class _Remote(bridge.FireGateBridge):
    def __init__(self, portfolios, transactions):
        self.portfolios = [copy.deepcopy(p) for p in portfolios]
        self.transactions = [copy.deepcopy(t) for t in transactions]
        self.creates = 0
        self.patches = 0
        self.reads = 0
        self.fail_create_at = None      # raise before storing
        self.land_then_fail_at = None   # store, then time out
        self.fail_patch_at = None       # n-th portfolio update fails
        self.on_list = None

    def list_portfolios(self):
        self.reads += 1
        return copy.deepcopy(self.portfolios)

    def get_portfolio(self, portfolio_id):
        self.reads += 1
        for row in self.portfolios:
            if str(row.get("id")) == str(portfolio_id):
                return copy.deepcopy(row)
        return None

    def list_transactions(self, portfolio_id):
        self.reads += 1
        if self.on_list:
            self.on_list(self)
        return [copy.deepcopy(t) for t in self.transactions if str(t.get("portfolioId")) == str(portfolio_id)]

    def create_transaction(self, tx, doc_id=None):
        self.creates += 1
        if self.fail_create_at == self.creates:
            raise bridge.FireGateBridgeError("FireGate request failed: 503")
        if doc_id and any(str(t.get("id")) == str(doc_id) for t in self.transactions):
            raise bridge.FireGateBridgeError("FireGate request failed: 409 ALREADY_EXISTS")
        row = {**copy.deepcopy(tx), "id": doc_id or f"tx-{len(self.transactions)}"}
        self.transactions.append(row)
        if self.land_then_fail_at == self.creates:
            raise TimeoutError("The read operation timed out")
        return copy.deepcopy(row)

    def update_portfolio(self, portfolio_id, changes):
        self.patches += 1
        if self.fail_patch_at == self.patches:
            raise bridge.FireGateBridgeError("FireGate request failed: 500")
        for row in self.portfolios:
            if str(row.get("id")) == str(portfolio_id):
                row.update(copy.deepcopy(changes))
                return copy.deepcopy(row)
        raise AssertionError("missing portfolio")

    def recent_prices(self, ticker, count=5):
        return [35.0] * count


class _FG:
    """The bridge model as the engine sees it, wired to the in-memory remote."""

    def __init__(self, remote):
        self.remote = remote
        self.pulls = []

    def __getattr__(self, name):
        return getattr(bridge.Model, name)

    def bridge_call(self, _struct, fn):
        return fn(self.remote, {"enabled": True})

    def sync_firegate_authoritative(self, _struct, symbol_filter=""):
        self.pulls.append(symbol_filter)
        return {}


class _Kis(base._KisApiStub):
    def __init__(self, held=165, avg=84.8162, price=33.37, history=None, history_error=None, balance_error=None):
        super().__init__({})
        self.held, self.avg, self.price = held, avg, price
        self.history, self.history_error, self.balance_error = history or [], history_error, balance_error
        self.history_calls = 0
        self.balance_calls = 0
        self.http_requests = 0
        self.during_history = None

    def _request(self, method, path, tr_id="", params=None, **_kw):
        self.http_requests += 1
        return {"rt_cd": "0"}

    def get_balance(self, exchange=None):
        self.balance_calls += 1
        if self.balance_error:
            raise self.balance_error
        return {"holdings": [{"symbol": "SOXL", "qty": self.held, "avg_price": self.avg, "current_price": self.price}]}

    def get_overseas_order_history(self, start_date=None, end_date=None, symbol="", exchanges=None, strict=False):
        self.history_calls += 1
        if not strict:
            raise AssertionError("reconcile must read the history strictly")
        if self.history_error:
            raise self.history_error
        if self.during_history:
            self.during_history()
        for _exchange in exchanges or ["NASD", "NYSE", "AMEX"]:
            self._request("GET", "/uapi/overseas-stock/v1/trading/inquire-ccnl")  # one HTTP request each
        return [dict(row) for row in self.history if start_date <= row["order_date"] <= end_date
                and (not symbol or row["symbol"] == symbol)]


def make(portfolios=None, transactions=None, history=None, cycles=None, configs=None, bridge_cfg=None,
         local_rows=None, **kis_kw):
    cycles = cycles if cycles is not None else [
        {"id": CYCLE_1, "symbol": "SOXL", "status": "COMPLETED", "cycle_number": 1, "total_qty": 0},
        {"id": CYCLE_2, "symbol": "SOXL", "status": "ACTIVE", "cycle_number": 2, "total_qty": 165,
         "avg_price": 84.8162, "current_round": 19, "t_value": 19.62, "division_count": 20,
         "total_investment": 15000.0}]
    engine, _stub, logs = base.InfiniteBuyLocScheduleRegressionTests._engine(
        None, buying_power_info={}, cycle_rows=cycles,
        configs={"fire_gate_bridge": bridge_cfg or CONFIGURED, "firegate_auto_reconcile_kis_interval_sec": "0",
                 **(configs or {})})
    kis = _Kis(history=history if history is not None else broker_history([GAP_FILL]), **kis_kw)
    engine._load_kis_api = lambda: kis
    engine._paper_trading_mode = lambda: False
    engine._now = lambda: NOW
    struct = engine.struct
    struct._db["cycle_trade"] = base._FakeDB(LOCAL_ROWS if local_rows is None else local_rows)
    struct.set_config = lambda key, value, description="": struct.configs.__setitem__(key, value)
    notes = []
    struct._firegate_reconcile_notify = notes.append
    remote = _Remote(portfolios if portfolios is not None else [PORTFOLIO],
                     transactions if transactions is not None else FIREGATE_TXS)
    fg = _FG(remote)
    engine._firegate_bridge_model = lambda: fg
    return engine, remote, kis, logs, notes, fg


def run(engine, now=NOW, sync=True):
    result = engine.run_firegate_auto_reconcile(sync_result=verified_sync() if sync else None, now=now)
    engine.struct.configs.pop("firegate_auto_reconcile:last_run", None)  # the next call is a later run
    return result


def verified_sync():
    return {"status": "partial_pending", "error_count": 0, "history_verification": {"verified": True}}


def retry_later(engine):
    state = json.loads(engine.struct.configs.get("firegate_auto_reconcile:SOXL", "{}") or "{}")
    state.update(failed_at=0)
    engine.struct.configs["firegate_auto_reconcile:SOXL"] = json.dumps(state)


def added(remote):
    return [t for t in remote.transactions if t["id"] not in ("old-1", "old-2")]


def symbol_status(result):
    return result["results"][0]["status"]


class AutoReconcileTests(unittest.TestCase):
    def test_missing_fills_and_a_broker_buy_close_the_gap_then_relink(self):
        engine, remote, kis, logs, notes, fg = make()
        result = run(engine)
        portfolio = remote.portfolios[0]
        self.assertEqual(symbol_status(result), "reconciled")
        self.assertEqual((portfolio["holdingQty"], portfolio["sourceCycleId"]), (165, CYCLE_2))
        self.assertEqual([t["id"] for t in added(remote)], ["KIS-0029000001"] + LOCAL_IDS)
        self.assertEqual(added(remote)[1]["brokerOrderNo"], "0030616750")
        self.assertEqual(fg.pulls, ["SOXL"])
        self.assertEqual([log["event_type"] for log in logs], ["FIREGATE_AUTO_RECONCILED"])
        self.assertEqual(len(notes), 1)
        for text in ("165주 일치", "전 112주 @ 117.61", "리버스", "잔여 시드", "다음 세션 예상"):
            self.assertIn(text, notes[0])
        self.assertEqual(kis.buy_calls + kis.sell_calls + kis.sell_reservation_calls, [])
        self.assertEqual(engine.struct.configs.get("firegate_auto_reconcile_job:SOXL"), "")

    def test_an_unexplained_gap_becomes_one_adjustment_at_the_broker_cost(self):
        engine, remote, _kis, _logs, notes, _fg = make(history=broker_history())
        self.assertEqual(symbol_status(run(engine)), "reconciled")
        txs = added(remote)
        self.assertEqual([t["id"] for t in txs], LOCAL_IDS + [ADJUST_ID])
        adjust = txs[-1]
        self.assertEqual((adjust["type"], adjust["size"], adjust["price"]), ("buy", 33, 64.68))
        self.assertEqual(adjust["memo"], "브로커 잔고 기준 자동 조정(원인 미확인 차이)")
        self.assertEqual((adjust["source"], adjust["tDelta"]), ("infinitystock", 0))
        portfolio = remote.portfolios[0]
        self.assertEqual(portfolio["holdingQty"], 165)
        self.assertAlmostEqual(portfolio["avgPrice"] * 165, 165 * 84.8162, delta=2.0)
        self.assertEqual(portfolio["tValue"], 18.7)  # the adjustment is not a round
        self.assertIn("조정 매수 33주 @ 64.68", notes[0])

    def test_adjustment_limits_write_nothing(self):
        cases = {
            "no broker average": (dict(avg=0), "adjust_no_price"),
            "more than half the holding": (dict(held=300, avg=84.8162), "adjust_too_large"),
            "price far from the market": (dict(price=10.0), "adjust_price_out_of_range"),
        }
        for name, (kis_kw, code) in cases.items():
            with self.subTest(name):
                engine, remote, _kis, logs, notes, _fg = make(history=broker_history(), **kis_kw)
                self.assertEqual(symbol_status(run(engine)), f"plan_{code}")
                self.assertEqual((added(remote), remote.patches), ([], 0))
                self.assertEqual(logs[-1]["event_type"], "FIREGATE_AUTO_RECONCILE_FAILED")
                self.assertEqual(len(notes), 1)

    def test_an_unbooked_broker_sell_goes_to_the_adjustment(self):
        sell = {**GAP_FILL, "order_no": "0029000002", "action": "SELL", "side": "SELL", "order_date": "20261104",
                "filled_qty": 5, "filled_price": 71.0}
        engine, remote, _kis, _logs, _notes, _fg = make(history=broker_history([GAP_FILL, sell]))
        self.assertEqual(symbol_status(run(engine)), "reconciled")
        ids = [t["id"] for t in added(remote)]
        self.assertNotIn("KIS-0029000001", ids)
        self.assertNotIn("KIS-0029000002", ids)
        self.assertEqual(ids[-1], ADJUST_ID)

    def test_rerun_sends_nothing_twice(self):
        engine, remote, _kis, _logs, _notes, _fg = make()
        run(engine)
        count = len(remote.transactions)
        self.assertEqual(symbol_status(run(engine)), "in_sync")
        self.assertEqual(len(remote.transactions), count)

    def resumed(self, **failure):
        engine, remote, _kis, logs, notes, _fg = make(history=broker_history())
        for key, value in failure.items():
            setattr(remote, key, value)
        self.assertEqual(symbol_status(run(engine)), "write_failed")
        self.assertEqual(remote.portfolios[0]["sourceCycleId"], OLD_LINK)
        self.assertTrue(engine.struct.configs.get("firegate_auto_reconcile_job:SOXL"))
        for key in failure:
            setattr(remote, key, None)
        self.assertEqual(symbol_status(run(engine)), "reconciled")
        ids = [t["id"] for t in remote.transactions]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([t["id"] for t in added(remote)], LOCAL_IDS + [ADJUST_ID])
        self.assertEqual(remote.portfolios[0]["holdingQty"], 165)
        return engine, remote

    def test_created_but_not_applied_is_finished(self):
        self.resumed(fail_patch_at=4)  # 4th transaction landed, its portfolio update did not

    def test_a_create_that_timed_out_after_landing_is_finished(self):
        self.resumed(land_then_fail_at=3)

    def test_a_create_that_never_landed_is_retried(self):
        self.resumed(fail_create_at=2)

    def test_an_unrecognised_partial_state_stops_for_good(self):
        engine, remote, _kis, logs, notes, _fg = make(history=broker_history())
        remote.fail_patch_at = 4
        run(engine)
        remote.fail_patch_at = None
        remote.portfolios[0]["holdingQty"] = 7  # edited by hand meanwhile
        self.assertEqual(symbol_status(run(engine)), "partial_stuck")
        self.assertIn("부분 반영, 확인 필요", notes[-1])
        writes = (remote.creates, remote.patches)
        self.assertEqual(symbol_status(run(engine)), "stuck")
        self.assertEqual((remote.creates, remote.patches), writes)

    def test_a_change_between_plan_and_write_stops_the_run(self):
        engine, remote, _kis, _logs, _notes, _fg = make(history=broker_history())
        calls = []

        def sneak_in(r):
            calls.append(1)
            if len(calls) == 2:  # the fresh read right before writing
                r.transactions.append({"id": "manual", "portfolioId": 1780022179464, "type": "buy",
                                       "date": "2026. 11. 22", "price": 33.0, "size": 1})
        remote.on_list = sneak_in
        self.assertEqual(symbol_status(run(engine)), "plan_changed")
        self.assertEqual((remote.creates, remote.patches), (0, 0))
        self.assertFalse(engine.struct.configs.get("firegate_auto_reconcile_job:SOXL"))

    def test_content_matched_local_fills_are_marked_reconciled(self):
        manual = FIREGATE_TXS + [{"id": "manual-sell", "portfolioId": 1780022179464, "type": "sell",
                                  "date": "2026. 11. 12", "price": 65.53, "size": 11}]
        engine, remote, _kis, _logs, _notes, _fg = make(portfolios=[{**PORTFOLIO, "holdingQty": 101}],
                                                        transactions=manual, history=broker_history())
        self.assertEqual(symbol_status(run(engine)), "reconciled")
        self.assertNotIn("skbeatbaih", [t["id"] for t in added(remote)])
        self.assertIn("skbeatbaih", remote.portfolios[0]["reconciledSourceTradeIds"])

    def test_read_failures_write_nothing(self):
        engine, remote, _kis, logs, _notes, _fg = make(history_error=RuntimeError("주문/체결 연속조회 미완료"))
        run(engine)
        self.assertEqual((added(remote), remote.patches), ([], 0))
        self.assertIn("조회 미완료", logs[0]["message"])
        engine, remote, _kis, _logs, _notes, _fg = make(balance_error=RuntimeError("timeout"))
        self.assertEqual(run(engine)["reason"], "balance_failed")
        self.assertEqual((added(remote), remote.patches), ([], 0))

    def test_kis_history_reads_are_capped_by_http_request(self):
        engine, remote, kis, logs, _notes, _fg = make(configs={"firegate_auto_reconcile_kis_call_cap": "5"})
        run(engine)
        self.assertEqual(kis.http_requests, 5)  # two history calls, the third stops at its 2nd request
        self.assertFalse("_request" in kis.__dict__)  # the counter is removed afterwards
        self.assertEqual((added(remote), remote.patches), ([], 0))
        self.assertIn("조회 미완료", logs[0]["message"])

    def test_off_paper_and_unsafe_moments_do_nothing(self):
        cases = {
            "off": dict(configs={"firegate_auto_reconcile_enabled": "false"}),
            "bridge auto sync off": dict(bridge_cfg=json.dumps({"enabled": True, "email": "u@example.test",
                                                                "auto_sync_enabled": False})),
            "paper": {},
            "pending": dict(configs={"kis_reservation_pending": json.dumps({"symbol": "SOXL"})}),
            "receipts": dict(configs={"kis_reservation_unseen_receipts": json.dumps({"0031": {}})}),
            "no sync result": {},
            "unverified sync": {},
        }
        for name, kw in cases.items():
            with self.subTest(name):
                engine, remote, kis, _logs, _notes, fg = make(**kw)
                if name == "paper":
                    engine._paper_trading_mode = lambda: True
                if name == "unverified sync":
                    engine.run_firegate_auto_reconcile(sync_result={"history_verification": {"verified": False}}, now=NOW)
                else:
                    run(engine, sync=name != "no sync result")
                self.assertEqual((remote.reads, remote.creates, remote.patches, kis.balance_calls, kis.history_calls,
                                  fg.pulls), (0, 0, 0, 0, 0, []))

    def test_only_the_morning_window_runs(self):
        cases = [
            (datetime.datetime(2026, 11, 23, 6, 14), False),
            (datetime.datetime(2026, 11, 23, 6, 15), True),
            (datetime.datetime(2026, 11, 23, 7, 59), True),
            (datetime.datetime(2026, 11, 23, 8, 0), False),
            (datetime.datetime(2026, 11, 23, 23, 35), False),   # the MOC window
            (datetime.datetime(2026, 7, 14, 6, 15), True),      # summer time: ET 17:15, close was 05:00 KST
            (datetime.datetime(2026, 11, 21, 6, 30), True),     # Saturday, after Friday's close
            (datetime.datetime(2026, 11, 22, 7, 0), True),      # Sunday
        ]
        for now, runs in cases:
            with self.subTest(now=now):
                engine, remote, kis, _logs, _notes, _fg = make()
                engine._now = lambda now=now: now
                result = run(engine, now=now)
                self.assertEqual(result.get("reason") != "outside_window", runs)
                if not runs:
                    self.assertEqual((remote.reads, kis.balance_calls), (0, 0))

    def test_throttle_comes_before_any_read(self):
        engine, remote, kis, _logs, _notes, _fg = make()
        engine.run_firegate_auto_reconcile(sync_result=verified_sync(), now=NOW)
        reads = (remote.reads, kis.balance_calls, kis.history_calls)
        again = engine.run_firegate_auto_reconcile(sync_result=verified_sync(), now=NOW)
        self.assertEqual(again["reason"], "throttled")
        self.assertEqual((remote.reads, kis.balance_calls, kis.history_calls), reads)

    def test_failed_plan_is_not_re_read_until_something_changes(self):
        engine, remote, kis, _logs, notes, _fg = make(history=broker_history(), avg=0)
        run(engine)
        calls = kis.history_calls
        self.assertEqual(symbol_status(run(engine)), "unchanged")
        self.assertEqual((kis.history_calls, len(notes)), (calls, 1))
        retry_later(engine)
        run(engine)
        self.assertGreater(kis.history_calls, calls)
        self.assertEqual(len(notes), 1)  # one Discord message a day

    def test_an_open_order_waits(self):
        pending = {**GAP_FILL, "order_no": "0031200000", "order_date": "20261122", "filled_qty": 0, "status": "PENDING"}
        engine, remote, _kis, _logs, _notes, _fg = make(history=broker_history([GAP_FILL, pending]))
        self.assertEqual(run(engine)["results"][0]["reason"], "orders_open")
        self.assertEqual((added(remote), remote.patches), ([], 0))

    def test_ambiguous_targets_do_nothing(self):
        second = {**PORTFOLIO, "id": 1783000000000, "sourceCycleId": ""}
        engine, remote, kis, logs, _notes, _fg = make(portfolios=[PORTFOLIO, second])
        run(engine)
        self.assertEqual((remote.creates, remote.patches, kis.history_calls), (0, 0, 0))
        self.assertIn("포트폴리오 2개", logs[0]["message"])
        cycles = [{"id": CYCLE_1, "symbol": "SOXL", "status": "PAUSED"},
                  {"id": CYCLE_2, "symbol": "SOXL", "status": "ACTIVE"}]
        engine, remote, kis, logs, _notes, _fg = make(cycles=cycles)
        run(engine)
        self.assertEqual((remote.creates, remote.patches, kis.history_calls), (0, 0, 0))
        self.assertIn("로컬 사이클 2개", logs[0]["message"])

    def test_linked_and_equal_is_left_alone(self):
        engine, remote, kis, logs, _notes, _fg = make(portfolios=[{**PORTFOLIO, "sourceCycleId": CYCLE_2,
                                                                  "holdingQty": 165}])
        self.assertEqual(symbol_status(run(engine)), "in_sync")
        self.assertEqual((remote.patches, kis.history_calls, logs), (0, 0, []))

    def test_requests_are_spaced(self):
        from unittest.mock import patch
        engine, _remote, kis, _logs, _notes, _fg = make(configs={"firegate_auto_reconcile_kis_interval_sec": "0.2"})
        sleeps = []
        with patch.object(base.engine_module.time, "sleep", lambda sec: sleeps.append(sec)):
            run(engine)
        self.assertEqual(sleeps.count(0.2), kis.http_requests - 1)

    def test_the_window_end_stops_reading_and_writing(self):
        clock = {"calls": 0}

        def ticking():
            clock["calls"] += 1
            return datetime.datetime(2026, 11, 23, 7, 59) if clock["calls"] < 40 else datetime.datetime(2026, 11, 23, 8, 0)
        engine, remote, kis, logs, _notes, _fg = make()
        engine._now = ticking
        run(engine, now=datetime.datetime(2026, 11, 23, 7, 59))
        self.assertEqual((remote.creates, remote.patches), (0, 0))
        self.assertIn("조회 미완료", logs[-1]["message"])

    def test_writes_start_only_before_the_window_end(self):
        engine, remote, _kis, _logs, _notes, _fg = make()
        late = {"on": False}
        original = engine._verified_external_order_history

        def history_then_late(*args, **kwargs):
            result = original(*args, **kwargs)
            late["on"] = True
            return result
        engine._verified_external_order_history = history_then_late
        engine._now = lambda: datetime.datetime(2026, 11, 23, 8, 0) if late["on"] else datetime.datetime(2026, 11, 23, 7, 59)
        result = run(engine, now=datetime.datetime(2026, 11, 23, 7, 59))
        self.assertEqual(result["results"][0]["reason"], "window_closed")
        self.assertEqual((remote.creates, remote.patches), (0, 0))

    def test_the_symbol_lock_is_free_while_reading_kis(self):
        import threading
        engine, _remote, kis, _logs, _notes, _fg = make()
        seen = []

        def try_lock():
            def other():
                try:
                    with bridge.firegate_symbol_lock("SOXL", timeout=0.05):
                        seen.append(True)
                except bridge.FireGateBridgeError:
                    seen.append(False)
            thread = threading.Thread(target=other)
            thread.start()
            thread.join()
            kis.during_history = None
        kis.during_history = try_lock
        run(engine)
        self.assertEqual(seen, [True])

    def test_absorbed_orders_are_never_written_again(self):
        """A buy/sell mix the broker shows but nobody booked goes into the
        adjustment; a later local row for one of those orders is a duplicate."""
        sell = {**GAP_FILL, "order_no": "0029000002", "action": "SELL", "side": "SELL", "order_date": "20261104",
                "filled_qty": 5, "filled_price": 71.0}
        engine, remote, _kis, _logs, _notes, _fg = make(history=broker_history([GAP_FILL, sell]))
        self.assertEqual(symbol_status(run(engine)), "reconciled")
        adjust = added(remote)[-1]
        self.assertEqual(adjust["absorbedOrderNos"], ["0029000001", "0029000002"])
        self.assertEqual(remote.portfolios[0]["reconciledBrokerOrderNos"], ["0029000001", "0029000002"])
        later_row = {**LOCAL_ROWS[3], "id": "late-sync-row", "trade_date": "2026-11-03", "filled_price": 70.0,
                     "filled_qty": 33, "broker_order_no": "0029000001"}
        creates = remote.creates
        original = bridge._bridge_call_from_config
        bridge._bridge_call_from_config = lambda _s, fn: fn(remote, {"enabled": True})
        try:
            result = bridge.sync_cycle_trade(None, {"id": CYCLE_2, "symbol": "SOXL"}, later_row, force=True)
        finally:
            bridge._bridge_call_from_config = original
        self.assertEqual((remote.creates, result.get("reason")), (creates, "duplicate"))
        again = plan(transactions=remote.transactions, local=LOCAL_ROWS + [later_row], history=[],
                     portfolio=remote.portfolios[0])
        self.assertEqual((again["status"], again["txs"]), ("ok", []))

    def test_a_leftover_job_record_is_not_a_partial_write(self):
        engine, remote, _kis, _logs, notes, _fg = make(history=broker_history())
        real_set = engine.struct.set_config

        def lose_the_delete(key, value, description=""):
            if key == "firegate_auto_reconcile_job:SOXL" and not value:
                return  # the delete does not stick
            real_set(key, value, description)
        engine.struct.set_config = lose_the_delete
        self.assertEqual(symbol_status(run(engine)), "reconciled")
        self.assertTrue(engine.struct.configs.get("firegate_auto_reconcile_job:SOXL"))
        engine.struct.set_config = real_set
        remote.portfolios[0]["holdingQty"] = 173  # a fill pushed after the relink
        engine._load_kis_api().held = 173
        result = run(engine)
        self.assertEqual(symbol_status(result), "reconciled")
        self.assertFalse(engine.struct.configs.get("firegate_auto_reconcile_job:SOXL"))
        self.assertFalse(any("부분 반영" in note for note in notes))

    def test_an_average_edited_mid_way_stops_the_resume(self):
        engine, remote, _kis, _logs, notes, _fg = make(history=broker_history())
        remote.fail_patch_at = 4
        run(engine)
        remote.fail_patch_at = None
        remote.portfolios[0]["avgPrice"] = 1.23  # only the average differs
        self.assertEqual(symbol_status(run(engine)), "partial_stuck")

    def test_a_re_applied_reverse_sell_gets_its_star(self):
        engine, remote, _kis, _logs, _notes, _fg = make(local_rows=LOCAL_ROWS[:1], history=broker_history()[:1], held=92)
        remote.fail_patch_at = 1  # the sell landed, its portfolio update did not
        self.assertEqual(symbol_status(run(engine)), "write_failed")
        remote.fail_patch_at = None
        self.assertEqual(symbol_status(run(engine)), "reconciled")
        self.assertEqual(remote.portfolios[0]["reverseModeStarPrice"], 35.0)

    def test_branch_change_policy_can_hold_the_adjustment(self):
        engine, remote, _kis, logs, _notes, _fg = make(history=broker_history(),
                                                       configs={"firegate_auto_reconcile_adjust_branch_change": "block"})
        self.assertEqual(symbol_status(run(engine)), "plan_adjust_branch_change")
        self.assertEqual((remote.creates, remote.patches), (0, 0))
        self.assertIn("리버스 분기", logs[-1]["message"])
        engine, remote, _kis, _logs, notes, _fg = make(history=broker_history())
        self.assertEqual(symbol_status(run(engine)), "reconciled")  # the default for now proceeds
        self.assertIn("잔여 시드 $1,535.75→$-598.69", notes[0])


def plan(transactions=FIREGATE_TXS, local=LOCAL_ROWS, history=None, portfolio=PORTFOLIO, held=165, **kw):
    history = broker_history([GAP_FILL]) if history is None else history
    return bridge.reconcile_plan(portfolio, transactions, local, history, held, CYCLE_2,
                                 broker_avg=kw.pop("broker_avg", 84.8162), current_price=kw.pop("current_price", 33.37),
                                 today=datetime.date(2026, 11, 23), **kw)


class ReconcilePlanTests(unittest.TestCase):
    def test_an_id_match_is_never_taken_by_an_earlier_content_match(self):
        """Two 1@30 buys the same day; FireGate has the second by order
        number. Content first would give A's slot to B and book B twice."""
        portfolio = {**PORTFOLIO, "holdingQty": 1, "avgPrice": 30, "totalBuy": 30, "tValue": 1, "reverseMode": False,
                     "reverseState": "NORMAL", "endDate": ""}
        rows = [{**LOCAL_ROWS[3], "id": rid, "trade_date": "2026-11-21", "filled_price": 30.0, "filled_qty": 1,
                 "commission": 0, "broker_order_no": order_no} for rid, order_no in (("A", "001"), ("B", "002"))]
        firegate = [{"id": "fg-b", "portfolioId": 1780022179464, "type": "buy", "date": "2026. 11. 21", "price": 30.0,
                     "size": 1, "source": "infinitystock", "sourceTradeId": "elsewhere", "brokerOrderNo": "002"}]
        result = plan(transactions=firegate, local=rows, history=[], portfolio=portfolio, held=2)
        self.assertEqual((result["status"], [tx["sourceTradeId"] for tx in result["txs"]]), ("ok", ["A"]))

    def test_an_earlier_adjustment_is_no_particular_fill(self):
        adjust = {"id": "ADJUST-SOXL-20261122-33", "portfolioId": 1780022179464, "type": "buy", "date": "2026. 11. 22",
                  "price": 70.0, "size": 33, "source": "infinitystock", "sourceTradeId": "ADJUST-SOXL-20261122-33",
                  "adjustment": True}
        fill = {**GAP_FILL, "order_date": "20261121"}
        result = plan(transactions=FIREGATE_TXS + [adjust], history=broker_history([fill]), held=198)
        self.assertIn("KIS-0029000001", [tx["sourceTradeId"] for tx in result["txs"]])

    def test_branch_change_is_judged_on_both_sides_of_the_adjustment(self):
        result = plan(history=broker_history())
        self.assertEqual(result["branch"], {"changed": True, "before_branch": "reverse_active",
                                            "after_branch": "reverse_re_exhausted",
                                            "before_seed": 1535.75, "after_seed": -598.69})
        same = bridge.adjustment_branch_change(PORTFOLIO, PORTFOLIO, 33.37)
        self.assertFalse(same["changed"])

    def test_one_broker_order_is_one_fill(self):
        rows = LOCAL_ROWS + [{**LOCAL_ROWS[3], "id": "dup-row", "cycle_id": CYCLE_1}]
        result = plan(local=rows)
        ids = [tx["sourceTradeId"] for tx in result["txs"]]
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("dup-row", ids)
        self.assertEqual(len(ids), 7)

    def test_a_reservation_number_on_a_local_fill_is_not_a_second_fill(self):
        twin = {"order_no": "R-0031155056", "symbol": "SOXL", "action": "BUY", "side": "BUY", "order_date": "20261120",
                "order_time": "160000", "filled_qty": 8, "filled_price": 33.02, "order_qty": 8, "status": "FILLED"}
        history = [row for row in broker_history([GAP_FILL]) if row["order_no"] != "0031155056"] + [twin]
        result = plan(history=history)
        self.assertNotIn("KIS-R-0031155056", [tx["sourceTradeId"] for tx in result["txs"]])
        self.assertEqual((result["status"], result["holding_after"], result["adjustment"]), ("ok", 165, None))

    def test_a_local_fill_older_than_firegates_last_entry_stops_the_plan(self):
        later = FIREGATE_TXS + [{"id": "late", "portfolioId": 1780022179464, "type": "buy", "date": "2026. 11. 15",
                                 "price": 50.0, "size": 1, "source": "infinitystock", "sourceTradeId": "late"}]
        self.assertEqual(plan(transactions=later)["status"], "stale_fill")

    def test_the_replay_may_not_pass_through_zero_or_stop(self):
        small = {**PORTFOLIO, "holdingQty": 20}
        self.assertEqual(plan(portfolio=small, local=LOCAL_ROWS[:1], history=[], held=20)["status"], "zero_crossing")

    def test_a_plan_over_the_cap_is_refused(self):
        self.assertEqual(plan(max_transactions=3)["status"], "too_many")

    def test_each_step_has_its_expected_state(self):
        result = plan(history=broker_history())
        self.assertEqual(len(result["snapshots"]), len(result["txs"]))
        self.assertEqual(result["snapshots"][-1]["holdingQty"], 165)
        self.assertTrue(all(step["isRunning"] and step["holdingQty"] > 0 for step in result["snapshots"]))


class PushDedupeTests(unittest.TestCase):
    def test_trade_push_skips_an_order_already_booked_by_the_reconcile(self):
        linked = {**PORTFOLIO, "sourceCycleId": CYCLE_2}
        remote = _Remote([linked], FIREGATE_TXS + [{"id": "KIS-0031155056", "portfolioId": 1780022179464,
                                                    "type": "buy", "date": "2026. 11. 20", "price": 33.02, "size": 8,
                                                    "source": "infinitystock", "sourceTradeId": "KIS-0031155056",
                                                    "brokerOrderNo": "0031155056"}])
        original = bridge._bridge_call_from_config
        bridge._bridge_call_from_config = lambda _s, fn: fn(remote, {"enabled": True})
        try:
            result = bridge.sync_cycle_trade(None, {"id": CYCLE_2, "symbol": "SOXL"}, LOCAL_ROWS[5], force=True)
        finally:
            bridge._bridge_call_from_config = original
        self.assertEqual(remote.creates, 0)
        self.assertEqual(result.get("reason"), "duplicate")

    def test_writers_share_one_lock_per_symbol(self):
        import threading
        entered = threading.Event()
        release = threading.Event()

        def holder():
            with bridge.firegate_symbol_lock("SOXL"):
                entered.set()
                release.wait(2)
        thread = threading.Thread(target=holder)
        thread.start()
        entered.wait(2)
        with self.assertRaises(bridge.FireGateBridgeError):
            with bridge.firegate_symbol_lock("SOXL", timeout=0.05):
                pass
        with bridge.firegate_symbol_lock("TQQQ", timeout=0.05):
            pass
        release.set()
        thread.join()


class SyncWorkerWiringTests(unittest.TestCase):
    """The LIVE sync worker runs the reconcile after its fill sync, only with
    the infinite-buy lane on."""

    def run_sync_job(self, policy):
        import ast
        from types import SimpleNamespace as NS
        from unittest.mock import Mock
        import flask

        class Stop(BaseException):
            pass
        tree = ast.parse((ROOT / "src/portal/trading/model/struct.py").read_text(encoding="utf-8-sig"))
        outer = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_ensure_live_policy_workers")
        fn = next(n for n in ast.walk(outer) if isinstance(n, ast.FunctionDef) and n.name == "account_job")
        engine = Mock()
        engine.sync_external_cycle_trades.return_value = {"message": "ok", "status": "completed"}
        trading = NS(order_policy=NS(_key=lambda: "test", read=lambda: policy, daytrade_allowed=lambda: True),
                     engine=engine, get_config=lambda *a: "")
        app = flask.Flask("worker-test")
        app.secret_key = "test-only"
        state = {}

        def stop(_):
            raise Stop()
        scope = {"registry": {"jobs": {("test", "sync"): state}}, "wiz": NS(server=NS(app=NS(flask=app))),
                 "Struct": lambda: trading, "_kst_now": lambda: NOW, "time": NS(sleep=stop)}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "<worker-test>", "exec"), scope)
        with self.assertRaises(Stop):
            scope["account_job"]("test", "owner", "sync")
        return engine, state

    def test_reconcile_follows_the_fill_sync(self):
        engine, state = self.run_sync_job({"infinite_buy": True})
        engine.run_firegate_auto_reconcile.assert_called_once_with(
            sync_result=engine.sync_external_cycle_trades.return_value)
        self.assertIn("firegate_reconcile", state)

    def test_lane_off_runs_nothing(self):
        engine, _state = self.run_sync_job({})
        engine.run_firegate_auto_reconcile.assert_not_called()
        engine.sync_external_cycle_trades.assert_not_called()


if __name__ == "__main__":
    unittest.main()
