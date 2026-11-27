"""11-27 LIVE SOXL: the running FireGate portfolio named a cycle from the
pre-11-09 DB, so no fill reached FireGate after 10-30 (112 vs KIS 165) and
PR #42 held every SOXL reservation. scripts/firegate_relink_soxl.py plans the
repair offline-first; these tests pin the plan math (FireGate's own
addTransaction rules, in time order), the refusals, and that a rerun never
adds a transaction twice. Nothing here touches the network."""
import contextlib
import copy
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("firegate_relink_soxl_under_test", ROOT / "scripts/firegate_relink_soxl.py")
relink = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relink)
fg = relink.fg

PID = 1780022179464
CYCLE = "dvijhiqxrdslimffqukbunqzisxccpde"
OLD_CYCLE = "tsevwkrrjetkjjunnsamosnumiuskebe"


def portfolio(**overrides):
    base = {
        "id": PID, "ticker": "SOXL", "isRunning": True, "source": "infinitystock",
        "portfolioGroup": "InfinityStock Auto", "sourceCycleId": OLD_CYCLE, "seed": 15000.0,
        "divisionDate": 20, "targetProfit": 20.0, "commissionRate": 0.25, "holdingQty": 112,
        "avgPrice": 117.61, "totalBuy": 20916.96, "totalSell": 7750.6, "tValue": 19.62,
        "reverseMode": True, "reverseState": "ENTERED", "reverseModeStarPrice": 94.0,
        "startDate": "2026-06-26", "reconciledSourceTradeIds": ["older-1"],
    }
    base.update(overrides)
    return base


def fg_tx(doc_id, date, kind, size, price, **extra):
    row = {"_doc_id": doc_id, "id": doc_id, "portfolioId": PID, "ticker": "SOXL", "date": date, "type": kind,
           "size": size, "price": price, "commission": round(size * price * 0.0025, 2),
           "source": "infinitystock", "sourceTradeId": doc_id, "tDelta": 0.5 if kind == "buy" else None}
    row.update(extra)
    return row


def kis(order_no, ymd, action, qty, price, hhmmss="100000"):
    return {"order_no": order_no, "symbol": "SOXL", "order_date": ymd, "order_time": hhmmss,
            "action": action, "filled_qty": qty, "filled_price": price}


def local(trade_id, cycle_id, trade_date, action, qty, price, order_no, commission):
    return {"id": trade_id, "cycle_id": cycle_id, "symbol": "SOXL", "trade_date": trade_date, "action": action,
            "filled_qty": qty, "filled_price": price, "broker_order_no": order_no, "commission": commission,
            "status": "FILLED", "order_type": "EXTERNAL", "strategy_type": "NORMAL", "source": "KIS"}


# FireGate already has the 10-30 buys (no broker order numbers, like the old pushes).
FG_TXS = [
    fg_tx("a1", "2026. 10. 30", "buy", 10, 77.05),
    fg_tx("a2", "2026. 10. 30", "buy", 1, 77.05),
    fg_tx("a3", "2026. 10. 30", "buy", 1, 77.05),
]
KIS_ORDERS = [
    kis("0030928307", "20261030", "BUY", 10, 77.05),
    kis("0030928323", "20261030", "BUY", 1, 77.05),
    kis("0030928337", "20261030", "BUY", 1, 77.05),
    kis("0031066164", "20261105", "BUY", 13, 44.0, "032956"),
    kis("0030167321", "20261102", "BUY", 8, 68.17),
    kis("0030616750", "20261111", "SELL", 20, 66.03),
    kis("0030494763", "20261124", "BUY", 30, 32.6),
]
LOCAL_TRADES = [
    local("loc-sell", "yudyhn-old", "2026-11-11", "SELL", 20, 66.03, "0030616750", 3.3),
    local("loc-buy", CYCLE, "2026-11-24", "BUY", 30, 32.6, "0030494763", 2.44),
]
FINAL_QTY = 112 + 13 + 8 - 20 + 30


class FakeFireGate:
    """In-memory FireGate: refuses writes unless switched on, refuses duplicate doc ids."""

    def __init__(self, portfolios, transactions, fail_update_once=False):
        self.portfolios = {str(p["id"]): copy.deepcopy(p) for p in portfolios}
        self.transactions = {str(t["_doc_id"]): copy.deepcopy(t) for t in transactions}
        self.allow_writes = False
        self.creates = 0
        self.fail_update_once = fail_update_once

    def _write(self):
        if not self.allow_writes:
            raise AssertionError("write while writes are off")

    def list_portfolios(self):
        return [copy.deepcopy(p) for p in self.portfolios.values()]

    def get_portfolio(self, portfolio_id):
        return copy.deepcopy(self.portfolios[str(portfolio_id)])

    def _list_collection(self, collection):
        assert collection == "transactions"
        return [copy.deepcopy(t) for t in self.transactions.values()]

    def list_transactions(self, portfolio_id):
        return [t for t in self._list_collection("transactions") if str(t.get("portfolioId")) == str(portfolio_id)]

    def create_transaction(self, tx, doc_id=None):
        self._write()
        if str(doc_id) in self.transactions:
            raise AssertionError(f"duplicate transaction {doc_id}")
        self.creates += 1
        self.transactions[str(doc_id)] = {**tx, "_doc_id": str(doc_id), "id": doc_id}
        return self.transactions[str(doc_id)]

    def update_portfolio(self, portfolio_id, changes):
        self._write()
        if self.fail_update_once:
            self.fail_update_once = False
            raise RuntimeError("network dropped")
        self.portfolios[str(portfolio_id)].update(copy.deepcopy(changes))
        return self.get_portfolio(portfolio_id)

    def create_portfolio(self, data, doc_id=None):
        self._write()
        self.portfolios[str(doc_id)] = {**copy.deepcopy(data), "id": doc_id}
        return self.get_portfolio(doc_id)


def context_from(client, kis_qty=FINAL_QTY, kis_orders=KIS_ORDERS, local_trades=LOCAL_TRADES, verified=True):
    """What build_context derives, from a fake FireGate and fixed KIS/local rows."""
    target = client.get_portfolio(PID)
    fg_txs = client.list_transactions(PID)
    applied = [t for t in fg_txs if not relink.is_pending_relink_tx(t, target)]
    window_start = max(relink.parse_date(t["date"]) for t in applied).isoformat()
    fills, problems = relink.merge_fills(relink.normalize_kis_fills(kis_orders),
                                         relink.normalize_local_fills(local_trades), window_start)
    fills = [f for f in fills if f["date"] >= window_start]
    soxl = [p for p in client.list_portfolios() if p.get("ticker") == "SOXL"]
    return {"cycle_id": CYCLE, "target": target, "portfolios": soxl, "all_portfolios": client.list_portfolios(),
            "fg_transactions": fg_txs, "fills": fills, "problems": problems, "kis_qty": kis_qty,
            "kis_qty_verified": verified, "local_cycle_ids": {CYCLE, "yudyhn-old"},
            "local_trade_ids": [t["id"] for t in local_trades]}


def plan_a(context):
    missing = relink.find_missing_fills(context["fg_transactions"], context["fills"], context["target"])
    return relink.plan_append(context["target"], missing, CYCLE)


class PlanTests(unittest.TestCase):
    def test_missing_fills_skip_the_boundary_day_and_keep_time_order(self):
        context = context_from(FakeFireGate([portfolio()], FG_TXS))
        missing = relink.find_missing_fills(context["fg_transactions"], context["fills"], context["target"])
        self.assertEqual([(m["date"], m["side"], m["qty"]) for m in missing],
                         [("2026-11-02", "buy", 8), ("2026-11-05", "buy", 13),
                          ("2026-11-11", "sell", 20), ("2026-11-24", "buy", 30)])

    def test_plan_a_follows_firegate_add_transaction_in_order(self):
        context = context_from(FakeFireGate([portfolio()], FG_TXS))
        plan = plan_a(context)
        # Independent chain through the bridge's own functions, as the app's push does.
        state = portfolio()
        for fill in relink.find_missing_fills(context["fg_transactions"], context["fills"], context["target"]):
            tx = {"type": fill["side"], "price": fill["price"], "size": fill["qty"],
                  "commission": fill["commission"] if fill["commission"] is not None
                  else round(fill["price"] * fill["qty"] * 0.0025, 2)}
            if tx["type"] == "buy":
                tx["tDelta"] = fg.calculate_v4_t_delta(state, tx)
            tx.update(fg.firegate_operator(state, tx))
            state = fg.apply_v4_transaction(state, tx)
        for key in ("holdingQty", "avgPrice", "totalBuy", "totalSell", "tValue", "reverseState"):
            self.assertEqual(plan["final"][key], state[key], key)
        self.assertEqual(plan["final"]["holdingQty"], FINAL_QTY)
        # The first reverse-mode sell ends the first day (ENTERED -> ACTIVE) with T x0.9.
        sell = next(t for t in plan["transactions"] if t["type"] == "sell")
        self.assertEqual((sell["tOperator"], sell["tDelta"], sell["reverseMode"]), ("x", 0.9, True))
        self.assertEqual(plan["final"]["reverseState"], "ACTIVE")
        # A local fill keeps its trade id and commission; a KIS-only one is marked estimated.
        by_order = {t["brokerOrderNo"]: t for t in plan["transactions"]}
        self.assertEqual(by_order["0030616750"]["sourceTradeId"], "loc-sell")
        self.assertEqual(by_order["0030616750"]["commission"], 3.3)
        self.assertTrue(by_order["0030167321"]["commissionUnverified"])
        self.assertEqual(len({t["_doc_id"] for t in plan["transactions"]}), len(plan["transactions"]))

    def test_portfolio_changes_link_the_cycle_and_mark_local_trades(self):
        context = context_from(FakeFireGate([portfolio()], FG_TXS))
        plan = plan_a(context)
        changes = relink.a_portfolio_changes(context["target"], plan, CYCLE, context["local_trade_ids"])
        self.assertEqual(changes["sourceCycleId"], CYCLE)
        self.assertEqual(changes["relinkedFromSourceCycleId"], OLD_CYCLE)
        self.assertEqual(changes["reconciledSourceTradeIds"], ["older-1", "loc-sell", "loc-buy"])
        self.assertEqual(changes["holdingQty"], FINAL_QTY)

    def test_plan_b_replays_every_original_transaction_from_zero(self):
        context = context_from(FakeFireGate([portfolio()], FG_TXS))
        missing = relink.find_missing_fills(context["fg_transactions"], context["fills"], context["target"])
        plan = relink.plan_rebuild(context["target"], context["fg_transactions"], missing, CYCLE,
                                   relink.REBUILD_PORTFOLIO_ID)
        self.assertEqual(plan["new_portfolio"]["sourceCycleId"], CYCLE)
        self.assertFalse(plan["new_portfolio"]["isRunning"])  # activated only after its history is in
        self.assertEqual(len(plan["transactions"]), len(FG_TXS) + len(missing))
        self.assertTrue(all(t["_doc_id"].startswith(f"rebuild-{relink.REBUILD_PORTFOLIO_ID}-")
                            for t in plan["transactions"]))
        # FireGate's 112 came partly from repairs without transactions: replaying the
        # history alone gives 12 + 31 = 43, so B is refused against KIS.
        self.assertEqual(plan["final"]["holdingQty"], 12 + 13 + 8 - 20 + 30)
        refusals = relink.apply_refusals(plan, context, relink.confirm_phrase(plan, CYCLE))
        self.assertTrue(any("≠ KIS" in r for r in refusals), refusals)


class RefusalTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeFireGate([portfolio()], FG_TXS)

    def test_exact_confirm_phrase_and_matching_kis_quantity_allow_apply(self):
        context = context_from(self.client)
        plan = plan_a(context)
        self.assertEqual(relink.apply_refusals(plan, context, relink.confirm_phrase(plan, CYCLE)), [])
        self.assertEqual(relink.confirm_phrase(plan, CYCLE), f"A SOXL {PID} {FINAL_QTY} dvijhi")

    def test_wrong_confirm_phrase_is_refused(self):
        context = context_from(self.client)
        plan = plan_a(context)
        self.assertTrue(any("확인 문구" in r for r in relink.apply_refusals(plan, context, "yes")))

    def test_quantity_different_from_kis_is_refused(self):
        context = context_from(self.client, kis_qty=FINAL_QTY + 3)
        plan = plan_a(context)
        refusals = relink.apply_refusals(plan, context, relink.confirm_phrase(plan, CYCLE))
        self.assertTrue(any("≠ KIS" in r for r in refusals), refusals)

    def test_unverified_kis_quantity_is_refused(self):
        context = context_from(self.client, verified=False)
        plan = plan_a(context)
        refusals = relink.apply_refusals(plan, context, relink.confirm_phrase(plan, CYCLE))
        self.assertTrue(any("확인되지 않음" in r for r in refusals), refusals)

    def test_disagreeing_kis_sources_are_refused(self):
        qty, problems = relink.reconcile_quantities({"snapshot": 165, "live": 160})
        self.assertIsNone(qty)
        self.assertTrue(problems)

    def test_second_running_managed_portfolio_is_refused(self):
        client = FakeFireGate([portfolio(), portfolio(id=1790000000000, sourceCycleId="other")], FG_TXS)
        context = context_from(client)
        plan = plan_a(context)
        refusals = relink.apply_refusals(plan, context, relink.confirm_phrase(plan, CYCLE))
        self.assertTrue(any("하나가 아님" in r for r in refusals), refusals)

    def test_link_to_another_local_cycle_is_refused(self):
        client = FakeFireGate([portfolio(sourceCycleId="yudyhn-old")], FG_TXS)
        context = context_from(client)
        plan = plan_a(context)
        refusals = relink.apply_refusals(plan, context, relink.confirm_phrase(plan, CYCLE))
        self.assertTrue(any("옛 연결이 아님" in r for r in refusals), refusals)

    def test_local_fill_the_broker_does_not_show_is_refused(self):
        extra = LOCAL_TRADES + [local("loc-ghost", CYCLE, "2026-11-20", "BUY", 3, 35.88, "0031121938", 0.27)]
        context = context_from(self.client, local_trades=extra)
        plan = plan_a(context)
        refusals = relink.apply_refusals(plan, context, relink.confirm_phrase(plan, CYCLE))
        self.assertTrue(any("KIS 체결내역에 없음" in r for r in refusals), refusals)


class ApplyTests(unittest.TestCase):
    def _apply(self, client):
        context = context_from(client)
        plan = plan_a(context)
        self.assertEqual(relink.apply_refusals(plan, context, relink.confirm_phrase(plan, CYCLE)), [])
        return relink.apply_a(client, plan, context, relink.Progress(None)), plan

    def test_apply_writes_once_and_a_rerun_finds_nothing_to_do(self):
        client = FakeFireGate([portfolio()], FG_TXS)
        after, plan = self._apply(client)
        self.assertEqual(after["holdingQty"], FINAL_QTY)
        self.assertEqual(after["sourceCycleId"], CYCLE)
        self.assertEqual(client.creates, len(plan["transactions"]))
        self.assertFalse(client.allow_writes)
        context = context_from(client)
        rerun = plan_a(context)
        self.assertEqual(rerun["transactions"], [])
        refusals = relink.apply_refusals(rerun, context, relink.confirm_phrase(rerun, CYCLE))
        self.assertTrue(any("이미 복구됨" in r for r in refusals), refusals)

    def test_rerun_after_a_failed_patch_reuses_the_created_transactions(self):
        client = FakeFireGate([portfolio()], FG_TXS, fail_update_once=True)
        context = context_from(client)
        plan = plan_a(context)
        progress = relink.Progress(None)
        with self.assertRaises(RuntimeError):
            relink.apply_a(client, plan, context, progress)
        self.assertEqual(client.get_portfolio(PID)["holdingQty"], 112)  # state not half-written
        self.assertIn("transaction_created", [s["step"] for s in progress.steps])
        created = client.creates
        after, plan2 = self._apply(client)  # fresh read: those transactions are still pending
        self.assertEqual(client.creates, created)  # nothing added twice
        self.assertEqual(len(plan2["transactions"]), len(plan["transactions"]))
        self.assertEqual(after["holdingQty"], FINAL_QTY)
        self.assertEqual(len(client.list_transactions(PID)), len(FG_TXS) + len(plan["transactions"]))

    def test_printed_errors_hide_the_email_path_and_account_numbers(self):
        text = relink.redact("exists: users/someone%40example.test/transactions/x acct 12345678-01")
        self.assertNotIn("example.test", text)
        self.assertNotIn("12345678-01", text)

    def test_plan_mode_client_refuses_every_write_before_any_request(self):
        client = relink.GuardedFireGate("user@example.test", "token")
        with self.assertRaises(relink.RelinkRefused):
            client.create_transaction({"type": "buy"}, doc_id="x")
        with self.assertRaises(relink.RelinkRefused):
            client.update_portfolio(PID, {"holdingQty": 1})
        client.allow_writes = True
        with self.assertRaises(relink.RelinkRefused):
            client._request("DELETE", "https://example.test/x")


class KisReadTests(unittest.TestCase):
    class Api:
        account_prefix, account_suffix = "00000000", "01"

        def __init__(self, script):
            self.script = script  # (pdno, exchange) -> list of responses
            self.calls = []

        @contextlib.contextmanager
        def request_options(self, **kwargs):
            yield

        def _request(self, method, path, tr_id, params=None, tr_cont=""):
            key = (params["PDNO"], params["OVRS_EXCG_CD"])
            self.calls.append(key)
            queue = self.script.get(key) or [{"rt_cd": "0", "tr_cont": "D", "output": []}]
            return queue.pop(0) if len(queue) > 1 else queue[0]

        def _overseas_ccnl_rows(self, data):
            return data.get("output", [])

        def _normalize_overseas_ccnl_row(self, item, exchange, start):
            return dict(item)

    def setUp(self):
        self._sleep = relink.time.sleep
        relink.time.sleep = lambda *_: None

    def tearDown(self):
        relink.time.sleep = self._sleep

    def test_a_query_whose_data_changed_starts_over_and_pages_to_the_end(self):
        changed = {"rt_cd": "1", "msg_cd": "SYDB0050", "msg1": "changed"}
        page1 = {"rt_cd": "0", "tr_cont": "M", "ctx_area_nk200": "n1", "ctx_area_fk200": "f1",
                 "output": [kis("1", "20261102", "BUY", 8, 68.17)]}
        page2 = {"rt_cd": "0", "tr_cont": "D", "output": [kis("2", "20261105", "BUY", 13, 44.0)]}
        api = self.Api({("SOXL", "AMEX"): [page1, changed, page1, page2]})
        orders, notes = relink.read_kis_fills(api, "20261030", "20261127")
        self.assertEqual(sorted(o["order_no"] for o in orders), ["1", "2"])

    def test_symbol_view_that_never_completes_raises_and_all_view_only_notes(self):
        changed = {"rt_cd": "1", "msg_cd": "SYDB0050", "msg1": "changed"}
        api = self.Api({("", "NASD"): [changed]})
        orders, notes = relink.read_kis_fills(api, "20261030", "20261127")
        self.assertTrue(any("NASD" in n for n in notes))
        api = self.Api({("SOXL", "NASD"): [changed]})
        with self.assertRaises(RuntimeError):
            relink.read_kis_fills(api, "20261030", "20261127")


if __name__ == "__main__":
    unittest.main()
